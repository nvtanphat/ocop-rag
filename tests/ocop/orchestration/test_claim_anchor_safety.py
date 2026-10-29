"""Deterministic adversarial probes: a real quote is not semantic support."""

import pytest

from ai_core.orchestration.ocop.answer import _judge_claims
from ai_core.orchestration.ocop.entailment import anchored


def judge(claim, source, *, quote=None, question="", status="verified", catalog=None):
    row = {"source_id": "DOC", "evidence_unit_id": "unit", "text": source,
           "review_status": status, "source_spans": [{"pdf_page": 1}]}
    citation = {"source_id": "DOC", "evidence_unit_id": "unit", "pdf_page": 1,
                "review_status": status}
    return _judge_claims([(claim, [1], quote or source)], [citation], [row], catalog=catalog, question=question)


@pytest.mark.parametrize("claim,source,question", [
    ("Đơn vị ALPHA xuất khẩu toàn bộ sản phẩm.", "Đơn vị ALPHA sản xuất sản phẩm.", ""),
    ("Đơn vị BETA là đơn vị sản xuất của sản phẩm ALPHA.",
     "Đơn vị ALPHA là đơn vị sản xuất của sản phẩm BETA.", ""),
    ("Phải nộp bản giấy.", "Không phải nộp bản giấy.", ""),
    ("Quá 90 điểm.", "Không quá 90 điểm.", ""),
    ("Hồ sơ nộp trong 99 ngày.", "Hồ sơ nộp trong 15 ngày.", "Hồ sơ nộp trong 99 ngày phải không?"),
    ("Nộp 2 bản giấy và 1 bản điện tử.", "Nộp 1 bản giấy và 2 bản điện tử.", ""),
    ("Sản phẩm ALPHA đạt 5 sao.", "Sản phẩm ALPHA đạt 3 sao. Sản phẩm BETA đạt 5 sao.", ""),
    ("Sản phẩm ALPHA được công nhận năm 2026.",
     "Quyết định 123/2026. Sản phẩm ALPHA được công nhận năm 2025.", ""),
])
def test_real_quote_does_not_launder_new_facts_negation_or_numeric_roles(claim, source, question):
    accepted, rejected = judge(claim, source, question=question)
    assert not accepted and rejected


def test_quote_matching_preserves_punctuation_instead_of_joining_clauses():
    source = "Không. Hồ sơ được chấp nhận."
    assert not anchored("Hồ sơ không được chấp nhận.", "Không Hồ sơ được chấp nhận", source)


def test_an_invented_provided_quote_is_rejected_even_when_the_claim_itself_is_exact():
    accepted, rejected = judge("Hồ sơ nộp trong 15 ngày.", "Hồ sơ nộp trong 15 ngày.",
                               quote="Đây là một đoạn trích không tồn tại.")
    assert not accepted and rejected


@pytest.mark.parametrize("source", [
    "Hồ sơ nộp trong 15 ngày.",
    "Không phải nộp bản giấy.",
    "Nộp 1 bản giấy và 2 bản điện tử.",
])
def test_exact_source_statement_remains_publishable(source):
    accepted, rejected = judge(source, source)
    assert accepted and not rejected


def test_generic_rule_exception_cannot_override_a_misbound_verified_rating():
    from ai_core.orchestration.ocop.catalog import EntityCatalog

    catalog = EntityCatalog({"entities": {"product": [{"label": "OTHER", "source_ids": []}]}})
    accepted, rejected = judge("Sản phẩm ALPHA đạt 5 sao.",
                               "Sản phẩm ALPHA đạt 3 sao. Sản phẩm BETA đạt 5 sao.", catalog=catalog)
    assert not accepted and rejected


def test_sensitive_guard_keeps_cells_of_the_same_checked_record_together():
    from ai_core.orchestration.ocop.verification import check_sensitive_claims

    rows = [{"source_id": "DOC", "evidence_unit_id": f"u{i}", "text": text,
             "review_status": "verified", "graph_node_ids": ["record"]}
            for i, text in enumerate(["Sản phẩm ALPHA", "4 sao"], 1)]
    citations = [{"source_id": "DOC", "evidence_unit_id": row["evidence_unit_id"]} for row in rows]
    verdict = check_sensitive_claims("Sản phẩm ALPHA đạt 4 sao [S1][S2].", rows, citations)
    assert not verdict["unsupported_score_or_star_claims"]


