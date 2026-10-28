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
from ai_core.graph.ocop.grounding import usable, public_record


def publish_neo4j(
    graph_dir: Path,
    *,
    uri: str = "bolt://localhost:7687",
    user: str = "neo4j",
    password: str,
    database: str = "neo4j",
    verified_only: bool = False,
    batch_size: int = 300,
) -> dict:
    if batch_size < 1 or batch_size > 10000:
        raise ValueError("batch_size must be between 1 and 10000")
    # Validate before connecting or mutating remote state.
    manifest = validate_graph_snapshot(graph_dir)
    from ai_core.graph.ocop.builder import SCHEMA_REVISION

    if not manifest.get("checks") or manifest.get("schema_revision") != SCHEMA_REVISION:
        raise ValueError("graph check policy changed; rebuild before publication")
    immutable = graph_dir / "snapshots" / manifest["graph_version"]
    if immutable.is_dir():
        validate_graph_snapshot(immutable)
        graph_dir = immutable
    nodes = list(records(graph_dir / "nodes.jsonl"))
    edges = list(records(graph_dir / "edges.jsonl"))
    expected = manifest["counts"]
    if len(nodes) != expected["nodes"] or len(edges) != expected["edges"]:
        raise ValueError("graph snapshot row counts differ from manifest")
    nodes = [
        public_record(n) for n in nodes if usable(n) and (not verified_only or n["check"] == "human_verified")
    ]
    edges = [public_record(e) for e in edges if usable(e)]
    allowed = {n["node_id"] for n in nodes}
    # An orphan in the full snapshot is corruption; verified-only mode may
    # intentionally omit lower-trust endpoints and their incident edges.
    if not verified_only and any(
        e["source_entity_id"] not in allowed or e["target_entity_id"] not in allowed for e in edges
    ):
        raise ValueError("graph snapshot contains dangling edge")
    edges = [
        e
        for e in edges
        if e["source_entity_id"] in allowed
        and e["target_entity_id"] in allowed
        and (not verified_only or e["check"] == "human_verified")
    ]
    invalid = {e["relation_type"] for e in edges} - EDGE_ENDPOINTS.keys()
    if invalid:
        raise ValueError(f"Unsafe relation types: {sorted(invalid)}")
    version = manifest["graph_version"]
    mode = "verified" if verified_only else "checked"
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
            group = nodes[offset : offset + batch_size]
            rows = [_properties(n) for n in group]
            tx.run(
                "UNWIND $rows AS row "
                "MERGE (n:OcopNode {snapshot_id:$snapshot_id,node_id:row.node_id}) "
                "SET n += row",
                rows=rows,
                snapshot_id=snapshot_id,
            ).consume()
        for relation in sorted({e["relation_type"] for e in edges}):
            group = [e for e in edges if e["relation_type"] == relation]
            # Relation interpolation is safe ONLY because it is allowlisted.
            cypher = (
                "UNWIND $rows AS row "
                "MATCH (a:OcopNode {snapshot_id:$snapshot_id,node_id:row.source_entity_id}) "
                "MATCH (b:OcopNode {snapshot_id:$snapshot_id,node_id:row.target_entity_id}) "
                f"MERGE (a)-[r:{relation} {{snapshot_id:$snapshot_id,edge_id:row.edge_id}}]->(b) "
                "SET r += row"
            )
            for offset in range(0, len(group), batch_size):
                tx.run(
                    cypher,
                    rows=[_properties(e) for e in group[offset : offset + batch_size]],
                    snapshot_id=snapshot_id,
                ).consume()
        # Activation happens only after all writes complete, within the SAME
        # transaction. Exceptions abort both publication and pointer switch.
        tx.run(
            "MERGE (a:OcopGraphActive {scope:$scope}) "
            "SET a.snapshot_id=$snapshot_id, a.graph_version=$version, "
            "a.source_knowledge_sha256=$source_hash",
            scope=scope,
            snapshot_id=snapshot_id,
            version=version,
            source_hash=manifest["source_knowledge_sha256"],
        ).consume()

    drv = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with drv.session(database=database) as session:
            session.run(
                "CREATE CONSTRAINT ocop_graph_node_snapshot IF NOT EXISTS "
                "FOR (n:OcopNode) REQUIRE (n.snapshot_id,n.node_id) IS UNIQUE"
            ).consume()
            session.run(
                "CREATE CONSTRAINT ocop_graph_active_scope IF NOT EXISTS "
                "FOR (a:OcopGraphActive) REQUIRE a.scope IS UNIQUE"
            ).consume()
            session.execute_write(write_snapshot)
        return {
            "status": "uploaded",
            "node_count": len(nodes),
            "edge_count": len(edges),
            "graph_version": version,
            "snapshot_id": snapshot_id,
            "active_scope": scope,
            "verified_only": verified_only,
        }
    finally:
        drv.close()


def publish_reviewed_graph(root, *, uri: str, user: str, password: str) -> dict:
    """Publish the current (reviewed) graph to Neo4j and record it in the graph manifest.

    The snapshot is immutable and version-scoped, so this is idempotent; a later graph rebuild writes a new manifest
    without the record, which is exactly when the published copy is stale.
    """
    import json

    from ocop_contracts.locking import process_lock
    from ai_core.graph.ocop.review import _write_lock

    root = Path(root)
    base = root / "data/processed/ocop"
    with (
        process_lock(base / ".system.lock", wait_timeout=900),
        _write_lock(root / "data/review/ocop_graph_projection"),
    ):
        manifest_path = base / "graph" / "manifest.json"
        outcome = publish_neo4j(base / "graph", uri=uri, user=user, password=password, verified_only=False)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["neo4j"] = outcome
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return outcome


def _properties(row):
    """Neo4j properties cannot contain nested maps or arrays of maps."""
    return {
        (key + "_json" if isinstance(value, (dict, list, tuple)) else key): (
            json.dumps(value, ensure_ascii=False, allow_nan=False)
            if isinstance(value, (dict, list, tuple))
            else value
        )
        for key, value in row.items()
    }
