"""Read-only source integration checks against the actual bundled source PDFs."""

from __future__ import annotations

import json
from pathlib import Path

from ai_core.processing.ocop_audit import audit
from ocop_contracts.registry import compare_lock, load_registry, snapshot

ROOT = Path(__file__).resolve().parents[2]


def test_locked_source_files_and_page_coverage():
    sources = load_registry(ROOT / "configs/ocop_sources.json")
    assert len(sources) == 12
    locked = json.loads((ROOT / "configs/ocop_sources.lock.json").read_text(encoding="utf-8"))
    compare_lock(snapshot(ROOT, sources), locked)


def test_real_corpus_read_only_profile_counts():
    result = audit(ROOT, ROOT / "configs/ocop_sources.json", ROOT / "configs/ocop_sources.lock.json")
    assert result["source_count"] == 12
    assert result["page_count"] == 583
    assert result["pages_needing_ocr_review"] == 315
    assert len({(x["source_id"], x["pdf_page"]) for x in result["pages"]}) == 583
    assert result["status"] == "audited_not_ingested"
