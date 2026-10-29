"""Deterministic coverage ordering; source text and review status are never rewritten."""

import re
import json

from ai_core.orchestration.ocop.language import fold
from ai_core.orchestration.ocop.semantic import normalize as _fold


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
            for field in ("graph_node_ids", "graph_edge_ids"):
                target[field] = list(dict.fromkeys(target.get(field, []) + row.get(field, [])))
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
            for field in ("graph_node_ids", "graph_edge_ids"):
                parent[field] = list(dict.fromkeys(parent.get(field, []) + row.get(field, [])))
    return retained
