"""One end-to-end OCOP corpus pipeline.

Immutable PDF inputs are checked against the approved snapshot. Everything
produced from those inputs is built off-line in a temporary tree, validated,
then promoted. Existing corpus artifacts remain available if construction
fails. RAG reads an independently produced OCR dataset and never executes OCR.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterator

from ocop_contracts.pdf_loader import checked_sources
from ocop_contracts.dataset import DEFAULT_DATASET, SCHEMA_VERSION, read_dataset, materialize_dataset
from ocop_contracts.locking import process_lock

PARTS = ("pages", "knowledge", "index", "graph")


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    """OS lock is released automatically when the build process dies."""
    with process_lock(path):
        yield



def _semantic_profile(options: "PipelineOptions") -> str:
    from ai_core.knowledge.ocop.llm_proposals import semantic_profile
    from ai_core.orchestration.ocop.llm import extraction_gleanings, extraction_identity
    return semantic_profile(extraction_identity(), options.semantic_max_units, extraction_gleanings())


SEMANTIC_STATES = ("disabled", "complete", "partial", "failed")


def semantic_state(metadata: dict, *, max_units: int | None = None) -> dict:
    """Readiness of the LLM extraction layer of a built corpus.

    * disabled: the corpus was built on purpose without the extraction LLM; this is a valid corpus, not an error;
    * complete: every selected unit was processed with no error;
    * partial: run without errors but some selected units were not processed (resume before publishing);
    * failed: the run recorded errors.
    ``fingerprint`` is the recorded extraction profile; whether it equals the *current* configuration is reported
    separately by status() (``semantic_matches_config``).
    """
    metadata = metadata or {}
    if metadata.get("enabled") is not True:
        return {"state": "disabled", "fingerprint": metadata.get("model") or "none"}
    eligible, selected = metadata.get("eligible_unit_count"), metadata.get("selected_unit_count")
    processed, errors = metadata.get("processed_unit_count"), metadata.get("errors")
    detail = {"fingerprint": metadata.get("model"), "eligible_units": eligible, "selected_units": selected,
              "processed_units": processed, "errors": errors}
    if not isinstance(errors, int) or errors > 0:
        return {"state": "failed", **detail}
    expected = eligible if max_units is None else (min(eligible, max_units) if isinstance(eligible, int) else None)
    if (isinstance(selected, int) and isinstance(eligible, int) and selected == expected and processed == selected):
        return {"state": "complete", **detail}
    return {"state": "partial", **detail}


def _semantic_complete(metadata: dict, options: "PipelineOptions") -> bool:
    if not options.semantic_extract:
        return True
    state = semantic_state(metadata, max_units=options.semantic_max_units)
    return state["state"] == "complete" and metadata.get("model") == _semantic_profile(options)


@dataclass(frozen=True)
class PipelineOptions:
    ocr_dataset: Path | None = None
    dpi: int = 300
    dense: bool = False
    mongo: bool = False
    neo4j: bool = False
    embedding_model: str = "google/embeddinggemma-300m"
    embedding_revision: str | None = None
    mongo_uri: str = "mongodb://127.0.0.1:27017"
    mongo_database: str = "ocop_rag"
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    refresh: bool = False
    semantic_extract: bool = True
    semantic_max_units: int | None = None  # every eligible unit unless explicitly capped


class OcopSystemPipeline:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.data = self.root / "data" / "processed" / "ocop"
        self.status_file = self.data / "system_manifest.json"

    def source_snapshot(self) -> tuple[int, str]:
        sources, lock = checked_sources(
            self.root,
            self.root / "configs" / "ocop_sources.json",
            self.root / "configs" / "ocop_sources.lock.json",
        )
        return len(sources), lock["aggregate_sha256"]

    def status(self, *, validate_sources: bool = False) -> dict[str, Any]:
        page = _load_json(self.data / "pages" / "manifest.json")
        knowledge = _load_json(self.data / "knowledge" / "manifest.json")
        index = _load_json(self.data / "index" / "manifest.json")
        graph = _load_json(self.data / "graph" / "manifest.json")
        manifest = _load_json(self.status_file)
        try:
            sources, snapshot = self.source_snapshot() if validate_sources else (None, page.get("input_snapshot_sha256"))
            source_ok = True
        except (RuntimeError, ValueError, FileNotFoundError, OSError) as exc:
            sources, snapshot, source_ok = None, None, False
            source_error = str(exc)
        required = {
            "pages": ("manifest.json",),
            "knowledge": ("manifest.json", "evidence_units.jsonl", "entities.jsonl", "relations.jsonl"),
            "index": ("manifest.json", "chunks.jsonl", "bm25.json.gz"),
            "graph": ("manifest.json", "nodes.jsonl", "edges.jsonl"),
        }
        files_ok = all(all((self.data / component / filename).is_file() for filename in filenames)
                       for component, filenames in required.items())
        business_files = ("business_entities.jsonl", "business_relations.jsonl", "business_rules.jsonl")
        business_ready = all((self.data / "knowledge" / name).is_file() for name in business_files)
        from ai_core.processing.ocop.knowledge_extract import VERSION as KNOWLEDGE_VERSION
        business_consistent = (
            knowledge.get("pipeline_version") == KNOWLEDGE_VERSION and business_ready
        )
        from ai_core.retrieval.ocop.index_pipeline import INDEX_VERSION
        from ai_core.graph.ocop.review import ledger_path,ledger_digest
        from ai_core.graph.ocop.builder import SCHEMA_REVISION
        from ai_core.graph.ocop.integrity import graph_index_mismatch
        semantic = semantic_state(knowledge.get("semantic_proposals", {}))
        try:
            matches_config = (semantic["state"] == "disabled"
                              or knowledge.get("semantic_proposals", {}).get("model") == _semantic_profile(PipelineOptions()))
        except (RuntimeError, ValueError):
            matches_config = None  # the extraction configuration itself is unusable
        review_current=(graph.get('human_review',{}).get('ledger_sha256',ledger_digest(None))
                        ==ledger_digest(ledger_path(self.root)))
        lineage_ok = bool(
            business_consistent and page.get("schema_version")==SCHEMA_VERSION
            and bool(page.get("dataset_digest"))
            and knowledge.get("ocr_dataset_digest")==page.get("dataset_digest") and
            source_ok and snapshot and page.get("complete") and knowledge.get("complete")
            and page.get("input_snapshot_sha256") == snapshot
            and knowledge.get("source_snapshot_sha256") == snapshot
            and index.get("source_knowledge_version") == knowledge.get("corpus_version")
            and index.get('index_version') == INDEX_VERSION
            and graph.get("source_knowledge_version") == knowledge.get("corpus_version")
            and graph_index_mismatch(graph, index, strict=True) is None
            and semantic["state"] in ("disabled", "complete")
            and index.get("status") in ("sparse_ready", "hybrid_ready")
            and graph.get("status") == "local_ready" and files_ok and review_current
            and graph.get('schema_revision') == SCHEMA_REVISION and bool(graph.get('checks'))
            and all((self.data/'graph'/name).is_file() for name in
                    ('nodes.jsonl','edges.jsonl'))
        )
        updating = (self.data / ".promoting").exists()
        result = {
            "state": "updating" if updating else ("ready" if lineage_ok else "not_ready"),
            "lineage_ok": bool(lineage_ok),
            "sources": sources,
            "source_snapshot_sha256": snapshot,
            "pdf_pages": page.get("counts", {}).get("pages", 0),
            "pdf_parser_version": page.get("ocr_version"),
            "pdf_parser_current":page.get("schema_version")==SCHEMA_VERSION,
            "ocr_dataset_digest":page.get("dataset_digest"),
            "evidence_units": knowledge.get("counts", {}).get("evidence_units", knowledge.get("counts", {}).get("units", 0)),
            "corpus_version": index.get("corpus_version"),
            "dense_ready": bool(index.get("dense", {}).get("enabled", False)),
            "graph_ready": graph.get("status") == "local_ready",
            'automatic_graph': graph.get('checks', {}),
            "human_review_current":review_current,
            "business_semantics_ready": business_ready,
            "semantic_proposals": knowledge.get("semantic_proposals",{}),
            "semantic": semantic,
            "semantic_matches_config": matches_config,
            "neo4j_ready": graph.get("neo4j", {}).get("status") == "uploaded",
            "mongo_ready": bool(index.get("mongo")),
            "model_generation": "qwen3.5:2b (optional Ollama service)",
            "provenance_status": "machine_extracted_not_legally_verified",
            "last_build": manifest.get("built_at"),
        }
        if not source_ok:
            result["source_error"] = source_error
        return result

    def ensure(self, options: PipelineOptions = PipelineOptions()) -> dict[str, Any]:
        """Build (or reuse) a coherent source-locked corpus, once per invocation."""
        with _exclusive_lock(self.data / ".system.lock"):
            # A killed build cannot clean TemporaryDirectory. The exclusive OS
            # lock proves no other builder owns these repo-local staging trees.
            for orphan in self.data.glob("ocop-build-*"):
                target = orphan.resolve()
                if target.is_relative_to(self.data.resolve()) and orphan.is_dir() and not orphan.is_symlink():
                    shutil.rmtree(orphan)
            current = self.status(validate_sources=True)
            if not current.get("source_snapshot_sha256"):
                raise RuntimeError(current.get("source_error", "source lock validation failed"))
            page_config = _load_json(self.data / "pages" / "manifest.json")
            dataset = (options.ocr_dataset or DEFAULT_DATASET).resolve()
            locked = _load_json(self.root / "configs/ocop_sources.lock.json")
            dataset_manifest, _ = read_dataset(dataset, locked)
            runtime_config_ok = page_config.get("dataset_digest") == dataset_manifest["dataset_digest"]
            if not options.refresh and current["state"] == "ready":
                index = _load_json(self.data / "index" / "manifest.json")
                graph = _load_json(self.data / "graph" / "manifest.json")
                mongo_ok = not options.mongo or bool(index.get("mongo"))
                neo4j_ok = not options.neo4j or graph.get("neo4j", {}).get("status") == "uploaded"
                dense_config_ok = (not options.dense or (current["dense_ready"]
                    and index.get("dense", {}).get("model_id") == options.embedding_model
                    and index.get("dense", {}).get("revision") == options.embedding_revision
                    and index.get("dense", {}).get("host") == options.qdrant_host
                    and index.get("dense", {}).get("port") == options.qdrant_port))
                page_config = _load_json(self.data / "pages" / "manifest.json")
                pdf_config_ok = runtime_config_ok
                knowledge_manifest = _load_json(self.data / "knowledge" / "manifest.json")
                semantic_ok = _semantic_complete(knowledge_manifest.get('semantic_proposals', {}), options)
                if dense_config_ok and pdf_config_ok and mongo_ok and neo4j_ok and semantic_ok:
                    return {**current, "reused": True}
            # Construct the complete pipeline away from the live artifact tree.
            with tempfile.TemporaryDirectory(prefix="ocop-build-", dir=self.data) as temporary:
                staging_dir = Path(temporary)
                try:
                    from ai_core.processing.ocop.knowledge_extract import extract_artifacts
                    from ai_core.retrieval.ocop.index_pipeline import build_index
                    from ai_core.graph.ocop.builder import build_graph, SCHEMA_REVISION

                    knowledge_config = _load_json(self.data / "knowledge" / "manifest.json")
                    # Reuse page extraction independently of knowledge version:
                    # upgrading evidence/schema MUST NOT trigger 315 expensive OCRs.
                    reuse_pages = (not options.refresh and page_config.get("complete")
                        and page_config.get("input_snapshot_sha256") == current.get("source_snapshot_sha256")
                        and runtime_config_ok)
                    knowledge_semantics = knowledge_config.get("semantic_proposals", {})
                    semantic_match = _semantic_complete(knowledge_semantics, options)
                    from ai_core.processing.ocop.knowledge_extract import VERSION as KNOWLEDGE_VERSION
                    reuse_knowledge = (reuse_pages and knowledge_config.get("complete")
                        and knowledge_config.get("ocr_dataset_digest") == dataset_manifest["dataset_digest"]
                        and knowledge_config.get("pipeline_version") == KNOWLEDGE_VERSION
                        and all((self.data / "knowledge" / name).is_file() for name in
                                ("business_entities.jsonl", "business_relations.jsonl", "business_rules.jsonl"))
                        and semantic_match)
                    if reuse_pages:
                        shutil.copytree(self.data / "pages", staging_dir / "pages")
                        page = page_config
                    else:
                        page = materialize_dataset(dataset, staging_dir / "pages", dataset_manifest)
                    if not page.get("complete"):
                        raise RuntimeError("PDF parser did not produce a complete source-locked corpus")
                    if reuse_knowledge:
                        shutil.copytree(self.data / "knowledge", staging_dir / "knowledge")
                        knowledge = knowledge_config
                    else:
                        semantic_client = None
                        if options.semantic_extract:
                            from ai_core.orchestration.ocop.llm import (
                                extraction_gleanings, extraction_workers, make_extraction_client)
                            semantic_client = make_extraction_client()
                        knowledge = extract_artifacts(self.root, input_dir=staging_dir / "pages",
                            output_dir=staging_dir / "knowledge", semantic_client=semantic_client,
                            semantic_max_units=options.semantic_max_units,
                            semantic_cache_dir=self.data / "cache" / "llm",
                            semantic_workers=extraction_workers() if options.semantic_extract else 1,
                            semantic_gleanings=extraction_gleanings() if options.semantic_extract else 1)
                    knowledge["ocr_dataset_version"] = dataset_manifest["ocr_version"]
                    knowledge["ocr_dataset_digest"] = dataset_manifest["dataset_digest"]
                    _write_json(staging_dir / "knowledge" / "manifest.json", knowledge)
                    if not knowledge.get("complete"):
                        raise RuntimeError("Evidence extraction did not cover the entire PDF corpus")
                    if not _semantic_complete(knowledge.get('semantic_proposals', {}), options):
                        raise RuntimeError('LLM extraction incomplete; rerun to resume cached chunks before publication')
                    old_graph = _load_json(self.data / "graph" / "manifest.json")
                    from ai_core.graph.ocop.review import ledger_path,ledger_digest
                    if (reuse_knowledge and old_graph.get("status") == "local_ready"
                            and old_graph.get('schema_revision') == SCHEMA_REVISION and old_graph.get('checks')
                            and old_graph.get("source_knowledge_version") == knowledge.get("corpus_version")
                            and old_graph.get('human_review',{}).get('ledger_sha256',ledger_digest(None))
                                ==ledger_digest(ledger_path(self.root))):
                        shutil.copytree(self.data / "graph", staging_dir / "graph")
                        graph = old_graph
                    else:
                        from ai_core.graph.ocop.review import ledger_path
                        prior_graph = self.data / 'graph'
                        if (prior_graph / 'snapshots').is_dir():
                            shutil.copytree(prior_graph / 'snapshots', staging_dir / 'graph' / 'snapshots', dirs_exist_ok=True)
                            if (prior_graph / 'manifest.json').is_file():
                                shutil.copy2(prior_graph / 'manifest.json', staging_dir / 'graph' / 'manifest.json')
                        graph = build_graph(staging_dir / "knowledge", staging_dir / "graph",review_decisions=ledger_path(self.root))
                    index = build_index(
                        knowledge=staging_dir / "knowledge", index_dir=staging_dir / "index",
                        with_dense=options.dense,
                        with_mongo=options.mongo,
                        mongo_uri=options.mongo_uri, mongo_database=options.mongo_database,
                        embedding_model=options.embedding_model, embedding_revision=options.embedding_revision,
                        qdrant_host=options.qdrant_host, qdrant_port=options.qdrant_port,
                        model_max_tokens=__import__('ai_core.retrieval.ocop.models_config', fromlist=['get_model_max_tokens']).get_model_max_tokens(self.root),
                    )
                    if index["source_knowledge_version"] != knowledge["corpus_version"] or graph["source_knowledge_version"] != knowledge["corpus_version"]:
                        raise RuntimeError("Cross-store corpus version mismatch")
                    if options.dense and not index.get("dense", {}).get("enabled"):
                        raise RuntimeError("Requested dense indexing was not completed")
                    if options.mongo and not index.get("mongo"):
                        raise RuntimeError("Requested MongoDB materialization was not completed")
                    if options.neo4j and graph.get("neo4j", {}).get("status") != "uploaded":
                        from ai_core.graph.ocop.store import publish_neo4j
                        password = os.getenv("NEO4J_PASSWORD")
                        if not password:
                            raise RuntimeError("NEO4J_PASSWORD is required for Neo4j publishing")
                        graph["neo4j"] = publish_neo4j(staging_dir / "graph", uri=options.neo4j_uri,
                                user=options.neo4j_user, password=password, verified_only=False)
                        _write_json(staging_dir / "graph" / "manifest.json", graph)
                    self._promote(staging_dir)
                except Exception:
                    # TemporaryDirectory removes partial products; current published corpus is untouched.
                    raise
            _write_json(self.status_file, {
                "built_at": datetime.now(timezone.utc).isoformat(),
                "source_snapshot_sha256": page["input_snapshot_sha256"],
                "corpus_version": index["corpus_version"],
                "knowledge_version": knowledge["corpus_version"],
                "graph_version": graph["graph_version"],
                "index_status": index["status"],
                "note": "Machine extraction is not legal review or official OCOP certification",
            })
            result = self.status(validate_sources=True)
            if result["state"] != "ready":
                raise RuntimeError(f"Post-publish corpus validation failed: {result}")
            return {**result, "reused": False}

    def _promote(self, staging_dir: Path) -> None:
        """Promote a checked local bundle with rollback on filesystem errors.

        Multiple directory renames cannot be transactionally atomic: API readers
        should not query while promotion is underway. Existing builds are saved
        until all renames finish. External DB publications have their own lifecycle.
        """
        backup = staging_dir / "_backup"
        backup.mkdir()
        promotion_marker = self.data / ".promoting"
        promotion_marker.write_text("updating\n", encoding="utf-8")
        moved: list[str] = []
        installed: list[str] = []
        try:
            for name in PARTS:
                target = self.data / name
                if target.exists():
                    target.rename(backup / name)
                    moved.append(name)
                (staging_dir / name).rename(target)
                installed.append(name)
            # Validate the *installed* bundle while backups are still on disk.
            # Prior behavior could publish an invalid bundle and only notice
            # after TemporaryDirectory had already discarded the backup.
            ready = self.status(validate_sources=True)
            if not ready["lineage_ok"]:
                raise RuntimeError("Promoted OCOP corpus failed cross-store/source validation")
        except Exception:
            for name in reversed(installed):
                shutil.rmtree(self.data / name, ignore_errors=True)
            for name in reversed(moved):
                (backup / name).rename(self.data / name)
            raise
        finally:
            promotion_marker.unlink(missing_ok=True)
