"""A deployment promises either sparse-only or hybrid retrieval and reports when it cannot keep that promise."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ai_core.system import profile as profile_module
from ai_core.system.profile import configured_profile, profile_status
from backend.api import ocop_routes as routes
from backend.api.ocop_main import app

client = TestClient(app)


def _write_manifest(root, dense):
    index = root / "data/processed/ocop/index"
    index.mkdir(parents=True)
    (index / "manifest.json").write_text(json.dumps({"dense": dense}), encoding="utf-8")


def test_default_profile_is_sparse_and_ready(tmp_path):
    assert profile_status(tmp_path, {}) == {"profile": "sparse", "ready": True, "missing": []}


def test_rerank_is_a_deployment_choice_that_needs_the_hybrid_profile(tmp_path):
    assert profile_status(tmp_path, {"OCOP_RERANK": "1"})["missing"] == ["rerank_requires_hybrid_profile"]
    assert profile_status(tmp_path, {"OCOP_RERANK": "0"})["ready"] is True


def test_only_hybrid_requests_use_the_reranker(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from ai_core.system.pipeline import OcopSystemPipeline

    (tmp_path / "index").mkdir()
    (tmp_path / "index/manifest.json").write_text('{"corpus_version":"fixture"}', encoding="utf-8")
    monkeypatch.setattr(routes, "DATA", tmp_path)
    monkeypatch.setattr(OcopSystemPipeline, "status", lambda self, **k: {"state": "ready"})
    monkeypatch.setattr(routes, "profile_status", lambda root: {"profile": "hybrid", "ready": True, "missing": []})
    seen = {}

    def fake_agent(with_llm, mode, version="", partial=False, rerank=False):
        seen[mode] = rerank
        return SimpleNamespace(ask=lambda *a, **k: SimpleNamespace(model_dump=lambda **o: {"status": "x", "citations": []}))

    monkeypatch.setattr(routes, "_agent", fake_agent)
    monkeypatch.setenv("OCOP_RERANK", "1")
    for mode in ("sparse", "hybrid"):
        client.post("/api/ocop/query", json={"query": "OCOP là gì", "retrieval_mode": mode, "use_llm": False})
    assert seen == {"sparse": False, "hybrid": True}
    monkeypatch.delenv("OCOP_RERANK")
    client.post("/api/ocop/query", json={"query": "OCOP là gì", "retrieval_mode": "hybrid", "use_llm": False})
    assert seen["hybrid"] is False


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError):
        configured_profile({"OCOP_RETRIEVAL_PROFILE": "dense-only"})


def test_hybrid_profile_names_every_unmet_requirement(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module.importlib.util, "find_spec", lambda name: None)
    status = profile_status(tmp_path, {"OCOP_RETRIEVAL_PROFILE": "hybrid"})
    assert status["ready"] is False
    assert {"dependency:sentence_transformers", "dependency:qdrant_client", "dense_index_not_built"} <= set(
        status["missing"]
    )


def test_hybrid_profile_requires_reachable_qdrant(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module.importlib.util, "find_spec", lambda name: object())
    _write_manifest(tmp_path, {"enabled": True, "host": "qdrant.invalid", "port": 6333})

    def refuse(*args, **kwargs):
        raise OSError("unreachable")

    monkeypatch.setattr(profile_module.socket, "create_connection", refuse)
    env = {"OCOP_RETRIEVAL_PROFILE": "hybrid"}
    assert profile_status(tmp_path, env)["missing"] == ["qdrant_unreachable"]

    class Open:
        def close(self):
            pass

    monkeypatch.setattr(profile_module.socket, "create_connection", lambda *a, **k: Open())
    assert profile_status(tmp_path, env)["ready"] is True


def test_sparse_deployment_rejects_dense_queries_instead_of_degrading(monkeypatch):
    monkeypatch.delenv("OCOP_RETRIEVAL_PROFILE", raising=False)
    for mode in ("dense", "hybrid"):
        response = client.post("/api/ocop/query", json={"query": "Mẫu số 01", "retrieval_mode": mode})
        assert response.status_code == 422


def test_unready_hybrid_deployment_is_not_ready_and_refuses_queries(monkeypatch, tmp_path):
    monkeypatch.setenv("OCOP_RETRIEVAL_PROFILE", "hybrid")
    monkeypatch.setattr(routes, "ROOT", tmp_path)
    assert client.get("/api/ocop/health").json()["status"] == "not_ready"
    response = client.post("/api/ocop/query", json={"query": "Mẫu số 01", "retrieval_mode": "hybrid"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "retrieval_profile_unready"
