"""Read-only, public subgraph of the checked knowledge graph around evidence units or nodes.

Only records that pass the graph check policy are returned (``traverse`` fails closed on a missing, partial
or stale snapshot), reviewer-only originals are stripped, and every node keeps the page, bbox and SHA-256 of
its supporting evidence so the UI can open the exact PDF region.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ai_core.graph.ocop.builder import records
from ai_core.graph.ocop.retriever import traverse

MAX_SEEDS = 12
MAX_CITATIONS = 6


class SubgraphCitation(BaseModel):
    source_id: str
    pdf_page: int
    bbox: list[float] | None = None
    evidence_unit_id: str | None = None
    source_sha256: str | None = None


class SubgraphNode(BaseModel):
    node_id: str
    node_type: str
    label: str
    check: str
    review_status: str
    source_id: str | None = None
    evidence_unit_ids: list[str] = []
    citations: list[SubgraphCitation] = []


class SubgraphEdge(BaseModel):
    edge_id: str
    relation_type: str
    source: str
    target: str
    check: str
    review_status: str


class SubgraphResponse(BaseModel):
    status: Literal["ok", "no_seed", "no_graph"]
    graph_version: str | None = None
    seed_ids: list[str] = []
    nodes: list[SubgraphNode] = []
    edges: list[SubgraphEdge] = []
    truncated: bool = False


def _graph_dir(root: Path) -> Path:
    return root / "data" / "processed" / "ocop" / "graph"


STRUCTURE = ("HAS_CRITERION", "HAS_SUBCRITERION")


@lru_cache(maxsize=2)
def _parents(edges_file: str, graph_version: str) -> dict[str, dict]:
    """Criterion -> its checked HAS_CRITERION/HAS_SUBCRITERION edge from the item above, read once per graph version."""
    return {
        e["target_entity_id"]: e
        for e in records(Path(edges_file))
        if e.get("relation_type") in STRUCTURE and e.get("check") == "passed"
    }


def _ancestry(graph: Path, version: str, seeds: list[str]) -> tuple[list[str], list[dict]]:
    """The sheet, part and group above each seed criterion, with the edges that place it there."""
    snapshot = graph / "snapshots" / version
    parents = _parents(str((snapshot if snapshot.is_dir() else graph) / "edges.jsonl"), version)
    ids, edges = [], []
    for seed in seeds:
        node = seed
        while node in parents and parents[node]["source_entity_id"] not in ids:
            edge = parents[node]
            edges.append(edge)
            node = edge["source_entity_id"]
            ids.append(node)
    return ids, edges


def _seeds(graph: Path, node_ids: list[str], evidence_unit_id: str | None) -> list[str]:
    found = list(node_ids)
    if evidence_unit_id:
        try:
            version = json.loads((graph / "manifest.json").read_text(encoding="utf-8")).get("graph_version", "")
        except (OSError, ValueError):
            return found
        snapshot = graph / "snapshots" / str(version)
        nodes_file = (snapshot if snapshot.is_dir() else graph) / "nodes.jsonl"
        matching = [
            n
            for n in records(nodes_file)
            if evidence_unit_id in n.get("evidence_unit_ids", ()) and n["node_type"] != "EvidenceUnit"
        ]
        # Entities first (what the evidence supports), at most MAX_SEEDS to keep the view readable.
        found += [n["node_id"] for n in matching][:MAX_SEEDS]
        found += [
            n["node_id"]
            for n in records(nodes_file)
            if n["node_type"] == "EvidenceUnit" and evidence_unit_id in n.get("evidence_unit_ids", ())
        ][:1]
    return list(dict.fromkeys(found))


def _citation(row: dict) -> SubgraphCitation | None:
    if not isinstance(row.get("pdf_page"), int) or not row.get("source_id"):
        return None
    return SubgraphCitation(
        source_id=row["source_id"],
        pdf_page=row["pdf_page"],
        bbox=row.get("bbox") or row.get("table_bbox"),
        evidence_unit_id=row.get("evidence_unit_id"),
        source_sha256=row.get("source_sha256"),
    )


def read_subgraph(
    root: Path,
    *,
    node_ids: list[str],
    evidence_unit_id: str | None,
    hops: int,
    limit: int,
) -> SubgraphResponse:
    graph = _graph_dir(Path(root))
    if not (graph / "manifest.json").is_file():
        return SubgraphResponse(status="no_graph")
    seeds = _seeds(graph, node_ids, evidence_unit_id)
    if not seeds:
        return SubgraphResponse(status="no_seed")
    result = traverse(graph, seeds, hops=hops, limit=limit)
    if not result["seed_ids"]:
        return SubgraphResponse(status="no_seed", graph_version=result["graph_version"])
    # A criterion is read in its place: the sheet, part and group above it join the neighbourhood.
    above, chain = _ancestry(graph, str(result["graph_version"]), result["seed_ids"])
    if above:
        known = {n["node_id"] for n in result["nodes"]}
        result["nodes"] += [n for n in traverse(graph, above, hops=0, limit=len(above))["nodes"] if n["node_id"] not in known]
        present = {n["node_id"] for n in result["nodes"]}
        linked = {e["edge_id"] for e in result["edges"]}
        result["edges"] += [e for e in chain if e["edge_id"] not in linked
                            and e["source_entity_id"] in present and e["target_entity_id"] in present]
    nodes = [
        SubgraphNode(
            node_id=n["node_id"],
            node_type=n["node_type"],
            label=n.get("label") or n["node_type"],
            check=n.get("check", ""),
            review_status=n.get("review_status", ""),
            source_id=n.get("source_id"),
            evidence_unit_ids=list(n.get("evidence_unit_ids", [])),
            citations=[c for c in map(_citation, n.get("citations", [])[:MAX_CITATIONS]) if c],
        )
        for n in result["nodes"]
    ]
    edges = [
        SubgraphEdge(
            edge_id=e["edge_id"],
            relation_type=e["relation_type"],
            source=e["source_entity_id"],
            target=e["target_entity_id"],
            check=e.get("check", ""),
            review_status=e.get("review_status", ""),
        )
        for e in result["edges"]
    ]
    return SubgraphResponse(
        status="ok",
        graph_version=result["graph_version"],
        seed_ids=result["seed_ids"],
        nodes=nodes,
        edges=edges,
        truncated=len(nodes) >= limit,
    )
