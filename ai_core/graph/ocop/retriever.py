"""Versioned graph traversal; read-only local graph or optional Neo4j separately."""

from __future__ import annotations
from collections import deque, defaultdict
from pathlib import Path
from ai_core.graph.ocop.builder import records, SCHEMA_REVISION
from ai_core.graph.ocop.ontology import EDGE_ENDPOINTS
from ai_core.graph.ocop.integrity import validate_graph_snapshot
from ai_core.graph.ocop.grounding import usable, public_record, relation_usable
from ai_core.graph.ocop.links import DOCUMENT_RELATIONS, LINK_RELATIONS

HUB_RELATIONS = DOCUMENT_RELATIONS | {"CITES", "AMENDS_PROVISION"}
PROVENANCE_RELATIONS = frozenset({"SUPPORTED_BY", "CONTAINS", "LOCATED_IN", "MENTIONS", "IN_VERSION"})
# Relations that only lay out a document's or a sheet's own structure: a unit is not "about" the entity they start at.
STRUCTURE_RELATIONS = frozenset(
    {
        "HAS_ARTICLE",
        "HAS_CLAUSE",
        "HAS_POINT",
        "HAS_ANNEX",
        "HAS_CRITERION",
        "HAS_SUBCRITERION",
        "HAS_OPTION",
        "HAS_CONDITION",
        "HAS_FIELD",
        "REQUIRES_EVIDENCE",
        "HAS_CRITERION_CANDIDATE",
    }
)


def _enter_through_evidence(nodes, adj, distance, limit, relevance, entry_limit, parents, seen_edges):
    """Add, one step from the seed evidence units, the entities they support that relate to other entities.

    A seed unit is where retrieval found text; the graph hops start at what that text is about: a recognition
    record, a product, a star level, a sheet, the document the unit belongs to (for what it amends or replaces).
    """
    seeds = set(distance)
    units = {u for seed in list(distance) if nodes[seed]["node_type"] == "EvidenceUnit" for u in nodes[seed].get("evidence_unit_ids", [])}
    sources = {nodes[seed]["source_id"] for seed in list(distance)}
    entering = []
    for node_id, node in nodes.items():
        if node_id in distance or all(e["relation_type"] in PROVENANCE_RELATIONS for e in adj.get(node_id, ())):
            continue
        if node["node_type"] == "SourceDocument":
            if node["source_id"] in sources:
                entering.append((1, 0.0, node_id))
        elif units & set(node.get("evidence_unit_ids", [])):
            # One table unit supports every row of the table: the rows the question is about enter first.
            entering.append((0, -relevance(node), node_id))
    from ai_core.retrieval.ocop.settings import get_settings

    ranked = sorted(entering)
    # Many norms can share one unit. Preserve a document entry and diversify
    # entity kinds before spending the remainder on another norm of that unit.
    documents = [item for item in ranked if nodes[item[2]]["node_type"] == "SourceDocument"]
    documents.sort(key=lambda item: (-sum(nodes[seed]["source_id"] == nodes[item[2]]["source_id"] for seed in seeds), item))
    chosen = documents[:min(entry_limit, get_settings().agent.graph_document_seed_nodes)]
    kinds = {nodes[item[2]]["node_type"] for item in chosen}
    for item in ranked:
        kind = nodes[item[2]]["node_type"]
        if kind not in kinds and len(chosen) < entry_limit:
            chosen.append(item)
            kinds.add(kind)
    selected = {item[2] for item in chosen}
    chosen.extend(item for item in ranked if item[2] not in selected)
    for _, _, node_id in chosen[:entry_limit]:
        if len(distance) >= limit:
            break
        distance[node_id] = 1
        # The way in is the provenance edge to the seed unit that supports the entity: that is its path.
        via = next(
            (
                (e, other)
                for e in adj.get(node_id, ())
                if e["relation_type"] in PROVENANCE_RELATIONS
                and (other := e["target_entity_id"] if node_id == e["source_entity_id"] else e["source_entity_id"]) in seeds
            ),
            None,
        )
        if via:
            seen_edges.add(via[0]["edge_id"])
            parents[node_id] = (via[1], via[0]["edge_id"])


