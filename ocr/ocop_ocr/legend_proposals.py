"""Pixel proposals for a damaged OCR legend; never rewrite text or verify it."""

from __future__ import annotations
import re
from ocop_contracts.ratings import asterisk_quantifier, level_class
import numpy as np


def asterisk_groups(gray):
    """Repeated matching glyph runs, including runs inside a legend line."""
    import cv2
    from .easy_viet_ocr import _looks_like_asterisk, _mask_iou

    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    count, _, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    glyphs = []
    for x, y, w, h, area in stats[1:count]:
        if h < 4 or w < 3 or area < 7 or not 0.35 <= w / h <= 2:
            continue
        mask = ink[y : y + h, x : x + w]
        if _looks_like_asterisk(mask):
            glyphs.append((int(x), int(y), int(w), int(h), mask))
    runs = []
    for glyph in sorted(glyphs, key=lambda g: g[0]):
        found = None
        for run in runs:
            prev = run[-1]
            scale = max(prev[3], glyph[3])
            if (
                0 <= glyph[0] - prev[0] - prev[2] <= 0.75 * scale
                and abs(glyph[1] - prev[1]) <= 0.32 * scale
                and abs(glyph[2] - prev[2]) <= 0.32 * scale
                and abs(glyph[3] - prev[3]) <= 0.32 * scale
                and _mask_iou(glyph[4], prev[4]) >= 0.45
            ):
                found = run
                break
        if found is None:
            runs.append([glyph])
        else:
            found.append(glyph)
    return [
        (
            "*" * len(run),
            [
                min(g[0] for g in run),
                min(g[1] for g in run),
                max(g[0] + g[2] for g in run),
                max(g[1] + g[3] for g in run),
            ],
        )
        for run in runs
        if 3 <= len(run) <= 5
    ]


