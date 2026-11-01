"""Agent independent adversarial regressions: offline, deterministic and source-safe."""

from __future__ import annotations
import pytest
from ai_core.orchestration.ocop.contracts import Intent, Route, AuthContext
from ai_core.orchestration.ocop.planner import build_plan
from ai_core.orchestration.ocop.workflow import OcopAgent
from ai_core.orchestration.ocop.evidence_grader import grade_evidence


def _route(names, *, strategy="structured", slots=None):
    return Route(intent=Intent.CRITERIA_LOOKUP, strategy=strategy, required_tools=names, slots=slots or {})


def _state(route):
    return {
        "query": "mật ong tiêu chí minh chứng",
        "route": route.model_dump(mode="json"),
        "plan": build_plan(route),
    }


def test_dependency_failure_skips_child_without_calling_registry(tmp_path, monkeypatch):
    route = _route(["lookup_product_subgroup", "lookup_criterion", "lookup_evidence_requirements"])
    agent = OcopAgent(tmp_path)
    calls = []

    def fake(name, **kw):
        calls.append(name)
        if name == "lookup_product_subgroup":
            raise OSError("backend_down")
        return {
            "results": [{"review_status": "verified", "source_id": "S", "source_spans": [{"pdf_page": 2}]}]
        }

    monkeypatch.setattr(agent.tools, "dispatch", fake)
    result = agent.execute(_state(route))
    assert calls == ["lookup_product_subgroup"]
    assert result["results"][1]["output"]["status"] == "dependency_unavailable"
    assert result["results"][2]["output"]["status"] == "dependency_unavailable"


def test_missing_verified_dependency_does_not_guess_criterion(tmp_path, monkeypatch):
    route = _route(["lookup_product_subgroup", "lookup_criterion"])
    agent = OcopAgent(tmp_path)
    calls = []

    def fake(name, **kw):
        calls.append(name)
        return {"results": [], "status": "not_found"}

    monkeypatch.setattr(agent.tools, "dispatch", fake)
    result = agent.execute(_state(route))
    assert calls == ["lookup_product_subgroup"]
    # Nothing found upstream is an ordinary miss: the child is skipped, and text recovery stays possible.
    assert result["results"][1]["output"]["status"] == "dependency_empty"


def test_valid_verified_dependency_allows_child(tmp_path, monkeypatch):
    route = _route(["lookup_product_subgroup", "lookup_criterion"])
    agent = OcopAgent(tmp_path)
    calls = []

    def fake(name, **kw):
        calls.append((name, kw["slots"].copy()))
        if name == "lookup_product_subgroup":
            return {
                "results": [
                    {
                        "source_id": "s1",
                        "source_spans": [{"pdf_page": 2}],
                        "product_group": "Nông sản",
                        "review_status": "verified",
                        "evidence_unit_id": "u1",
                    }
                ]
            }
        return {"results": []}

    monkeypatch.setattr(agent.tools, "dispatch", fake)
    agent.execute(_state(route))
    assert len(calls) == 2
    assert calls[1][1]["product_group"] == "Nông sản"


def test_malformed_tool_payload_is_safely_reported(tmp_path, monkeypatch):
    route = _route(["lookup_criterion"])
    agent = OcopAgent(tmp_path)
    monkeypatch.setattr(agent.tools, "dispatch", lambda *a, **kw: None)
    results = agent.execute(_state(route))["results"]
    assert results[0]["output"]["status"] == "invalid_tool_output"
    assert results[0]["output"]["results"] == []


def test_malformed_results_container_is_safely_reported(tmp_path, monkeypatch):
    route = _route(["lookup_criterion"])
    agent = OcopAgent(tmp_path)
    monkeypatch.setattr(agent.tools, "dispatch", lambda *a, **kw: {"results": "not a list"})
    assert agent.execute(_state(route))["results"][0]["output"]["status"] == "invalid_tool_output"


def test_tool_error_does_not_trigger_text_recovery(tmp_path):
    route = _route(["lookup_form"])
    agent = OcopAgent(tmp_path)
    state = {
        **_state(route),
        "results": [{"tool": "lookup_form", "output": {"status": "tool_unavailable", "results": []}}],
    }
    assert not agent._should_recover(state)


