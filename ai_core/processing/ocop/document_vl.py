"""Optional local PaddleOCR-VL document parsing adapter.

OCR/VLM output remains an unverified candidate. Source geometry is converted to
PDF points; missing or invalid model geometry is kept missing, never invented.
Model assets must be provisioned locally and are fingerprinted for cache lineage.
"""
from __future__ import annotations

from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
import hashlib
import os

import numpy as np

from ai_core.processing.ocop.ocr_extractor import OCRResult
from ai_core.processing.ocop.registry import sha256_file
from ai_core.processing.ocop.structure_engine import parse_html_cells


class _PlainHTML(HTMLParser):
    """Extract readable table text without decoding source entities twice."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, text: str):
        if text:
            self.parts.append(text)

    def handle_starttag(self, tag: str, attrs):
        if tag in ("br", "p", "div", "li"):
            self.parts.append("\n" if tag != "br" else " ")

    def handle_endtag(self, tag: str):
        if tag in ("td", "th"):
            self.parts.append(" | ")
        elif tag == "tr":
            self.parts.append("\n")


def table_plaintext(html: str) -> str:
    parser = _PlainHTML()
    parser.feed(html)
    parser.close()
    return " ".join("".join(parser.parts).split())


def _local_model_dir(env_name: str) -> Path:
    configured = os.environ.get(env_name, "").strip()
    if not configured:
        raise RuntimeError(f"paddleocr_vl_local_model_required:set_{env_name}")
    path = Path(configured).expanduser().resolve()
    if not path.is_dir():
        raise RuntimeError(f"paddleocr_vl_model_dir_not_found:{env_name}")
    if not any(item.is_file() and not item.is_symlink() for item in path.rglob("*")):
        raise RuntimeError(f"paddleocr_vl_model_dir_empty:{env_name}")
    return path


def _directory_signature(path: Path) -> dict[str, Any]:
    files = sorted(
        (item for item in path.rglob("*") if item.is_file() and not item.is_symlink()),
        key=lambda item: item.relative_to(path).as_posix(),
    )
    digest = hashlib.sha256()
    for item in files:
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(item)))
    return {"files": len(files), "sha256": digest.hexdigest()}


def runtime_signature(version: str) -> dict[str, Any]:
    """Fingerprint local model bytes and fixed inference settings for page caches."""
    if version not in ("v1.5", "v1.6"):
        raise ValueError("unsupported_paddleocr_vl_pipeline_version")
    vl_dir = _local_model_dir("OCOP_PADDLE_VL_MODEL_DIR")
    layout_dir = _local_model_dir("OCOP_PADDLE_VL_LAYOUT_MODEL_DIR")
    return {
        "pipeline_version": version,
        "backend": "native",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "decode": {"temperature": 0.0, "top_p": 1.0},
        "vl_model": _directory_signature(vl_dir),
        "layout_model": _directory_signature(layout_dir),
    }


@lru_cache(maxsize=2)
def _get_vl_model(version: str, layout_dir: str, vl_dir: str):
    from paddleocr import PaddleOCRVL

    # Explicit local backend/paths prevent implicit downloads or remote calls.
    return PaddleOCRVL(
        pipeline_version=version,
        vl_rec_backend="native",
        vl_rec_model_dir=vl_dir,
        layout_detection_model_dir=layout_dir,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_layout_detection=True,
    )


def load_vl_model(version: str = "v1.6"):
    """Load configured local model assets once, allowing callers to fail fast."""
    if version not in ("v1.5", "v1.6"):
        raise ValueError("unsupported_paddleocr_vl_pipeline_version")
    layout_dir = _local_model_dir("OCOP_PADDLE_VL_LAYOUT_MODEL_DIR")
    vl_dir = _local_model_dir("OCOP_PADDLE_VL_MODEL_DIR")
    return _get_vl_model(version, str(layout_dir), str(vl_dir))


def _pdf_bbox(raw: Any, width_px: int, height_px: int, page) -> tuple[list[float] | None, str | None]:
    """Convert model pixels to PDF points, retaining invalid geometry as absent."""
    if width_px <= 0 or height_px <= 0:
        return None, "vl_image_size_invalid"
    try:
        arr = np.asarray(raw, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return None, "vl_block_bbox_invalid"
    if arr.size < 4 or arr.size % 2 or not np.isfinite(arr).all():
        return None, "vl_block_bbox_invalid"
    if arr.size == 4:
        x0, y0, x1, y1 = (float(value) for value in arr.reshape(4))
    else:
        points = arr.reshape(-1, 2)
        x0, y0 = points.min(axis=0)
        x1, y1 = points.max(axis=0)
    if x0 >= x1 or y0 >= y1:
        return None, "vl_block_bbox_invalid"
    if x1 <= 0 or y1 <= 0 or x0 >= width_px or y0 >= height_px:
        return None, "vl_block_bbox_out_of_image"

    warning = None
    clipped = [max(0.0, x0), max(0.0, y0), min(float(width_px), x1), min(float(height_px), y1)]
    if clipped != [x0, y0, x1, y1]:
        warning = "vl_block_bbox_clipped_to_image"
    width_pt = float(page.rect.width)
    height_pt = float(page.rect.height)
    if width_pt <= 0 or height_pt <= 0:
        return None, "vl_page_size_invalid"
    bbox = [
        round(clipped[0] / width_px * width_pt, 2),
        round(clipped[1] / height_px * height_pt, 2),
        round(clipped[2] / width_px * width_pt, 2),
        round(clipped[3] / height_px * height_pt, 2),
    ]
    return bbox, warning


def _result_payload(output: Any) -> dict:
    payload = getattr(output, "json", output)
    if callable(payload):
        payload = payload()
    if isinstance(payload, dict):
        payload = payload.get("res", payload)
    if not isinstance(payload, dict):
        raise ValueError("unsupported_paddleocr_vl_result")
    return payload


def parse_vl_results(results, image, page) -> tuple[OCRResult, list[dict]]:
    """Parse the public PaddleOCR-VL result contract with source PDF anchors.

    The result list follows model reading order. Blocks with bad/missing boxes
    retain their text and carry ``bbox=None`` plus a warning for human review.
    """
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("invalid_paddleocr_vl_image_size")
    blocks: list[dict] = []
    tables: list[dict] = []
    warnings: list[str] = []

    for output in results:
        parsed = _result_payload(output).get("parsing_res_list")
        if not isinstance(parsed, list):
            raise ValueError("missing_parsing_res_list_from_paddleocr_vl")
        for entry_index, entry in enumerate(parsed):
            if not isinstance(entry, dict):
                warnings.append("vl_parsing_entry_invalid")
                continue

            raw_bbox = entry.get("block_bbox")
            if raw_bbox is None:
                bbox, bbox_warning = None, "vl_block_bbox_missing"
            else:
                bbox, bbox_warning = _pdf_bbox(raw_bbox, width, height, page)
            if bbox_warning:
                warnings.append(bbox_warning)

            raw_label = entry.get("block_label", "text")
            label = str(raw_label or "text").strip().lower() or "text"
            raw_content = entry.get("block_content")
            if raw_content is not None and not isinstance(raw_content, str):
                warnings.append("vl_block_content_not_text")
                value = ""
            else:
                value = raw_content or ""

            if label == "table":
                html = value if "<table" in value.casefold() else ""
                cells: list[dict] = []
                n_rows = n_cols = 0
                table_warnings = ["vl_table_cell_coordinates_unknown", "verify_points_asterisks_and_merges"]
                if html:
                    try:
                        cells, n_rows, n_cols = parse_html_cells(html)
                    except ValueError as exc:
                        table_warnings.append(f"vl_table_html_unparsed:{str(exc)[:100]}")
                else:
                    table_warnings[0] = "vl_table_no_html"
                if bbox is None:
                    table_warnings.append("vl_table_bbox_unavailable")
                tables.append(
                    {
                        "table_id": f"table:paddle_vl:{len(tables)}",
                        "method": "paddleocr_vl",
                        "bbox": bbox,
                        "row_count": n_rows or None,
                        "col_count": n_cols or None,
                        "cells": cells,
                        "html": html,
                        "review_status": "needs_review",
                        "candidate_only": True,
                        "warnings": table_warnings,
                    }
                )
                text = table_plaintext(html) if html else value
            else:
                text = value

            if text.strip():
                provider_order = entry.get("block_order")
                order = provider_order if isinstance(provider_order, int) and provider_order >= 0 else entry_index
                block = {
                    "block_id": f"vl:{entry_index}",
                    "text": text.strip(),
                    "bbox": bbox,
                    "method": "paddleocr_vl",
                    "confidence": None,
                    "order": order,
                    "layout_label": label,
                    "review_status": "needs_review",
                    "candidate_only": True,
                }
                provider_id = entry.get("block_id")
                if provider_id is not None:
                    block["provider_block_id"] = str(provider_id)
                if bbox is None:
                    block["location_warning"] = bbox_warning or "vl_block_bbox_unavailable"
                blocks.append(block)

    return OCRResult(blocks, "paddle_vl", sorted(set(warnings)), list(blocks)), tables


def run_vl(image, page, *, model: Any = None, version: str = "v1.6"):
    if version not in ("v1.5", "v1.6"):
        raise ValueError("unsupported_paddleocr_vl_pipeline_version")
    if model is None:
        pipeline = load_vl_model(version)
    else:
        pipeline = model
    output = pipeline.predict(
        np.asarray(image.convert("RGB")),
        temperature=0.0,
        top_p=1.0,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_layout_detection=True,
    )
    return parse_vl_results(output, image, page)
