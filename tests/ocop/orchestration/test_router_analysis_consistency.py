"""Regression cases at the query -> accepted route -> tool plan boundary."""

from types import SimpleNamespace

import pytest

from ai_core.orchestration.ocop.catalog import EntityCatalog
from ai_core.orchestration.ocop.contracts import Intent
from ai_core.orchestration.ocop.planner import build_plan
from ai_core.orchestration.ocop.router import route_query


def test_explicit_page_and_document_share_the_exact_lookup_decision():
    calls = []
    route = route_query(
        "Trang 7 Quyết định 88/2024/QĐ-TTg nói gì?",
        llm_scope=lambda text: calls.append(text) or {"intent": "OCOP_OVERVIEW"},
    )
    assert route.intent == Intent.EXACT_LOOKUP
    assert route.capabilities == ["exact_article"]
    assert build_plan(route).required_names == ("lookup_legal_unit",)
    assert not calls


def test_a_catalogued_place_does_not_make_a_recipe_an_ocop_question():
    catalog = EntityCatalog({"entities": {"region": [{"label": "Huế", "source_ids": []}]}})
    route = route_query("Hướng dẫn nấu món chay ở Huế giúp tôi?", catalog=catalog)
    assert route.intent == Intent.OUT_OF_SCOPE
    assert not build_plan(route).names


@pytest.mark.parametrize("coverage", [None, 1.0])
def test_unresolved_document_reference_is_clarified_before_scope_recovery(coverage):
    asked = []
    route = route_query(
        "Văn bản đó còn được áp dụng cho doanh nghiệp không?",
        indexed_content_bigram_coverage=lambda text: coverage,
        llm_scope=lambda text: asked.append(text) or {"intent": "TEMPORAL_COMPARE"},
    )
    assert route.intent == Intent.CLARIFY
    assert route.needs_clarification
    assert "referent_document" in route.missing_slots
    assert not build_plan(route).names
    assert not asked


def test_resolved_document_reference_preserves_the_pinned_version():
    prior = {
        "last_query": "Điều 9 Quyết định 88/2024/QĐ-TTg ghi gì?",
        "intent": "EXACT_LOOKUP",
        "slots": {"document_code": "88/2024/QĐ-TTg"},
        "capabilities": ["exact_article"],
    }
    route = route_query("Văn bản đó còn hiệu lực không?", session=prior)
    assert not route.needs_clarification
    assert route.slots["document_code"] == "88/2024/QĐ-TTg"


def test_weak_rule_can_ask_the_model_when_semantic_proposal_abstains():
    asked = []
    route = route_query(
        "Mẫu hồ sơ cần điền những gì?",
        semantic_route=lambda text: None,
        llm_scope=lambda text: asked.append(text) or {"intent": "CRITERIA_LOOKUP"},
    )
    assert route.intent == Intent.CRITERIA_LOOKUP
    assert route.capabilities == ["criteria"]
    assert "model_override" in route.reason_codes
    assert len(asked) == 1


def test_semantic_override_keeps_an_independent_relation_capability():
    route = route_query(
        "Quyết định 88/2024/QĐ-TTg căn cứ văn bản nào về tiêu chí?",
        semantic_route=lambda text: SimpleNamespace(intent="PROCEDURE_FORM", score=0.9, margin=0.3),
    )
    assert route.intent == Intent.PROCEDURE_FORM
    assert "procedure_form" in route.capabilities
    assert "relation_reasoning" in route.capabilities
    assert "search_graph" in build_plan(route).names


def test_explicit_document_replacement_does_not_lose_its_temporal_task():
    route = route_query("Quyết định 88/2024/QĐ-TTg có thay thế bộ tiêu chí trước không?")
    assert route.intent == Intent.TEMPORAL_COMPARE
    assert {"temporal", "relation_reasoning"} <= set(route.capabilities)
    assert "resolve_temporal_applicability" in route.required_tools
    assert "search_graph" in build_plan(route).names


def test_bare_criterion_preserves_the_code_while_asking_for_its_scope():
    route = route_query("2.7")
    assert route.intent == Intent.CLARIFY
    assert route.slots.get("criterion_id") == "2.7"
    assert route.needs_clarification


def test_model_secondary_tasks_are_mapped_by_the_server_and_cannot_change_slots():
    route = route_query(
        "Xin giải thích OCOP giúp tôi?",
        llm_scope=lambda text: {
            "intent": "PROCEDURE_FORM", "secondary_intents": ["TEMPORAL_COMPARE", "system_shell"],
            "slots": {"document_code": "INVENTED"}, "required_tools": ["system_shell"],
        },
    )
    assert {"procedure_form", "temporal"} <= set(route.capabilities)
    assert Intent.TEMPORAL_COMPARE in route.secondary_intents
    assert "document_code" not in route.slots
    plan = build_plan(route)
    assert "resolve_temporal_applicability" in plan.names
    assert "system_shell" not in plan.names
    assert len(plan.names) <= 5


def test_two_explicit_legal_questions_keep_the_relation_and_temporal_tasks():
    route = route_query(
        "Quyết định 88/2024/QĐ-TTg thay thế văn bản nào và quy định chuyển tiếp ra sao?"
    )
    assert route.intent == Intent.MULTIHOP_REASONING
    assert {"temporal", "relation_reasoning"} <= set(route.capabilities)
    assert {"search_graph", "resolve_temporal_applicability"} <= set(build_plan(route).names)


@pytest.mark.parametrize("documents", [["88/2024/QĐ-TTg"], ["88/2024/QĐ-TTg", "89/2024/QĐ-TTg"]])
def test_document_reference_uses_a_unique_conversation_candidate_or_asks(documents):
    prior = {
        "last_query": "Cho biết quy định OCOP?", "intent": "OCOP_OVERVIEW", "slots": {},
        "memory": {"referents": {"document": documents}},
    }
    route = route_query("Văn bản đó còn hiệu lực không?", session=prior)
    if len(documents) == 1:
        assert not route.needs_clarification
        assert route.slots.get("document_code") == documents[0]
    else:
        assert route.intent == Intent.CLARIFY
        assert not build_plan(route).names
