"""Attach a short, de-duplicated parent chain from the checked graph to each child passage.

Technique (Anthropic "contextual retrieval", LlamaIndex parent/child): the indexed text of a chunk is
``Ngữ cảnh: <ancestor> > <ancestor>`` followed by the chunk, so BM25 and the embedding both see where the
passage sits. The chain holds only direct ancestors (never sibling points or the chunk's own nodes),
is cut to a token cap measured with the model tokenizer when one is available, and is stored separately
in ``context['parent_chain']`` so display code never has to strip it off the passage again.
"""

import re

from ai_core.graph.ocop.lookup import GraphEvidence
from ai_core.retrieval.ocop.settings import get_settings
from ai_core.retrieval.ocop.structure_chunker import estimated_tokens

PARENT_RELATIONS = {
    "HAS_CRITERION",
    "HAS_SUBCRITERION",
    "HAS_OPTION",
    "HAS_CONDITION",
    "HAS_ARTICLE",
    "HAS_CLAUSE",
    "HAS_POINT",
}
CHUNK_NODE_TYPES = {"Criterion", "ScoreOption", "Condition", "Article", "Clause", "Point"}
CHAIN_NODE_TYPES = {"CriterionSheet", "Criterion", "Article", "Clause", "Point"}
CONTEXT_PREFIX = "Ngữ cảnh: "


def _short(label: str, limit: int) -> str:
    label = re.sub(r"\s+", " ", label).strip()
    if len(label) <= limit:
        return label
    cut = label[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut + "…"


def _chain(node_id, incoming, nodes):
    """Ancestors of a node, nearest last (root first), following the first parent edge."""
    chain, seen = [], {node_id}
    while True:
        edges = incoming.get(node_id) or []
        parent = next((e["source_entity_id"] for e in edges if e["source_entity_id"] not in seen), None)
        if parent is None or parent not in nodes:
            return list(reversed(chain))
        seen.add(parent)
        chain.append(parent)
        node_id = parent


def enrich_chunks(chunks, graph_dir, *, allow_partial_debug=False, counter=None, root=None):
    cfg = get_settings(root).context
    count = counter or estimated_tokens
    graph = GraphEvidence(graph_dir, allow_partial_debug=allow_partial_debug)
    incoming = {}
    for edge in graph.edges:
        if edge["relation_type"] in PARENT_RELATIONS:
            incoming.setdefault(edge["target_entity_id"], []).append(edge)
    by_source = {}
    for node in graph.nodes.values():
        by_source.setdefault(node["source_id"], []).append(node)
    for chunk in chunks:
        uid = chunk["evidence_unit_id"]
        row_ids = set(chunk.get("row_ids", []))
        raw = chunk.get("raw_text") or ""
        backing = graph.units.get(uid, {}).get("properties", {}).get("evidence_text", "")

        def overlaps(ref):
            if ref.get("evidence_unit_id") != uid:
                return False
            if row_ids:
                return ref.get("row") in row_ids
            quote = ref.get("quote", "")
            start = backing.find(quote) if quote else -1
            if start < 0:
                return False
            return (chunk.get("char_start", 0) or 0) < start + len(quote) and (
                chunk.get("char_end") or len(backing)
            ) > start

        pool = by_source.get(chunk["source_id"], [])
        candidates = [
            n
            for n in pool
            if n["node_type"] in CHUNK_NODE_TYPES and any(overlaps(ref) for ref in n.get("citations", []))
        ]
        if row_ids:
            # Notes inherit the nearest observed criterion within the same table.
            def heading_rows(node):
                return [
                    ref["row"]
                    for ref in node.get("citations", [])
                    if ref.get("evidence_unit_id") == uid
                    and isinstance(ref.get("row"), int)
                    and node["label"] in ref.get("quote", "")
                ]

            preceding = [
                n
                for n in pool
                if n["node_type"] == "Criterion"
                and re.match(r"^\d+\.\d+", n["label"])
                and any(row <= min(row_ids) for row in heading_rows(n))
            ]
            if preceding:
                candidates.append(
                    max(preceding, key=lambda n: max(row for row in heading_rows(n) if row <= min(row_ids)))
                )
        if not candidates:
            continue
        candidate_ids = {n["node_id"] for n in candidates}
        # Structural set (candidates + ancestors) feeds codes/provenance; the displayed chain is ancestors only.
        parents, used = set(candidate_ids), []
        while True:
            edges = [
                e
                for identity in list(parents)
                for e in incoming.get(identity, [])
                if e["source_entity_id"] not in parents
            ]
            if not edges:
                break
            used.extend(edges)
            parents.update(e["source_entity_id"] for e in edges)
        structural = [
            graph.nodes[i] for i in sorted(parents) if graph.nodes[i]["node_type"] in CHAIN_NODE_TYPES
        ]
        if not structural:
            continue
        ancestors_of_candidates = set()
        for identity in candidate_ids:
            ancestors_of_candidates.update(_chain(identity, incoming, graph.nodes))
        leafmost = sorted(
            (i for i in candidate_ids if i not in ancestors_of_candidates),
            key=lambda i: (
                min(
                    [
                        ref.get("row", 0)
                        for ref in graph.nodes[i].get("citations", [])
                        if ref.get("evidence_unit_id") == uid
                    ]
                    or [0]
                ),
                i,
            ),
        )
        chain_ids = _chain(leafmost[0], incoming, graph.nodes) if leafmost else []
        folded_raw = re.sub(r"\s+", " ", raw).casefold()
        labels = []
        for identity in chain_ids:
            node = graph.nodes[identity]
            if node["node_type"] not in CHAIN_NODE_TYPES:
                continue
            label = _short(node["label"], cfg.parent_label_max_chars)
            if not label or re.sub(r"\s+", " ", node["label"]).casefold() in folded_raw:
                continue  # the chunk itself already shows it
            if not labels or labels[-1] != label:
                labels.append(label)
        kept = []
        for label in reversed(labels):  # keep the nearest ancestors first when the cap bites
            if count(CONTEXT_PREFIX + " > ".join([label, *kept])) > cfg.parent_chain_max_tokens and kept:
                break
            kept.insert(0, label)
        if kept and count(CONTEXT_PREFIX + " > ".join(kept)) > cfg.parent_chain_max_tokens:
            kept = []
        if kept:
            prefix = CONTEXT_PREFIX + " > ".join(kept) + "\n"
            chunk["text_for_bm25"] = prefix + chunk["text_for_bm25"]
            chunk["text_for_embedding"] = prefix + chunk["text_for_embedding"]
        codes = [m.group(0) for n in structural for m in [re.match(r"\d{1,2}\.\d{1,2}", n["label"])] if m]
        chunk.setdefault("context", {}).update(
            {
                "parent_chain": kept,
                "criterion_codes": list(dict.fromkeys(codes)),
                "parent_graph_node_ids": [n["node_id"] for n in structural],
                "graph_edge_ids": list(dict.fromkeys(e["edge_id"] for e in used)),
                "parent_source_spans": [ref for n in structural for ref in n.get("citations", [])],
            }
        )
    return chunks
