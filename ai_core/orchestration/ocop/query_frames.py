"""Conservative full-question coverage for exact, server-owned record lookups."""

from __future__ import annotations

import re
import unicodedata

from ai_core.orchestration.ocop.capabilities import TOOL_REGISTRY
from ai_core.orchestration.ocop.language import get_language
from ai_core.orchestration.ocop.memory import REFERENT_SLOTS


def _values(value):
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, (str, int))]
    return [str(value)] if isinstance(value, (str, int)) else []


def identity_request(query: str, name: str, slots: dict) -> list[str]:
    """Canonical identities only when every task word belongs to a known lookup frame.

    An unconsumed predicate, causal question, or unsupported scope keeps generic
    retrieval available. This classifies retrieval sufficiency, never entailment.
    """
    language = get_language()
    spec = TOOL_REGISTRY.get(name)
    frames = language.cues.get("direct_lookup", {})
    if not spec or not isinstance(frames, dict) or name not in frames:
        return []
    if language.hit(query, "direct_lookup_exclusion"):
        return []
    identities = next((_values(slots[k]) for k in spec.identity_slots if slots.get(k)), [])
    if not identities or any(k not in spec.input_slots for k in slots):
        return []
    explained = set()
    for key in spec.input_slots:
        for value in _values(slots.get(key)):
            explained.update(language.content_words(value))
    for family in frames[name]:
        for hit in language.hits(query, family):
            explained.update(language.content_words(hit))
    for kind, keys in REFERENT_SLOTS.items():
        if set(keys) & set(spec.identity_slots):
            for noun in language.structure_nouns.get(kind, []):
                explained.update(language.content_words(noun))
    for phrase in language.followup.reference_quantities:
        explained.update(language.content_words(phrase))
    codes = _values(slots.get("document_codes") or slots.get("document_code"))
    if codes:
        for aliases in language.document_types.values():
            for alias in aliases:
                explained.update(language.content_words(alias))
                for code in codes:
                    explained.update(language.content_words(alias + code))
    return identities if not set(language.content_words(query)) - explained else []


def _normal(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value).casefold()).strip()


def identity_coverage(rows: list[dict], names: list[str], tool: str):
    """Match complete source cell values within each typed record's provenance group.

    None means this adapter has no typed record identity contract. An empty set
    means a typed result did not contain all requested identities.
    """
    kind = TOOL_REGISTRY[tool].identity_node_type
    groups = {}
    for row in rows:
        ids = row.get("graph_node_ids")
        if row.get("graph_node_type") != kind or not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
            continue
        key = (row.get("source_id"), tuple(sorted(ids)))
        values = groups.setdefault(key, set())
        for field in ("text", "row_text", "evidence_text", "label_candidate", "title"):
            value = row.get(field)
            if isinstance(value, str):
                values.update(_normal(part) for part in value.split("|"))
    if not groups:
        return None
    wanted = {_normal(n) for n in names}
    found = {key: values & wanted for key, values in groups.items()}
    if set().union(*found.values()) != wanted:
        return set()
    return {key for key, matches in found.items() if matches}
