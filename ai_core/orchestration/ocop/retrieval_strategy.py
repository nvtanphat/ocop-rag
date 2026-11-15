"""Second-stage retrieval-path classification, derived from allowlisted tool plan.

Business intent is stage 1. This label is stage 2 *observability*, not a
permission or a promise of external databases/parallel execution. Tool DAG
remains the single authority for execution and private authorization.
"""

from __future__ import annotations
from enum import Enum


class RetrievalPath(str, Enum):
    NONE = "NONE"
    PINPOINT = "PINPOINT"
    TEXT = "TEXT"
    GRAPH = "GRAPH"
    HYBRID_GRAPH = "HYBRID_GRAPH"
    AGENTIC = "AGENTIC"


def choose_retrieval_path(tools: list[str]) -> RetrievalPath:
    requested = set(tools)
    if not requested:
        return RetrievalPath.NONE
    if "search_graph" in requested:
        if requested & {
            "search_regulations",
            "lookup_legal_unit",
            "lookup_criterion",
            "lookup_evidence_requirements",
            "lookup_product_subgroup",
            "lookup_recognition",
            "lookup_form",
        }:
            return RetrievalPath.HYBRID_GRAPH
        return RetrievalPath.GRAPH
    if requested & {
        "lookup_legal_unit",
        "lookup_criterion",
        "lookup_form",
        "lookup_product_subgroup",
        "lookup_recognition",
    }:
        return RetrievalPath.PINPOINT
    return RetrievalPath.TEXT
