"""Publish an additive graph revision only when indexed inputs are unchanged.

This does not rebuild chunks, embeddings or collections. A changed catalog or
parent-chain input refuses this path and requires a real index refresh.
"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from ai_core.graph.ocop.builder import records, SCHEMA_REVISION
from ai_core.graph.ocop.grounding import usable, relation_usable
from ai_core.graph.ocop.integrity import validate_graph_snapshot, graph_index_mismatch
from ai_core.orchestration.ocop.catalog import build_catalog, _ENTITY_NODE_KINDS
from ai_core.retrieval.ocop.graph_context import CHUNK_NODE_TYPES, CHAIN_NODE_TYPES, PARENT_RELATIONS

CATALOG_TYPES = set(_ENTITY_NODE_KINDS) | {"CriterionSheet", "FormTemplate"}
INDEX_NODE_TYPES = CATALOG_TYPES | CHUNK_NODE_TYPES | CHAIN_NODE_TYPES | {"EvidenceUnit"}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _snapshot(graph, manifest):
    nested = graph / "snapshots" / manifest["graph_version"]
    return nested if nested.is_dir() else graph


def knowledge_digest(path):
    files = sorted(path.glob("*.jsonl")) + [path / "manifest.json"]
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.name.encode("utf-8") + b"\0")
        with file.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def _rows_digest(rows):
    digest = hashlib.sha256()
    for row in rows:
        digest.update((_json(row) + "\n").encode("utf-8"))
    return digest.hexdigest()


def indexed_evidence_inputs(units):
    """Match the page-root fallback projection of the unchanged index builder.

    All other fields remain byte-value equivalent; INDEX_VERSION is checked
    before this compatibility path can be used.
    """
    child_pages = {(u["source_id"], u["spans"][0]["pdf_page"]) for u in units if u["unit_kind"] != "page"}
    return [{**u, "unit_kind": "page_fallback"}
            if u["unit_kind"] == "page" and (u["source_id"], u["spans"][0]["pdf_page"]) not in child_pages else u
            for u in units]


def indexed_inputs(graph):
    """The ordered node fields and parent edges consumed by catalog/context builders."""
    digest, catalog_nodes, endpoints = hashlib.sha256(), [], {}
    for row in records(Path(graph) / "nodes.jsonl"):
        if not usable(row):
            continue
        endpoints[row["node_id"]] = {key: row.get(key) for key in ("source_id", "check", "review_status", "derived")}
        if row["node_type"] in CATALOG_TYPES:
            catalog_nodes.append(row)
        if row["node_type"] in INDEX_NODE_TYPES:
            view = {key: row.get(key) for key in ("node_id", "node_type", "source_id", "label",
                                                  "evidence_unit_ids", "citations", "properties")}
            digest.update((_json(view) + "\n").encode("utf-8"))
    for row in records(Path(graph) / "edges.jsonl"):
        if row["relation_type"] in PARENT_RELATIONS and relation_usable(row, endpoints):
            view = {key: row.get(key) for key in ("edge_id", "relation_type", "source_entity_id",
                                                  "target_entity_id", "evidence_unit_ids", "citations")}
            digest.update((_json(view) + "\n").encode("utf-8"))
    return digest.hexdigest(), catalog_nodes


def prove_index_compatibility(root, candidate_graph):
    root, candidate_graph = Path(root), Path(candidate_graph)
    base = root / "data/processed/ocop"
    old_graph = validate_graph_snapshot(base / "graph", check_semantic_config=False)
    new_graph = validate_graph_snapshot(candidate_graph)
    if new_graph.get("schema_revision") != SCHEMA_REVISION:
        raise ValueError("candidate graph schema differs from current builder")
    index = json.loads((base / "index/manifest.json").read_text(encoding="utf-8"))
    from ai_core.retrieval.ocop.index_pipeline import INDEX_VERSION, structured_records

    if index.get("index_version") != INDEX_VERSION:
        raise ValueError("index code changed; a genuine index refresh is required")
    problem = graph_index_mismatch(old_graph, index, strict=True)
    if problem:
        raise ValueError("current index is already inconsistent: " + problem)
    if new_graph["source_knowledge_version"] != old_graph["source_knowledge_version"]:
        raise ValueError("source knowledge version changed; index refresh required")
    if knowledge_digest(base / "knowledge") != new_graph["source_knowledge_sha256"]:
        raise ValueError("source knowledge changed after graph construction")
    units = list(records(base / "knowledge/evidence_units.jsonl"))
    unit_signature = _rows_digest(indexed_evidence_inputs(units))
    structured_signature = _rows_digest(structured_records(base / "knowledge", units))
    if unit_signature != _rows_digest(records(base / "index/evidence_units.jsonl")):
        raise ValueError("indexed evidence differs from current source; index refresh required")
    if structured_signature != _rows_digest(records(base / "index/structured.jsonl")):
        raise ValueError("indexed structured records differ; index refresh required")
    old_snapshot, new_snapshot = _snapshot(base / "graph", old_graph), _snapshot(candidate_graph, new_graph)
    validate_graph_snapshot(old_snapshot, check_semantic_config=False)
    validate_graph_snapshot(new_snapshot)
    old_signature, old_nodes = indexed_inputs(old_snapshot)
    new_signature, new_nodes = indexed_inputs(new_snapshot)
    if old_signature != new_signature:
        raise ValueError("indexed graph inputs changed; index refresh required")
    registry = root / "configs/ocop_sources.json"
    catalog = json.loads((base / "index/entity_catalog.json").read_text(encoding="utf-8"))
    if build_catalog(registry, old_nodes) != catalog or build_catalog(registry, new_nodes) != catalog:
        raise ValueError("entity catalog changed; index refresh required")
    outcome = deepcopy(index)
    outcome["structural_graph_version"] = new_graph["graph_version"]
    outcome["graph_binding"] = {"method": "identical_index_inputs_v1", "input_sha256": old_signature,
                                "previous_graph_version": old_graph["graph_version"],
                                "graph_version": new_graph["graph_version"],
                                "evidence_sha256": unit_signature, "structured_sha256": structured_signature,
                                "previous_knowledge_sha256": old_graph["source_knowledge_sha256"],
                                "current_knowledge_sha256": new_graph["source_knowledge_sha256"]}
    return new_graph, outcome


def _replace_json(path, value):
    pending = path.with_name("." + path.name + ".publish-next")
    pending.write_text(_json(value), encoding="utf-8")
    os.replace(pending, path)


def publish_additive_graph(root, candidate_graph):
    """Validate before writing; preserve old snapshots and roll back root files on failure."""
    from ocop_contracts.locking import process_lock

    root, candidate_graph = Path(root).resolve(), Path(candidate_graph).resolve()
    base = root / "data/processed/ocop"
    with process_lock(base / ".system.lock", wait_timeout=900):
        manifest, index = prove_index_compatibility(root, candidate_graph)
        destination = base / "graph"
        source = _snapshot(candidate_graph, manifest)
        snapshot = destination / "snapshots" / manifest["graph_version"]
        snapshot.parent.mkdir(exist_ok=True)
        if not snapshot.exists():
            pending = snapshot.with_name(".publication-" + uuid.uuid4().hex)
            pending.mkdir()
            for name in ("nodes.jsonl", "edges.jsonl", "manifest.json"):
                shutil.copyfile(source / name, pending / name)
            validate_graph_snapshot(pending)
            os.replace(pending, snapshot)
        else:
            existing = validate_graph_snapshot(snapshot)
            if existing["file_sha256"] != manifest["file_sha256"]:
                raise ValueError("immutable snapshot collision")
        protected_index = {path.name: _digest_file(path) for path in (base / "index").iterdir()
                           if path.is_file() and path.name != "manifest.json"}
        old = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
        old_index = json.loads((base / "index/manifest.json").read_text(encoding="utf-8"))
        old_snapshot = _snapshot(destination, old)
        if old_snapshot == destination:
            raise ValueError("publication requires an immutable rollback snapshot")
        marker = base / ".promoting"
        if marker.exists():
            raise ValueError("another publication is active")
        marker.write_text("updating\n", encoding="utf-8")
        try:
            for name in ("nodes.jsonl", "edges.jsonl"):
                pending = destination / ("." + name + ".publish-next")
                shutil.copyfile(snapshot / name, pending)
                os.replace(pending, destination / name)
            _replace_json(base / "index/manifest.json", index)
            _replace_json(destination / "manifest.json", manifest)
            if any(_digest_file(base / "index" / name) != digest for name, digest in protected_index.items()):
                raise RuntimeError("index content changed during graph-only publication")
        except Exception:
            for name in ("nodes.jsonl", "edges.jsonl"):
                pending = destination / ("." + name + ".publish-next")
                shutil.copyfile(old_snapshot / name, pending)
                os.replace(pending, destination / name)
            _replace_json(base / "index/manifest.json", old_index)
            _replace_json(destination / "manifest.json", old)
            raise
        finally:
            marker.unlink(missing_ok=True)
        return {"graph_version": manifest["graph_version"], "index_rebuilt": False,
                "index_binding": index["graph_binding"], "index_files_sha256": protected_index}


def rebuild_additive_graph(root):
    """Graph-only rebuild from existing EvidenceUnits; never invokes extraction or embedding."""
    from tempfile import TemporaryDirectory
    from ai_core.graph.ocop.builder import build_graph

    root = Path(root)
    # Built next to the corpus, not in the system temp directory, which may sit on a small drive.
    with TemporaryDirectory(prefix="ocop-build-graph-", dir=root / "data/processed/ocop") as temporary:
        candidate = Path(temporary) / "graph"
        build_graph(root / "data/processed/ocop/knowledge", candidate, extraction_dir=root / "data/extraction")
        return publish_additive_graph(root, candidate)
