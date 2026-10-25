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
    monkeypatch.setattr(ocop_routes, "_agent", lambda *a: SimpleNamespace(ask=lambda *a, **k: answer))
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
        "/api/ocop/query",
    }