def _articles_of(nodes, adj, document_id, relevance, limit):
    """The few articles of a document hub that the question is about (a document is crossed to its text, not wholesale)."""
    if nodes[document_id]["node_type"] != "SourceDocument" or limit < 1:
        return ()
    articles = [
        e
        for e in adj.get(document_id, ())
        if e["relation_type"] == "HAS_ARTICLE" and e["source_entity_id"] == document_id
    ]
    articles.sort(key=lambda e: (-relevance(nodes[e["target_entity_id"]]), e["edge_id"]))
    return tuple(articles[:limit])


def _attach_proof(nodes, adj, distance, seen_edges, parents, fanout):
    """Give every node reached up to ``fanout`` provenance edges to evidence units (the text that proves it)."""
    for node_id in [n for n in distance if nodes[n]["node_type"] != "EvidenceUnit"]:
        added = 0
        for e in adj.get(node_id, ()):
            if e["relation_type"] != "SUPPORTED_BY" or added >= fanout:
                continue
            other = e["target_entity_id"] if node_id == e["source_entity_id"] else e["source_entity_id"]
            if nodes[other]["node_type"] != "EvidenceUnit":
                continue
            seen_edges.add(e["edge_id"])
            if other not in distance:
                distance[other] = distance[node_id] + 1
                parents[other] = (node_id, e["edge_id"])
            added += 1


def personalized_rank(nodes, adj, seeds, *, damping, iterations, tolerance):
    """Rank an already filtered graph; hub/structure connectivity cannot create semantic authority."""
    active = set(seeds) & nodes.keys()
    if not active:
        return {}
    neighbours = {}
    for identity in nodes:
        hub = identity not in active and nodes[identity]["node_type"] in {
            "SourceDocument", "RecognitionDecision", "Organization", "EvidenceUnit"}
        neighbours[identity] = sorted({
            e["target_entity_id"] if identity == e["source_entity_id"] else e["source_entity_id"]
            for e in adj.get(identity, ())
            if e["relation_type"] not in PROVENANCE_RELATIONS | STRUCTURE_RELATIONS
            and (not hub or e["relation_type"] in HUB_RELATIONS)
        })
    restart = {identity: 1.0 / len(active) for identity in active}
    ranks = dict(restart)
    for _ in range(iterations):
        updated = {identity: (1 - damping) * weight for identity, weight in restart.items()}
        dangling = 0.0
        for identity, weight in ranks.items():
            targets = neighbours[identity]
            if not targets:
                dangling += damping * weight
            else:
                share = damping * weight / len(targets)
                for other in targets:
                    updated[other] = updated.get(other, 0.0) + share
        for identity, weight in restart.items():
            updated[identity] += dangling * weight
        change = sum(abs(updated.get(n, 0.0) - ranks.get(n, 0.0)) for n in updated.keys() | ranks.keys())
        ranks = updated
        if change < tolerance:
            break
    return ranks


