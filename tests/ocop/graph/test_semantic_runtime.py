"""Typed semantic relations must reach tools and survive the context budget."""

from collections import defaultdict
import hashlib
import json
import shutil

from ai_core.graph.ocop.builder import SCHEMA_REVISION
from ai_core.graph.ocop.retriever import personalized_rank
from ai_core.orchestration.ocop.answer import _most_relevant
from ai_core.orchestration.ocop.context import fit_budget
from ai_core.orchestration.ocop.tools import ToolRegistry
from ai_core.retrieval.ocop.settings import get_settings


def test_rank_propagates_from_both_seeds_without_crossing_a_document_hub():
    nodes = {identity: {"node_type": kind} for identity, kind in
             (("a", "Concept"), ("b", "Concept"), ("c", "Concept"), ("hub", "SourceDocument"), ("other", "Concept"))}
    adj = defaultdict(list)
    for source, relation, target in (("a", "SAME_CONCEPT", "b"), ("c", "SAME_CONCEPT", "b"),
                                     ("a", "LOCATED_IN", "hub"), ("hub", "HAS_ARTICLE", "other")):
        edge = {"source_entity_id": source, "target_entity_id": target, "relation_type": relation}
        adj[source].append(edge)
        adj[target].append(edge)
    scores = personalized_rank(nodes, adj, ["a", "c"], damping=0.85, iterations=100, tolerance=0.000001)
    assert scores["b"] > 0 and scores["a"] == scores["c"]
    assert scores.get("other", 0) == 0 and scores.get("hub", 0) == 0
    assert abs(sum(scores.values()) - 1) < 0.000001


