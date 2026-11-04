"""The closed role vocabulary the answer path and Neo4j read (docs/adr/012); stored types and IDs stay unchanged."""

from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import yaml

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "ocop_graph_roles.yaml"
PROVENANCE_FIELDS = ("source_id", "evidence_unit_id", "pdf_page", "bbox", "source_sha256", "quote")


@lru_cache(maxsize=1)
def _config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def node_roles() -> dict[str, str]:
    return {kind: role for role, kinds in _config()["nodes"].items() for kind in kinds}


@lru_cache(maxsize=1)
def edge_roles() -> dict[str, str]:
    return {relation: role for role, relations in _config()["edges"].items() for relation in relations}


def _flat(row: dict) -> dict:
    """Provenance as flat fields, taken from the first citation (the quote that grounds the row)."""
    citation = next(iter(row.get("citations") or ()), {})
    flat = {name: citation[name] for name in PROVENANCE_FIELDS if citation.get(name) is not None}
    flat["evidence_unit_ids"] = list(row.get("evidence_unit_ids") or ())
    return flat


def project(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict]]:
    """The role view of already checked nodes and edges: role nodes and edges with folded properties.

    A node or edge whose type has no role is left out. A child that is a property of its parent (a score option of a
    criterion) is folded into it, an edge that ends at an evidence unit is lifted to the deepest provision that
    quotes the unit, and a norm keeps only its nearest provision.
    """
    config = _config()
    kinds, relations = node_roles(), edge_roles()
    by_id = {n["node_id"]: n for n in nodes}
    depth = {kind: i for i, kind in enumerate(config["provision_depth"])}
    projected = {}
    for node in nodes:
        role = kinds.get(node["node_type"])
        if role:
            projected[node["node_id"]] = {
                "node_id": node["node_id"],
                "role": role,
                "stored_type": node["node_type"],
                "label": node.get("label"),
                "check": node.get("check"),
                "derived": bool(node.get("derived")),
                "properties": dict(node.get("properties") or {}),
                **_flat(node),
            }
    for name, spec in config["properties"].items():
        at_target = spec.get("parent_side") == "target"
        for edge in edges:
            if edge["relation_type"] != spec["relation"]:
                continue
            parent, child = (edge["target_entity_id"], edge["source_entity_id"]) if at_target else (
                edge["source_entity_id"], edge["target_entity_id"])
            if parent in projected and by_id.get(child, {}).get("node_type") == spec["child"]:
                projected[parent]["properties"].setdefault(name, []).append(
                    {"label": by_id[child].get("label"), **(by_id[child].get("properties") or {}), **_flat(by_id[child])}
                )
    deepest = {}
    for node_id, node in projected.items():
        if node["role"] != "Provision":
            continue
        for unit in node["evidence_unit_ids"]:
            current = deepest.get(unit)
            if current is None or (depth.get(node["stored_type"], -1), node_id) > (
                depth.get(projected[current]["stored_type"], -1), current
            ):
                deepest[unit] = node_id

    folded_parent = {}
    for spec in config["properties"].values():
        for edge in edges:
            if edge["relation_type"] == spec["relation"]:
                parent, child = (edge["target_entity_id"], edge["source_entity_id"]) if spec.get(
                    "parent_side") == "target" else (edge["source_entity_id"], edge["target_entity_id"])
                folded_parent.setdefault(child, parent)

    def resolve(identity):
        if identity in projected:
            return identity
        if folded_parent.get(identity) in projected:
            return folded_parent[identity]  # a folded child (a score option) speaks through its parent
        source = by_id.get(identity)
        if source and source["node_type"] == "EvidenceUnit":
            return next((deepest[u] for u in source.get("evidence_unit_ids", ()) if u in deepest), None)
        return None

    kept = {}
    for edge in sorted(edges, key=lambda e: e["edge_id"]):
        role = relations.get(edge["relation_type"])
        start, end = resolve(edge["source_entity_id"]), resolve(edge["target_entity_id"])
        if role is None or start is None or end is None or start == end:
            continue
        key = (start, role, end)
        if key not in kept:
            kept[key] = {
                "edge_id": edge["edge_id"],
                "relation_type": role,
                "stored_relation": edge["relation_type"],
                "source_entity_id": start,
                "target_entity_id": end,
                "check": edge.get("check"),
                "derived": bool(edge.get("derived")),
                **_flat(edge),
            }
    nearest = {}
    for key, edge in kept.items():
        if key[1] == "EXPRESSES":
            norm = key[2]
            rank = (depth.get(projected[key[0]]["stored_type"], -1), key[0])
            if norm not in nearest or rank > nearest[norm][0]:
                nearest[norm] = (rank, key)
    out_edges = [e for k, e in kept.items() if k[1] != "EXPRESSES" or nearest[k[2]][1] == k]
    return sorted(projected.values(), key=lambda n: n["node_id"]), sorted(out_edges, key=lambda e: e["edge_id"])
