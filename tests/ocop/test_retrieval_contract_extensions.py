"""Additional evidence extraction/4 contracts — written but deliberately not executed here."""
from __future__ import annotations

import json

from ai_core.processing.ocop.knowledge_extract import page_units
from ai_core.processing.ocop.temporal_candidates import temporal_candidates
from ai_core.retrieval.ocop.index_pipeline import build_index, split_units
from ai_core.retrieval.ocop.lookup import exact_lookup


def _page(text: str) -> dict:
    return {
        "source_id": "VN.TEST.QD.2026",
        "pdf_page": 8,
        "extracted_text": text,
        "review_status": "needs_review",
        "tables": [],
    }


def test_temporal_dates_are_candidates_not_legal_assertions():
    unit = page_units(_page("Điều 11. Quyết định này có hiệu lực từ ngày 22 tháng 5 năm 2026."))[1]
    out = temporal_candidates([unit])
    assert any(v["date_candidate"] == "2026-05-22" for v in out)
    assert all(v["is_authoritative"] is False for v in out)
    assert all(v["source_spans"][0]["pdf_page"] == 8 for v in out)


def test_transition_mentioned_without_date_remains_unverified():
    unit = page_units(_page("Điều 12. Quy định chuyển tiếp đối với hồ sơ."))[1]
    rows = temporal_candidates([unit])
    assert len(rows) == 1
    assert rows[0]["date_candidate"] is None
    assert rows[0]["review_status"] == "needs_review"


def test_table_chunking_preserves_rows_and_repeats_table_context():
    body = "\n".join(["Tên tiêu chí | Thang điểm"] + [f"Tiêu chí {i} | {i % 4}" for i in range(30)])
    unit = page_units(_page(""), source_kind="ocop_framework")[0]
    unit["unit_kind"] = "criterion_table_candidate"
    unit["text"] = body
    rows = split_units(unit, max_words=50, overlap=5)
    assert len(rows) > 1
    assert all("Bảng từ VN.TEST.QD.2026" in row for row in rows)
    assert all(any(f"Tiêu chí {i} | {i % 4}" in row for row in rows) for i in range(30))


def test_exact_lookup_joins_candidates_to_evidence(tmp_path):
    kb = tmp_path / "knowledge"
    kb.mkdir()
    unit = page_units(_page("Mẫu số 01. Phiếu đăng ký đánh giá"))[1]
    (kb / "evidence_units.jsonl").write_text(json.dumps(unit, ensure_ascii=False) + "\n", encoding="utf-8")
    row = {
        "candidate_id": "test:form:1",
        "evidence_unit_id": unit["unit_id"],
        "source_id": unit["source_id"],
        "form_number": 1,
        "title": "Phiếu đăng ký đánh giá",
        "review_status": "needs_review",
    }
    (kb / "form_candidates.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    (kb / "manifest.json").write_text(json.dumps({
        "complete": True, "corpus_version": "fixture-version", "counts": {"pages": 1}
    }), encoding="utf-8")
    idx = tmp_path / "index"
    build_index(knowledge=kb, index_dir=idx)
    evidence = exact_lookup(idx, identity=unit["unit_id"], include_candidates=False)
    assert len(evidence) == 1
    assert evidence[0]["spans"][0]["pdf_page"] == 8
    facts = exact_lookup(idx, identity="test:form:1")
    assert len(facts) == 1
    assert facts[0]["record_kind"] == "form_candidates"
    assert facts[0]["source_spans"][0]["pdf_page"] == 8
