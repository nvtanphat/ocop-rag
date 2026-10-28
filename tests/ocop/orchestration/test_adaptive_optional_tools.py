"""Exact record lookups use their structured identity, with bounded optional recovery."""

import pytest

from ai_core.orchestration.ocop.catalog import EntityCatalog
from ai_core.orchestration.ocop.contracts import Intent, Route
from ai_core.orchestration.ocop.evidence_grader import grade_evidence
from ai_core.orchestration.ocop.planner import build_plan, recovery_safe
from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.workflow import OcopAgent

NAMES = ["Gạo ALPHA", "Gạo BETA"]
QUESTION = "ALPHA và BETA thuộc chủ thể nào theo quyết định 900?"


def records(*, source="VN.TEST.QD900.2044", verified=True):
    return [
        {
            "text": text,
            "source_id": source,
            "evidence_unit_id": f"unit-{index}-{field}",
            "source_spans": [{"pdf_page": 2, "bbox": [0, 0, 1, 1], "source_sha256": "a" * 64}],
            "review_status": "verified" if verified else "needs_review",
            "graph_node_type": "RecognitionRecord",
            "graph_node_ids": [f"record-{index}", f"product-{index}"],
        }
        for index, name in enumerate(NAMES)
        for field, text in enumerate([name, "Hợp tác xã Thử Nghiệm"])
    ]


def route(question=QUESTION):
    catalog = EntityCatalog({"entities": {"product": [{"label": n} for n in NAMES]}})
    return route_query(question, catalog=catalog)


def grade(rows):
    return grade_evidence(
        QUESTION,
        [{"tool": "lookup_recognition", "output": {"results": rows, "status": "ok"}}],
        slots=route().slots,
        expected_tools=["lookup_recognition"],
    )


def test_verified_exact_records_are_not_lost_to_cell_level_word_overlap():
    result = grade(records())
    assert result["status"] == "sufficient_for_generation"
    assert result["missing_tools"] == []
    assert result["tool_grades"][0]["structured_resolved"]


def test_known_full_and_partial_names_are_not_two_uncovered_tasks():
    question = "Gạo ALPHA và BETA thuộc chủ thể nào theo quyết định 900?"
    result = grade_evidence(
        question,
        [{"tool": "lookup_recognition", "output": {"results": records(), "status": "ok"}}],
        slots=route(question).slots,
        expected_tools=["lookup_recognition"],
    )
    assert result["status"] == "sufficient_for_generation"
    assert result["uncovered_parts"] == []


@pytest.mark.parametrize("rows", [records(source="VN.TEST.QD901.2044"), records(verified=False)])
def test_identity_resolution_cannot_bypass_source_or_verification_scope(rows):
    assert not grade(rows)["verified_business_resolution"]


def test_partial_identity_set_is_not_a_complete_structured_lookup():
    assert not grade(records()[:2])["verified_business_resolution"]


def execute(tmp_path, monkeypatch, *, question=QUESTION, primary=None):
    agent = OcopAgent(tmp_path)
    calls = []

    def dispatch(name, **kwargs):
        calls.append((name, kwargs))
        if name == "lookup_recognition":
            return primary if primary is not None else {"results": records(), "status": "ok"}
        return {"results": [], "status": "no_results"}

    monkeypatch.setattr(agent.tools, "dispatch", dispatch)
    selected = route(question)
    state = {"query": question, "route": selected.model_dump(mode="json"), "plan": build_plan(selected)}
    state.update(agent.execute(state))
    return calls, state, agent


def test_complete_point_lookup_does_not_execute_optional_generic_search(tmp_path, monkeypatch):
    calls, state, agent = execute(tmp_path, monkeypatch)
    assert [name for name, _ in calls] == ["lookup_recognition"]
    assert agent.grade(state)["evidence_grade"]["status"] == "sufficient_for_generation"


def test_intentionally_unused_search_is_not_reported_as_missing_evidence(tmp_path, monkeypatch):
    from ai_core.orchestration.ocop import workflow

    _, state, agent = execute(tmp_path, monkeypatch)
    monkeypatch.setattr(agent, "_catalog", lambda: None)
    monkeypatch.setattr(workflow, "assemble", lambda *args, **kwargs: {
        "answer": "Complete answer", "status": "answered", "citations": [],
    })
    answer = agent.answer(state)["answer"]
    assert answer["answer"] == "Complete answer"
    assert "optional_gaps" not in answer


@pytest.mark.parametrize(
    "question",
    [
        "ALPHA và BETA thuộc chủ thể nào và giấy chứng nhận có hiệu lực bao lâu theo quyết định 900?",
        "ALPHA và BETA bảo quản như thế nào theo quyết định 900?",
        "Tại sao ALPHA và BETA được công nhận theo quyết định 900?",
    ],
)
def test_uncovered_or_non_record_question_keeps_supplemental_retrieval(tmp_path, monkeypatch, question):
    calls, _, _ = execute(tmp_path, monkeypatch, question=question)
    assert "search_regulations" in [name for name, _ in calls]


def test_blocked_primary_does_not_launch_optional_generic_search(tmp_path, monkeypatch):
    calls, _, _ = execute(tmp_path, monkeypatch, primary={"results": [], "status": "entity_not_found"})
    assert [name for name, _ in calls] == ["lookup_recognition"]


def test_optional_structured_gap_does_not_downgrade_the_required_tool():
    result = grade_evidence(
        "nội dung quy định",
        [
            {"tool": "lookup_legal_unit", "output": {"results": [{**records()[0], "text": "nội dung quy định"}]}},
            {"tool": "lookup_form", "optional": True, "output": {"results": [], "status": "unknown"}},
        ],
        expected_tools=["lookup_legal_unit"],
    )
    assert result["status"] == "sufficient_for_generation"
    assert result["missing_tools"] == []


@pytest.mark.parametrize("bookkeeping", [{"memory": True, "tool": "memory_evidence"}, {"skipped": True, "tool": "lookup_recognition"}])
def test_bookkeeping_does_not_spend_the_last_recovery_call(bookkeeping):
    names = ["lookup_product_subgroup", "lookup_criterion", "lookup_evidence_requirements", "lookup_form"]
    selected = Route(intent=Intent.MULTIHOP_REASONING, strategy="structured", required_tools=names)
    plan = build_plan(selected)
    outputs = [{"tool": name, "output": {"results": [], "status": "no_results"}} for name in names]
    outputs.append({**bookkeeping, "optional": True, "output": {"results": [], "status": "not_needed"}})
    assert recovery_safe(selected, outputs, plan)
    outputs.append({"tool": "lookup_recognition", "output": {"results": [], "status": "no_results"}})
    assert not recovery_safe(selected, outputs, plan)


def test_targeted_recovery_respects_remaining_actual_call_budget(tmp_path, monkeypatch):
    agent = OcopAgent(tmp_path)
    names = ["lookup_product_subgroup", "lookup_criterion", "lookup_evidence_requirements", "lookup_form"]
    selected = Route(intent=Intent.MULTIHOP_REASONING, strategy="structured", required_tools=names)
    calls = []

    def search_part(part, *args):
        calls.append(part)
        return {"results": [], "status": "no_results"}

    monkeypatch.setattr(agent.tools, "search_part", search_part)
    agent.recover({
        "query": "Two remaining parts",
        "route": selected.model_dump(mode="json"),
        "plan": build_plan(selected),
        "results": [{"tool": name, "output": {"results": [], "status": "no_results"}} for name in names],
        "evidence_grade": {"status": "partial", "uncovered_parts": ["First part", "Second part"], "missing_tools": []},
    })
    assert calls == ["First part"]
