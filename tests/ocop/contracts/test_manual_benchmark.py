"""Source-locked manual benchmark and business-router regression checks."""

from pathlib import Path

import pytest

from ai_core.orchestration.ocop.contracts import Intent
from ai_core.orchestration.ocop.router import route_query
from tools.evaluate_manual_pdf import load_gold, score_case

ROOT = Path(__file__).resolve().parents[3]


def test_normative_star_is_not_a_recognition_list_query():
    for q in (
        "Theo quy định OCOP, điều kiện để sản phẩm được công nhận 5 sao là gì?",
        "Sản phẩm cần đáp ứng những điều kiện gì để được công nhận 4 sao OCOP?",
    ):
        route = route_query(q)
        assert route.intent == Intent.CRITERIA_LOOKUP
        assert "lookup_recognition" not in route.required_tools
        assert "search_regulations" in route.required_tools
    past = route_query("Hải Phòng đã công nhận bao nhiêu sản phẩm OCOP 4 sao?")
    assert past.intent == Intent.RECOGNITION_LOOKUP
    assert "lookup_recognition" in past.required_tools


def test_independent_manual_benchmark_is_source_locked():
    if not (ROOT / "data/evaluations/ocop/manual_pdf_benchmark.jsonl").is_file():
        pytest.skip("no manual PDF benchmark has been provided")
    gold, mapping = load_gold(ROOT)
    assert gold and mapping
    assert len({r["id"] for r in gold}) == len(gold)
    assert all(r["gold_label_origin"] == "manual_pdf_read_not_pipeline" for r in gold)


def test_citation_matching_measures_page_not_llm_answer():
    gold = {"evidence": [{"document_id": "OCOPPDF_05", "pdf_page": 2}]}
    mapping = {"OCOPPDF_05": "VN.HUE.QD797.2026"}
    correct = score_case(gold, [{"source_id": "VN.HUE.QD797.2026", "pdf_page": 2}], mapping)
    wrong = score_case(gold, [{"source_id": "VN.HAIPHONG.QD525.2026", "pdf_page": 2}], mapping)
    assert correct["page_hit"] is True
    assert wrong["page_hit"] is False