def test_approved_semantic_relation_and_both_seed_sources_reach_tool(tmp_path):
    graph = tmp_path / "data/processed/ocop/graph"
    graph.mkdir(parents=True)
    text = "ALPHA requires the original supplementary label."
    span = {"pdf_page": 1, "bbox": [0, 0, 100, 100], "source_sha256": "a" * 64}
    ref = {**span, "source_id": "S", "evidence_unit_id": "u", "quote": text}
    common = {"source_id": "S", "check": "passed", "review_status": "verified",
              "evidence_unit_ids": ["u"], "citations": [ref], "properties": {}}
    nodes = [{**common, "node_id": identity, "node_type": kind, "label": label}
             for identity, kind, label in (("concept", "Concept", "ALPHA"), ("norm", "Obligation", text))]
    nodes.append({**common, "node_id": "evidence", "node_type": "EvidenceUnit", "label": "u",
                  "properties": {"evidence_text": text, "source_spans": [span]}})
    edges = [{**common, "edge_id": "edge", "source_entity_id": "norm", "target_entity_id": "concept",
              "relation_type": "REQUIRES_LABEL", "derived": True, "validation": {"legal_verified": False}}]
    for filename, rows in (("nodes.jsonl", nodes), ("edges.jsonl", edges)):
        (graph / filename).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    manifest = {"graph_version": "fixture", "schema_revision": SCHEMA_REVISION, "status": "local_ready",
                "source_knowledge_version": "fixture", "checks": {"ok": True},
                "file_sha256": {name: hashlib.sha256((graph / name).read_bytes()).hexdigest()
                                for name in ("nodes.jsonl", "edges.jsonl")}}
    (graph / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    snapshot = graph / "snapshots/fixture"
    snapshot.mkdir(parents=True)
    for name in ("nodes.jsonl", "edges.jsonl", "manifest.json"):
        shutil.copyfile(graph / name, snapshot / name)
    result = ToolRegistry(tmp_path).dispatch("search_graph", query="ALPHA", slots={},
                                           context={"retrieved_evidence_ids": ["u"]})
    assert {"concept", "evidence"} <= set(result["seed_ids"])
    assert any(e["relation_type"] == "REQUIRES_LABEL" for e in result["edges"])
    proof = next(row for row in result["results"] if row["chunk_id"].startswith("graph-evidence:"))
    assert proof["text"] == text and proof["graph_hops"] == [1]
    assert result["ranking"]["method"] == "personalized_pagerank"


def test_each_graph_hop_reserves_a_block_despite_low_term_overlap():
    entries = [(("S", 1, str(i), str(i)), {"text": "requested terms", "raw_text": "requested terms"}, {}, False)
               for i in range(8)]
    for hop in (1, 2, 3):
        entries.append((("S", 1, str(hop), "hop" + str(hop)),
                        {"text": "unrelated wording", "graph_hop": hop}, {}, False))
    kept = _most_relevant(entries, ["requested", "terms"], 3)
    assert {entry[1]["graph_hop"] for entry in kept} == {1, 2, 3}


def test_budget_drops_prose_before_the_only_block_for_a_hop():
    rows = [{"text": "alpha " * 60}, {"text": "beta " * 60, "graph_hop": 1},
            {"text": "gamma " * 60, "graph_hop": 2}]
    excerpts = fit_budget(rows, [False] * 3, [], get_settings().context, 125, [0] * 3)
    assert excerpts[0] is None and excerpts[1] and excerpts[2]


def test_impossible_chain_budget_withholds_all_hops():
    rows = [{"text": "alpha " * 60, "graph_hop": 1}, {"text": "beta " * 60, "graph_hop": 2}]
    assert fit_budget(rows, [False] * 2, [], get_settings().context, 1, [10] * 2) == [None, None]


def test_evidence_deduplication_retains_all_hops_without_changing_source():
    from ai_core.retrieval.ocop.fusion import deduplicate
    from ai_core.orchestration.ocop.answer import _drop_repeats
    from ai_core.orchestration.ocop.context import graph_hops

    first = {"source_id": "S", "text": "same original proof", "review_status": "verified", "graph_hop": 1}
    second = {**first, "graph_hop": 2}
    combined = deduplicate([first, second])
    assert len(combined) == 1 and graph_hops(combined[0]) == {1, 2}
    assert "graph_hops" not in first
    entries = [(("S", 1, str(i), str(i)), row, {}, False) for i, row in enumerate((first, second))]
    kept = _drop_repeats(entries)
    assert len(kept) == 1 and graph_hops(kept[0][1]) == {1, 2}


def test_repeated_norms_cannot_starve_document_and_other_entity_seed_kinds():
    from ai_core.graph.ocop.retriever import _enter_through_evidence

    nodes = {"u": {"node_type": "EvidenceUnit", "source_id": "S", "evidence_unit_ids": ["unit"]},
             "doc": {"node_type": "SourceDocument", "source_id": "S"},
             "concept": {"node_type": "Concept", "source_id": "S", "evidence_unit_ids": ["unit"]}}
    nodes.update({f"n{i}": {"node_type": "Obligation", "source_id": "S", "evidence_unit_ids": ["unit"]}
                  for i in range(10)})
    adj = {identity: [{"relation_type": "HAS_NORM"}] for identity in nodes}
    distance = {"u": 0}
    _enter_through_evidence(nodes, adj, distance, 20, lambda n: 100 if n["node_type"] == "Obligation" else 0,
                            3, {}, set())
    assert {"doc", "concept"} <= distance.keys()
    assert sum(identity.startswith("n") for identity in distance) == 1


def test_optional_graph_enrichment_never_takes_more_than_its_share_of_the_blocks():
    from ai_core.retrieval.ocop.settings import get_settings

    cap = get_settings().context.max_enrichment_blocks
    primary = [(("S", 1, "p" + str(i), "p" + str(i)), {"text": "khác"}, {}, False) for i in range(6)]
    enrichment = [(("S", 2, "g" + str(i), "g" + str(i)), {"text": "hiệu lực nghị định", "enrichment": True}, {}, False)
                  for i in range(6)]
    kept = _most_relevant(enrichment + primary, ["hieu", "luc", "nghi", "dinh"], 8)
    assert sum(1 for entry in kept if entry[1].get("enrichment")) == cap
    assert len(kept) == 8