def traverse(
    graph_dir: Path,
    seed_ids: list[str],
    *,
    hops: int = 2,
    relations: list[str] | None = None,
    limit: int = 100,
    direction: str = "both",
    include_failed: bool = False,
    allow_partial_debug: bool = False,
    semantic_first: bool = False,
    provenance_fanout: int = 4,
    relevance=lambda node: 1.0,
    entry_limit: int = 8,
    document_articles: int = 3,
    pagerank: bool = False,
) -> dict:
    """Breadth-first hops from the seed nodes.

    ``semantic_first`` spends the hop and node budget on the relations that say something (links between units and
    documents, recognitions, ownership, structure) and not on provenance edges: an evidence unit supports dozens of
    criteria, so following ``SUPPORTED_BY`` first uses the whole budget on the unit's own neighbourhood. The seeds
    enter through the entities their evidence supports, and each node reached then gets a few proof edges.
    """
    if direction not in ("out", "in", "both"):
        raise ValueError("invalid direction")
    if not 0 <= hops <= 3:
        raise ValueError("graph hops must be in [0,3]")
    if not 1 <= limit <= 500:
        raise ValueError("graph limit out of range")
    known = set(EDGE_ENDPOINTS) | LINK_RELATIONS
    allowed = set(relations or known)
    if not allowed.issubset(known):
        raise ValueError("Unknown graph relation")
    # Version-aware fail-closed read; legacy isolated graph fixtures may omit a manifest.
    manifest = validate_graph_snapshot(graph_dir, allow_legacy=True, allow_partial=allow_partial_debug)
    if manifest.get("status") != "legacy_unverified" and not include_failed:
        if not manifest.get("checks") or manifest.get("schema_revision") != SCHEMA_REVISION:
            raise ValueError("graph check policy changed; rebuild corpus")
    immutable = graph_dir / "snapshots" / str(manifest.get("graph_version", ""))
    if immutable.is_dir():
        validate_graph_snapshot(immutable, allow_partial=allow_partial_debug)
        graph_dir = immutable
    node_file = graph_dir / "nodes.jsonl"
    edge_file = graph_dir / "edges.jsonl"
    nodes = {
        n["node_id"]: (n if include_failed else public_record(n))
        for n in records(node_file)
        if include_failed or usable(n)
    }
    edges = {}
    adj = defaultdict(list)
    for e in records(edge_file):
        if e["relation_type"] not in allowed:
            continue
        if not include_failed and not usable(e):
            continue
        start, end = e["source_entity_id"], e["target_entity_id"]
        if start not in nodes or end not in nodes:
            continue
        if not include_failed and not relation_usable(e, nodes):
            continue
        edges[e["edge_id"]] = e if include_failed else public_record(e)
        if direction in ("out", "both"):
            adj[start].append(e)
        if direction in ("in", "both"):
            adj[end].append(e)
    distance = {}
    for seed in seed_ids:
        if seed in nodes:
            distance.setdefault(seed, 0)
            if len(distance) >= limit:
                break
    queue = deque()
    seen_edges = set()
    parents = {}
    if semantic_first:
        _enter_through_evidence(nodes, adj, distance, limit, relevance, entry_limit, parents, seen_edges)
    ranks = {}
    if pagerank:
        from ai_core.retrieval.ocop.settings import get_settings

        cfg = get_settings().agent
        ranks = personalized_rank(nodes, adj, distance, damping=cfg.graph_pagerank_damping,
                                  iterations=cfg.graph_pagerank_iterations, tolerance=cfg.graph_pagerank_tolerance)
    queue = deque(distance)
    while queue and len(distance) < limit:
        cur = queue.popleft()
        if distance[cur] >= hops:
            continue
        # Do not fan out from a document/decision hub reached indirectly: Product -> RecognitionDecision -> all
        # unrelated products. A hub is crossed only by the relations that are its own meaning: a document by what it
        # amends or replaces, an evidence unit by the provisions it cites or changes.
        hub = cur not in seed_ids and nodes[cur]["node_type"] in (
            "SourceDocument",
            "RecognitionDecision",
            "Organization",
            "EvidenceUnit",
        )
        opened = _articles_of(nodes, adj, cur, relevance, document_articles) if hub and semantic_first else ()
        outgoing = [*adj[cur], *opened]
        if ranks:
            outgoing.sort(key=lambda e: (-ranks.get(e["target_entity_id"] if cur == e["source_entity_id"]
                                                  else e["source_entity_id"], 0.0), e["edge_id"]))
        for e in outgoing:
            if hub and e["relation_type"] not in HUB_RELATIONS and e not in opened:
                continue
            if semantic_first and e["relation_type"] in PROVENANCE_RELATIONS:
                continue  # proof is attached after the hops, so it never uses their budget
            if len(seen_edges) >= limit:
                break
            seen_edges.add(e["edge_id"])
            other = e["target_entity_id"] if cur == e["source_entity_id"] else e["source_entity_id"]
            if other not in distance and len(distance) < limit:
                distance[other] = distance[cur] + 1
                queue.append(other)
                parents[other] = (cur, e["edge_id"])
    if semantic_first:
        _attach_proof(nodes, adj, distance, seen_edges, parents, provenance_fanout)
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
        "node_hops": distance,
        "ranking": {"method": "personalized_pagerank" if pagerank else "breadth_first", "scores": ranks},
        "include_failed": include_failed,
        "graph_version": manifest.get("graph_version"),
        "seed_ids": [s for s in seed_ids if s in distance],
        "hops": hops,
    }
