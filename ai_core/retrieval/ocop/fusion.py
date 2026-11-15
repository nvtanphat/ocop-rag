"""Deterministic coverage ordering; source text and review status are never rewritten."""

import re
import json

from ai_core.orchestration.ocop.language import fold
from ai_core.orchestration.ocop.semantic import normalize as _fold
from ai_core.orchestration.ocop.context import graph_hops


def merge_graph_provenance(target, row):
    """Combine traversal metadata when two rows share the same source proof."""
    for field in ("graph_node_ids", "graph_edge_ids"):
        target[field] = list(dict.fromkeys(target.get(field, []) + row.get(field, [])))
    hops = graph_hops(target) | graph_hops(row)
    if hops:
        target["graph_hops"] = sorted(hops)
    for field in ("graph_edge_id", "graph_relation"):
        if not target.get(field) and row.get(field):
            target[field] = row[field]


def criterion_facets(question):
    """Criterion codes ("1.6") of a question that names a sheet or a criterion, nouns taken from the vocabulary file."""
    from ai_core.orchestration.ocop.language import get_language

    lang = get_language()
    nouns = [*lang.structure_nouns["sheet"], *lang.structure_nouns["criterion"]]
    if not lang.words("criterion_reference", nouns).search(fold(question)):
        return []
    return list(dict.fromkeys(re.findall(r"(?<![\d.])\d{1,2}\.\d{1,2}(?![\d.])", question)))


# Question words and function words carry no evidence content of their own.
_STOP = frozenset(
    """la gi nao nhung cac cua va cho theo thi co khong duoc ve voi trong tai nhu the ai bao nhieu
may hay hoac can phai ra sao gom bao nao lam viec mot nay do khi neu thi se da dang cung nhu dong thoi""".split()
)
_PART_BREAK = re.compile(r"\s*(?:[;?]|,\s*va\b|\bdong thoi\b|\bcung nhu\b)\s*")
_MIN_PART_TERMS = 3


def _terms(text):
    return [w for w in re.findall(r"[a-z0-9]+", _fold(text)) if len(w) > 1 and w not in _STOP]


def text_facets(question):
    """Natural-language parts of a multi-part question, each as its content terms.

    Splits only at strong separators (;, ?, ', và', 'đồng thời', 'cũng như') and keeps
    parts with enough content, so coordinated names are not torn apart."""
    parts = [_terms(part) for part in _PART_BREAK.split(_fold(question))]
    parts = [list(dict.fromkeys(terms)) for terms in parts if len(set(terms)) >= _MIN_PART_TERMS]
    return ["terms:" + " ".join(terms) for terms in parts] if len(parts) >= 2 else []


