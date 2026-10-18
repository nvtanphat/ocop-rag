"""Explicit ontology; no free-form relation types from LLM/OCR."""
from __future__ import annotations
from dataclasses import dataclass

NODE_TYPES = frozenset({
    "SourceDocument", "EvidenceUnit", "Article", "Clause", "Annex", "Regulation",
    "ProductGroup", "ProductSubgroup", "CriterionSheet", "Criterion",
    "ScoreOption", "Condition", "EvidenceType", "FormTemplate", "FormField",
    "RecognitionDecision", "Product", "Organization", "AdministrativeArea", "LocalGuidance",
    "CandidateFact", "Mention", "CriterionRowCandidate", "RecognitionRecord", "RuleCandidate",
})
EDGE_ENDPOINTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "CONTAINS": (frozenset(NODE_TYPES), frozenset(NODE_TYPES)),
    "MENTIONS": (frozenset(NODE_TYPES), frozenset(NODE_TYPES)),
    "REFERENCES": (frozenset(NODE_TYPES), frozenset(NODE_TYPES)),
    "HAS_CRITERION_CANDIDATE": (frozenset(NODE_TYPES), frozenset({"CandidateFact","Criterion"})),
    "HAS_ARTICLE": (frozenset({"Regulation","SourceDocument"}), frozenset({"Article"})),
    "HAS_CLAUSE": (frozenset({"Article"}), frozenset({"Clause"})),
    "HAS_ANNEX": (frozenset({"SourceDocument","Regulation"}), frozenset({"Annex"})),
    "DEFINES_GROUP": (frozenset({"Annex"}), frozenset({"ProductGroup"})),
    "HAS_SUBGROUP": (frozenset({"ProductGroup"}), frozenset({"ProductSubgroup"})),
    "USES_SHEET": (frozenset({"ProductSubgroup","ProductGroup"}), frozenset({"CriterionSheet"})),
    "HAS_CRITERION": (frozenset({"CriterionSheet"}), frozenset({"Criterion"})),
    "HAS_OPTION": (frozenset({"Criterion"}), frozenset({"ScoreOption"})),
    "HAS_CONDITION": (frozenset({"Criterion"}), frozenset({"Condition"})),
    "REQUIRES_EVIDENCE": (frozenset({"Criterion"}), frozenset({"EvidenceType"})),
    "HAS_FIELD": (frozenset({"FormTemplate"}), frozenset({"FormField"})),
    "RECOGNIZES": (frozenset({"RecognitionDecision","RecognitionRecord"}), frozenset({"Product"})),
    "HAS_RECORD": (frozenset({"RecognitionDecision"}), frozenset({"RecognitionRecord"})),
    "DECLARED_BY": (frozenset({"RecognitionRecord"}), frozenset({"Organization"})),
    "OWNED_BY": (frozenset({"Product"}), frozenset({"Organization"})),
    "BASED_ON": (frozenset({"RecognitionDecision"}), frozenset({"Regulation","SourceDocument"})),
    "APPLIES_IN": (frozenset({"LocalGuidance"}), frozenset({"AdministrativeArea"})),
    "AMENDS": (frozenset({"Regulation","SourceDocument"}), frozenset({"Regulation","SourceDocument"})),
    "REPLACES": (frozenset({"Regulation","SourceDocument"}), frozenset({"Regulation","SourceDocument"})),
    "SUSPENDS": (frozenset({"Regulation","SourceDocument"}), frozenset({"Regulation","SourceDocument"})),
    "SUPPORTED_BY": (frozenset(NODE_TYPES - {"EvidenceUnit"}), frozenset({"EvidenceUnit"})),
    "LOCATED_IN": (frozenset({"EvidenceUnit"}), frozenset({"SourceDocument"})),
}

@dataclass(frozen=True)
class EdgeCheck:
    ok: bool
    reason: str = ""

def validate_edge(relation: str, source_type: str, target_type: str) -> EdgeCheck:
    endpoints = EDGE_ENDPOINTS.get(relation)
    if endpoints is None:
        return EdgeCheck(False, "unknown_relation")
    if source_type not in endpoints[0] or target_type not in endpoints[1]:
        return EdgeCheck(False, "invalid_endpoint_types")
    return EdgeCheck(True)
