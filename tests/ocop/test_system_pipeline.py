"""Regression contracts for the single PDF-to-answer orchestration entrypoint.

These run with local dummy artifacts: no OCR, network, models or databases.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_core.system.pipeline import OcopSystemPipeline, PipelineOptions


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture_pipeline(tmp_path: Path, monkeypatch, *, fail_graph=False):
    # Hermetic: never read the developer's .env (it may hold a paid API key).
    import ai_core.orchestration.ocop.llm as llm_mod
    monkeypatch.setattr(llm_mod, "load_env_file", lambda path=None: None)
    for key in ("OCOP_EXTRACT_LLM_PROVIDER", "OCOP_EXTRACT_LLM_MODEL", "OCOP_EXTRACT_OPENAI_BASE_URL",
                "OCOP_EXTRACT_OPENAI_API_KEY", "OCOP_EXTRACT_LLM_GLEANINGS", "OCOP_EXTRACT_LLM_WORKERS"):
        monkeypatch.delenv(key, raising=False)
    system = OcopSystemPipeline(tmp_path)
    monkeypatch.setattr(OcopSystemPipeline, "source_snapshot", lambda self: (12, "approved-snapshot"))
    calls = []
    from ai_core.graph.ocop.builder import build_graph as real_build_graph

    def pdf(root, *, output, **kwargs):
        calls.append("pdf")
        output.mkdir(parents=True)
        from ai_core.processing.ocop.artifact_cache import PARSER_VERSION
        manifest = {"complete": True, "parser_version":PARSER_VERSION,
                    "input_snapshot_sha256": "approved-snapshot", "counts": {"pages": 1},
                    "dpi": kwargs["dpi"], "engine_requested": "easyocr_vietocr", "ocr_enabled": True}
        write_json(output / "manifest.json", manifest)
        return manifest

    def knowledge(root, *, input_dir, output_dir, **kwargs):
        assert (input_dir / "manifest.json").is_file()
        calls.append("evidence")
        output_dir.mkdir(parents=True)
        from ai_core.processing.ocop.knowledge_extract import VERSION as KNOWLEDGE_VERSION
        from ai_core.knowledge.ocop.llm_proposals import semantic_profile
        client = kwargs.get("semantic_client")
        # Same semantic_proposals contract as the real extractor, so reuse is exercised honestly.
        semantic = {"enabled": client is not None, "processed_unit_count": 0, "errors": 0,
                    "eligible_unit_count": 0, "selected_unit_count": 0, "omitted_unit_count": 0,
                    "model": "none" if client is None else semantic_profile(
                        client.model, kwargs.get("semantic_max_units", 50), kwargs.get("semantic_gleanings", 1))}
        manifest = {"complete": True, "source_snapshot_sha256": "approved-snapshot",
                    "pipeline_version": KNOWLEDGE_VERSION, "semantic_proposals": semantic,
                    "corpus_version": "knowledge-fixture", "counts": {"evidence_units": 2}}
        write_json(output_dir / "manifest.json", manifest)
        for filename in ("evidence_units.jsonl", "entities.jsonl", "relations.jsonl",
                         "business_entities.jsonl", "business_relations.jsonl", "business_rules.jsonl"):
            (output_dir / filename).write_text("", encoding="utf-8")
        return manifest

    def index(*, knowledge, index_dir, **kwargs):
        assert (knowledge / "evidence_units.jsonl").exists()
        calls.append("index")
        index_dir.mkdir(parents=True)
        from ai_core.retrieval.ocop.index_pipeline import INDEX_VERSION
        manifest = {"source_knowledge_version": "knowledge-fixture", "corpus_version": "index-fixture",
                    "index_version": INDEX_VERSION,
                    "status": "sparse_ready", "dense": {"enabled": False}}
        write_json(index_dir / "manifest.json", manifest)
        (index_dir / "chunks.jsonl").write_text("", encoding="utf-8")
        (index_dir / "bm25.json.gz").write_bytes(b"TEST")
        return manifest

    def graph(knowledge, output, *, review_decisions=None):
        assert (knowledge / "manifest.json").exists()
        calls.append("graph")
        if fail_graph:
            raise RuntimeError("graph failure")
        # Exercise the real graph snapshot contract, including automatic acceptance
        # files and hashes; only expensive OCR/index services remain mocked.
        return real_build_graph(knowledge, output, review_decisions=review_decisions)

    import ai_core.processing.ocop.pdf_pipeline as pdf_mod
    import ai_core.processing.ocop.knowledge_extract as knowledge_mod
    import ai_core.retrieval.ocop.index_pipeline as index_mod
    import ai_core.graph.ocop.builder as graph_mod
    monkeypatch.setattr(pdf_mod, "run_pipeline", pdf)
    monkeypatch.setattr(knowledge_mod, "extract_artifacts", knowledge)
    monkeypatch.setattr(index_mod, "build_index", index)
    monkeypatch.setattr(graph_mod, "build_graph", graph)
    return system, calls


def test_run_follows_one_dependency_chain_and_reuses_corpus(tmp_path, monkeypatch):
    system, calls = fixture_pipeline(tmp_path, monkeypatch)
    first = system.ensure()
    assert first["state"] == "ready"
    assert first["reused"] is False
    assert calls == ["pdf", "evidence", "graph", "index"]
    second = system.ensure()
    assert second["reused"] is True
    assert calls == ["pdf", "evidence", "graph", "index"]
    assert not list(system.data.glob("ocop-build-*"))


def test_stale_retrieval_algorithm_version_requires_reindex(tmp_path,monkeypatch):
    system,_=fixture_pipeline(tmp_path,monkeypatch)
    system.ensure()
    manifest_path=system.data/'index'/'manifest.json'
    previous=json.loads(manifest_path.read_text())
    previous['index_version']='old-tokenizer-index'
    write_json(manifest_path,previous)
    assert system.status(validate_sources=True)['state']=='not_ready'
    assert system.ensure()['state']=='ready'


def test_failed_rebuild_preserves_previous_corpus(tmp_path, monkeypatch):
    system, _ = fixture_pipeline(tmp_path, monkeypatch)
    system.ensure()
    original = (system.data / "index" / "manifest.json").read_bytes()
    fixture_pipeline(tmp_path, monkeypatch, fail_graph=True)
    with pytest.raises(RuntimeError, match="graph failure"):
        system.ensure(PipelineOptions(refresh=True))
    assert (system.data / "index" / "manifest.json").read_bytes() == original
    assert system.status(validate_sources=True)["state"] == "ready"
    assert not (system.data / ".system.lock").exists()


def test_changed_approved_source_forces_not_ready(tmp_path, monkeypatch):
    system, _ = fixture_pipeline(tmp_path, monkeypatch)
    system.ensure()
    monkeypatch.setattr(OcopSystemPipeline, "source_snapshot", lambda self: (12, "different-snapshot"))
    assert system.status(validate_sources=True)["state"] == "not_ready"


def test_explicit_dense_requirement_does_not_silently_accept_sparse(tmp_path, monkeypatch):
    system, _ = fixture_pipeline(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="dense indexing"):
        system.ensure(PipelineOptions(dense=True))
    assert system.status()["state"] == "not_ready"


def test_dense_upgrade_does_not_rerun_pdf_or_extraction(tmp_path, monkeypatch):
    system, calls = fixture_pipeline(tmp_path, monkeypatch)
    system.ensure()
    import ai_core.retrieval.ocop.index_pipeline as index_mod
    original_index = index_mod.build_index

    def dense_index(**kwargs):
        result = original_index(**kwargs)
        result["status"] = "hybrid_ready"
        result["dense"] = {"enabled": True, "model_id": "google/embeddinggemma-300m",
                           "revision": None, "host": "localhost", "port": 6333}
        write_json(kwargs["index_dir"] / "manifest.json", result)
        return result

    monkeypatch.setattr(index_mod, "build_index", dense_index)
    upgraded = system.ensure(PipelineOptions(dense=True))
    assert upgraded["dense_ready"] is True
    assert calls == ["pdf", "evidence", "graph", "index", "index"]
    assert system.ensure(PipelineOptions(dense=True))["reused"] is True


def test_promotion_exposes_explicit_updating_state(tmp_path, monkeypatch):
    system, _ = fixture_pipeline(tmp_path, monkeypatch)
    system.ensure()
    (system.data / ".promoting").write_text("updating", encoding="utf-8")
    assert system.status(validate_sources=True)["state"] == "updating"
    (system.data / ".promoting").unlink()


def test_invalid_new_bundle_rolls_back_after_directory_promotion(tmp_path, monkeypatch):
    system, _ = fixture_pipeline(tmp_path, monkeypatch)
    system.ensure()
    before = (system.data / 'index' / 'manifest.json').read_bytes()
    import ai_core.graph.ocop.builder as graph_mod
    real_graph = graph_mod.build_graph

    def malformed_graph(knowledge, output, *, review_decisions=None):
        result = real_graph(knowledge, output,review_decisions=review_decisions)
        result['source_knowledge_version'] = 'knowledge-fixture'
        # Force a post-rename lineage failure not caught by the preflight.
        result['status'] = 'broken_state'
        write_json(output / 'manifest.json', result)
        return result

    monkeypatch.setattr(graph_mod, 'build_graph', malformed_graph)
    with pytest.raises(RuntimeError, match='Promoted OCOP corpus failed'):
        system.ensure(PipelineOptions(refresh=True))
    assert (system.data / 'index' / 'manifest.json').read_bytes() == before
    assert system.status(validate_sources=True)['state'] == 'ready'
    assert not (system.data / '.promoting').exists()


def test_llm_extraction_is_reused_until_the_extraction_model_changes(tmp_path, monkeypatch):
    system, calls = fixture_pipeline(tmp_path, monkeypatch)
    assert PipelineOptions().semantic_extract is True
    system.ensure()
    assert system.ensure()["reused"] is True and calls.count("evidence") == 1
    monkeypatch.setenv("OCOP_EXTRACT_LLM_MODEL", "another-model")
    system.ensure()
    assert calls.count("evidence") == 2   # different model: knowledge is extracted again


def test_incomplete_llm_run_is_resumed_instead_of_reused(tmp_path, monkeypatch):
    system, calls = fixture_pipeline(tmp_path, monkeypatch)
    system.ensure()
    path=system.data/'knowledge/manifest.json'
    manifest=json.loads(path.read_text(encoding='utf-8'))
    manifest['semantic_proposals']['errors']=1
    write_json(path,manifest)
    system.ensure()
    assert calls.count('evidence') == 2
