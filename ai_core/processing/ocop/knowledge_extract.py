"""evidence extraction: PageArtifact -> source-grounded OCOP EvidenceUnits, entities and relations.

This is extraction, not legal approval. OCR candidates are retained with provenance
and review flags. There is deliberately no LLM/model/network dependency here.
"""

from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

from ocop_contracts.ids import code_fingerprint, stable_id, content_sha256
from ocop_contracts.models import EvidenceUnit, SourceSpan, ReviewStatus, cell_display_text
from ocop_contracts.layout import group_blocks_by_line, join_blocks_by_line
from ocop_contracts.registry import load_registry
from ocop_contracts import layout as shared_layout
from ocop_contracts import table_continuity as shared_continuity
from ai_core.processing.ocop.business_candidates import candidates
from ai_core.processing.ocop.temporal_candidates import temporal_candidates
from ai_core.knowledge.ocop.extractor import extract_semantics
from ai_core.knowledge.ocop.llm_proposals import client_identity, propose, reconcile, semantic_profile
from ai_core.knowledge.ocop.quality import audit_knowledge
from ai_core.knowledge.ocop.contracts import BusinessEntity, BusinessRelation, validate_business_graph

ROOT = Path(__file__).resolve().parents[3]
_PROCESSING = Path(__file__).resolve().parent
_ROOT = _PROCESSING.parents[1]
# Every module whose code shapes evidence units, entities, relations, rules and temporal candidates.


VERSION = code_fingerprint(
    "evidence",
    [
        Path(shared_layout.__file__),
        Path(shared_continuity.__file__),
        ROOT / "ocop_contracts/models.py",
        ROOT / "ocop_contracts/ids.py",
        *(
            _PROCESSING / name
            for name in ("knowledge_extract.py", "business_candidates.py", "temporal_candidates.py")
        ),
        *(
            _ROOT / "knowledge" / "ocop" / name
            for name in (
                "extractor.py",
                "contracts.py",
                "quality.py",
                "llm_proposals.py",
                "legal_structure.py",
                "article_tree.py",
                "star_requirements.py",
                "criterion_sheets.py",
                "procedures.py",
                "authorities.py",
                "shapes.py",
            )
        ),
        ROOT / "configs" / "ocop_authorities.json",
        _ROOT / "orchestration/ocop/llm.py",
        _ROOT / "domain" / "ocop_citations.py",
    ],
)
LEGAL_START = re.compile(
    r"^\s*(Điều\s+\d+[a-zđ]?(?:[.:]\s*.*)?|Chương\s+[IVXLCDM0-9]+\b.*|Mục\s+\d+\b.*|PHỤ\s*LỤC\s*[IVXLCDM0-9]*\b.*|Mẫu\s*(?:số)?\s*0?\d{1,3}(?!\d).*)\s*$",
    re.IGNORECASE,
)
LEGAL_REFERENCE = re.compile(
    r"\b\d{1,4}/20\d{2}/(?:QĐ-TTg|NĐ-CP|NQ-CP|QH\d+|QĐ-UBND|TT-[A-ZĐ]+)\b", re.IGNORECASE
)
FORM = re.compile(r"\bMẫu\s*(?:số)?\s*0?(\d{1,3})(?!\d)", re.IGNORECASE)
TERMS = {
    "chứng nhận": "certificate",
    "hợp tác xã": "organization",
    "doanh nghiệp": "organization",
    "thực phẩm": "food",
    "sản phẩm": "product",
    "an toàn thực phẩm": "food_safety",
    "truy xuất nguồn gốc": "traceability",
    "tiêu chí": "criterion",
    "chấm điểm": "scoring",
    "phụ lục": "annex",
}


def _jsonl_atomic(path: Path, records: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str) + "\n")
            count += 1
    os.replace(tmp, path)
    return count


def _span(
    page: dict, *, bbox=None, table_bbox=None, table_id=None, cell_id=None, block_id=None
) -> SourceSpan:
    return SourceSpan(
        pdf_page=page["pdf_page"],
        bbox=tuple(bbox) if bbox is not None else None,
        table_bbox=tuple(table_bbox) if table_bbox is not None else None,
        table_id=table_id,
        cell_id=cell_id,
        block_id=block_id,
        source_sha256=page.get("source_sha256"),
    )


