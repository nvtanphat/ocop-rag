"""OCOP business capabilities independent from router labels and search strategies.

This registry is server-owned. Retrieved PDFs and LLM output cannot register a
new tool, change a tool's permissions, or designate evidence as verified.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

MAX_TOOL_CALLS = 5


class Capability(str, Enum):
    OVERVIEW = 'overview'
    CLASSIFY_PRODUCT = 'classify_product'
    CRITERIA = 'criteria'
    EVIDENCE_REQUIREMENTS = 'evidence_requirements'
    PROCEDURE_FORM = 'procedure_form'
    TEMPORAL = 'temporal'
    RECOGNITION = 'recognition'
    SECTOR_COMPLIANCE = 'sector_compliance'
    REVIEW_DOSSIER = 'review_dossier'
    ESTIMATE_SCORE = 'estimate_score'
    EXACT_ARTICLE = 'exact_article'
    RELATION_REASONING = 'relation_reasoning'


@dataclass(frozen=True)
class ToolSpec:
    name: str
    input_slots: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    requires_auth: bool = False
    source_backed: bool = True
    description: str = ''


# Explicit allowlist shared by router, planner and dispatch. Tool specs describe
# *inputs*, not a claim that candidate OCR outputs are trustworthy.
TOOL_REGISTRY: dict[str, ToolSpec] = {
    'search_regulations': ToolSpec('search_regulations', produces=('evidence_unit_id',), description='Sparse/dense text evidence'),
    'lookup_legal_unit': ToolSpec('lookup_legal_unit', produces=('evidence_unit_id',), description='Exact article or document'),
    'lookup_product_subgroup': ToolSpec('lookup_product_subgroup', produces=('product_group','product_subgroup'), description='Source-backed product taxonomy candidates'),
    'lookup_criterion': ToolSpec('lookup_criterion', produces=('criterion_id','sheet_id'), description='Criterion candidates for a product group'),
    'lookup_evidence_requirements': ToolSpec('lookup_evidence_requirements', produces=('evidence_unit_id',), description='Evidence requirements grounded to criteria'),
    'lookup_form': ToolSpec('lookup_form', produces=('form_id',), description='OCOP form template'),
    'lookup_recognition': ToolSpec('lookup_recognition', produces=('evidence_unit_id',), description='Recognition decision candidates'),
    'resolve_temporal_applicability': ToolSpec('resolve_temporal_applicability', input_slots=('as_of_date',), produces=('temporal_verdict',), description='Verified temporal rules only'),
    'search_graph': ToolSpec('search_graph', produces=('evidence_unit_id',), description='Typed source-backed graph traversal'),
    'review_dossier': ToolSpec('review_dossier', input_slots=('dossier_id',), requires_auth=True, description='Private checklist'),
    'estimate_score': ToolSpec('estimate_score', input_slots=('dossier_id',), requires_auth=True, description='Private provisional score from verified rules'),
    'open_source_span': ToolSpec('open_source_span', input_slots=('evidence_unit_id',), description='Open exact PDF source evidence'),
}

CAPABILITY_TO_TOOLS: dict[Capability, tuple[str, ...]] = {
    Capability.OVERVIEW: ('search_regulations',),
    Capability.CLASSIFY_PRODUCT: ('lookup_product_subgroup',),
    Capability.CRITERIA: ('lookup_criterion',),
    Capability.EVIDENCE_REQUIREMENTS: ('lookup_evidence_requirements',),
    Capability.PROCEDURE_FORM: ('lookup_form',),
    Capability.TEMPORAL: ('resolve_temporal_applicability','search_regulations'),
    Capability.RECOGNITION: ('lookup_recognition',),
    Capability.SECTOR_COMPLIANCE: ('search_regulations',),
    Capability.REVIEW_DOSSIER: ('review_dossier',),
    Capability.ESTIMATE_SCORE: ('estimate_score',),
    Capability.EXACT_ARTICLE: ('lookup_legal_unit',),
    Capability.RELATION_REASONING: ('search_graph',),
}

# Server-side sequencing constraints when both tools are requested. Cycles are
# rejected by the planner, rather than letting an LLM choose arbitrary order.
TOOL_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    'lookup_criterion': ('lookup_product_subgroup',),
    'lookup_evidence_requirements': ('lookup_criterion',),
    'lookup_form': ('lookup_evidence_requirements',),
    'search_graph': ('search_regulations',),
}

PRIVATE_TOOLS = frozenset(name for name, spec in TOOL_REGISTRY.items() if spec.requires_auth)
