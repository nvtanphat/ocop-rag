"""OCOP business capabilities independent from router labels and search strategies.

This registry is server-owned. Retrieved PDFs and LLM output cannot register a
new tool, change a tool's permissions, or designate evidence as verified.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

from ai_core.retrieval.ocop.settings import get_settings

MAX_TOOL_CALLS = get_settings().agent.max_tool_calls


class Capability(str, Enum):
    OVERVIEW = "overview"
    CLASSIFY_PRODUCT = "classify_product"
    CRITERIA = "criteria"
    EVIDENCE_REQUIREMENTS = "evidence_requirements"
    PROCEDURE_FORM = "procedure_form"
    TEMPORAL = "temporal"
    RECOGNITION = "recognition"
    SECTOR_COMPLIANCE = "sector_compliance"
    EXACT_ARTICLE = "exact_article"
    RELATION_REASONING = "relation_reasoning"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    input_slots: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    requires_auth: bool = False
    source_backed: bool = True
    description: str = ""
    public_description: str = ""


# Explicit allowlist shared by router, planner and dispatch. Tool specs describe
# *inputs*, not a claim that candidate OCR outputs are trustworthy.
TOOL_REGISTRY: dict[str, ToolSpec] = {
    "search_regulations": ToolSpec(
        "search_regulations",
        produces=("evidence_unit_id",),
        description="Sparse/dense text evidence",
        public_description="tìm hiểu quy định OCOP",
    ),
    "lookup_legal_unit": ToolSpec(
        "lookup_legal_unit",
        produces=("evidence_unit_id",),
        description="Exact article or document",
        public_description="tra cứu văn bản và điều khoản",
    ),
    "lookup_product_subgroup": ToolSpec(
        "lookup_product_subgroup",
        produces=("product_group", "product_subgroup"),
        description="Source-backed product taxonomy candidates",
        public_description="tìm nhóm sản phẩm",
    ),
    "lookup_criterion": ToolSpec(
        "lookup_criterion",
        produces=("criterion_id", "sheet_id"),
        description="Criterion candidates for a product group",
        public_description="tra tiêu chí đánh giá",
    ),
    "lookup_evidence_requirements": ToolSpec(
        "lookup_evidence_requirements",
        produces=("evidence_unit_id",),
        description="Evidence requirements grounded to criteria",
        public_description="tra yêu cầu minh chứng",
    ),
    "lookup_form": ToolSpec(
        "lookup_form",
        produces=("form_id",),
        description="OCOP form template",
        public_description="tìm biểu mẫu hồ sơ",
    ),
    "lookup_recognition": ToolSpec(
        "lookup_recognition",
        produces=("evidence_unit_id",),
        description="Recognition decision candidates",
        public_description="tra quyết định công nhận",
    ),
    "resolve_temporal_applicability": ToolSpec(
        "resolve_temporal_applicability",
        input_slots=("as_of_date",),
        produces=("temporal_verdict",),
        description="Verified temporal rules only",
        public_description="đối chiếu thời điểm áp dụng khi có quy tắc đã xác minh",
    ),
    "search_graph": ToolSpec(
        "search_graph",
        produces=("evidence_unit_id",),
        description="Typed source-backed graph traversal",
        public_description="tìm liên hệ giữa các văn bản",
    ),
    "open_source_span": ToolSpec(
        "open_source_span", input_slots=("evidence_unit_id",), description="Open exact PDF source evidence"
    ),
}

CAPABILITY_TO_TOOLS: dict[Capability, tuple[str, ...]] = {
    Capability.OVERVIEW: ("search_regulations",),
    Capability.CLASSIFY_PRODUCT: ("lookup_product_subgroup",),
    Capability.CRITERIA: ("lookup_criterion",),
    Capability.EVIDENCE_REQUIREMENTS: ("lookup_evidence_requirements",),
    Capability.PROCEDURE_FORM: ("lookup_form",),
    Capability.TEMPORAL: ("resolve_temporal_applicability", "search_regulations"),
    Capability.RECOGNITION: ("lookup_recognition",),
    Capability.SECTOR_COMPLIANCE: ("search_regulations",),
    Capability.EXACT_ARTICLE: ("lookup_legal_unit",),
    Capability.RELATION_REASONING: ("search_graph",),
}

# Server-side sequencing constraints when both tools are requested. Cycles are
# rejected by the planner, rather than letting an LLM choose arbitrary order.
TOOL_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "lookup_criterion": ("lookup_product_subgroup",),
    "lookup_evidence_requirements": ("lookup_criterion",),
    "lookup_form": ("lookup_evidence_requirements",),
    "search_graph": ("search_regulations",),
}

PRIVATE_TOOLS = frozenset(name for name, spec in TOOL_REGISTRY.items() if spec.requires_auth)