def covers(row, facet):
    body = str(row.get("text") or row.get("evidence_text") or row.get("row_text") or "")
    codes = row.get("context", {}).get("criterion_codes", [])
    if facet.startswith("form:"):
        return facet[5:] in {str(int(n)) for n in re.findall(r"\bmau\s+(?:so\s+)?(\d{1,2})\b", _fold(body))}
    if facet.startswith("terms:"):
        wanted = facet[6:].split()
        present = set(_terms(body))
        return sum(term in present for term in wanted) >= max(_MIN_PART_TERMS, -(-len(wanted) * 3 // 5))
    return facet in codes or bool(re.search(r"(?<![\d.])" + re.escape(facet) + r"(?!\d)", body))


def query_facets(question):
    facets = criterion_facets(question)
    folded = _fold(question)
    forms = re.findall(r"\bmau\s*(?:so\s*)?(\d{1,2})\b", folded)
    for match in re.finditer(r"\bmau\s*(?:so\s*)?\d{1,2}\b((?:\s*(?:,|va|&|/)\s*\d{1,2}\b){1,6})", folded):
        forms += re.findall(r"(?:,|va|&|/)\s*(\d{1,2})\b", match.group(1))
    facets += ["form:" + str(int(n)) for n in forms]
    if not facets:  # explicit codes already identify the parts
        facets = text_facets(question)
    return list(dict.fromkeys(facets))


def fuse_tool_rows(records):
    """One order for the rows of every tool: weighted reciprocal-rank fusion over each tool's own ranking.

    Tools score on different scales (BM25, cross-encoder, graph relevance, table lookups), so only ranks are compared,
    as in ViCAS-RAG's global fusion. A passage several tools return collects several contributions. Rows keep their
    content; only their order changes. ``row["tool"]`` names the family; rows without it count as one family.
    """
    from ai_core.retrieval.ocop.settings import get_settings

    cfg = get_settings().retrieval
    rank_in_tool = {}
    scores = {}
    first_seen = {}
    for index, row in enumerate(records):
        tool = row.get("tool") or "unknown"
        key = (row.get("source_id"), row.get("evidence_unit_id") or row.get("unit_id"), row.get("chunk_id"))
        rank = rank_in_tool.get(tool, 0)
        rank_in_tool[tool] = rank + 1
        scores[key] = scores.get(key, 0.0) + cfg.rrf_tool_weights.get(tool, 1.0) / (cfg.rrf_k + rank + 1)
        first_seen.setdefault(key, index)

    def key_of(row):
        return (row.get("source_id"), row.get("evidence_unit_id") or row.get("unit_id"), row.get("chunk_id"))

    order = sorted(range(len(records)), key=lambda i: (-scores[key_of(records[i])], first_seen[key_of(records[i])], i))
    return [records[i] for i in order]


def order_evidence(question, records):
    records = deduplicate(records)
    facets = query_facets(question)
    selected = []
    seen = set()
    # Round-robin reserves evidence for every explicitly requested criterion.
    groups = [[i for i, row in enumerate(records) if covers(row, facet)] for facet in facets]
    for rank in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if rank < len(group) and group[rank] not in seen:
                selected.append(records[group[rank]])
                seen.add(group[rank])
    selected.extend(row for i, row in enumerate(records) if i not in seen)
    return selected


def deduplicate(records):
    unique = []
    seen = {}
    for row in records:
        spans = row.get("source_spans") or row.get("spans") or []
        key = json.dumps(
            [
                row.get("source_id"),
                row.get("evidence_unit_id") or row.get("unit_id"),
                row.get("text"),
                row.get("review_status"),
                spans,
                row.get("fields_candidate"),
            ],
            sort_keys=True,
            default=str,
        )
        if key not in seen:
            seen[key] = len(unique)
            unique.append(dict(row))
        else:
            target = unique[seen[key]]
            merge_graph_provenance(target, row)
    retained = []
    for row in unique:
        refs = row.get("source_spans") or row.get("spans") or []
        ref = next((ref for ref in refs if isinstance(ref, dict)), {}) if isinstance(refs, list) else {}
        parent = None
        if ref.get("cell_id"):
            for other in unique:
                anchors = other.get("source_spans") or other.get("spans") or []
                anchor = (
                    next((ref for ref in anchors if isinstance(ref, dict)), {})
                    if isinstance(anchors, list)
                    else {}
                )
                if (
                    other is not row
                    and other.get("source_id") == row.get("source_id")
                    and other.get("review_status") == row.get("review_status")
                    and not anchor.get("cell_id")
                    and anchor.get("row") == ref.get("row")
                    and anchor.get("row") is not None
                    and anchor.get("table_id") == ref.get("table_id")
                    and anchor.get("evidence_unit_id") == ref.get("evidence_unit_id")
                    and ref.get("evidence_unit_id")
                    and ref.get("source_sha256")
                    and anchor.get("source_sha256") == ref["source_sha256"]
                    and anchor.get("pdf_page") == ref.get("pdf_page")
                    and isinstance(row.get("text"), str)
                    and row["text"]
                    and isinstance(other.get("text"), str)
                    and row["text"] in other["text"]
                ):
                    parent = other
                    break
        if parent is None:
            retained.append(row)
        else:
            merge_graph_provenance(parent, row)
    return retained