def test_explicit_region_or_year_unknown_blocks_recovery(tmp_path):
    agent = OcopAgent(tmp_path)
    for slots in (
        {"region": "Gia Lai"},
        {"years": ["2025"]},
        {"document_code": "26/2026", "years": ["2025", "2026"]},
    ):
        route = _route(["lookup_form"], slots=slots)
        state = {**_state(route), "results": [{"tool": "lookup_form", "output": {"results": []}}]}
        assert not agent._should_recover(state)


def test_verified_temporal_row_with_unknown_verdict_not_business_resolved():
    row = {
        "source_id": "S",
        "source_spans": [{"pdf_page": 1}],
        "review_status": "verified",
        "text": "hiệu lực của quyết định 2025",
        "verdict": {"status": "unknown"},
    }
    grade = grade_evidence(
        "hiệu lực của quyết định 2025",
        [
            {
                "tool": "resolve_temporal_applicability",
                "output": {
                    "results": [row],
                    "status": "checked_verified_rules",
                    "applicability_status": "unknown",
                },
            }
        ],
        expected_tools=["resolve_temporal_applicability"],
    )
    assert not grade["verified_business_resolution"]
    assert "resolve_temporal_applicability" in grade["missing_tools"]


def test_verified_temporal_row_with_not_applicable_is_resolved_but_not_applicable():
    row = {
        "source_id": "S",
        "source_spans": [{"pdf_page": 1}],
        "review_status": "verified",
        "text": "hiệu lực của quyết định 2025",
        "verdict": {"status": "not_applicable"},
    }
    grade = grade_evidence(
        "hiệu lực của quyết định 2025",
        [
            {
                "tool": "resolve_temporal_applicability",
                "output": {
                    "results": [row],
                    "status": "checked_verified_rules",
                    "applicability_status": "not_applicable",
                },
            }
        ],
        expected_tools=["resolve_temporal_applicability"],
    )
    assert grade["verified_business_resolution"]


def test_checkpoint_public_state_strips_untrusted_secrets(tmp_path, monkeypatch):
    agent = OcopAgent(tmp_path)

    class FakeSaver:
        pass

    class FakeCheckpoint:
        def __init__(self, path):
            self.saver = FakeSaver()

    class FakeGraph:
        def invoke(self, initial, config=None):
            captured.update(initial)
            raise RuntimeError("test_stop")

    captured = {}
    monkeypatch.setattr("ai_core.orchestration.ocop.workflow.should_checkpoint", lambda **kw: True)
    monkeypatch.setattr("ai_core.orchestration.ocop.workflow.SQLiteCheckpoint", FakeCheckpoint)
    monkeypatch.setenv("OCOP_LANGGRAPH_CHECKPOINT_PATH", str(tmp_path / "store.sqlite"))
    monkeypatch.setattr(agent, "graph", lambda checkpointer=None: FakeGraph())
    with pytest.raises(RuntimeError, match="test_stop"):
        agent.ask(
            "OCOP là gì?",
            auth_context=AuthContext(principal_id="p", tenant_id="t"),
            session={"session_id": "sid", "token": "SECRET", "slots": {}, "last_query": "OCOP"},
            context={"jwt": "SECRET", "as_of_date": "2025-01-01", "tenant_id": "evil"},
        )
    assert "SECRET" not in str(captured)
    assert "token" not in captured["session"] and "jwt" not in captured["context"]
    assert captured.get("auth") is None
    assert captured["session"]["last_query"] == "OCOP"


def test_unverified_evidence_must_not_seed_graph():
    from ai_core.orchestration.ocop.planner import evidence_ids

    rows = [
        {
            "tool": "search_regulations",
            "output": {
                "results": [
                    {
                        "evidence_unit_id": "candidate",
                        "review_status": "needs_review",
                        "source_id": "S",
                        "source_spans": [{"pdf_page": 1}],
                    },
                    {
                        "evidence_unit_id": "confirmed",
                        "review_status": "verified",
                        "source_id": "S",
                        "source_spans": [{"pdf_page": 2}],
                    },
                    {
                        "evidence_unit_id": "badpage",
                        "review_status": "verified",
                        "source_id": "S",
                        "source_spans": [{"pdf_page": 0}],
                    },
                ]
            },
        }
    ]
    assert evidence_ids(rows, verified_only=True) == ["confirmed"]


