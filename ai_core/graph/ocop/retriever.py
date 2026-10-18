"""Versioned graph traversal; read-only local graph or optional Neo4j separately."""
from __future__ import annotations
from collections import deque, defaultdict
from pathlib import Path
from ai_core.graph.ocop.builder import records
from ai_core.graph.ocop.ontology import EDGE_ENDPOINTS
from ai_core.graph.ocop.integrity import validate_graph_snapshot

def traverse(graph_dir:Path,seed_ids:list[str],*,hops:int=2,relations:list[str]|None=None,
             verified_only:bool=False,limit:int=100,direction:str="both")->dict:
    if direction not in ("out","in","both"):raise ValueError("invalid direction")
    if not 0<=hops<=3:raise ValueError("graph hops must be in [0,3]")
    if not 1<=limit<=500:raise ValueError("graph limit out of range")
    allowed=set(relations or EDGE_ENDPOINTS)
    if not allowed.issubset(EDGE_ENDPOINTS):raise ValueError("Unknown graph relation")
    # Version-aware fail-closed read; legacy isolated graph fixtures may omit a manifest.
    validate_graph_snapshot(graph_dir, allow_legacy=True)
    nodes={n["node_id"]:n for n in records(graph_dir/"nodes.jsonl")}
    edges=[];adj=defaultdict(list)
    for e in records(graph_dir/"edges.jsonl"):
        if e["relation_type"] not in allowed:continue
        if verified_only and e["review_status"]!="verified":continue
        start,end=e["source_entity_id"],e["target_entity_id"]
        if start not in nodes or end not in nodes:continue
        if verified_only and (nodes[start]["review_status"]!="verified" or nodes[end]["review_status"]!="verified"):continue
        if direction in ("out","both"):adj[start].append(e)
        if direction in ("in","both"):adj[end].append(e)
    distance={s:0 for s in seed_ids if s in nodes and
              (not verified_only or nodes[s]["review_status"]=="verified")}
    queue=deque(distance);seen_edges=set()
    while queue and len(distance)<limit:
        cur=queue.popleft()
        if distance[cur]>=hops:continue
        # Do not fan out from a document/decision hub reached indirectly:
        # e.g. Product -> RecognitionDecision -> all unrelated products.
        if cur not in seed_ids and nodes[cur]["node_type"] in ("SourceDocument","RecognitionDecision"):
            continue
        for e in adj[cur]:
            if len(seen_edges)>=limit:break
            seen_edges.add(e["edge_id"])
            other=e["target_entity_id"] if cur==e["source_entity_id"] else e["source_entity_id"]
            if other not in distance and len(distance)<limit:
                distance[other]=distance[cur]+1;queue.append(other)
    # Edges are only useful if the other endpoint has actually been reached.
    seen_edges={e["edge_id"] for e in records(graph_dir/"edges.jsonl") if
                e["edge_id"] in seen_edges and e["source_entity_id"] in distance and
                e["target_entity_id"] in distance}
    return {"nodes":[nodes[n] for n in sorted(distance)],
            "edges":[e for e in records(graph_dir/"edges.jsonl") if e["edge_id"] in seen_edges],
            "seed_ids":[s for s in seed_ids if s in distance],"hops":hops,"verified_only":verified_only}
