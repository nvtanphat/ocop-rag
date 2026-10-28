"""API contract tests for clean, source-only OCOP distribution."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.api.ocop_main import app
from backend.api import ocop_routes as routes
from ai_core.system.pipeline import OcopSystemPipeline

ROOT = Path(__file__).resolve().parents[3]
client = TestClient(app)


def test_sources_and_signed_pdf_remain_available_before_build():
    sources = client.get("/api/ocop/sources").json()
    assert len(sources) == 12
    first = sources[0]["source_id"]
    response = client.get(f"/api/ocop/sources/{first}/pdf")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert client.get("/api/ocop/sources/NOT-REGISTERED/pdf").status_code == 404


def test_sources_report_their_page_and_ocr_page_counts(monkeypatch, tmp_path):
    import json

    source_id = client.get("/api/ocop/sources").json()[0]["source_id"]
    (tmp_path / "pages/pages").mkdir(parents=True)
    entry = {"source_id": source_id, "pages": [1, 2, 3], "artifact": f"pages/{source_id}.jsonl", "artifact_sha256": "sha-fixture"}
    (tmp_path / "pages/manifest.json").write_text(json.dumps({"sources": [entry]}), encoding="utf-8")
    rows = [{"pdf_page": 1, "ocr_engine": "easyocr"}, {"pdf_page": 2, "ocr_engine": None}, {"pdf_page": 3, "ocr_engine": "easyocr"}]
    (tmp_path / "pages/pages" / f"{source_id}.jsonl").write_text(
        "\n".join(map(json.dumps, rows)), encoding="utf-8"
    )
    monkeypatch.setattr(routes, "DATA", tmp_path)
    listed = {s["source_id"]: s for s in client.get("/api/ocop/sources").json()}
    assert (listed[source_id]["page_count"], listed[source_id]["ocr_pages"]) == (3, 2)


def test_api_fails_closed_without_built_corpus(monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "DATA", tmp_path)
    response = client.post(
        "/api/ocop/query", json={"query": "Mẫu số 01", "retrieval_mode": "sparse", "use_llm": False}
    )
    assert response.status_code == 503
    # Even a forged index manifest is insufficient without an approved build.
    index = tmp_path / "index"
    index.mkdir()
    (index / "manifest.json").write_text('{"dense":{"enabled":true}}', encoding="utf-8")
    monkeypatch.setattr(OcopSystemPipeline, "status", lambda self, **k: {"state": "not_ready"})
    assert (
        client.post(
            "/api/ocop/query",
            json={
                "query": "Mẫu số 01",
                "retrieval_mode": "sparse",
                "use_llm": False,
            },
        ).status_code
        == 503
    )


def test_api_query_after_coherent_build_uses_agent(monkeypatch, tmp_path):
    idx = tmp_path / "index"
    idx.mkdir()
    (idx / "manifest.json").write_text(
        '{"dense":{"enabled":false},"corpus_version":"clean-fixture"}', encoding="utf-8"
    )
    monkeypatch.setattr(routes, "DATA", tmp_path)
    # Agent behavior itself is checked in separate contract tests; only verify public wiring here.
    monkeypatch.setattr(OcopSystemPipeline, "status", lambda self, **kwargs: {"state": "ready"})
    calls = []

    class FakeAgent:
        def ask(self, query, **kwargs):
            calls.append((query, kwargs))
            return SimpleNamespace(model_dump=lambda **opts: {"status": "retrieval_only", "citations": []})

    monkeypatch.setattr(routes, "_agent", lambda *args, **kwargs: FakeAgent())
    response = client.post(
        "/api/ocop/query",
        json={
            "query": "Mẫu số 01",
            "retrieval_mode": "sparse",
            "use_llm": False,
        },
    )
    assert response.status_code == 200
    assert calls[0][0] == "Mẫu số 01"
    # A sparse-only deployment refuses dense/hybrid instead of silently answering with BM25.
    hybrid = {"query": "Mẫu số 01", "retrieval_mode": "hybrid", "use_llm": False}
    assert client.post("/api/ocop/query", json=hybrid).status_code == 422
    monkeypatch.setenv("OCOP_RETRIEVAL_PROFILE", "hybrid")
    monkeypatch.setattr(
        routes, "profile_status", lambda root: {"profile": "hybrid", "ready": True, "missing": []}
    )
    assert client.post("/api/ocop/query", json=hybrid).status_code == 200


def test_user_cannot_pass_private_auth_context():
    response = client.post(
        "/api/ocop/query",
        json={
            "query": "Rà soát hồ sơ của tôi",
            "tenant_id": "some-tenant",
            "authenticated": True,
            "use_llm": False,
        },
    )
    assert response.status_code == 422