def propose_legend_images(root, source_info, pages, units):
    """Pair image runs with literal OCR level numbers in the SAME OCR block.

    Only exact source-locked PDF bytes are rendered. An uncertain glyph count
    or number/run alignment yields no proposal, not a guessed standard legend.
    """
    import fitz
    from ocop_contracts.registry import sha256_file

    page_index = {(p["source_id"], int(p["pdf_page"])): p for p in pages}
    hashes = {}
    for unit in units:
        text = unit.get("text") or ""
        if unit.get("unit_kind") == "page" or not re.search(
            r"Dấu\s+sao\s+là\s+yêu\s+cầu\s+tối\s+thiểu", text, re.I
        ):
            continue
        literal = re.findall(
            r"(\*" + asterisk_quantifier() + r")\s*[-–—:]\s*" + level_class(certified=True) + r"\s*sao",
            text,
            re.I,
        )
        if {len(marker) for marker in literal} == {3, 4, 5}:
            continue
        sid = unit["source_id"]
        spec = source_info[sid]
        path = (root / spec["path"]).resolve()
        if not path.is_file():
            continue
        sha = hashes.setdefault(sid, sha256_file(path))
        proposals = []
        with fitz.open(path) as pdf:
            for span in unit.get("spans", []):
                if span.get("source_sha256") != sha:
                    continue
                page = page_index.get((sid, int(span["pdf_page"])))
                blocks = page.get("blocks", []) if page else []
                block = next((b for b in blocks if b.get("block_id") == span.get("block_id")), None)
                if not block or not block.get("bbox"):
                    continue
                # Corrupted OCR stars such as 44% are not level numbers.
                levels = [
                    int(m[1])
                    for m in re.finditer(
                        r"(?<!\d)(" + level_class(certified=True) + r")(?![\d%])", block["text"]
                    )
                ]
                if not levels:
                    continue
                box = fitz.Rect(block["bbox"]) + (-1, -1, 1, 1)
                pix = pdf[int(span["pdf_page"]) - 1].get_pixmap(
                    matrix=fitz.Matrix(300 / 72, 300 / 72), clip=box, colorspace=fitz.csGRAY, alpha=False
                )
                gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
                groups = asterisk_groups(gray)
                if len(groups) != len(levels):
                    continue
                for (marker, rect), level in zip(groups, levels, strict=True):
                    proposals.append(
                        {
                            "text": marker,
                            "star_level_candidate": level,
                            "marker_bbox": [
                                (pix.x + rect[0]) * 72 / 300,
                                (pix.y + rect[1]) * 72 / 300,
                                (pix.x + rect[2]) * 72 / 300,
                                (pix.y + rect[3]) * 72 / 300,
                            ],
                            "pdf_page": span["pdf_page"],
                            "block_id": span["block_id"],
                            "source_sha256": sha,
                            "status": "candidate",
                            "method": "repeated_matching_glyphs_with_same_block_number",
                            "interpretation_verified": False,
                        }
                    )
        if proposals:
            unit.setdefault("structured", {})["image_legend_candidates"] = proposals
    # Independently check cached, deskew-restored option markers against the
    # locked PDF raster. Keep original proposals; disagreements become omissions.
    for sid in sorted({u["source_id"] for u in units}):
        if source_info[sid]["source_kind"] not in {"ocop_framework", "ocop_historical"}:
            continue
        path = (root / source_info[sid]["path"]).resolve()
        if not path.is_file():
            continue
        sha = sha256_file(path)
        with fitz.open(path) as pdf:
            for unit in units:
                if unit["source_id"] != sid or unit.get("unit_kind") == "page":
                    continue
                span = next(iter(unit.get("spans", [])), {})
                if span.get("source_sha256") != sha:
                    continue
                for cell in unit.get("structured", {}).get("cells", []):
                    if not cell.get("image_marker_candidates") or not cell.get("bbox"):
                        continue
                    pix = pdf[int(span["pdf_page"]) - 1].get_pixmap(
                        matrix=fitz.Matrix(300 / 72, 300 / 72),
                        clip=fitz.Rect(cell["bbox"]),
                        colorspace=fitz.csGRAY,
                        alpha=False,
                    )
                    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
                    cell["independent_marker_counts_candidate"] = sorted(
                        {len(m) for m, _ in asterisk_groups(gray)}
                    )


def annotate_page_images(filename, page, source_kind):
    """Image-derived candidates belong to OCR output, before the RAG boundary."""
    from pathlib import Path

    sid = page["source_id"]
    units = []
    blocks = {}
    for index, block in enumerate(page.get("blocks", [])):
        block_id = block.get("block_id")
        if block_id is None:
            continue
        unit = {
            "source_id": sid,
            "unit_kind": "paragraph",
            "text": block.get("text", ""),
            "spans": [
                {"source_sha256": page["source_sha256"], "pdf_page": page["pdf_page"], "block_id": block_id}
            ],
            "structured": {},
        }
        units.append(unit)
        blocks[id(unit)] = block
    if any(c.get("image_marker_candidates") for t in page.get("tables", []) for c in t.get("cells", [])):
        units.append(
            {
                "source_id": sid,
                "unit_kind": "table",
                "text": "",
                "spans": [{"source_sha256": page["source_sha256"], "pdf_page": page["pdf_page"]}],
                "structured": {"cells": [c for t in page.get("tables", []) for c in t.get("cells", [])]},
            }
        )
    if not any(
        re.search(r"Dấu\s+sao\s+là\s+yêu\s+cầu\s+tối\s+thiểu", u["text"], re.I) for u in units
    ) and not any(u["unit_kind"] == "table" for u in units):
        return
    path = Path(filename).resolve()
    propose_legend_images(path.parent, {sid: {"path": str(path), "source_kind": source_kind}}, [page], units)
    for unit in units:
        candidates = unit["structured"].get("image_legend_candidates")
        if candidates:
            blocks[id(unit)]["image_legend_candidates"] = candidates
