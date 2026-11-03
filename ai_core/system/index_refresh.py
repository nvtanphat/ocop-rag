"""Rebuild the retrieval index after the graph snapshot changed (human review, rebuild).

The index records ``structural_graph_version`` and its entity catalog and parent chains come from the graph, so a new
graph snapshot needs a matching index. The refresh reuses the settings the current index was built with, builds into a
staging directory, checks the graph<->index contract, then swaps the directory under the ``.promoting`` marker that
makes the public API answer "updating" instead of mixing versions. A failed refresh leaves the old index in place.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ai_core.graph.ocop.integrity import graph_index_mismatch


LOCK_WAIT_SECONDS = 900


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def refresh_index_after_graph_change(root: Path) -> dict:
    """Serialised with corpus builds and review rebuilds; a waiting refresh finds the index already current."""
    from ocop_contracts.locking import process_lock

    with process_lock(Path(root) / "data/processed/ocop/.system.lock", wait_timeout=LOCK_WAIT_SECONDS):
        return _refresh(Path(root))


def _refresh(root: Path) -> dict:
    from ai_core.retrieval.ocop.index_pipeline import INDEX_VERSION, build_index
    from ai_core.retrieval.ocop import search as search_module

    base = Path(root) / "data/processed/ocop"
    index_dir, graph_dir, staging, previous = (
        base / "index",
        base / "graph",
        base / "index.refresh",
        base / "index.previous",
    )
    old, graph = _read(index_dir / "manifest.json"), _read(graph_dir / "manifest.json")
    if not old or not graph:
        raise RuntimeError("index and graph must both exist before a refresh")
    # The chunker and the index builder are fingerprinted (INDEX_VERSION): changed code makes the index stale too.
    if graph_index_mismatch(graph, old, strict=True) is None and old.get("index_version") == INDEX_VERSION:
        return {"status": "current", "graph_version": graph["graph_version"]}
    config, dense = old.get("config") or {}, old.get("dense") or {}
    for leftover in (staging, previous):
        shutil.rmtree(leftover, ignore_errors=True)
    options = {
        "max_words": config.get("max_words", 200),
        "overlap": config.get("overlap", 24),
        "token_budget": config.get("token_budget", 512),
        "model_max_tokens": config.get("model_max_tokens"),
        "tokenizer_path": config.get("tokenizer_path"),
        "allow_partial": old.get("source_complete") is False,
    }
    if dense.get("enabled"):
        options.update(
            with_dense=True,
            embedding_model=dense["model_id"],
            embedding_revision=dense.get("revision"),
            qdrant_host=dense["host"],
            qdrant_port=dense["port"],
        )
    try:
        new = build_index(knowledge=base / "knowledge", index_dir=staging, graph_dir=graph_dir, **options)
        problem = graph_index_mismatch(graph, new, strict=True)
        if problem:
            raise RuntimeError("refreshed index does not match the graph: " + problem)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    marker = base / ".promoting"
    marker.write_text("updating\n", encoding="utf-8")
    try:
        index_dir.rename(previous)
        try:
            staging.rename(index_dir)
        except OSError:
            previous.rename(index_dir)
            raise
        shutil.rmtree(previous, ignore_errors=True)
    finally:
        marker.unlink(missing_ok=True)
    search_module._indexed_scope_tokens.cache_clear()
    old_collection, new_collection = dense.get("collection"), (new.get("dense") or {}).get("collection")
    if old_collection and old_collection != new_collection:
        _drop_collection(dense, old_collection)
    return {
        "status": "refreshed",
        "graph_version": graph["graph_version"],
        "corpus_version": new["corpus_version"],
        "dense": bool(new.get("dense", {}).get("enabled")),
    }


def _drop_collection(dense: dict, name: str) -> None:
    """Best effort: the superseded Qdrant collection is garbage once the new index is live."""
    try:
        from qdrant_client import QdrantClient

        QdrantClient(host=dense["host"], port=dense["port"]).delete_collection(name)
    except Exception:  # a leftover collection costs disk only; never fail a published refresh over it
        pass
