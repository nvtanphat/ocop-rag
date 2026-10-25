"""New multi-capability, dependency, recovery and isolation tests.

Synthetic expectations are regression fixtures, not independent SOTA results.
"""

from __future__ import annotations
import json
import pytest

from ai_core.orchestration.ocop.capabilities import TOOL_REGISTRY
from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.planner import build_plan, _ordered_tasks
from ai_core.orchestration.ocop.contracts import Intent, Route
from ai_core.orchestration.ocop.tools import ToolRegistry
from ai_core.orchestration.ocop.workflow import OcopAgent
from ai_core.retrieval.ocop.index_pipeline import create_bm25


def _fixture(tmp_path):
    idx = tmp_path / "data/processed/ocop/index"
    idx.mkdir(parents=True)
    rows = [
        {
            "chunk_id": "a",
            "evidence_unit_id": "u1",
            "source_id": "VN.OCOP.QD26.2026",
            "spans": [{"pdf_page": 19}],
            "review_status": "needs_review",
            "corpus_version": "r1",
            "text_for_bm25": "Tiêu chí OCOP mật ong điểm minh chứng bảng yêu cầu",
        },
        {
            "chunk_id": "b",
            "evidence_unit_id": "u2",
            "source_id": "VN.ND.15.2018",
            "spans": [{"pdf_page": 10}],
            "review_status": "verified",
            "corpus_version": "r1",
            "text_for_bm25": "Giấy chứng nhận cơ sở an toàn thực phẩm ATTP",
        },
    ]
    for filename, records in [("chunks.jsonl", rows), ("structured.jsonl", []), ("evidence_units.jsonl", [])]:
        (idx / filename).write_text(
            "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in records), encoding="utf-8"
        )
    create_bm25(rows, idx / "bm25.json.gz")
    (idx / "manifest.json").write_text(json.dumps({"corpus_version": "r1", "dense": {"enabled": False}}))
    return idx


def test_question_with_taxonomy_criteria_requirements_creates_dependency_dag():
    r = route_query("Mật ong thuộc nhóm nào, cần minh chứng gì để đạt 4 sao?")
    assert {"classify_product", "criteria", "evidence_requirements"} <= set(r.capabilities)
    p = build_plan(r)
    assert (
        p.names.index("lookup_product_subgroup")
        < p.names.index("lookup_criterion")
        < p.names.index("lookup_evidence_requirements")
    )
    assert "search_graph" in p.names
    assert p.max_calls == 5 and len(p.names) <= 5
    assert all(t.name in TOOL_REGISTRY for t in p.tasks)


def test_compliance_and_unspecified_form_retrieves_source_not_random_form():
    r = route_query("Mật ong có bắt buộc giấy ATTP và cần mẫu hồ sơ nào?")
    assert {"sector_compliance", "procedure_form"} <= set(r.capabilities)
    assert "search_regulations" in r.required_tools
    assert "lookup_form" not in r.required_tools


def test_comparison_recognition_is_not_product_name():
    r = route_query("So sánh công nhận sản phẩm 2025 và 2026 tại Huế")
    assert "product_name" not in r.slots
    assert r.slots["region"] == "Huế"
    assert {"recognition", "temporal"} <= set(r.capabilities)
    assert {"lookup_recognition", "resolve_temporal_applicability"} <= set(r.required_tools)


def test_exact_article_and_temporal_are_both_planned():
    r = route_query("Điều 6 QĐ26/2026 có hiệu lực từ ngày nào?")
    assert "exact_article" in r.capabilities
    assert "temporal" in r.capabilities
    assert {"lookup_legal_unit", "resolve_temporal_applicability"} <= set(build_plan(r).names)


def test_followup_over_tool_budget_requests_a_split():
    previous = route_query("Mật ong thuộc nhóm nào, cần minh chứng gì để đạt 4 sao?")
    prev = {
        "last_query": "Mật ong thuộc nhóm nào, cần minh chứng gì để đạt 4 sao?",
        "slots": previous.slots,
        "intent": previous.intent.value,
        "capabilities": previous.capabilities,
    }
    r = route_query("Thế năm 2025?", session=prev)
    assert r.intent == Intent.CLARIFY
    assert r.needs_clarification
    assert "tool_budget_exceeded" in r.reason_codes
    assert r.slots["years"] == ["2025"]


def test_unknown_local_deadline_is_not_answered_with_national_deadline(tmp_path):
    _fixture(tmp_path)
    r = route_query("Nộp hồ sơ OCOP ở Bình Định trước ngày nào?")
    assert r.slots["region"] == "Bình Định"
    reg = ToolRegistry(tmp_path)
    result = reg.dispatch(
        "search_regulations",
        query="Nộp hồ sơ OCOP ở Bình Định trước ngày nào?",
        slots=r.slots,
        context={"business_intent": r.intent.value},
    )
    assert result["status"] == "local_guidance_not_in_corpus"
    assert result["results"] == []


