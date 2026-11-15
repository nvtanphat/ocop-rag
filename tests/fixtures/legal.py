"""Synthetic literal-source fixtures; no real PDF or OCR gold labels."""

from ai_core.knowledge.ocop.extractor import extract_semantics
from ai_core.processing.ocop.business_candidates import candidates


REGISTRY = {
    "DOC.CURRENT": {"document_number": "26/2026/QĐ-TTg"},
    "DOC.OLD": {"document_number": "148/QĐ-TTg"},
    "DOC.AMEND": {"document_number": "1489/QĐ-TTg"},
    "DOC.RECOGNITION": {"document_number": "525/QĐ-UBND"},
}


def unit(sid, page, text, kind="article"):
    return {
        "source_id": sid,
        "unit_id": f"evidence:{sid}:{page}:{kind}",
        "unit_kind": kind,
        "text": text,
        "structured": {},
        "spans": [{"pdf_page": page, "bbox": [0, 0, 500, 700], "source_sha256": "a" * 64}],
    }


def extract(units, kinds=None, registry=None):
    kinds = kinds or {"DOC.CURRENT": "ocop_framework", "DOC.AMEND": "ocop_amendment"}
    return extract_semantics(units, kinds, candidates(units, kinds), source_registry=registry or REGISTRY)
