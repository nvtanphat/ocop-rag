"""Checked structure and original evidence from the same immutable graph snapshot."""

from __future__ import annotations

import json
import re
from ocop_contracts.ratings import level_class
from ai_core.orchestration.ocop.language import get_language

from ocop_contracts.ids import content_sha256
from ai_core.graph.ocop.builder import SCHEMA_REVISION, records
from ai_core.graph.ocop.grounding import public_record, usable, relation_usable
from ai_core.graph.ocop.integrity import graph_index_mismatch, validate_graph_snapshot


_LEGAL_UNIT_TYPES = {"Article", "Clause", "Point"}


def authority_nodes(nodes, *, star_rating=None):
    """Legal units that state which authority recognises (công nhận) a star level.

    A unit qualifies only when it names an authority, uses "công nhận", and - if a
    star level was asked - lists that level; merely mentioning "thẩm quyền" is not enough."""
    from ai_core.knowledge.ocop.authorities import find_authorities

    lang = get_language()
    star = lang.alternation(lang.star_noun)
    selected = []
    for node in nodes:
        label = str(node.get("label") or "")
        if node.get("node_type") not in _LEGAL_UNIT_TYPES or not lang.hit(label, "recognition"):
            continue
        if not any(True for _ in find_authorities(label)):
            continue
        stars = {int(n) for n in re.findall(r"(?<!\d)(" + level_class() + r")\s*" + star + r"\b", label, re.I)}
        if star_rating is not None and int(star_rating) not in stars:
            continue
        selected.append(node)
    return selected


class GraphEvidence:
    def __init__(self, graph_dir, index_dir=None, *, allow_partial_debug=False):
        self.manifest = validate_graph_snapshot(graph_dir, allow_partial=allow_partial_debug)
        if self.manifest.get("schema_revision") != SCHEMA_REVISION:
            raise ValueError("graph check policy changed; rebuild corpus")
        path = graph_dir / "snapshots" / self.manifest["graph_version"]
        validate_graph_snapshot(path, allow_partial=allow_partial_debug)
        if index_dir is not None and (index_dir / "manifest.json").is_file():
            index = json.loads((index_dir / "manifest.json").read_text(encoding="utf8"))
            problem = graph_index_mismatch(self.manifest, index)
            if problem:
                raise ValueError(problem)
        self.nodes = {
            n["node_id"]: public_record(n)
            for n in records(path / "nodes.jsonl")
            if usable(n)
        }
        self.edges = [
            public_record(e)
            for e in records(path / "edges.jsonl")
            if usable(e)
            and e["source_entity_id"] in self.nodes
            and e["target_entity_id"] in self.nodes
            and relation_usable(e, self.nodes)
        ]
        self.units = {
            uid: n
            for n in self.nodes.values()
            if n["node_type"] == "EvidenceUnit"
            for uid in n.get("evidence_unit_ids", [])
        }

    def descendants(self, seeds, relations):
        found = set(seeds)
        used = []
        while True:
            edges = [
                e
                for e in self.edges
                if e["source_entity_id"] in found
                and e["target_entity_id"] not in found
                and e["relation_type"] in relations
            ]
            if not edges:
                break
            used.extend(edges)
            found.update(e["target_entity_id"] for e in edges)
        return found, used

    def evidence(self, refs, *, node_ids=(), edge_ids=(), check="passed", review_status="needs_review"):
        rows = []
        for ref in refs:
            uid = ref.get("evidence_unit_id")
            unit = self.units.get(uid)
            if not unit or unit["source_id"] != ref.get("source_id"):
                continue
            props = unit["properties"]
            source = props.get("evidence_text", "")
            quote = ref.get("quote") or source
            if not quote or quote not in source:
                continue
            anchors = props.get("source_spans", [])
            if not any(
                a.get("pdf_page") == ref.get("pdf_page")
                and a.get("source_sha256") == ref.get("source_sha256")
                for a in anchors
            ):
                continue
            if not ref.get("bbox") or not re.fullmatch(r"[0-9a-f]{64}", ref.get("source_sha256", "")):
                continue
            rows.append(
                {
                    "source_id": unit["source_id"],
                    "unit_id": uid,
                    "evidence_unit_id": uid,
                    "chunk_id": "graph-evidence:" + content_sha256(json.dumps(ref, sort_keys=True))[:24],
                    "text": quote,
                    "spans": [ref],
                    "source_spans": [ref],
                    "pdf_page": ref["pdf_page"],
                    "review_status": (
                        "verified"
                        if unit["review_status"] == "verified" and review_status == "verified"
                        else "needs_review"
                    ),
                    "source_review_status": unit["review_status"],
                    "corpus_version": self.manifest["source_knowledge_version"],
                    "unit_kind": props.get("unit_kind"),
                    "structured": props.get("structured", {}),
                    "graph_node_ids": list(node_ids),
                    "graph_edge_ids": list(edge_ids),
                    "check": check,
                }
            )
        return rows

    def authority(self, *, star_rating=None, source_id=None):
        """Checked legal units naming who recognises a star level (see authority_nodes)."""
        return self.node_rows(
            authority_nodes(
                [n for n in self.nodes.values() if not source_id or n["source_id"] == source_id],
                star_rating=star_rating,
            )
        )

    def node_rows(self, nodes):
        rows = []
        for node in nodes:
            for row in self.evidence(
                node.get("citations", []),
                node_ids=[node["node_id"]],
                check=node["check"],
                review_status=node["review_status"],
            ):
                rows.append(
                    {
                        **node.get("properties", {}),
                        **row,
                        "label_candidate": node["label"],
                        "title": node["label"],
                        "graph_node_type": node["node_type"],
                    }
                )
        return rows

    def legal(self, *, source_id=None, article=None, pdf_page=None, query=""):
        units = sorted(
            [n for n in self.units.values() if not source_id or n["source_id"] == source_id],
            key=lambda n: n["properties"].get("source_order", 0),
        )
        if pdf_page is not None:
            return self.node_rows(
                [
                    n
                    for n in units
                    if any(r.get("pdf_page") == pdf_page for r in n.get("citations", []))
                    and n["properties"].get("unit_kind") != "page"
                ]
            )
        if article:
            noun = get_language().alternation(get_language().structure_nouns["article"])
            rx = re.compile(r"^" + noun + r"\s*" + re.escape(str(article)) + r"(?=\b|[.])", re.I)
            selected = []
            active = False
            last_page = None
            active_source = None
            for unit in units:
                p = unit["properties"]
                page = (p.get("source_spans") or [{}])[0].get("pdf_page")
                if p.get("unit_kind") == "page":
                    continue
                if p.get("unit_kind") == "article":
                    active = bool(rx.search(p.get("evidence_text", "").lstrip()))
                    if active:
                        active_source = unit["source_id"]
                        last_page = None
                if active and (
                    unit["source_id"] != active_source or last_page is not None and page > last_page + 1
                ):
                    active = False
                if active:
                    selected.append(unit)
                    last_page = page
            return self.node_rows(selected)
        return self.node_rows(
            [n for n in units if query.casefold() in n["properties"].get("evidence_text", "").casefold()]
        )
