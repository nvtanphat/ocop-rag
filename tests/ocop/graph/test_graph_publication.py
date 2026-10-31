from copy import deepcopy
import hashlib
import json
import shutil

import pytest

from ai_core.graph.ocop.builder import SCHEMA_REVISION
from ai_core.orchestration.ocop.catalog import build_catalog
from ai_core.retrieval.ocop.index_pipeline import INDEX_VERSION
from ai_core.system import graph_publication as publication


def _graph(path, version, nodes, knowledge_hash):
    path.mkdir(parents=True)
    (path / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in nodes), encoding="utf-8")
    (path / "edges.jsonl").write_text("", encoding="utf-8")
    manifest = {"graph_version": version, "schema_revision": SCHEMA_REVISION, "status": "local_ready",
                "source_knowledge_version": "k", "source_knowledge_sha256": knowledge_hash,
                "file_sha256": {name: hashlib.sha256((path / name).read_bytes()).hexdigest()
                                for name in ("nodes.jsonl", "edges.jsonl")}}
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    snapshot = path / "snapshots" / version
    snapshot.mkdir(parents=True)
    for name in ("nodes.jsonl", "edges.jsonl", "manifest.json"):
        shutil.copyfile(path / name, snapshot / name)


def _fixture(root, changed=False):
    base = root / "data/processed/ocop"
    (base / "knowledge").mkdir(parents=True)
    (base / "knowledge/manifest.json").write_text('{"corpus_version":"k"}')
    (base / "knowledge/evidence_units.jsonl").write_text("")
    digest = publication.knowledge_digest(base / "knowledge")
    row = {"node_id": "e", "node_type": "EvidenceUnit", "label": "e", "source_id": "S",
           "check": "passed", "evidence_unit_ids": ["u"], "properties": {"evidence_text": "original"}}
    _graph(base / "graph", "old", [row], digest)
    new_row = deepcopy(row)
    if changed:
        new_row["properties"]["evidence_text"] = "changed"
    proposal = {"node_id": "n", "node_type": "Obligation", "check": "passed", "derived": True}
    candidate = root / "candidate"
    _graph(candidate, "new", [new_row, proposal], digest)
    (root / "configs").mkdir()
    registry = root / "configs/ocop_sources.json"
    registry.write_text('{"sources":[]}', encoding="utf-8")
    (base / "index").mkdir()
    (base / "index/entity_catalog.json").write_text(json.dumps(build_catalog(registry, [])), encoding="utf-8")
    (base / "index/chunks.jsonl").write_bytes(b"immutable chunk content\n")
    (base / "index/evidence_units.jsonl").write_text("")
    (base / "index/structured.jsonl").write_text("")
    index = {"index_version": INDEX_VERSION, "source_knowledge_version": "k", "structural_graph_version": "old",
             "dense": {"collection": "unchanged-collection"}}
    (base / "index/manifest.json").write_text(json.dumps(index), encoding="utf-8")
    return base, candidate, index


def test_additive_publication_keeps_index_bytes_collection_and_old_snapshot(tmp_path):
    base, candidate, _ = _fixture(tmp_path)
    chunks = (base / "index/chunks.jsonl").read_bytes()
    result = publication.publish_additive_graph(tmp_path, candidate)
    assert result["index_rebuilt"] is False
    assert (base / "index/chunks.jsonl").read_bytes() == chunks
    index = json.loads((base / "index/manifest.json").read_text())
    assert index["structural_graph_version"] == "new"
    assert index["dense"]["collection"] == "unchanged-collection"
    assert (base / "graph/snapshots/old/manifest.json").exists()
    assert not (base / ".promoting").exists()


def test_changed_index_input_refuses_to_rebind_or_publish(tmp_path):
    base, candidate, original = _fixture(tmp_path, changed=True)
    with pytest.raises(ValueError, match="indexed graph inputs changed"):
        publication.publish_additive_graph(tmp_path, candidate)
    assert json.loads((base / "index/manifest.json").read_text()) == original
    assert json.loads((base / "graph/manifest.json").read_text())["graph_version"] == "old"


def test_failure_between_index_and_graph_commit_rolls_back(tmp_path, monkeypatch):
    base, candidate, original = _fixture(tmp_path)
    real = publication._replace_json
    failed = []

    def fail_once(path, value):
        if path == base / "graph/manifest.json" and not failed:
            failed.append(1)
            raise OSError("injected publication failure")
        return real(path, value)

    monkeypatch.setattr(publication, "_replace_json", fail_once)
    with pytest.raises(OSError, match="injected"):
        publication.publish_additive_graph(tmp_path, candidate)
    assert json.loads((base / "index/manifest.json").read_text()) == original
    assert json.loads((base / "graph/manifest.json").read_text())["graph_version"] == "old"
    assert (base / "graph/nodes.jsonl").read_bytes() == (base / "graph/snapshots/old/nodes.jsonl").read_bytes()
    assert not (base / ".promoting").exists()


def test_source_change_after_construction_refuses_publication(tmp_path):
    base, candidate, _ = _fixture(tmp_path)
    (base / "knowledge/manifest.json").write_text('{"corpus_version":"different"}')
    with pytest.raises(ValueError, match="source knowledge changed after"):
        publication.publish_additive_graph(tmp_path, candidate)


def test_changed_indexed_record_refuses_metadata_rebinding(tmp_path):
    base, candidate, _ = _fixture(tmp_path)
    (base / "index/structured.jsonl").write_text('{"changed":true}\n')
    with pytest.raises(ValueError, match="indexed structured records differ"):
        publication.publish_additive_graph(tmp_path, candidate)


def test_page_fallback_normalization_is_limited_to_pages_without_children():
    page = {"unit_id": "p", "unit_kind": "page", "source_id": "S", "spans": [{"pdf_page": 1}], "text": "source"}
    assert publication.indexed_evidence_inputs([page])[0]["unit_kind"] == "page_fallback"
    child = {**page, "unit_id": "c", "unit_kind": "article"}
    assert publication.indexed_evidence_inputs([page, child])[0] == page
    assert page["unit_kind"] == "page"


def test_index_input_signature_filters_unusable_parent_endpoints(tmp_path):
    doc = {"node_id": "d", "node_type": "SourceDocument", "source_id": "S", "label": "doc", "check": "passed"}
    article = {"node_id": "a", "node_type": "Article", "source_id": "S", "label": "article", "check": "passed"}
    parent = {"edge_id": "e", "source_entity_id": "d", "target_entity_id": "a", "relation_type": "HAS_ARTICLE",
              "source_id": "S", "check": "passed"}
    _graph(tmp_path / "before", "b", [doc, article], "k")
    _graph(tmp_path / "after", "a", [{**doc, "check": "failed"}, article], "k")
    for name in ("before", "after"):
        (tmp_path / name / "edges.jsonl").write_text(json.dumps(parent) + "\n", encoding="utf-8")
    assert publication.indexed_inputs(tmp_path / "before")[0] != publication.indexed_inputs(tmp_path / "after")[0]