def test_verified_slots_require_real_pdf_page(tmp_path, monkeypatch):
    route = _route(["lookup_product_subgroup", "lookup_criterion"])
    agent = OcopAgent(tmp_path)
    args = []

    def fake(name, **kw):
        args.append((name, dict(kw["slots"])))
        if name == "lookup_product_subgroup":
            return {
                "results": [
                    {
                        "product_group": "giả",
                        "review_status": "verified",
                        "source_id": "S",
                        "source_spans": [{"pdf_page": 0}],
                    },
                    {
                        "product_group": "thật",
                        "review_status": "verified",
                        "source_id": "S",
                        "source_spans": [{"pdf_page": 3}],
                    },
                ]
            }
        return {"results": []}

    monkeypatch.setattr(agent.tools, "dispatch", fake)
    agent.execute(_state(route))
    assert args[1][1]["product_group"] == "thật"


def test_transitive_verified_slots_keep_business_dependency_chain(tmp_path, monkeypatch):
    route = _route(["lookup_product_subgroup", "lookup_criterion", "lookup_evidence_requirements"])
    agent = OcopAgent(tmp_path)
    calls = []

    def fake(name, **kw):
        calls.append((name, dict(kw["slots"])))
        data = {
            "lookup_product_subgroup": ("product_group", "Nông sản"),
            "lookup_criterion": ("criterion_id", "3.2"),
            "lookup_evidence_requirements": ("x", "y"),
        }
        attr, value = data[name]
        return {
            "results": [
                {
                    "evidence_unit_id": name,
                    "source_id": "S",
                    "source_spans": [{"pdf_page": 2}],
                    "review_status": "verified",
                    attr: value,
                }
            ]
        }

    monkeypatch.setattr(agent.tools, "dispatch", fake)
    agent.execute(_state(route))
    assert calls[2][1]["product_group"] == "Nông sản"
    assert calls[2][1]["criterion_id"] == "3.2"


def test_checkpoint_preserves_valid_public_followup_capabilities():
    from ai_core.orchestration.ocop.workflow import OcopAgent

    initial = {
        "query": "Thế năm 2025?",
        "session": {
            "session_id": "s",
            "last_query": "Mật ong thuộc nhóm nào?",
            "slots": {"product_name": "mật ong", "tenant_id": "forged"},
            "capabilities": ["classify_product", "criteria", "malicious_tool"],
        },
        "context": {"verified_criteria": [{"id": "fake"}]},
    }
    sanitized = OcopAgent._checkpoint_public_input(initial)
    assert sanitized["session"]["capabilities"] == ["classify_product", "criteria"]
    assert sanitized["session"]["slots"] == {"product_name": "mật ong"}
    assert "verified_criteria" not in sanitized["context"]


def test_recovery_budget_and_scope_match_between_planner_and_workflow(tmp_path):
    from ai_core.orchestration.ocop.planner import needs_recovery

    agent = OcopAgent(tmp_path)
    for scope in (
        {},
        {"region": "Gia Lai"},
        {"years": ["2025"]},
        {"document_code": "26/2026", "years": ["2026"]},
    ):
        route = _route(["lookup_form"], slots=scope)
        outputs = [{"tool": "lookup_form", "output": {"results": []}}]
        state = {**_state(route), "results": outputs}
        assert needs_recovery(route, outputs, build_plan(route)) == agent._should_recover(state)


def test_recovery_invalid_output_fails_closed(tmp_path, monkeypatch):
    route = _route(["lookup_form"])
    agent = OcopAgent(tmp_path)
    monkeypatch.setattr(agent.tools, "dispatch", lambda *a, **kw: {"results": None})
    state = {**_state(route), "results": [{"tool": "lookup_form", "output": {"results": []}}]}
    result = agent.recover(state)
    assert len(result["results"]) == 2
    assert result["results"][1]["output"]["status"] == "invalid_tool_output"
    assert result["results"][1]["output"]["results"] == []