def test_semantic_review_cannot_quote_synthetic_context_appended_to_original_text():
    import json
    from ai_core.orchestration.ocop.entailment import review

    source = "Hồ sơ nộp trong 15 ngày."
    excerpt = source + "\nDOC.2026"
    class Judge:
        def chat_structured(self, *args, **kwargs):
            return json.dumps({"verdicts": [{"id": 0, "entails": True, "quote": excerpt}]})
    assert review(Judge(), [{"claim": source, "excerpt": excerpt, "quote_sources": [source]}]) == {}


def _locator_judge(claim, locator):
    source = "Hồ sơ nộp trong 15 ngày."
    row = {"source_id": "VN.OCOP.QD26.2026", "evidence_unit_id": "unit", "text": source, "review_status": "verified",
           "source_spans": [{"pdf_page": 1}], **({"resolved_locator": locator} if locator else {})}
    citation = {"source_id": "VN.OCOP.QD26.2026", "evidence_unit_id": "unit", "pdf_page": 1, "review_status": "verified"}
    return _judge_claims([(claim, [1], source)], [citation], [row], question="")[1][0]["reasons"]


def test_the_article_a_tool_resolved_grounds_a_claim_that_names_it_but_a_wrong_article_is_not_grounded():
    claim = "Điều 6 quy định hồ sơ nộp trong 15 ngày."
    assert _locator_judge(claim, None) == ["grounding_numbers_missing"]  # nothing says the passage sits in Điều 6
    assert _locator_judge(claim, {"article_id": "6"}) == ["needs_semantic_entailment_check"]  # numbers pass; meaning is reviewed
    assert _locator_judge(claim.replace("Điều 6", "Điều 7"), {"article_id": "6"}) == ["grounding_numbers_missing"]


def test_the_sheet_and_criterion_a_tool_resolved_ground_a_claim_that_names_them():
    claim = "Phiếu 1 mục 1.1: hồ sơ nộp trong 15 ngày."
    assert _locator_judge(claim, None) == ["grounding_numbers_missing"]
    assert _locator_judge(claim, {"sheet_number": "1", "criterion_id": "1.1"}) == ["needs_semantic_entailment_check"]
    wrong = claim.replace("Phiếu 1", "Phiếu 3")
    assert _locator_judge(wrong, {"sheet_number": "2", "criterion_id": "1.1"}) == ["grounding_numbers_missing"]


def test_the_semantic_review_is_told_which_document_a_deictic_reference_points_to():
    import json

    from ai_core.orchestration.ocop.answer import _document_label
    from ai_core.orchestration.ocop.entailment import review

    assert _document_label("VN.OCOP.QD26.2026") == "26/2026/QĐ-TTg"
    assert _document_label("NO.SUCH.SOURCE") == "NO.SUCH.SOURCE"
    seen = []

    class Judge:
        def chat_structured(self, system, user, **kwargs):
            seen.append((system, user))
            return json.dumps({"verdicts": []})

    item = {"claim": "Quyết định 26/2026 có hiệu lực từ ngày 22/5/2026.", "excerpt": "Quyết định này có hiệu lực."}
    review(Judge(), [{**item, "document": "26/2026/QĐ-TTg"}])
    review(Judge(), [item])
    assert "VĂN BẢN CHỨA ĐOẠN TRÍCH: 26/2026/QĐ-TTg" in seen[0][1] and "VĂN BẢN CHỨA ĐOẠN TRÍCH" not in seen[1][1]
    assert "Quyết định này" in seen[0][0]


def test_a_legal_unit_lookup_marks_each_passage_with_the_article_it_was_fetched_under():
    from pathlib import Path

    from ai_core.orchestration.ocop.tools import ToolRegistry

    root = Path(__file__).resolve().parents[3]
    out = ToolRegistry(root).dispatch(
        "lookup_legal_unit",
        query="Điều 6 Quyết định 26/2026",
        slots={"document_code": "26/2026", "article_id": "6"},
        context={"retrieval_mode": "sparse"},
    )
    assert out["results"] and all(r["resolved_locator"] == {"article_id": "6"} for r in out["results"])