def _unit(
    page: dict,
    kind: str,
    ordinal: str,
    text: str,
    *,
    structured: dict | None = None,
    spans: list[SourceSpan] | None = None,
    parent: str | None = None,
) -> dict:
    # Stable even when OCR text changes, keyed by document/page/unit position.
    unit_id = stable_id("evidence", page["source_id"], [page["pdf_page"], kind, ordinal], revision=VERSION)
    raw_status = page.get("review_status", "needs_review")
    if raw_status not in ("machine_extracted", "verified"):
        status = ReviewStatus.NEEDS_REVIEW
    else:
        status = ReviewStatus.MACHINE_EXTRACTED
    record = EvidenceUnit(
        unit_id=unit_id,
        source_id=page["source_id"],
        unit_kind=kind,
        parent_unit_id=parent,
        hierarchy_path=[page["source_id"], str(page["pdf_page"]), kind, ordinal],
        text=text,
        structured={**(structured or {}), "text_reviewed": bool(page.get("reviewed"))},
        spans=spans or [_span(page)],
        extractor_version=VERSION,
        review_status=status,
        unit_hash=content_sha256(text),
    ).model_dump(mode="json")
    return record


def _segments(text: str) -> list[tuple[str, str]]:
    """Section-aware splitting; retains all nonblank source text, including OCR noise."""
    lines = text.splitlines()
    segments = []
    buf = []
    kind = "paragraph"
    idx = 0

    def flush():
        nonlocal buf, idx
        value = "\n".join(buf).strip()
        if value:
            segments.append((kind, value))
            idx += 1
        buf = []

    for line in lines:
        clean = line.strip()
        if not clean:
            continue
        m = LEGAL_START.match(clean)
        if m:
            flush()
            low = clean.casefold()
            kind = (
                "article"
                if low.startswith("điều")
                else "annex"
                if "phụ" in low and "lục" in low
                else "form"
                if low.startswith("mẫu")
                else "section"
            )
            buf.append(clean)
        else:
            buf.append(clean)
            if len("\n".join(buf)) >= 1800 and kind in ("paragraph", "section"):
                flush()
                kind = "paragraph"
    flush()
    return segments


def _segments_with_line_indices(text: str):
    """Attach original page line offsets to each section-aware segment."""
    source_lines = text.splitlines()
    cursor = 0
    for kind, body in _segments(text):
        indices = []
        for segment_line in body.splitlines():
            while cursor < len(source_lines) and source_lines[cursor].strip() != segment_line:
                cursor += 1
            if cursor >= len(source_lines):
                yield kind, body, []
                break
            indices.append(cursor)
            cursor += 1
        else:
            yield kind, body, indices


def _line_blocks(page: dict) -> list[list[dict]] | None:
    """Blocks behind each page text line, or None when the text stream does not agree."""
    text = page.get("extracted_text", "")
    aligned = page.get("line_blocks")
    if isinstance(aligned, list) and len(aligned) == len(text.splitlines()):
        # Reviewed text no longer equals the OCR block stream; the import aligned every line to its source blocks.
        return aligned
    source_blocks = [
        block
        for block in page.get("blocks", [])
        if isinstance(block, dict) and isinstance(block.get("text"), str) and block["text"].strip()
    ]
    if not source_blocks or "\r" in text or join_blocks_by_line(source_blocks) != text:
        return None
    lines = []
    for group in group_blocks_by_line(source_blocks):
        lines.extend([group] * len(group[0]["text"].split("\n")))
    return lines


def _segment_spans(page: dict, line_indices: list[int]) -> list[SourceSpan]:
    """Map segment lines to exact page blocks when the text stream agrees."""
    line_blocks = _line_blocks(page)
    if line_blocks is None or not line_indices or any(i < 0 or i >= len(line_blocks) for i in line_indices):
        return [_span(page)]
    spans = []
    seen = set()
    for line_index in line_indices:
        for block in line_blocks[line_index]:
            key = (line_index, block.get("block_id"))
            if key in seen:
                continue
            seen.add(key)
            spans.append(_span(page, bbox=block.get("bbox"), block_id=block.get("block_id")))
    return spans or [_span(page)]


def _norm(value: str) -> str:
    return " ".join(value.split())


