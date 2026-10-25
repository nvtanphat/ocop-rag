"""Entire review lifecycle on a synthetic PDF. Never approves real corpus data."""

import json
import shutil
from pathlib import Path
import pytest
from ai_core.graph.ocop.builder import build_graph
from ai_core.graph.ocop.review import load_queue, record_decision, rebuild_reviewed_graph, ledger_path
from ai_core.graph.ocop.retriever import traverse


@pytest.fixture
def corpus(tmp_path):
    import fitz
    from ocop_contracts.registry import SourceDocument, snapshot, sha256_file

    pdf = tmp_path / "data/raw/ocop/synthetic.pdf"
    pdf.parent.mkdir(parents=True)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((20, 30), "Synthetic product and owner")
    doc.save(pdf)
    doc.close()
    source = SourceDocument(
        source_id="SYNTHETIC", path="data/raw/ocop/synthetic.pdf", source_kind="recognition_decision"
    )
    config = tmp_path / "configs"
    config.mkdir()
    (config / "ocop_sources.json").write_text(
        json.dumps({"schema_version": 1, "sources": [source.model_dump(mode="json")]})
    )
    (config / "ocop_sources.lock.json").write_text(json.dumps(snapshot(tmp_path, [source])))
    base = tmp_path / "data/processed/ocop"
    k = base / "knowledge"
    k.mkdir(parents=True)
    ref = {
        "source_id": "SYNTHETIC",
        "evidence_unit_id": "unit:synthetic",
        "pdf_page": 1,
        "bbox": [10, 10, 210, 50],
        "quote": "Synthetic product and owner",
        "source_sha256": sha256_file(pdf),
    }
    unit = {
        "unit_id": "unit:synthetic",
        "source_id": "SYNTHETIC",
        "unit_kind": "paragraph",
        "review_status": "needs_review",
        "text": ref["quote"],
        "spans": [{"pdf_page": 1, "bbox": ref["bbox"], "source_sha256": ref["source_sha256"]}],
        "structured": {},
    }

    def entity(eid, kind, label):
        return {
            "entity_id": eid,
            "kind": kind,
            "label": label,
            "source_id": "SYNTHETIC",
            "status": "candidate",
            "attributes": {"points_candidate": None} if kind == "Product" else {},
            "evidence": [ref],
        }

    layers = {
        "evidence_units": [unit],
        "entities": [],
        "relations": [],
        "business_entities": [
            entity("product:synthetic", "Product", "Synthetic product"),
            entity("owner:synthetic", "Organization", "Synthetic owner"),
        ],
        "business_relations": [
            {
                "relation_id": "relation:synthetic",
                "source_entity_id": "product:synthetic",
                "target_entity_id": "owner:synthetic",
                "relation_type": "OWNED_BY",
                "status": "candidate",
                "evidence": [ref],
            }
        ],
    }
    (k / "manifest.json").write_text(
        json.dumps(
            {"complete": True, "corpus_version": "synthetic-review", "counts": {"pages": 1, "units": 1}}
        )
    )
    for name, rows in layers.items():
        (k / (name + ".jsonl")).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    build_graph(k, base / "graph")
    index = base / "index"
    index.mkdir()
    (index / "manifest.json").write_text(
        json.dumps({"corpus_version": "synthetic-review", "source_knowledge_version": "synthetic-review"})
    )
    (index / "evidence_units.jsonl").write_text(json.dumps(unit) + "\n")
    return tmp_path


def decide(root, target, decision="approve", correction=None):
    item = next(i for i in load_queue(root) if i["target_id"] == target)
    record_decision(
        root, target, item["content_hash"], decision, "Synthetic human tester", correction=correction
    )
    rebuild_reviewed_graph(root)


