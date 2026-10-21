"""OCOP agent route and response contracts."""
from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, ConfigDict
from ai_core.orchestration.ocop.retrieval_strategy import RetrievalPath

class Intent(str,Enum):
    OCOP_OVERVIEW="OCOP_OVERVIEW"
    EXACT_LOOKUP="EXACT_LOOKUP"
    PRODUCT_CLASSIFICATION="PRODUCT_CLASSIFICATION"
    CRITERIA_LOOKUP="CRITERIA_LOOKUP"
    PROCEDURE_FORM="PROCEDURE_FORM"
    TEMPORAL_COMPARE="TEMPORAL_COMPARE"
    RECOGNITION_LOOKUP="RECOGNITION_LOOKUP"
    SECTOR_COMPLIANCE="SECTOR_COMPLIANCE"
    DOSSIER_REVIEW="DOSSIER_REVIEW"
    SCORE_ESTIMATE="SCORE_ESTIMATE"
    MULTIHOP_REASONING="MULTIHOP_REASONING"
    FOLLOWUP="FOLLOWUP"
    CLARIFY="CLARIFY"
    OUT_OF_SCOPE="OUT_OF_SCOPE"

class Route(BaseModel):
    model_config=ConfigDict(extra="forbid")
    intent: Intent
    strategy: str
    retrieval_path: RetrievalPath = RetrievalPath.NONE
    slots: dict[str,Any]=Field(default_factory=dict)
    required_tools: list[str]=Field(default_factory=list)
    secondary_tools: list[str]=Field(default_factory=list)
    secondary_intents: list[Intent]=Field(default_factory=list)
    capabilities: list[str]=Field(default_factory=list)
    needs_clarification: bool=False
    missing_slots: list[str]=Field(default_factory=list)
    reason_codes: list[str]=Field(default_factory=list)
    confidence: float|None=None

class AuthContext(BaseModel):
    """Only a trusted server-side authentication adapter may construct/pass this.

    Never deserialize this object from a user-provided session or chat context.
    """
    model_config=ConfigDict(extra="forbid", frozen=True)
    principal_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)


class AgentResponse(BaseModel):
    answer: str
    intent: Intent
    status: str
    citations: list[dict]=Field(default_factory=list)
    tools_used: list[str]=Field(default_factory=list)
    tool_trace: list[dict]=Field(default_factory=list)
    evidence_coverage: dict[str,Any]=Field(default_factory=dict)
    evidence_grade: dict[str,Any]=Field(default_factory=dict)
    claim_verification: dict[str,Any]=Field(default_factory=dict)
    generation_diagnostics: dict[str,Any]=Field(default_factory=dict)
    evidence_fusion: dict[str,Any]=Field(default_factory=dict)
    workflow_engine: str
    corpus_version: str|None=None
    route: Route