def _table_fragment_matches(fragment: str, cell_text: str) -> bool:
    fragment_norm = _norm(fragment).casefold()
    cell_norm = _norm(cell_text).casefold()
    if not fragment_norm or fragment_norm in cell_norm:
        return bool(fragment_norm)
    fragment_tokens = re.findall(r"[^\W_]+", fragment_norm, re.UNICODE)
    cell_tokens = re.findall(r"[^\W_]+", cell_norm, re.UNICODE)
    if len(fragment_tokens) < 4 or not cell_tokens:
        return False
    matched = sum(
        block.size
        for block in SequenceMatcher(None, fragment_tokens, cell_tokens, autojunk=False).get_matching_blocks()
    )
    return matched / len(fragment_tokens) >= 0.8


def _line_geometry(page: dict) -> list[dict] | None:
    """Return source-text lines with exact block bounds when streams agree."""
    lines = page.get("extracted_text", "").splitlines()
    grouped = _line_blocks(page)
    width = page.get("width_pt")
    height = page.get("height_pt")
    if (
        grouped is None
        or len(grouped) != len(lines)
        or not isinstance(width, (int, float))
        or width <= 0
        or not isinstance(height, (int, float))
        or height <= 0
    ):
        return None
    result = []
    for index, (text, blocks) in enumerate(zip(lines, grouped, strict=True)):
        boxes = []
        for block in blocks:
            box = block.get("bbox")
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                continue
            try:
                bounds = tuple(float(value) for value in box)
            except (TypeError, ValueError, OverflowError):
                continue
            boxes.append(bounds)
        if not text.strip() or not boxes:
            continue
        left = min(box[0] for box in boxes)
        right = max(box[2] for box in boxes)
        top = min(box[1] for box in boxes)
        bottom = max(box[3] for box in boxes)
        result.append(
            {
                "line_index": index,
                "text": text,
                "bbox": [left, top, right, bottom],
                "center_x": (left + right) / (2 * width),
                "center_y": (top + bottom) / (2 * height),
                "height_ratio": (bottom - top) / height,
            }
        )
    return result