def test_failed_dangling_edge_remains_reviewable_without_promotion(corpus):
    base = corpus / "data/processed/ocop"
    path = base / "knowledge/business_relations.jsonl"
    relation = json.loads(path.read_text(encoding="utf-8"))
    relation["target_entity_id"] = "missing:owner"
    path.write_text(json.dumps(relation) + "\n", encoding="utf-8")
    build_graph(base / "knowledge", base / "graph")
    items = load_queue(corpus)
    decide(corpus, next(i["target_id"] for i in items if i["type"] == "EvidenceUnit"))
    decide(corpus, "product:synthetic")
    edge = next(i for i in load_queue(corpus) if i["type"] == "OWNED_BY")
    decide(corpus, edge["target_id"])
    current = next(i for i in load_queue(corpus) if i["target_id"] == edge["target_id"])
    assert current["check"] == "failed" and current["check_reason"] == "missing_endpoint"
    assert not traverse(base / "graph", ["product:synthetic"], relations=["OWNED_BY"])["edges"]


def test_approve_is_scoped_and_verified_edge_requires_both_endpoints(corpus):
    items = load_queue(corpus)
    proof = next(i for i in items if i["type"] == "EvidenceUnit")
    edge = next(i for i in items if i["type"] == "OWNED_BY")
    decide(corpus, "product:synthetic")
    assert (
        next(i for i in load_queue(corpus) if i["target_id"] == "product:synthetic")["state"]
        == "waiting_for_evidence_review"
    )
    decide(corpus, proof["target_id"])
    decide(corpus, edge["target_id"])
    assert (
        next(i for i in load_queue(corpus) if i["target_id"] == edge["target_id"])["review_status"]
        != "verified"
    )
    decide(corpus, "owner:synthetic")
    graph = traverse(
        corpus / "data/processed/ocop/graph",
        ["product:synthetic"],
        verified_only=True,
        hops=1,
        relations=["OWNED_BY"],
    )
    assert len(graph["nodes"]) == 2 and len(graph["edges"]) == 1
    from ai_core.orchestration.ocop.tools import ToolRegistry

    result = ToolRegistry(corpus).dispatch(
        "search_graph", query="Synthetic product", slots={"graph_seed_ids": ["product:synthetic"]}, context={}
    )
    # Explicit ledger decisions, with evidence and endpoints approved, are usable.
    assert result["include_failed"] is False
    assert any(n["node_id"] == "owner:synthetic" and n["check"] == "human_verified" for n in result["nodes"])
    assert any(e["relation_type"] == "OWNED_BY" and e["check"] == "human_verified" for e in result["edges"])


