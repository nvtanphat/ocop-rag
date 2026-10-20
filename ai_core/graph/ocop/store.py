"""Publish immutable, version-scoped OCOP graph snapshots to Neo4j.

A single write transaction creates the snapshot and advances its active pointer.
Consumers MUST select the version through :OcopGraphActive rather than querying
all :OcopNode nodes, which can contain retained historical snapshots.
"""
from __future__ import annotations
import json
from pathlib import Path
from ai_core.graph.ocop.builder import records
from ai_core.graph.ocop.integrity import validate_graph_snapshot
from ai_core.graph.ocop.ontology import EDGE_ENDPOINTS


def publish_neo4j(graph_dir: Path, *, uri: str = "bolt://localhost:7687",
                  user: str = "neo4j", password: str, database: str = "neo4j",
                  verified_only: bool = False, batch_size: int = 300,
                  grounded_only: bool = False) -> dict:
    if batch_size < 1 or batch_size > 10000:
        raise ValueError("batch_size must be between 1 and 10000")
    # Validate before connecting or mutating remote state.
    manifest = validate_graph_snapshot(graph_dir)
    if grounded_only and not manifest.get('grounding'):
        raise ValueError('graph lacks automatic grounding; rebuild before publication')
    nodes = list(records(graph_dir/('agent_nodes.jsonl' if grounded_only else 'nodes.jsonl')))
    edges = list(records(graph_dir/('agent_edges.jsonl' if grounded_only else 'edges.jsonl')))
    expected = manifest['grounding'] if grounded_only else manifest['counts']
    if (len(nodes) != expected['nodes'] or len(edges) != expected['edges']):
        raise ValueError("graph snapshot row counts differ from manifest")
    if verified_only:
        nodes = [n for n in nodes if n["review_status"] == "verified"]
    allowed = {n["node_id"] for n in nodes}
    # An orphan in the full snapshot is corruption; verified-only mode may
    # intentionally omit lower-trust endpoints and their incident edges.
    if not verified_only and any(e["source_entity_id"] not in allowed or
                                  e["target_entity_id"] not in allowed for e in edges):
        raise ValueError("graph snapshot contains dangling edge")
    edges = [e for e in edges if e["source_entity_id"] in allowed and
             e["target_entity_id"] in allowed and
             (not verified_only or e["review_status"] == "verified")]
    invalid = {e["relation_type"] for e in edges} - EDGE_ENDPOINTS.keys()
    if invalid:
        raise ValueError(f"Unsafe relation types: {sorted(invalid)}")
    version = manifest["graph_version"]
    mode = ('grounded_verified' if verified_only else 'grounded') if grounded_only else ('verified' if verified_only else 'all')
    snapshot_id = f"{version}:{mode}"
    scope = f"ocop:{mode}"
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError("Install neo4j driver to publish OCOP graph") from exc

    def write_snapshot(tx):
        # Every MATCH/MERGE is constrained to this immutable snapshot. No
        # relationship can accidentally connect different corpus versions.
        for offset in range(0, len(nodes), batch_size):
            group = nodes[offset:offset + batch_size]
            rows = [_properties(n) for n in group]
            tx.run("UNWIND $rows AS row "
                   "MERGE (n:OcopNode {snapshot_id:$snapshot_id,node_id:row.node_id}) "
                   "SET n += row", rows=rows, snapshot_id=snapshot_id).consume()
        for relation in sorted({e["relation_type"] for e in edges}):
            group = [e for e in edges if e["relation_type"] == relation]
            # Relation interpolation is safe ONLY because it is allowlisted.
            cypher = ("UNWIND $rows AS row "
                      "MATCH (a:OcopNode {snapshot_id:$snapshot_id,node_id:row.source_entity_id}) "
                      "MATCH (b:OcopNode {snapshot_id:$snapshot_id,node_id:row.target_entity_id}) "
                      f"MERGE (a)-[r:{relation} {{snapshot_id:$snapshot_id,edge_id:row.edge_id}}]->(b) "
                      "SET r += row")
            for offset in range(0,len(group),batch_size):
                tx.run(cypher, rows=[_properties(e) for e in group[offset:offset+batch_size]],snapshot_id=snapshot_id).consume()
        # Activation happens only after all writes complete, within the SAME
        # transaction. Exceptions abort both publication and pointer switch.
        tx.run("MERGE (a:OcopGraphActive {scope:$scope}) "
               "SET a.snapshot_id=$snapshot_id, a.graph_version=$version, "
               "a.source_knowledge_sha256=$source_hash",
               scope=scope,snapshot_id=snapshot_id,version=version,
               source_hash=manifest["source_knowledge_sha256"]).consume()

    drv = GraphDatabase.driver(uri, auth=(user,password))
    try:
        with drv.session(database=database) as session:
            session.run("CREATE CONSTRAINT ocop_graph_node_snapshot IF NOT EXISTS "
                        "FOR (n:OcopNode) REQUIRE (n.snapshot_id,n.node_id) IS UNIQUE").consume()
            session.run("CREATE CONSTRAINT ocop_graph_active_scope IF NOT EXISTS "
                        "FOR (a:OcopGraphActive) REQUIRE a.scope IS UNIQUE").consume()
            session.execute_write(write_snapshot)
        return {"status":"uploaded","node_count":len(nodes),"edge_count":len(edges),
                "graph_version":version,"snapshot_id":snapshot_id,
                "active_scope":scope,"verified_only":verified_only,'grounded_only':grounded_only}
    finally:
        drv.close()


def _properties(row):
    """Neo4j properties cannot contain nested maps or arrays of maps."""
    return {(key + '_json' if isinstance(value, (dict, list, tuple)) else key):
            (json.dumps(value, ensure_ascii=False, allow_nan=False) if isinstance(value, (dict, list, tuple)) else value)
            for key, value in row.items()}
