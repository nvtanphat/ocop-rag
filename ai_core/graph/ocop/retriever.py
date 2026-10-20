"""Versioned graph traversal; read-only local graph or optional Neo4j separately."""

from __future__ import annotations
from collections import deque, defaultdict
from pathlib import Path
from ai_core.graph.ocop.builder import records, SCHEMA_REVISION
from ai_core.graph.ocop.ontology import EDGE_ENDPOINTS
from ai_core.graph.ocop.integrity import validate_graph_snapshot


def traverse(
    graph_dir: Path,
    seed_ids: list[str],
    *,
    hops: int = 2,
    relations: list[str] | None = None,
    verified_only: bool = False,
    limit: int = 100,
    direction: str = "both",
    grounded_only: bool = False,
) -> dict:
    if direction not in ("out", "in", "both"):
        raise ValueError("invalid direction")
    if not 0 <= hops <= 3:
        raise ValueError("graph hops must be in [0,3]")
    if not 1 <= limit <= 500:
        raise ValueError("graph limit out of range")
    allowed = set(relations or EDGE_ENDPOINTS)
    if not allowed.issubset(EDGE_ENDPOINTS):
        raise ValueError("Unknown graph relation")
    # Version-aware fail-closed read; legacy isolated graph fixtures may omit a manifest.
    manifest = validate_graph_snapshot(graph_dir, allow_legacy=not grounded_only)
    if grounded_only and not manifest.get("grounding"):
        raise ValueError("graph lacks automatic grounding; rebuild corpus")
    if grounded_only and manifest.get("schema_revision") != SCHEMA_REVISION:
        raise ValueError("graph grounding policy changed; rebuild corpus")
    immutable = graph_dir / "snapshots" / str(manifest.get("graph_version", ""))
    if immutable.is_dir():
        validate_graph_snapshot(immutable)
        graph_dir = immutable
    node_file = graph_dir / ("agent_nodes.jsonl" if grounded_only else "nodes.jsonl")
    edge_file = graph_dir / ("agent_edges.jsonl" if grounded_only else "edges.jsonl")
    nodes = {n["node_id"]: n for n in records(node_file) if n.get("review_status") != "rejected"}
    edges = {}
    adj = defaultdict(list)
    for e in records(edge_file):
        if e["relation_type"] not in allowed:
            continue
        if e.get("review_status") == "rejected":
            continue
        if verified_only and e["review_status"] != "verified":
            continue
        start, end = e["source_entity_id"], e["target_entity_id"]
        if start not in nodes or end not in nodes:
            continue
        if verified_only and (
            nodes[start]["review_status"] != "verified" or nodes[end]["review_status"] != "verified"
        ):
            continue
        edges[e["edge_id"]] = e
        if direction in ("out", "both"):
            adj[start].append(e)
        if direction in ("in", "both"):
            adj[end].append(e)
    distance = {}
    for seed in seed_ids:
        if seed in nodes and (not verified_only or nodes[seed]["review_status"] == "verified"):
            distance.setdefault(seed, 0)
            if len(distance) >= limit:
                break
    queue = deque(distance)
    seen_edges = set()
    parents = {}
    while queue and len(distance) < limit:
        cur = queue.popleft()
        if distance[cur] >= hops:
            continue
        # Do not fan out from a document/decision hub reached indirectly:
        # e.g. Product -> RecognitionDecision -> all unrelated products.
        if cur not in seed_ids and nodes[cur]["node_type"] in ("SourceDocument", "RecognitionDecision"):
            continue
        for e in adj[cur]:
            if len(seen_edges) >= limit:
                break
            seen_edges.add(e["edge_id"])
            other = e["target_entity_id"] if cur == e["source_entity_id"] else e["source_entity_id"]
            if other not in distance and len(distance) < limit:
                distance[other] = distance[cur] + 1
                queue.append(other)
                parents[other] = (cur, e["edge_id"])
    # Edges are only useful if the other endpoint has actually been reached.
    reached_edges = [
        e
        for identity, e in edges.items()
        if identity in seen_edges and e["source_entity_id"] in distance and e["target_entity_id"] in distance
    ]
    paths = []
    for node in sorted(parents):
        current = node
        path_nodes = [node]
        path_edges = []
        while current in parents:
            current, edge_id = parents[current]
            path_nodes.append(current)
            path_edges.append(edge_id)
        paths.append({"node_ids": list(reversed(path_nodes)), "edge_ids": list(reversed(path_edges))})
    return {
        "nodes": [nodes[n] for n in sorted(distance)],
        "edges": reached_edges,
        "paths": paths,
        "grounded_only": grounded_only,
        "graph_version": manifest.get("graph_version"),
        "seed_ids": [s for s in seed_ids if s in distance],
        "hops": hops,
        "verified_only": verified_only,
    }