def test_correct_preserves_ocr_and_reject_overrides_append_only(corpus):
    proof = next(i for i in load_queue(corpus) if i["type"] == "EvidenceUnit")
    decide(corpus, proof["target_id"])
    decide(corpus, "product:synthetic", "correct", {"properties": {"points_candidate": 3}})
    nodes = [
        json.loads(s)
        for s in (corpus / "data/processed/ocop/graph/nodes.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    node = next(n for n in nodes if n["node_id"] == "product:synthetic")
    assert node["properties"]["points_candidate"] == 3
    assert node["machine_candidate"]["properties"]["points_candidate"] is None
    assert node["human_review"]["asserted_correction"]["properties"]["points_candidate"] == 3
    first = ledger_path(corpus).read_bytes()
    decide(corpus, "product:synthetic", "reject")
    assert ledger_path(corpus).read_bytes().startswith(first)
    assert not traverse(corpus / "data/processed/ocop/graph", ["product:synthetic"], verified_only=True)[
        "nodes"
    ]


def test_stale_hash_blocks_write_and_extraction_change_requires_rereview(corpus):
    item = next(i for i in load_queue(corpus) if i["target_id"] == "product:synthetic")
    with pytest.raises(ValueError, match="stale"):
        record_decision(corpus, item["target_id"], "0" * 64, "approve", "tester")
    decide(corpus, item["target_id"])
    path = corpus / "data/processed/ocop/knowledge/business_entities.jsonl"
    rows = [json.loads(s) for s in path.read_text().splitlines()]
    rows[0]["label"] = "Changed extraction"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    rebuild_reviewed_graph(corpus)
    changed = next(i for i in load_queue(corpus) if i["target_id"] == item["target_id"])
    assert changed["state"] == "stale_content_needs_review" and changed["review_status"] != "verified"


def test_cli_queue_stats_and_synthetic_decision(corpus, monkeypatch, capsys):
    from tools.cli import main

    def run(*args):
        monkeypatch.setattr("sys.argv", ["cli.py", "review", *args, "--root", str(corpus)])
        main()
        return json.loads(capsys.readouterr().out)

    assert run("stats")["total"] > 0
    exported = run("queue", "--render")
    assert exported["unique_crops"] == 1 and Path(exported["output"]).is_file()
    item = next(i for i in load_queue(corpus) if i["target_id"] == "product:synthetic")
    result = run(
        "decide",
        "--target-id",
        item["target_id"],
        "--content-hash",
        item["content_hash"],
        "--decision",
        "approve",
        "--reviewer",
        "Synthetic CLI tester",
    )
    assert result["decision"]["decision"] == "approve" and ledger_path(corpus).is_file()


def test_inspection_regions_raise_priority_without_asserting_values(corpus):
    item = next(i for i in load_queue(corpus) if i["target_id"] == "product:synthetic")
    ref = item["citations"][0]
    path = corpus / "data/review/ocop_review_attention_regions.jsonl"
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps({k: ref[k] for k in ["source_id", "pdf_page", "bbox", "source_sha256"]}) + "\n"
    )
    flagged = next(i for i in load_queue(corpus) if i["target_id"] == item["target_id"])
    assert flagged["priority"] == "P2" and flagged["properties"] == item["properties"]
    assert flagged["review_status"] != "verified" and not ledger_path(corpus).exists()


def test_reextraction_changed_target_id_flags_rereview_without_reusing_approval(corpus):
    decide(corpus, "product:synthetic")
    base = corpus / "data/processed/ocop/knowledge"
    path = base / "business_entities.jsonl"
    rows = [json.loads(s) for s in path.read_text().splitlines()]
    rows[0]["entity_id"] = "product:reextracted"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    path = base / "business_relations.jsonl"
    row = json.loads(path.read_text())
    row["source_entity_id"] = "product:reextracted"
    path.write_text(json.dumps(row) + "\n")
    rebuild_reviewed_graph(corpus)
    item = next(i for i in load_queue(corpus) if i["target_id"] == "product:reextracted")
    assert item["state"] == "stale_content_needs_review" and item["review_status"] != "verified"
    assert item["latest_decision"]["target_id"] == "product:synthetic"


def test_review_changes_graph_then_index_is_refreshed_before_queries(corpus):
    """review -> rebuild graph -> (mismatch is refused) -> refresh index -> query."""
    from ai_core.graph.ocop.integrity import graph_index_mismatch
    from ai_core.graph.ocop.lookup import GraphEvidence
    from ai_core.retrieval.ocop.index_pipeline import build_index
    from ai_core.retrieval.ocop.search import search
    from ai_core.system.index_refresh import refresh_index_after_graph_change

    base = corpus / "data/processed/ocop"
    shutil.rmtree(base / "index")
    build_index(
        knowledge=base / "knowledge", index_dir=base / "index", graph_dir=base / "graph", allow_partial=True
    )
    first = json.loads((base / "graph/manifest.json").read_text())["graph_version"]
    GraphEvidence(base / "graph", base / "index", allow_partial_debug=True)
    assert refresh_index_after_graph_change(corpus)["status"] == "current"
    decide(corpus, next(i["target_id"] for i in load_queue(corpus) if i["type"] == "EvidenceUnit"))
    decide(corpus, "product:synthetic")
    graph = json.loads((base / "graph/manifest.json").read_text())
    index = json.loads((base / "index/manifest.json").read_text())
    assert graph["graph_version"] != first and index["structural_graph_version"] == first
    assert graph_index_mismatch(graph, index) == "graph/index graph version mismatch"
    with pytest.raises(ValueError, match="graph version mismatch"):
        GraphEvidence(base / "graph", base / "index", allow_partial_debug=True)
    result = refresh_index_after_graph_change(corpus)
    assert result["status"] == "refreshed" and result["graph_version"] == graph["graph_version"]
    index = json.loads((base / "index/manifest.json").read_text())
    assert index["structural_graph_version"] == graph["graph_version"] and index["entity_catalog"]["sha256"]
    GraphEvidence(base / "graph", base / "index", allow_partial_debug=True)
    assert search(base / "index", "Synthetic product")[0]["source_id"] == "SYNTHETIC"
    assert (
        not (base / "index.previous").exists()
        and not (base / "index.refresh").exists()
        and not (base / ".promoting").exists()
    )
    assert refresh_index_after_graph_change(corpus)["status"] == "current"


def test_concurrent_refreshes_are_serialised_and_leave_one_coherent_index(corpus):
    import threading
    from ai_core.retrieval.ocop.index_pipeline import build_index
    from ai_core.system.index_refresh import refresh_index_after_graph_change

    base = corpus / "data/processed/ocop"
    shutil.rmtree(base / "index")
    build_index(
        knowledge=base / "knowledge", index_dir=base / "index", graph_dir=base / "graph", allow_partial=True
    )
    decide(corpus, next(i["target_id"] for i in load_queue(corpus) if i["type"] == "EvidenceUnit"))
    outcomes, errors = [], []

    def run():
        try:
            outcomes.append(refresh_index_after_graph_change(corpus)["status"])
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and sorted(outcomes) == ["current", "current", "refreshed"]
    graph = json.loads((base / "graph/manifest.json").read_text())
    index = json.loads((base / "index/manifest.json").read_text())
    assert index["structural_graph_version"] == graph["graph_version"]
    assert (
        not (base / "index.previous").exists()
        and not (base / "index.refresh").exists()
        and not (base / ".promoting").exists()
    )


def test_failed_refresh_keeps_the_previous_index(corpus, monkeypatch):
    from ai_core.retrieval.ocop import index_pipeline
    from ai_core.retrieval.ocop.index_pipeline import build_index
    from ai_core.system.index_refresh import refresh_index_after_graph_change

    base = corpus / "data/processed/ocop"
    shutil.rmtree(base / "index")
    build_index(
        knowledge=base / "knowledge", index_dir=base / "index", graph_dir=base / "graph", allow_partial=True
    )
    decide(corpus, next(i["target_id"] for i in load_queue(corpus) if i["type"] == "EvidenceUnit"))
    before = (base / "index/manifest.json").read_text()
    monkeypatch.setattr(
        index_pipeline, "build_index", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    with pytest.raises(RuntimeError, match="boom"):
        refresh_index_after_graph_change(corpus)
    assert (base / "index/manifest.json").read_text() == before and not (base / "index.refresh").exists()


def test_strict_contract_rejects_an_index_that_names_no_graph():
    from ai_core.graph.ocop.integrity import graph_index_mismatch

    graph = {"source_knowledge_version": "k", "graph_version": "g"}
    assert graph_index_mismatch(graph, {"source_knowledge_version": "k"}) is None
    assert (
        graph_index_mismatch(graph, {"source_knowledge_version": "k"}, strict=True)
        == "index was built without a graph snapshot"
    )
    assert (
        graph_index_mismatch(graph, {"source_knowledge_version": "x", "structural_graph_version": "g"})
        == "graph/index knowledge version mismatch"
    )
    assert (
        graph_index_mismatch(
            graph, {"source_knowledge_version": "k", "structural_graph_version": "g"}, strict=True
        )
        is None
    )
