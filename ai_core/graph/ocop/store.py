"""Publish immutable, version-scoped OCOP graph snapshots to Neo4j.

Bounded transactions stage a snapshot; a final count-checked transaction activates it.
Consumers MUST select the version through :OcopGraphActive rather than querying
all :OcopNode nodes, which can contain retained historical snapshots.
"""

from __future__ import annotations
import json
from pathlib import Path
from ai_core.graph.ocop.builder import records
from ai_core.graph.ocop.integrity import validate_graph_snapshot
from ai_core.graph.ocop.ontology import EDGE_ENDPOINTS
from ai_core.graph.ocop.grounding import usable, public_record, relation_usable


def publish_neo4j(
    graph_dir: Path,
    *,
    uri: str = "bolt://localhost:7687",
    user: str = "neo4j",
    password: str,
    database: str = "neo4j",
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
    nodes = [public_record(n) for n in nodes if usable(n)]
    edges = [public_record(e) for e in edges if usable(e)]
    allowed = {n["node_id"] for n in nodes}
    node_map = {n["node_id"]: n for n in nodes}
    # An orphan in the snapshot is corruption.
    if any(
        e["source_entity_id"] not in allowed or e["target_entity_id"] not in allowed for e in edges
    ):
        raise ValueError("graph snapshot contains dangling edge")
    edges = [
        e
        for e in edges
        if e["source_entity_id"] in allowed
        and e["target_entity_id"] in allowed
        and relation_usable(e, node_map)
    ]
    invalid = {e["relation_type"] for e in edges} - EDGE_ENDPOINTS.keys()
    if invalid:
        raise ValueError(f"Unsafe relation types: {sorted(invalid)}")
    from ai_core.graph.ocop.roles import project

    # Neo4j holds the role view (docs/adr/012): the closed role labels and relation types, not the stored types.
    nodes, edges = project(nodes, edges)
    version = manifest["graph_version"]
    mode = "checked"
    snapshot_id = f"{version}:{mode}"
    scope = f"ocop:{mode}"
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError("Install neo4j driver to publish OCOP graph") from exc

    def write_batch(tx, query, rows):
        tx.run(query, rows=rows, snapshot_id=snapshot_id).consume()

    def activate(tx):
        node_count = tx.run("MATCH (n:OcopNode {snapshot_id:$snapshot_id}) RETURN count(n) AS count",
                            snapshot_id=snapshot_id).single()["count"]
        edge_count = tx.run(
            "MATCH (:OcopNode {snapshot_id:$snapshot_id})-[r {snapshot_id:$snapshot_id}]->"
            "(:OcopNode {snapshot_id:$snapshot_id}) RETURN count(r) AS count",
            snapshot_id=snapshot_id).single()["count"]
        if node_count != len(nodes) or edge_count != len(edges):
            raise RuntimeError("Neo4j staged snapshot counts differ; active pointer unchanged")
        # A failed batch leaves only an inactive version. Activation and its
        # completeness check share one transaction; existing snapshots stay live.
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
            node_query = ("UNWIND $rows AS row "
                          "MERGE (n:OcopNode {snapshot_id:$snapshot_id,node_id:row.node_id}) SET n += row")
            for role in sorted({n["role"] for n in nodes}):
                group = [n for n in nodes if n["role"] == role]
                # The label is interpolated, so it is only ever a role name from the validated vocabulary.
                labelled = node_query + f", n:{role}"
                for offset in range(0, len(group), batch_size):
                    session.execute_write(write_batch, labelled, [_properties(n) for n in group[offset:offset + batch_size]])
            for relation in sorted({e["relation_type"] for e in edges}):
                group = [e for e in edges if e["relation_type"] == relation]
                # Interpolation remains restricted to the validated ontology.
                query = ("UNWIND $rows AS row "
                         "MATCH (a:OcopNode {snapshot_id:$snapshot_id,node_id:row.source_entity_id}) "
                         "MATCH (b:OcopNode {snapshot_id:$snapshot_id,node_id:row.target_entity_id}) "
                         f"MERGE (a)-[r:{relation} {{snapshot_id:$snapshot_id,edge_id:row.edge_id}}]->(b) SET r += row")
                for offset in range(0, len(group), batch_size):
                    session.execute_write(write_batch, query,
                                          [_properties(e) for e in group[offset:offset + batch_size]])
            session.execute_write(activate)
        return {
            "status": "uploaded",
            "node_count": len(nodes),
            "edge_count": len(edges),
            "graph_version": version,
            "snapshot_id": snapshot_id,
            "active_scope": scope,
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
    root = Path(root)
    base = root / "data/processed/ocop"
    with process_lock(base / ".system.lock", wait_timeout=900):
        manifest_path = base / "graph" / "manifest.json"
        outcome = publish_neo4j(base / "graph", uri=uri, user=user, password=password)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["neo4j"] = outcome
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return outcome


_REFERENCE_KINDS = {"criteria": "Criterion", "products": "Product"}
_CITATION_FIELDS = (
    "source_id", "evidence_unit_id", "source_sha256", "pdf_page", "bbox", "printed_page", "table_bbox",
    "block_id", "table_id", "cell_id",
)


def export_reference_files(root) -> dict:
    """Write the public criteria/products lists the reference endpoints serve, from the checked graph.

    Only nodes in the graph's verified bucket are listed, each with the citations the graph holds for it. The file is
    bound to the active index corpus; the endpoint re-validates every citation against the locked PDF, so a stale or
    inconsistent file lists nothing. Run again after any graph or index rebuild.
    """
    import json

    base = Path(root) / "data/processed/ocop"
    version = json.loads((base / "index/manifest.json").read_text(encoding="utf-8"))["corpus_version"]
    nodes = [json.loads(line) for line in (base / "graph/nodes.jsonl").read_text(encoding="utf-8").splitlines() if line]
    counts = {}
    for kind, node_type in _REFERENCE_KINDS.items():
        lines, seen = [], set()
        for node in nodes:
            if node.get("node_type") != node_type or not usable(node) or node.get("review_status") != "verified":
                continue
            citations, keys = [], set()
            for citation in node.get("citations", []):
                key = (citation.get("evidence_unit_id"), citation.get("pdf_page"), tuple(citation.get("bbox") or ()))
                if key in keys or not all(citation.get(f) for f in ("source_id", "evidence_unit_id", "pdf_page", "bbox")):
                    continue
                keys.add(key)
                citations.append({f: citation[f] for f in _CITATION_FIELDS if citation.get(f) is not None})
            label = " ".join(str(node.get("label", "")).split())
            if not citations or not label or (label, citations[0]["source_id"]) in seen:
                continue
            seen.add((label, citations[0]["source_id"]))
            lines.append(
                json.dumps(
                    {
                        "id": node["node_id"],
                        "label": label,
                        "corpus_version": version,
                        "review_status": "verified",
                        "visibility": "public",
                        "citations": citations,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        target = base / "knowledge" / f"verified_{kind}.jsonl"
        temporary = target.with_suffix(".jsonl.tmp")
        temporary.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        temporary.replace(target)
        counts[kind] = len(lines)
    return {"corpus_version": version, "exported": counts}


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