def test_recover_at_most_once_even_when_no_evidence(tmp_path, monkeypatch):
    route = _route(["lookup_form"])
    agent = OcopAgent(tmp_path)
    calls = []

    def fake(*a, **k):
        calls.append(a[0])
        return {"results": []}

    monkeypatch.setattr(agent.tools, "dispatch", fake)
    state = {**_state(route), "results": [{"tool": "lookup_form", "output": {"results": []}}]}
    updated = agent.recover(state)
    assert calls == ["search_regulations"]
    assert not agent._should_recover({**state, **updated})
    agent.recover({**state, **updated})
    assert calls == ["search_regulations"]


def test_targeted_recovery_searches_only_the_parts_no_evidence_speaks_to(tmp_path, monkeypatch):
    """Isolated fixture for the recovery branch: the structured tool answered the first part; only the second is searched."""
    question = "Sản phẩm HANA do đơn vị nào sản xuất, và cơ quan nào ban hành quyết định công nhận?"
    route = Route(
        intent=Intent.RECOGNITION_LOOKUP,
        strategy="structured",
        required_tools=["lookup_recognition"],
        slots={},
    )
    agent = OcopAgent(tmp_path)
    row = {
        "source_id": "S1",
        "evidence_unit_id": "u1",
        "review_status": "needs_review",
        "source_spans": [{"pdf_page": 3}],
        "text": "Gạo ruộng rươi giống HANA do Hợp tác xã Thụy Hương sản xuất",
    }
    found_for = {}

    def search_part(part, slots, context, auth):
        found_for[part] = True
        return {
            "results": [
                {
                    **row,
                    "evidence_unit_id": "u2",
                    "text": "Ủy ban nhân dân thành phố Hải Phòng ban hành quyết định công nhận",
                }
            ]
        }

    monkeypatch.setattr(agent.tools, "search_part", search_part)
    monkeypatch.setattr(
        agent.tools, "dispatch", lambda *a, **k: pytest.fail("recovery must not re-run the whole question")
    )
    state = {
        "query": question,
        "effective_query": question,
        "route": route.model_dump(mode="json"),
        "plan": build_plan(route),
        "results": [{"tool": "lookup_recognition", "output": {"results": [row], "status": "ok"}}],
    }
    grade = grade_evidence(question, state["results"], expected_tools=["lookup_recognition"])
    assert (
        grade["uncovered_parts"]
        and len(grade["uncovered_parts"]) == 1
        and "ban hành" in grade["uncovered_parts"][0]
    )
    updated = agent.recover({**state, "evidence_grade": grade})
    assert list(found_for) == grade["uncovered_parts"]  # the covered part was not searched again
    assert updated["results"][0] == state["results"][0]  # evidence already found is kept as it was
    assert (
        updated["results"][-1]["recovery"] is True
        and updated["results"][-1]["output"]["results"][0]["query_part"] == grade["uncovered_parts"][0]
    )
    assert updated["trace"][-1]["reason"] == "uncovered_question_parts"


def test_an_empty_dependency_allows_text_recovery_but_a_failed_service_does_not():
    from ai_core.orchestration.ocop.planner import recovery_safe

    route = _route(["lookup_product_subgroup", "lookup_criterion"])
    plan = build_plan(route)
    empty = [{"tool": "lookup_product_subgroup", "output": {"results": [], "status": "no_results"}},
             {"tool": "lookup_criterion", "output": {"results": [], "status": "dependency_empty"}}]
    failed = [{"tool": "lookup_product_subgroup", "output": {"results": [], "status": "tool_unavailable"}},
              {"tool": "lookup_criterion", "output": {"results": [], "status": "dependency_unavailable"}}]
    assert recovery_safe(Route.model_validate(route.model_dump()), empty, plan)
    assert not recovery_safe(Route.model_validate(route.model_dump()), failed, plan)