def _page_furniture_lines(pages: Iterable[dict]) -> dict[tuple[str, int], dict[int, str]]:
    """Find recurring edge text and adjacent printed page numbers per source."""
    page_list = list(pages)
    by_source: dict[str, list[dict]] = {}
    geometry: dict[tuple[str, int], list[dict]] = {}
    sightings: dict[tuple[str, str, int], list[tuple[int, int, float, float]]] = {}
    for page in page_list:
        sid = str(page.get("source_id") or "")
        pdf_page = int(page.get("pdf_page") or 0)
        by_source.setdefault(sid, []).append(page)
        lines = _line_geometry(page)
        if lines is None:
            continue
        geometry[(sid, pdf_page)] = lines
        for line in lines:
            y = line["center_y"]
            if y <= 0.12 or y >= 0.88:
                key = (sid, _norm(line["text"]).casefold(), round(y, 2))
                sightings.setdefault(key, []).append((pdf_page, line["line_index"], y, line["height_ratio"]))

    threshold_by_source = {
        sid: max(3, (len(source_pages) * 3 + 4) // 5) for sid, source_pages in by_source.items()
    }
    anchors: dict[str, list[tuple[float, float]]] = {}
    marked: dict[tuple[str, int], dict[int, str]] = {}
    for (sid, normalized, _), occurrences in sightings.items():
        if not normalized or len({row[0] for row in occurrences}) < threshold_by_source[sid]:
            continue
        anchors.setdefault(sid, []).append(
            (
                sum(row[2] for row in occurrences) / len(occurrences),
                sum(row[3] for row in occurrences) / len(occurrences),
            )
        )
        for pdf_page, line_index, _, _ in occurrences:
            marked.setdefault((sid, pdf_page), {})[line_index] = "repeated_margin_text"

    for page in page_list:
        sid = str(page.get("source_id") or "")
        pdf_page = int(page.get("pdf_page") or 0)
        for line in geometry.get((sid, pdf_page), []):
            if not re.fullmatch(r"\s*\d{1,4}\s*", line["text"]):
                continue
            y = line["center_y"]
            if y > 0.12 and y < 0.88:
                continue
            for anchor_y, anchor_height in anchors.get(sid, []):
                tolerance = max(1.5 * line["height_ratio"], 1.5 * anchor_height, 0.012)
                if abs(y - anchor_y) <= tolerance:
                    marked.setdefault((sid, pdf_page), {}).setdefault(
                        line["line_index"], "page_number_adjacent_to_repeated_margin_text"
                    )
                    break

    # A source without a running header can still expose page numbers as isolated
    # numeric blocks. Trust exact PDF-page matches, or a sequential run at one
    # stable page-edge position; do not remove an unsupported isolated number.
    numeric_by_source: dict[str, list[dict]] = {}
    for page in page_list:
        sid = str(page.get("source_id") or "")
        pdf_page = int(page.get("pdf_page") or 0)
        for line in geometry.get((sid, pdf_page), []):
            if not re.fullmatch(r"\s*\d{1,4}\s*", line["text"]):
                continue
            y = line["center_y"]
            if y > 0.12 and y < 0.88:
                continue
            candidate = {**line, "source_id": sid, "pdf_page": pdf_page, "value": int(line["text"])}
            numeric_by_source.setdefault(sid, []).append(candidate)
            if candidate["value"] == pdf_page:
                marked.setdefault((sid, pdf_page), {}).setdefault(
                    line["line_index"], "page_number_matches_pdf_page"
                )
    for sid, candidates_for_source in numeric_by_source.items():
        sequences = []
        for first in candidates_for_source:
            for second in candidates_for_source:
                if (
                    second["pdf_page"] != first["pdf_page"] + 1
                    or second["value"] != first["value"] + 1
                    or abs(second["center_x"] - first["center_x"]) > 0.04
                    or abs(second["center_y"] - first["center_y"]) > 0.02
                ):
                    continue
                sequences.append((first, second))
        for first, second in sequences:
            for candidate in candidates_for_source:
                if (
                    candidate["pdf_page"] in (first["pdf_page"], second["pdf_page"])
                    and abs(candidate["center_x"] - first["center_x"]) <= 0.04
                    and abs(candidate["center_y"] - first["center_y"]) <= 0.02
                ):
                    marked.setdefault((sid, candidate["pdf_page"]), {}).setdefault(
                        candidate["line_index"], "sequential_page_number_at_consistent_position"
                    )
    return marked


def _furniture_metadata(page: dict, furniture_lines: dict[int, str]) -> list[dict]:
    if not furniture_lines:
        return []
    geometries = {row["line_index"]: row for row in (_line_geometry(page) or [])}
    source_lines = page.get("extracted_text", "").splitlines()
    return [
        {
            "line_index": index,
            "text": source_lines[index],
            "reason": reason,
            **({"bbox": geometries[index]["bbox"]} if index in geometries else {}),
        }
        for index, reason in sorted(furniture_lines.items())
        if 0 <= index < len(source_lines)
    ]


def _page_furniture_candidates(page: dict) -> dict[int, str]:
    """Separate isolated margin page numbers and legal closing blocks from body text.

    Reading-order heuristics can place a short ``Nơi nhận`` label after its
    recipient lines, especially when a signature or seal forms another visual
    region. Use the marker's geometry to classify the whole closing block while
    keeping every line as source-backed furniture evidence.
    """
    geometry = _line_geometry(page)
    if geometry is None:
        return {}
    result = {}
    marker = next(
        (
            line
            for line in geometry
            if re.fullmatch(r"\s*(?:nơi nhận|noi nhan)\s*:?\s*", line["text"], flags=re.IGNORECASE)
        ),
        None,
    )
    if marker is not None:
        marker_top = float(marker["bbox"][1])
        marker_height = max(1.0, float(marker["bbox"][3]) - marker_top)
        threshold = marker_top - max(1.5, marker_height * 0.3)
        for line in geometry:
            if float(line["bbox"][1]) >= threshold:
                result[line["line_index"]] = "legal_distribution_or_signature_block"
    height = float(page.get("height_pt") or 0)
    if height > 0:
        for line in geometry:
            if re.fullmatch(r"\s*\d{1,4}\s*", line["text"]):
                y0, y1 = float(line["bbox"][1]), float(line["bbox"][3])
                if y1 <= height * 0.10 or y0 >= height * 0.90:
                    result.setdefault(line["line_index"], "isolated_page_number_at_margin")
    return result


def _lines_duplicated_in_tables(page: dict) -> set[int]:
    """Text lines whose source blocks and near-matching OCR text are already in table cells."""
    line_blocks = _line_blocks(page)
    if line_blocks is None:
        return set()
    tables = []
    for table in page.get("tables", []):
        box = table.get("bbox")
        if isinstance(box, (list, tuple)) and len(box) == 4:
            cells = []
            for cell in table.get("cells", []):
                cell_box = cell.get("bbox")
                if isinstance(cell_box, (list, tuple)) and len(cell_box) == 4:
                    cells.append((cell_box, _norm(cell_display_text(cell))))
            tables.append((box, _norm(" ".join(cell_display_text(c) for c in table.get("cells", []))), cells))
    dropped = set()
    source_lines = page.get("extracted_text", "").splitlines()
    for index, blocks in enumerate(line_blocks):
        if not blocks:
            continue  # a reviewed line with no OCR block has no position, so it cannot be shown to sit in a table
        # A joined line can span two cells, so each fragment must be found in the table on its own.
        fragments = [source_lines[index]] if len(blocks) == 1 else [b["text"] for b in blocks]
        for box, cell_text, cells in tables:
            inside = all(
                b.get("bbox")
                and box[0] <= (b["bbox"][0] + b["bbox"][2]) / 2 <= box[2]
                and box[1] <= (b["bbox"][1] + b["bbox"][3]) / 2 <= box[3]
                for b in blocks
            )
            if not inside:
                continue
            if cells:
                matched = []
                for block, fragment in zip(blocks, fragments, strict=True):
                    bounds = block.get("bbox")
                    if not bounds:
                        matched.append(False)
                        continue
                    center = ((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)
                    containing = [
                        text
                        for cell_box, text in cells
                        if cell_box[0] <= center[0] <= cell_box[2] and cell_box[1] <= center[1] <= cell_box[3]
                    ]
                    if containing:
                        matched.append(any(_table_fragment_matches(fragment, text) for text in containing))
                    else:
                        matched.append(_table_fragment_matches(fragment, cell_text))
            else:
                matched = [_table_fragment_matches(fragment, cell_text) for fragment in fragments]
            if all(matched):
                dropped.add(index)
                break
    return dropped


def page_units(
    page: dict, *, source_kind: str = "", furniture_lines: dict[int, str] | None = None
) -> list[dict]:
    """Creates page root, structural units, and independent table evidence units."""
    text = page.get("extracted_text", "")
    furniture_lines = dict(furniture_lines or {})
    for line_index, reason in _page_furniture_candidates(page).items():
        furniture_lines.setdefault(line_index, reason)
    page_bbox = None
    try:
        width = float(page["width_pt"])
        height = float(page["height_pt"])
        if width > 0 and height > 0:
            page_bbox = (0.0, 0.0, width, height)
    except (KeyError, TypeError, ValueError, OverflowError):
        pass
    root = _unit(
        page,
        "page",
        "root",
        text[:5000],
        structured={
            "source_kind": source_kind,
            "extraction_method": page.get("extraction_method"),
            "warnings": page.get("warnings", []),
            "text_length": len(text),
            "table_count": len(page.get("tables", [])),
            "has_ocr": bool(page.get("ocr_engine")),
            "page_furniture": _furniture_metadata(page, furniture_lines),
        },
        spans=[_span(page, bbox=page_bbox)] if page_bbox else None,
    )
    units = [root]
    if not text.strip() and not page.get("tables"):
        return units
    active_legal_heading = None
    dropped = _lines_duplicated_in_tables(page)
    source_lines = text.splitlines()
    kept = [i for i in range(len(source_lines)) if i not in dropped and i not in furniture_lines]
    paragraph_text = "\n".join(source_lines[i] for i in kept)
    for i, (kind, body, kept_indices) in enumerate(_segments_with_line_indices(paragraph_text)):
        line_indices = [kept[j] for j in kept_indices]
        # Preserve only headings seen on this very page: do not infer absent
        # cross-page legislation or invent article numbers from OCR noise.
        first = body.splitlines()[0][:180]
        structured = {"source_kind": source_kind, "heading": first}
        geometry = {line["line_index"]: line for line in (_line_geometry(page) or [])}
        if len(line_indices) == len(body.splitlines()) and all(j in geometry for j in line_indices):
            structured["quote_lines"] = [
                {"text": line, "bbox": geometry[j]["bbox"], "pdf_page": page["pdf_page"]}
                for line, j in zip(body.splitlines(), line_indices)
            ]
        if kind in ("article", "annex", "form", "section"):
            active_legal_heading = first
        elif active_legal_heading is not None:
            structured["legal_heading"] = active_legal_heading
            structured["legal_heading_origin"] = "same_page_previous_segment"
        units.append(
            _unit(
                page,
                kind,
                str(i),
                body,
                parent=root["unit_id"],
                structured=structured,
                spans=_segment_spans(page, line_indices),
            )
        )
    for i, table in enumerate(page.get("tables", [])):
        cells = table.get("cells", [])
        # Stable row-major table text, preserve coordinate and row/column.
        cells_sorted = sorted(cells, key=lambda x: (x.get("row", 0), x.get("col", 0)))
        rows = {}
        for c in cells_sorted:
            rows.setdefault(int(c.get("row", 0)), []).append(cell_display_text(c))
        txt = "\n".join(" | ".join(r) for _, r in sorted(rows.items())).strip()
        if not txt:
            txt = (
                f"[Phát hiện vùng bảng trên trang PDF {page['pdf_page']} nhưng chưa nhận dạng được nội dung]"
            )
        table_id = str(table.get("table_id") or f"table:{i}")
        candidate = (
            "criterion_table_candidate"
            if source_kind in ("ocop_framework", "ocop_historical", "ocop_amendment")
            else "table"
        )
        units.append(
            _unit(
                page,
                candidate,
                str(i),
                txt,
                parent=root["unit_id"],
                structured={
                    "source_kind": source_kind,
                    "table_id": table_id,
                    "cells": cells_sorted,
                    "row_count": table.get("row_count"),
                    "col_count": table.get("col_count"),
                    "method": table.get("method"),
                    "candidate_only": True,
                    "warnings": table.get("warnings", []),
                },
                spans=[_span(page, bbox=table.get("bbox"), table_id=table_id)],
            )
        )
    return units


def extract_entities_relations(units: list[dict], sources: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Source-anchored entity and relation candidates; no fabricated cross-document links."""
    entities = {}
    relations = {}

    def entity(sid: str, etype: str, key: str, display: str, unit_id: str) -> str:
        eid = stable_id("entity", sid, [etype, key.casefold()])
        rec = entities.setdefault(
            eid,
            {
                "entity_id": eid,
                "source_id": sid,
                "entity_type": etype,
                "name": display,
                "evidence_unit_ids": [],
                "review_status": "machine_extracted",
            },
        )
        if unit_id not in rec["evidence_unit_ids"]:
            rec["evidence_unit_ids"].append(unit_id)
        return eid

    def rel(sid: str, reltype: str, start: str, end: str, uid: str) -> None:
        if start == end:
            return
        rid = stable_id("relation", sid, [reltype, start, end, uid])
        relations[rid] = {
            "relation_id": rid,
            "source_id": sid,
            "relation_type": reltype,
            "source_entity_id": start,
            "target_entity_id": end,
            "evidence_unit_id": uid,
            "review_status": "needs_review",
        }

    for u in units:
        sid = u["source_id"]
        uid = u["unit_id"]
        body = u["text"]
        if u["unit_kind"] == "page":
            continue
        docid = entity(sid, "source_document", sid, sources.get(sid, {}).get("document_number") or sid, uid)
        eu = entity(sid, "evidence_unit", uid, u["unit_kind"] + " — " + (body[:90] if body else ""), uid)
        rel(sid, "CONTAINS", docid, eu, uid)
        for val in dict.fromkeys(LEGAL_REFERENCE.findall(body)):
            rid = entity(sid, "regulation_reference", val, val, uid)
            rel(sid, "REFERENCES", eu, rid, uid)
        for num in dict.fromkeys(FORM.findall(body)):
            val = f"Mẫu {num}"
            rid = entity(sid, "form_reference", num, val, uid)
            rel(sid, "MENTIONS", eu, rid, uid)
        if u["unit_kind"] == "criterion_table_candidate":
            rid = entity(
                sid,
                "criterion_table_candidate",
                uid,
                "Bảng tiêu chí — trang " + str(u["spans"][0]["pdf_page"]),
                uid,
            )
            rel(sid, "HAS_CRITERION_CANDIDATE", eu, rid, uid)
        # Static topic mention candidates; no external entity-linking assumptions.
        for term, typ in TERMS.items():
            if term in body.casefold():
                rid = entity(sid, "topic", typ, term, uid)
                rel(sid, "MENTIONS", eu, rid, uid)
    return list(entities.values()), list(relations.values())


def extract_artifacts(
    root: Path,
    *,
    input_dir: Path,
    output_dir: Path,
    max_pages: int | None = None,
    semantic_client=None,
    semantic_max_units: int | None = None,
    semantic_cache_dir: Path | None = None,
    semantic_workers: int = 1,
    semantic_gleanings: int = 1,
) -> dict:
    manifest = json.loads((input_dir / "manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("complete") and max_pages is None:
        raise RuntimeError("PDF PageArtifact manifest not complete")
    source_info = {
        s.source_id: s.model_dump(mode="json") for s in load_registry(root / "configs/ocop_sources.json")
    }
    snapshot = manifest["input_snapshot_sha256"]
    profile = (
        "none"
        if semantic_client is None
        else semantic_profile(client_identity(semantic_client), semantic_max_units, semantic_gleanings)
    )
    version = hashlib.sha256(
        (VERSION + "|" + snapshot + "|" + profile + "|" + manifest.get("dataset_digest", "")).encode()
    ).hexdigest()[:20]
    output_dir.mkdir(parents=True, exist_ok=True)
    units_file = output_dir / "evidence_units.jsonl"
    facts_file = output_dir / "domain_facts.jsonl"
    entities_file = output_dir / "entities.jsonl"
    relations_file = output_dir / "relations.jsonl"
    files_by_source = {s["source_id"]: input_dir / s["artifact"] for s in manifest["sources"]}
    counts = Counter()
    all_units = []
    facts = []
    page_records = []
    stop = False
    for sid in sorted(files_by_source):
        path = files_by_source[sid]
        with path.open(encoding="utf-8") as f:
            for line in f:
                if max_pages is not None and counts["pages"] >= max_pages:
                    stop = True
                    break
                page = json.loads(line)
                if page["source_id"] != sid:
                    raise ValueError("PageArtifact source mismatch")
                page_records.append(page)
                counts["pages"] += 1
                counts["tables"] += len(page.get("tables", []))
                counts["ocr_pages"] += int(bool(page.get("ocr_engine")))
        if stop:
            break
    furniture_by_page = _page_furniture_lines(page_records)
    for page in page_records:
        sid = page["source_id"]
        generated = page_units(
            page,
            source_kind=source_info[sid]["source_kind"],
            furniture_lines=furniture_by_page.get((sid, int(page["pdf_page"])), {}),
        )
        image_candidates = {
            b.get("block_id"): b.get("image_legend_candidates", []) for b in page.get("blocks", [])
        }
        for unit in generated:
            unit["structured"]["text_reviewed"] = bool(page.get("reviewed"))
            proposals = [
                candidate
                for span in unit["spans"]
                for candidate in image_candidates.get(span.get("block_id"), [])
            ]
            if proposals:
                unit["structured"]["image_legend_candidates"] = proposals
        all_units.extend(generated)
        counts["units"] += len(generated)
        for u in generated:
            if u["unit_kind"] in ("form", "article", "annex", "criterion_table_candidate"):
                facts.append(
                    {
                        "fact_id": stable_id("fact", sid, [u["unit_id"]]),
                        "fact_type": u["unit_kind"],
                        "evidence_unit_id": u["unit_id"],
                        "source_id": sid,
                        "text": u["text"][:3000],
                        "review_status": u["review_status"],
                        "spans": u["spans"],
                        "structured": {k: v for k, v in u["structured"].items() if k != "cells"},
                    }
                )
    from ocop_contracts.table_continuity import possible_continuations

    boundary_hints = []
    ordered_pages = sorted(page_records, key=lambda p: (p["source_id"], int(p["pdf_page"])))
    for previous, current in zip(ordered_pages, ordered_pages[1:]):
        if source_info[current["source_id"]]["source_kind"] in {
            "ocop_framework",
            "ocop_historical",
            "ocop_amendment",
        }:
            boundary_hints.extend(possible_continuations(previous, current, min_columns=2))
    for unit in all_units:
        unit["structured"]["table_continuity"] = [
            hint
            for hint in boundary_hints
            if hint["source_id"] == unit["source_id"]
            and hint["to_pdf_page"] == unit["spans"][0]["pdf_page"]
            and hint["to_table_id"] == unit["structured"].get("table_id")
        ]
    domain_candidates = candidates(all_units, {sid: row["source_kind"] for sid, row in source_info.items()})
    domain_candidates["temporal_candidates"] = temporal_candidates(all_units)
    semantics = extract_semantics(
        all_units,
        {sid: row["source_kind"] for sid, row in source_info.items()},
        domain_candidates,
        source_registry=source_info,
    )
    llm_stats = {
        "enabled": semantic_client is not None,
        "model": profile,
        "processed_unit_count": 0,
        "errors": 0,
    }
    if semantic_client is not None:
        llm_stats["client_identity"] = client_identity(semantic_client)
    if semantic_client is not None:
        proposed = propose(
            all_units,
            semantic_client,
            max_units=semantic_max_units,
            cache_dir=semantic_cache_dir,
            max_workers=semantic_workers,
            gleanings=semantic_gleanings,
        )
        proposed = reconcile(proposed, semantics["business_entities"], semantics["business_relations"])
        for category, name in (
            ("entities", "business_entities"),
            ("relations", "business_relations"),
            ("rules", "business_rules"),
        ):
            semantics[name] = sorted(
                semantics[name] + proposed[category],
                key=lambda row: next(
                    (row[k] for k in ("entity_id", "relation_id", "rule_id") if k in row), ""
                ),
            )
        llm_stats["processed_unit_count"] = proposed["processed_unit_count"]
        llm_stats["errors"] = len(proposed["errors"])
        llm_stats["chunk_count"] = proposed["chunk_count"]
        llm_stats["grounding_dropped"] = proposed["grounding"]
        llm_stats["reconciled"] = proposed["reconciled"]
        llm_stats["eligible_unit_count"] = proposed["eligible_unit_count"]
        llm_stats["selected_unit_count"] = proposed["selected_unit_count"]
        llm_stats["omitted_unit_count"] = len(proposed["omissions"])
        semantics["business_llm_errors"] = proposed["chunk_errors"]
        semantics["business_llm_omissions"] = proposed["omissions"]
        semantics["business_llm_unit_statuses"] = proposed["unit_statuses"]
    # Validate the combined graph, including any opt-in LLM proposals; isolated
    # validation per extractor is insufficient once datasets are merged.
    validate_business_graph(
        [BusinessEntity.model_validate(row) for row in semantics["business_entities"]],
        [BusinessRelation.model_validate(row) for row in semantics["business_relations"]],
        source_registry=source_info,
    )
    quality = audit_knowledge(all_units, semantics)
    quality_tmp = output_dir / "business_quality.json.tmp"
    quality_tmp.write_text(
        json.dumps(quality, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(quality_tmp, output_dir / "business_quality.json")
    ents, rels = extract_entities_relations(all_units, source_info)
    counts["facts"] = len(facts)
    counts["entities"] = len(ents)
    counts["relations"] = len(rels)
    counts.update({key: len(values) for key, values in domain_candidates.items()})
    for path, data in (
        (units_file, all_units),
        (facts_file, facts),
        (entities_file, ents),
        (relations_file, rels),
    ):
        _jsonl_atomic(path, data)
    for name, items in domain_candidates.items():
        _jsonl_atomic(output_dir / f"{name}.jsonl", items)
    for name, items in semantics.items():
        counts[name] = _jsonl_atomic(output_dir / f"{name}.jsonl", items)
    summary = {
        "pipeline_version": VERSION,
        "corpus_version": version,
        "semantic_proposals": llm_stats,
        "source_snapshot_sha256": snapshot,
        "document_registry": {
            sid: {"document_number": s.get("document_number"), "source_kind": s.get("source_kind")}
            for sid, s in source_info.items()
        },
        "counts": dict(sorted(counts.items())),
        "business_quality": "business_quality.json",
        "complete": (
            bool(manifest.get("complete")) and not stop and counts["pages"] == manifest["counts"]["pages"]
        ),
        "status": "machine_extracted_not_verified",
        "files": {
            "evidence_units": units_file.name,
            "domain_facts": facts_file.name,
            "entities": entities_file.name,
            "relations": relations_file.name,
            **{name: f"{name}.jsonl" for name in domain_candidates},
            **{name: f"{name}.jsonl" for name in semantics},
        },
    }
    tmp = output_dir / "manifest.tmp"
    tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, output_dir / "manifest.json")
    return summary


def main():
    ap = argparse.ArgumentParser(
        description="evidence extraction: extract OCOP evidence and graph candidates from page artifacts"
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--input", type=Path, default=Path("data/processed/ocop/pages"))
    ap.add_argument("--output", type=Path, default=Path("data/processed/ocop/knowledge"))
    ap.add_argument("--max-pages", type=int)
    args = ap.parse_args()
    root = args.root.resolve()

    def local(p):
        return p if p.is_absolute() else root / p

    result = extract_artifacts(
        root, input_dir=local(args.input), output_dir=local(args.output), max_pages=args.max_pages
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
