"""Public API contracts used by the browser, without LLM or network services."""

from types import SimpleNamespace

import pytest

from backend.api import ocop_routes
from ai_core.orchestration.ocop.contracts import AgentResponse, Intent, Route


def test_query_preserves_every_citation_field(api_client, monkeypatch):
    citation = {
        "source_id": "SOURCE",
        "pdf_page": 3,
        "bbox": [10, 20, 30, 40],
        "evidence_unit_id": "evidence",
        "source_sha256": "a" * 64,
        "source_spans": [{"pdf_page": 3, "bbox": [10, 20, 30, 40], "source_sha256": "a" * 64}],
    }
    answer = AgentResponse(
        answer="Evidence [S1]",
        intent=Intent.EXACT_LOOKUP,
        status="retrieval_only",
        workflow_engine="deterministic_fallback",
        citations=[citation],
        route=Route(intent=Intent.EXACT_LOOKUP, strategy="structured"),
    )
    monkeypatch.setattr(ocop_routes, "_agent", lambda *a, **k: SimpleNamespace(ask=lambda *a, **k: answer))
    response = api_client.post("/api/ocop/query", json={"query": "Evidence", "use_llm": False})
    assert response.status_code == 200
    assert response.json()["citations"] == [citation]
    assert response.json().keys() == AgentResponse.model_fields.keys()


@pytest.mark.parametrize(
    "body",
    [
        {"query": ""},
        {"query": "a" * 4001},
        {"query": "q", "retrieval_mode": "invalid"},
        {"query": "q", "tenant_id": "private"},
        {"query": "q", "rules": [{"points": 100}]},
    ],
)
def test_public_query_rejects_invalid_or_client_owned_rules(api_client, body):
    assert api_client.post("/api/ocop/query", json=body).status_code == 422


def test_health_identifies_corpus_and_backend_state(api_client):
    response = api_client.get("/api/ocop/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "pipeline": {"state": "ready"},
        "retrieval_profile": {"profile": "sparse", "ready": True, "missing": []},
        "answer_llm": False,
        "sources_registered": 0,
        "pages": 0,
        "index_status": "missing",
        "dense_ready": False,
        "graph_status": "missing",
        "corpus_version": "fixture",
    }


def test_read_routes_have_no_unrelated_domain_endpoints(api_client):
    paths = api_client.get("/openapi.json").json()["paths"]
    assert set(paths) == {
        "/api/ocop/health",
        "/api/ocop/sources",
        "/api/ocop/sources/{source_id}/pdf",
        "/api/ocop/sources/{source_id}/pages/{page}/evidence.png",
        "/api/ocop/criteria",
        "/api/ocop/products",
        "/api/ocop/graph/subgraph",
        "/api/ocop/query",
    }


def test_health_reports_a_hosted_answer_model_as_ready_by_default(api_client, monkeypatch):
    monkeypatch.setenv("OCOP_ANSWER_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OCOP_ANSWER_OPENAI_API_KEY", "test-key")
    assert api_client.get("/api/ocop/health").json()["answer_llm"] is True
    monkeypatch.delenv("OCOP_ANSWER_OPENAI_API_KEY")
    monkeypatch.delenv("OCOP_EXTRACT_OPENAI_API_KEY", raising=False)
    assert api_client.get("/api/ocop/health").json()["answer_llm"] is False


def test_query_summary_says_where_a_question_went_and_never_what_it_said():
    payload = {
        "status": "generated_claims_verified",
        "intent": "RECOGNITION_LOOKUP",
        "answer": "Câu trả lời riêng tư",
        "route": {"retrieval_path": "PINPOINT"},
        "tools_used": ["lookup_recognition"],
        "citations": [{}, {}],
        "generation_diagnostics": {"accepted": 5, "rejected": [{"claim": "ý bị loại"}]},
        "tool_trace": [
            {"step": "route"},
            {"step": "tool", "name": "lookup_recognition", "latency_ms": 1200.4},
            {"step": "tool", "name": "search_regulations", "latency_ms": 800},
        ],
    }
    summary = ocop_routes.query_summary(payload, 30500, True, "hybrid")
    assert summary == {
        "status": "generated_claims_verified", "intent": "RECOGNITION_LOOKUP", "path": "PINPOINT",
        "tools": ["lookup_recognition"], "mode": "hybrid", "llm": True, "citations": 2,
        "claims_accepted": 5, "claims_rejected": 1, "total_ms": 30500, "tools_ms": 2000, "generation_ms": 28500,
    }
    assert "riêng tư" not in str(summary) and "bị loại" not in str(summary)


def test_a_503_leaves_a_trace_for_the_operator_without_the_exception_text(caplog, monkeypatch):
    import logging

    monkeypatch.setattr(logging.getLogger("ocop"), "propagate", True)
    with caplog.at_level("WARNING", logger="ocop.api"):
        error = ocop_routes.service_unavailable("llm_unavailable", "configuration", RuntimeError("secret-key-123"))
    assert error.status_code == 503
    assert "code=llm_unavailable" in caplog.text and "layer=configuration" in caplog.text
    assert "RuntimeError" in caplog.text and "secret-key-123" not in caplog.text
