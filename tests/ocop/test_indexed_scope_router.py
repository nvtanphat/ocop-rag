"""Regression checks for corpus-backed scope recovery and the tool budget."""
from __future__ import annotations

import json

import pytest

from ai_core.orchestration.ocop.contracts import Intent, Route
from ai_core.orchestration.ocop.answer import assemble
from ai_core.orchestration.ocop.planner import MAX_TOOLS, build_plan
from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.tools import ToolRegistry
from ai_core.retrieval.ocop.index_pipeline import create_bm25
from ai_core.retrieval.ocop.search import query_content_bigram_coverage
from ai_core.orchestration.ocop.verification import verify_claims


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")


def _index(root, texts):
    index_dir = root / "data/processed/ocop/index"
    chunks = [{
        "chunk_id": f"chunk-{i}",
        "evidence_unit_id": f"evidence-{i}",
        "source_id": "VN.TEST.SOURCE",
        "text_for_bm25": text,
        "review_status": "needs_review",
        "corpus_version": "scope-fixture",
        "spans": [{"pdf_page": 1, "bbox": [1, 2, 3, 4], "source_sha256": "a" * 64}],
    } for i, text in enumerate(texts)]
    _write_jsonl(index_dir / "chunks.jsonl", chunks)
    bm25 = create_bm25(chunks, index_dir / "bm25.json.gz")
    (index_dir / "manifest.json").write_text(json.dumps({
        "corpus_version": "scope-fixture",
        "counts": {"chunks": len(chunks)},
        "bm25": bm25,
        "dense": {"enabled": False},
    }), encoding="utf-8")
    return index_dir


def test_content_bigram_coverage_is_accent_folded_and_excludes_question_words(tmp_path):
    index_dir = _index(tmp_path, ["Hợp tác xã tham gia chương trình OCOP"])
    query = "Hợp tác xã cần làm gì để tham gia chương trình?"

    assert query_content_bigram_coverage(index_dir, query) == 1.0


def test_indexed_content_coverage_reopens_only_a_keyword_rejection(tmp_path):
    index_dir = _index(tmp_path, ["Cách ghi hạn sử dụng trên nhãn hàng hóa"])
    query = "Cách ghi hạn sử dụng trên nhãn?"
    score = query_content_bigram_coverage(index_dir, query)

    assert score >= 0.60
    assert route_query(query).intent == Intent.OUT_OF_SCOPE
    recovered = route_query(query, indexed_content_bigram_coverage=lambda _: score)
    assert recovered.intent == Intent.OCOP_OVERVIEW
    assert recovered.required_tools == ["search_regulations"]
    assert "indexed_content_bigram_scope_recovery" in recovered.reason_codes

    assert route_query(query, indexed_content_bigram_coverage=lambda _: 0.59).intent == Intent.OUT_OF_SCOPE


def test_explicitly_off_topic_question_stays_blocked_even_if_callback_scores_high():
    route = route_query("Giá bitcoin hôm nay?", indexed_content_bigram_coverage=lambda _: 1.0)

    assert route.intent == Intent.OUT_OF_SCOPE
    assert "indexed_content_bigram_scope_recovery" not in route.reason_codes


@pytest.mark.parametrize("business_intent", ["PROCEDURE_FORM", "CRITERIA_LOOKUP", "OCOP_OVERVIEW"])
def test_general_text_search_does_not_implicitly_pin_decision_version(
        tmp_path, monkeypatch, business_intent):
    seen = {}

    def capture_search(index_dir, query, **kwargs):
        seen.update(query=query, kwargs=kwargs)
        return []

    monkeypatch.setattr("ai_core.orchestration.ocop.tools.search", capture_search)
    registry = ToolRegistry(tmp_path)
    registry.dispatch("search_regulations", query="thủ tục đăng ký xuất khẩu", slots={},
                      context={"business_intent": business_intent})

    assert seen["query"] == "thủ tục đăng ký xuất khẩu"
    assert seen["kwargs"]["source_id"] is None


def test_distinct_chunks_of_one_evidence_unit_keep_exact_citations():
    first = {
        "chunk_id": "chunk-article-start",
        "evidence_unit_id": "evidence-article-22",
        "source_id": "VN.ND.15.2018",
        "review_status": "verified",
        "text": "Cơ quan nước xuất khẩu gửi hồ sơ đăng ký.",
        "source_spans": [{"pdf_page": 18, "bbox": [10, 20, 100, 40], "source_sha256": "a" * 64}],
    }
    sibling = {
        **first,
        "chunk_id": "chunk-article-end",
        "text": "Danh sách cơ sở sản xuất, kinh doanh đăng ký xuất khẩu.",
        "source_spans": [{"pdf_page": 18, "bbox": [10, 100, 100, 120], "source_sha256": "a" * 64}],
    }
    response = assemble("thủ tục đăng ký xuất khẩu", [{
        "tool": "search_regulations", "output": {"results": [first, sibling]},
    }])

    assert [item["chunk_id"] for item in response["citations"]] == [
        "chunk-article-start", "chunk-article-end",
    ]
    assert all(item["evidence_unit_id"] == "evidence-article-22" for item in response["citations"])
    verified = verify_claims(
        "Cơ quan nước xuất khẩu gửi hồ sơ đăng ký [S1]",
        [response["citations"][0]], [first, sibling],
    )
    assert verified["status"] == "verified"


def test_citation_marker_alone_cannot_support_a_new_committee_claim():
    row = {
        "chunk_id": "decision-preamble",
        "evidence_unit_id": "evidence-decision-preamble",
        "source_id": "VN.HAIPHONG.QD525.2026",
        "review_status": "verified",
        "text": "Theo đề nghị của Hội đồng đánh giá, phân hạng sản phẩm OCOP thành phố Hải Phòng.",
        "source_spans": [{"pdf_page": 1, "bbox": [10, 20, 200, 40], "source_sha256": "b" * 64}],
    }

    class UnsupportedAnswer:
        def chat(self, system, prompt, *, max_tokens):
            return "Hội đồng gồm đại diện Sở Nông nghiệp và Ủy ban cấp tỉnh [S1]."

    response = assemble("Ai tham gia Hội đồng đánh giá?", [{
        "tool": "search_regulations", "output": {"results": [row]},
    }], llm=UnsupportedAnswer())

    assert response["status"] == "citation_verification_failed"
    assert "Chỉ cung cấp bản trích xuất" in response["answer"]


def test_planner_enforces_five_registered_tool_calls():
    assert MAX_TOOLS == 5
    route = Route(intent=Intent.MULTIHOP_REASONING, strategy="hybrid", required_tools=[
        "search_regulations", "search_graph", "lookup_legal_unit", "lookup_criterion",
        "lookup_form", "lookup_recognition",
    ])

    with pytest.raises(ValueError, match="tool budget"):
        build_plan(route)


def test_router_clarifies_instead_of_planning_more_than_five_calls():
    route = route_query("Mật ong thuộc nhóm nào, cần minh chứng gì để đạt 4 sao năm 2026?")

    assert route.intent == Intent.CLARIFY
    assert route.needs_clarification
    assert "tool_budget_exceeded" in route.reason_codes
    assert build_plan(route).names == ()

