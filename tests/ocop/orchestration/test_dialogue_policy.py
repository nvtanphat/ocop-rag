"""Conversation behavior and safety boundaries, independent of model availability."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_core.orchestration.ocop import memory
from ai_core.orchestration.ocop.contracts import AgentResponse, Intent
from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.sessions import SessionStore
from ai_core.orchestration.ocop.workflow import OcopAgent

ROOT = Path(__file__).resolve().parents[3]
DATA = json.loads((ROOT / "tests/fixtures/conversation_eval.json").read_text(encoding="utf-8"))
PRIOR = {
    "last_query": "QĐ26/2026 Điều 6 quy định gì về hồ sơ?",
    "slots": {"document_code": "26/2026", "article_id": "6"},
    "intent": "EXACT_LOOKUP",
    "capabilities": ["exact_article"],
}


def response(route, query="active knowledge question", citations=None):
    return AgentResponse(
        answer="answer",
        intent=route.intent,
        status="ok",
        route=route,
        standalone_query=query,
        citations=citations or [],
        corpus_version="v1",
        workflow_engine="langgraph",
    )


@pytest.mark.parametrize("query", DATA["dev"]["social"])
def test_social_turn_requires_neither_tools_nor_llm(query):
    def forbidden(*a, **kw):
        pytest.fail("Social turns must not consult a model or the index")

    route = route_query(query, session=PRIOR, llm_route=forbidden, indexed_content_bigram_coverage=forbidden)
    assert route.intent == Intent.CONVERSATION
    assert not route.required_tools and not route.secondary_tools
    assert not route.slots and route.dialogue.action == "respond"


@pytest.mark.parametrize("query", DATA["dev"]["mixed"])
def test_mixed_message_never_bypasses_business(query):
    assert route_query(query, session=PRIOR).intent != Intent.CONVERSATION


def test_social_interruption_preserves_complete_knowledge_snapshot():
    store = SessionStore()
    route = route_query(PRIOR["last_query"])
    cite = {"source_id": "source", "chunk_id": "chunk", "evidence_unit_id": "unit", "pdf_page": 3}
    store.save("a", PRIOR["last_query"], response(route, PRIOR["last_query"], [cite]))
    snapshot = store.get("a")
    for _ in range(6):
        store.save("a", "Cảm ơn bạn nhiều", response(route_query("Cảm ơn bạn nhiều")))
    after = store.get("a")
    assert {k: after[k] for k in snapshot} == snapshot
    assert after["memory"]["evidence"] == snapshot["memory"]["evidence"]
    follow = route_query("Còn Điều 7?", session=after)
    assert follow.slots["document_code"] == "26/2026" and follow.slots["article_id"] == "7"
    assert store.get("b") == {}
    assert route_query("Hai mẫu này khác nhau gì?", session=store.get("b")).needs_clarification
    assert memory.reusable_evidence(after["memory"], corpus_version="v2", source_ids=None)[0] == []


def test_clarification_can_resume_after_social_without_creating_fake_topic():
    store = SessionStore()
    store.save("a", "1.6", response(route_query("1.6"), "1.6"))
    assert "last_query" not in store.get("a")
    store.save("a", "Cảm ơn", response(route_query("Cảm ơn")))
    resumed = route_query("Quyết định 26 nhé", session=store.get("a"))
    assert "clarification_resumed" in resumed.reason_codes
    assert resumed.slots["criterion_id"] == "1.6" and resumed.slots["document_code"] == "26"


def test_correction_replaces_target_without_losing_document():
    prior = {**PRIOR, "slots": {"document_code": "26/2026", "form_id": "2"}, "intent": "PROCEDURE_FORM"}
    route = route_query("Không phải, mình muốn mẫu số 01", session=prior)
    assert route.slots["document_code"] == "26/2026" and route.slots["form_id"] == "1"
    assert "article_id" not in route.slots
    assert route_query("Bạn trả lời sai rồi", session=prior).needs_clarification


def test_switch_to_an_explicit_document_drops_unscoped_form_and_old_capability():
    prior = {
        "last_query": "Mẫu số 01?",
        "slots": {"form_id": "1"},
        "intent": "PROCEDURE_FORM",
        "capabilities": ["procedure_form"],
    }
    switched = route_query("Thế còn Quyết định 525?", session=prior)
    assert switched.slots == {"document_code": "525"}
    assert "lookup_form" not in switched.required_tools
    after = {
        "last_query": "Quyết định 525 nói gì?",
        "slots": switched.slots,
        "intent": switched.intent.value,
        "capabilities": switched.capabilities,
    }
    follow = route_query("Văn bản mới này nói gì về hồ sơ?", session=after)
    assert follow.slots["document_code"] == "525"


def test_capability_help_tracks_public_registry_and_avoids_internal_tool_names():
    from ai_core.orchestration.ocop.capabilities import TOOL_REGISTRY, ToolSpec
    from ai_core.orchestration.ocop.dialogue import respond

    choice = route_query("Bạn giúp được gì?")
    original = TOOL_REGISTRY["lookup_form"]
    try:
        TOOL_REGISTRY["lookup_form"] = ToolSpec("lookup_form", public_description="chức năng công khai mới")
        answer = respond(choice.dialogue)
        assert "chức năng công khai mới" in answer
        assert "lookup_form" not in answer
    finally:
        TOOL_REGISTRY["lookup_form"] = original


def test_repeated_repairs_keep_the_active_knowledge_question():
    store = SessionStore()
    store.save("a", PRIOR["last_query"], response(route_query(PRIOR["last_query"]), PRIOR["last_query"]))
    for query in ("Giải thích dễ hiểu hơn", "Cho mình xem nguồn của câu đó", "Mình chưa hiểu"):
        route = route_query(query, session=store.get("a"))
        assert "dialogue_revalidate_topic" in route.reason_codes
        assert route.required_tools and all(route.slots[k] == v for k, v in PRIOR["slots"].items())
        store.save("a", query, response(route, PRIOR["last_query"]))
        assert store.get("a")["last_query"] == PRIOR["last_query"]


def test_social_does_not_resurrect_expired_topic_or_cross_session_limits():
    clock = [10.0]
    store = SessionStore(ttl=2, limit=1, clock=lambda: clock[0])
    store.save("a", PRIOR["last_query"], response(route_query(PRIOR["last_query"]), PRIOR["last_query"]))
    clock[0] += 3
    store.save("a", "Hello", response(route_query("Hello")))
    assert "last_query" not in store.get("a")
    store.save("b", "Hello", response(route_query("Hello")))
    assert store.get("a") == {}


@pytest.mark.parametrize("fallback", [False, True])
def test_graph_and_dependency_free_paths_do_not_execute_social_tools(tmp_path, monkeypatch, fallback):
    agent = OcopAgent(tmp_path)
    monkeypatch.setattr(agent.tools, "dispatch", lambda *a, **kw: pytest.fail("unexpected tool"))
    monkeypatch.setattr(agent, "plan", lambda *a, **kw: pytest.fail("unexpected plan"))
    if fallback:

        def no_graph(**kw):
            raise RuntimeError("langgraph not installed")

        monkeypatch.setattr(agent, "graph", no_graph)
    result = agent.ask("Xin chào")
    assert result.intent == Intent.CONVERSATION and result.status == "conversation"
    assert not result.tools_used and not result.citations
    assert result.workflow_engine == ("deterministic_fallback" if fallback else "langgraph")


@pytest.mark.parametrize(
    "raw",
    [
        '{"act":"help","task_present":true,"confidence":1}',
        '{"act":"help","task_present":false,"confidence":0.5}',
        '{"act":"help","task_present":false,"confidence":1,"tools":["delete_database"]}',
        "not json",
        '{"act":"execute","task_present":false,"confidence":1}',
    ],
)
def test_structured_fallback_abstains_on_unsafe_or_uncertain_output(raw):
    from ai_core.orchestration.ocop.dialogue import assisted

    assert (
        assisted(SimpleNamespace(chat_structured=lambda *a, **kw: raw), "some message", has_topic=True)
        is None
    )


def test_business_signals_cannot_be_overridden_by_dialogue_llm():
    client = SimpleNamespace(chat_structured=lambda *a, **kw: pytest.fail("business called dialogue LLM"))
    route = route_query("Chào bạn, Điều 7 QĐ26 nói gì?", dialogue_client=client)
    assert route.required_tools and route.intent != Intent.CONVERSATION
    malicious = route_query(
        "OCOP là gì?", llm_route=lambda q: {"intent": "CONVERSATION", "tools": ["delete_database"]}
    )
    assert malicious.intent != Intent.CONVERSATION
    assert "delete_database" not in malicious.required_tools


def test_mixed_task_passes_only_task_words_to_retrieval(tmp_path):
    agent = OcopAgent(tmp_path)
    state = agent.route({"query": "Chào bạn, Điều 7 QĐ26 nói gì?"})
    assert state["effective_query"] == "Điều 7 QĐ26 nói gì"
    assert state["route"]["slots"]["article_id"] == "7"


def test_rephrase_uses_current_corpus_query_and_separate_generation_style(tmp_path, monkeypatch):
    from ai_core.orchestration.ocop import workflow

    agent = OcopAgent(tmp_path)
    state = {"query": "Giải thích dễ hiểu hơn", "session": PRIOR}
    state.update(agent.route(state))
    calls = []

    def assemble(question, outputs, **kwargs):
        calls.append((question, kwargs))
        return {"answer": "grounded", "status": "retrieval_only", "citations": []}

    monkeypatch.setattr(workflow, "assemble", assemble)
    agent.answer(state)
    assert calls[0][0] == PRIOR["last_query"]
    assert calls[0][1]["style"] == "simple"


def test_model_failure_preserves_deterministic_route():
    def unavailable(*a, **kw):
        raise RuntimeError("offline")

    query = "I would love to know what assistance is offered here"
    old = route_query(query)
    current = route_query(query, dialogue_client=SimpleNamespace(chat_structured=unavailable))
    assert current == old


def test_workflow_keeps_experimental_dialogue_model_out_of_production(tmp_path):
    from ai_core.orchestration.ocop import diacritics_model, scope_model

    def structured(system, *args, **kwargs):
        # The router's own model tier (closed label list) is a different call from the experimental dialogue model.
        if system == scope_model.SYSTEM:
            return '{"intent": "OUT_OF_SCOPE"}'
        if system == diacritics_model.SYSTEM:  # unaccented text is restored first; nothing to add here
            return '{"text": "Some unfamiliar conversational wording without a clear task"}'
        pytest.fail("experimental model called")

    client = SimpleNamespace(route=lambda q: {}, chat_structured=structured)
    agent = OcopAgent(tmp_path, llm=client)
    result = agent.route({"query": "Some unfamiliar conversational wording without a clear task"})
    assert result["route"]["intent"] in ("CLARIFY", "OUT_OF_SCOPE")


def test_public_http_social_survives_missing_model_configuration(api_client, monkeypatch):
    from backend.api import ocop_routes

    def unavailable():
        raise RuntimeError("model not configured")

    monkeypatch.setattr(ocop_routes, "make_answer_client", unavailable)
    with api_client as client:
        social = client.post("/api/ocop/query", json={"query": "Hello", "use_llm": True})
        assert social.status_code == 200
        assert social.json()["intent"] == "CONVERSATION" and not social.json()["tools_used"]
        task = client.post("/api/ocop/query", json={"query": "Điều 7 QĐ26", "use_llm": True})
        assert task.status_code == 503


def test_public_http_social_does_not_construct_model(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import ocop_routes

    (tmp_path / "index").mkdir()
    (tmp_path / "index/manifest.json").write_text('{"corpus_version":"v1"}', encoding="utf-8")
    monkeypatch.setattr(ocop_routes, "DATA", tmp_path)
    monkeypatch.setattr(ocop_routes.OcopSystemPipeline, "status", lambda *a, **kw: {"state": "ready"})

    def construct(use_llm, *a, **kw):
        assert use_llm is False
        return OcopAgent(tmp_path)

    monkeypatch.setattr(ocop_routes, "_agent", construct)
    app = FastAPI()
    app.include_router(ocop_routes.router)
    with TestClient(app) as client:
        result = client.post("/api/ocop/query", json={"query": "Hello", "use_llm": True})
    assert result.status_code == 200 and result.json()["intent"] == "CONVERSATION"


def test_checkpoint_preserves_bounded_public_dialogue_context_without_authority():
    public = memory.update(
        None, slots={"document_code": "26"}, standalone="active topic", citations=[], corpus_version="v1"
    )
    initial = {
        "query": "Hello",
        "session": {
            **PRIOR,
            "tenant_id": "untrusted",
            "memory": {**public, "text": "not evidence"},
            "unresolved": {
                "question": "1.6",
                "missing_slots": ["document_or_sheet_for_code"],
                "permission": True,
            },
        },
        "auth": None,
    }
    safe = OcopAgent._checkpoint_public_input(initial)["session"]
    assert safe["memory"] == public
    assert safe["unresolved"] == {"question": "1.6", "missing_slots": ["document_or_sheet_for_code"]}
    assert "tenant_id" not in safe and "text" not in safe["memory"]


def test_http_fast_path_normalizes_decomposed_unicode_before_model_construction():
    import unicodedata
    from ai_core.orchestration.ocop.dialogue import understand

    decision, remainder = understand(unicodedata.normalize("NFD", "Xin chào bạn nhé!"))
    assert decision.action == "respond" and not remainder
