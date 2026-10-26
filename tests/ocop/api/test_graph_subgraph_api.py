"""The subgraph endpoint exposes only checked, public graph records with their PDF provenance."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from ai_core.graph.ocop.builder import build_graph
from backend.api import ocop_routes as routes
from backend.api.ocop_main import app

client = TestClient(app)


def _dump(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _build(root):
    knowledge = root / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "manifest.json").write_text(json.dumps({"complete": True, "corpus_version": "fixture"}))
    span = {"pdf_page": 3, "bbox": [0, 0, 200, 20], "block_id": "native:0:0", "source_sha256": "a" * 64}
    _dump(
        knowledge / "evidence_units.jsonl",
        [
            {
                "unit_id": "u1",
                "source_id": "D1",
                "review_status": "verified",
                "unit_kind": "article",
                "text": "Điều kiện OCOP từ hồ sơ A",
                "spans": [span],
            }
        ],
    )
    _dump(
        knowledge / "entities.jsonl",
        [
            {
                "entity_id": "doc1",
                "entity_type": "source_document",
                "source_id": "D1",
                "name": "Quy định A",
                "review_status": "verified",
                "evidence_unit_ids": ["u1"],
            }
        ],
    )
    _dump(knowledge / "relations.jsonl", [])
    graph = root / "data/processed/ocop/graph"
    build_graph(knowledge, graph)
    return graph


def test_subgraph_returns_checked_neighbourhood_with_provenance(tmp_path, monkeypatch):
    graph = _build(tmp_path)
    monkeypatch.setattr(routes, "ROOT", tmp_path)
    nodes = [json.loads(line) for line in (graph / "nodes.jsonl").read_text(encoding="utf-8").splitlines()]
    evidence_id = next(n["evidence_unit_ids"][0] for n in nodes if n["node_type"] == "SourceDocument")
    response = client.get("/api/ocop/graph/subgraph", params={"evidence_unit_id": evidence_id})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["graph_version"]
    assert body["nodes"] and set(body["seed_ids"]) <= {n["node_id"] for n in body["nodes"]}
    assert {n["check"] for n in body["nodes"]} <= {"passed", "human_verified"}
    assert all("machine_candidate" not in n for n in body["nodes"])
    cited = [c for n in body["nodes"] for c in n["citations"]]
    assert cited and all(c["pdf_page"] == 3 and c["source_sha256"] == "a" * 64 for c in cited)
    assert all(e["source"] in {n["node_id"] for n in body["nodes"]} for e in body["edges"])


def test_subgraph_requires_a_seed_and_reports_unknown_ones(tmp_path, monkeypatch):
    _build(tmp_path)
    monkeypatch.setattr(routes, "ROOT", tmp_path)
    assert client.get("/api/ocop/graph/subgraph").status_code == 422
    assert client.get("/api/ocop/graph/subgraph", params={"hops": 3, "node_id": "x"}).status_code == 422
    assert client.get("/api/ocop/graph/subgraph", params={"node_id": "unknown"}).json()["status"] == "no_seed"


def test_subgraph_without_a_graph_is_reported_not_invented(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "ROOT", tmp_path)
    body = client.get("/api/ocop/graph/subgraph", params={"node_id": "x"}).json()
    assert body["status"] == "no_graph" and body["nodes"] == []


def test_subgraph_fails_closed_on_a_stale_graph(tmp_path, monkeypatch):
    graph = _build(tmp_path)
    manifest = json.loads((graph / "manifest.json").read_text(encoding="utf-8"))
    manifest["schema_revision"] = "stale"
    (graph / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(routes, "ROOT", tmp_path)
    response = client.get("/api/ocop/graph/subgraph", params={"node_id": "x"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "graph_unavailable"