def test_form_without_explicit_id_never_returns_arbitrary_form(tmp_path):
    _fixture(tmp_path)
    result = ToolRegistry(tmp_path).dispatch("lookup_form", query="Mẫu nào?", slots={})
    assert result["status"] == "form_identifier_not_specified"
    assert not result["results"]


def test_requirements_lookup_without_graph_fails_closed(tmp_path):
    _fixture(tmp_path)
    result = ToolRegistry(tmp_path).dispatch(
        "lookup_evidence_requirements",
        query="mật ong cần minh chứng gì?",
        slots={"product_name": "mật ong"},
        context={},
    )
    assert result["status"] == "graph_not_built"
    assert result["results"] == []


def test_tool_coverage_surfaces_missing_business_evidence(tmp_path):
    _fixture(tmp_path)
    agent = OcopAgent(tmp_path)
    answer = agent.ask("Mật ong thuộc nhóm nào, cần minh chứng gì để đạt 4 sao?")
    assert "lookup_product_subgroup" in answer.tools_used
    assert (
        "lookup_evidence_requirements" in answer.tools_used + answer.tools_skipped
    )  # skipped steps are reported, not claimed as used
    assert answer.evidence_coverage["status"] in ("partial", "complete", "none")
    assert answer.tool_trace[0]["step"] == "route"
    assert all("tenant_id" not in json.dumps(x) for x in answer.tool_trace)
    if answer.evidence_coverage["status"] == "partial":
        assert "CHƯA ĐỦ CHỨNG CỨ" in answer.answer


def test_tool_registry_does_not_accept_llm_created_tools(tmp_path):
    _fixture(tmp_path)
    registry = ToolRegistry(tmp_path)
    with pytest.raises(ValueError, match="Unknown or unauthorized"):
        registry.dispatch("shell_exec", query="run command", slots={})
    assert "review_dossier" not in TOOL_REGISTRY
    with pytest.raises(ValueError, match="Unknown or unauthorized"):
        registry.dispatch("review_dossier", query="review", slots={}, context={"authenticated": True})


def test_planner_rejects_unknown_and_over_budget():
    route = Route(intent=Intent.OCOP_OVERVIEW, strategy="hybrid", required_tools=["not_a_tool"])
    with pytest.raises(ValueError):
        build_plan(route)
    with pytest.raises(ValueError):
        _ordered_tasks(("not_a_tool",))
    names = list(TOOL_REGISTRY)[:9]
    with pytest.raises(ValueError, match="budget"):
        build_plan(Route(intent=Intent.MULTIHOP_REASONING, strategy="hybrid", required_tools=names))


def test_agent_clarifies_multicapability_followup_over_tool_budget(tmp_path):
    _fixture(tmp_path)
    agent = OcopAgent(tmp_path)
    first = agent.ask("Mật ong thuộc nhóm nào, cần minh chứng gì để đạt 4 sao?")
    session = {
        "last_query": "Mật ong thuộc nhóm nào, cần minh chứng gì để đạt 4 sao?",
        "intent": first.intent.value,
        "slots": first.route.slots,
        "capabilities": first.route.capabilities,
    }
    follow = agent.ask("Thế năm 2025?", session=session)
    assert follow.route.slots["years"] == ["2025"]
    assert follow.route.intent == Intent.CLARIFY
    assert "tool_budget_exceeded" in follow.route.reason_codes
    assert not follow.tools_used


def test_secondary_tool_gap_never_blocks_the_primary_answer(tmp_path):
    """PLN-01: an article question that also names a form is answered from the article."""
    from ai_core.orchestration.ocop.contracts import Route
    from ai_core.orchestration.ocop.planner import build_plan

    route = Route(
        intent="EXACT_LOOKUP",
        strategy="exact",
        required_tools=["lookup_legal_unit"],
        secondary_tools=["lookup_form"],
    )
    plan = build_plan(route)
    assert plan.required_names == ("lookup_legal_unit",) and plan.optional == frozenset({"lookup_form"})
    agent = OcopAgent(tmp_path)
    state = {
        "query": "q",
        "route": route.model_dump(mode="json"),
        "results": [
            {
                "tool": "lookup_legal_unit",
                "output": {
                    "results": [
                        {
                            "source_id": "S",
                            "evidence_unit_id": "u",
                            "text": "Điều 6 nội dung",
                            "source_spans": [
                                {"pdf_page": 4, "bbox": [0, 0, 1, 1], "source_sha256": "a" * 64}
                            ],
                            "review_status": "verified",
                        }
                    ]
                },
            },
            {
                "tool": "lookup_form",
                "optional": True,
                "output": {"results": [], "status": "incomplete_form_ids", "missing_form_ids": ["1"]},
            },
        ],
    }
    answer = agent.answer(state)["answer"]
    assert answer["status"] != "insufficient_form_scope" and answer["citations"]
    assert answer["optional_gaps"] == ["lookup_form"]
