"""Source-grounded page-level OCR/table coverage diagnostics.

Numbers here indicate *completeness signals*, not correctness or legal approval.
"""

from __future__ import annotations
import re
from ocop_contracts.ratings import asterisk_quantifier

_SCORE = re.compile(r"^\s*(?:\d{1,3})(?:[,.]0+)?\s*$")
_STARS = re.compile(r"\*" + asterisk_quantifier())


def score_page_quality(
    profile: dict, blocks: list[dict], tables: list[dict], word_blocks: list[dict] | None = None
) -> dict:
    total = sum(len(t.get("cells") or []) for t in tables)
    covered = sum(bool(str(c.get("text") or "").strip()) for t in tables for c in t.get("cells") or [])
    positioned = sum(c.get("bbox") is not None for t in tables for c in t.get("cells") or [])
    blank_score = 0
    score_candidates = 0
    star_mentions = 0
    missing_table_boxes = 0
    for t in tables:
        cells = t.get("cells") or []
        cols = t.get("col_count")
        if t.get("bbox") is None:
            missing_table_boxes += 1
        for c in cells:
            txt = str(c.get("text") or "")
            star_mentions += len(_STARS.findall(txt))
            if cols is not None and cols >= 2 and c.get("col") == cols - 1:
                score_candidates += int(bool(_SCORE.fullmatch(txt)))
                blank_score += int(not txt.strip())
    text = "\n".join(str(b.get("text") or "") for b in blocks)
    star_mentions += len(_STARS.findall(text))
    conf = [b.get("confidence") for b in blocks if isinstance(b.get("confidence"), (int, float))]
    return {
        "page_class": profile.get("page_class"),
        "table_regions": len(tables),
        "table_cells": total,
        "table_cells_with_text": covered,
        "table_cells_with_bbox": positioned,
        "table_text_coverage": round(covered / total, 4) if total else None,
        "potential_score_cells_blank": blank_score,
        "strict_numeric_score_candidates": score_candidates,
        "critical_star_markers_observed": star_mentions,
        "mean_block_ocr_confidence": round(sum(conf) / len(conf), 4) if conf else None,
        "table_region_bbox_missing": missing_table_boxes,
        "requires_manual_score_validation": bool(tables),
        "quality_is_not_legal_verification": True,
    }


def refresh_attention(artifact: dict) -> dict:
    """Recompute diagnostics after cache lookup without changing text or boxes."""
    quality = score_page_quality(
        artifact.get("profile", {}),
        artifact.get("blocks", []),
        artifact.get("tables", []),
        artifact.get("ocr_words", []),
    )
    artifact["page_quality"] = quality
    artifact["ocr_confidence_mean"] = quality["mean_block_ocr_confidence"]
    flags = set(artifact.get("warnings", []))
    if artifact.get("profile", {}).get("needs_ocr_review") and not artifact.get("ocr_engine"):
        flags.add("ocr_required_but_not_executed")
    if quality["potential_score_cells_blank"]:
        flags.add("potential_score_cells_blank")
    if quality["mean_block_ocr_confidence"] is not None and quality["mean_block_ocr_confidence"] < 0.8:
        flags.add("low_ocr_confidence")
    if any(c.get("score_ocr_candidates") for t in artifact.get("tables", []) for c in t.get("cells", [])):
        flags.add("unverified_score_ocr_candidates")
    artifact["ocr_attention"] = sorted(flags)
    artifact["needs_human_verification"] = bool(
        flags
        or artifact.get("ocr_engine")
        or artifact.get("tables")
        or artifact.get("review_status") == "needs_review"
    )
    return artifact
