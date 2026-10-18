"""Business-grade, source-grounded graph/rule contracts.

An OCR extraction is a CANDIDATE, never a legal fact or executable scoring rule.
IDs are stable and review is an explicit operation separate from extraction.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Status(str, Enum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    REJECTED = "rejected"


class EntityType(str, Enum):
    PRODUCT = "Product"
    ORGANIZATION = "Organization"
    RECOGNITION_DECISION = "RecognitionDecision"
    RECOGNITION_RECORD = "RecognitionRecord"
    CRITERION_ROW = "CriterionRowCandidate"
    FORM_TEMPLATE = "FormTemplate"
    FORM_FIELD = "FormField"
    REGULATORY_CLAIM = "RegulatoryClaim"
    CRITERION = "Criterion"
    SCORE_OPTION = "ScoreOption"
    EVIDENCE_TYPE = "EvidenceType"
    PRODUCT_GROUP = "ProductGroup"
    PRODUCT_SUBGROUP = "ProductSubgroup"
    CONDITION = "Condition"
    FORMAL_RULE = "RuleCandidate"


# Only relationships with explicitly checked endpoints can enter the business graph.
RELATION_TYPES = {
    "HAS_RECORD": (EntityType.RECOGNITION_DECISION, EntityType.RECOGNITION_RECORD),
    "RECOGNIZES": (EntityType.RECOGNITION_RECORD, EntityType.PRODUCT),
    "DECLARED_BY": (EntityType.RECOGNITION_RECORD, EntityType.ORGANIZATION),
    "HAS_FIELD": (EntityType.FORM_TEMPLATE, EntityType.FORM_FIELD),
    "HAS_OPTION": (EntityType.CRITERION, EntityType.SCORE_OPTION),
    "HAS_CONDITION": (EntityType.CRITERION, EntityType.CONDITION),
    "REQUIRES_EVIDENCE": (EntityType.CRITERION, EntityType.EVIDENCE_TYPE),
    "HAS_SUBGROUP": (EntityType.PRODUCT_GROUP, EntityType.PRODUCT_SUBGROUP),
}


class EvidenceRef(Strict):
    source_id: str = Field(min_length=3)
    evidence_unit_id: str = Field(min_length=5)
    pdf_page: int = Field(ge=1)
    table_id: str | None = None
    row: int | None = Field(default=None, ge=0)
    cell_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    quote: str = Field(min_length=1)

    @field_validator("bbox")
    @classmethod
    def valid_bbox(cls, value):
        if value is not None and (value[0] > value[2] or value[1] > value[3]):
            raise ValueError("bbox invalid")
        return value


class BusinessEntity(Strict):
    entity_id: str = Field(min_length=5)
    kind: EntityType
    label: str = Field(min_length=1)
    source_id: str
    evidence: list[EvidenceRef] = Field(min_length=1)
    status: Status = Status.CANDIDATE
    attributes: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    extraction_method: str = "deterministic_from_structure"


class BusinessRelation(Strict):
    relation_id: str = Field(min_length=5)
    relation_type: str
    source_entity_id: str
    target_entity_id: str
    evidence: list[EvidenceRef] = Field(min_length=1)
    status: Status = Status.CANDIDATE
    extraction_method: str = "deterministic_from_structure"

    @field_validator("relation_type")
    @classmethod
    def whitelisted(cls, v):
        if v not in RELATION_TYPES:
            raise ValueError("relation type not in business ontology")
        return v


class Condition(Strict):
    """Atomic test; never evaluate free-text conditions as Python or LLM code."""
    field: str = Field(min_length=1)
    operation: Literal["equals", "in", "exists", "gte", "lte"]
    value: str | int | float | bool | None = None


class BusinessRule(Strict):
    rule_id: str
    source_id: str
    kind: Literal["obligation", "prohibition", "permission", "exemption", "scoring", "temporal"]
    statement: str = Field(min_length=1)
    evidence: list[EvidenceRef] = Field(min_length=1)
    status: Status = Status.CANDIDATE
    # Only a source-backed, *reviewed* formalization may have executable conditions.
    if_all: list[Condition] = Field(default_factory=list)
    consequence: dict[str, str | int | float | bool] = Field(default_factory=dict)
    except_when: list[Condition] = Field(default_factory=list)
    valid_from: date | None = None
    valid_to_exclusive: date | None = None
    jurisdiction: str | None = None
    scope: str | None = None

    @model_validator(mode="after")
    def validate_rule(self):
        if self.valid_from and self.valid_to_exclusive and self.valid_from >= self.valid_to_exclusive:
            raise ValueError("invalid time interval")
        if self.status != Status.VERIFIED and (self.if_all or self.consequence or self.except_when):
            raise ValueError("unverified OCR/LLM rule cannot contain executable logic")
        if self.status == Status.VERIFIED and not self.consequence:
            raise ValueError("verified rule requires explicitly formalized consequence")
        return self


def validate_business_graph(entities: list[BusinessEntity], relations: list[BusinessRelation]) -> None:
    """Fail closed for missing, mistyped, cross-source or ungrounded relations."""
    by_id = {x.entity_id: x for x in entities}
    if len(by_id) != len(entities):
        raise ValueError("duplicate business entity id")
    relation_ids = set()
    for r in relations:
        if r.relation_id in relation_ids:
            raise ValueError("duplicate business relation id")
        relation_ids.add(r.relation_id)
        src, dst = by_id.get(r.source_entity_id), by_id.get(r.target_entity_id)
        if src is None or dst is None:
            raise ValueError("business relation missing endpoint")
        if (src.kind, dst.kind) != RELATION_TYPES[r.relation_type]:
            raise ValueError("business relation endpoint type mismatch")
        if src.source_id != dst.source_id:
            raise ValueError("cross-document relation needs explicit resolution")
        shared = {(e.source_id, e.evidence_unit_id) for e in src.evidence}
        shared &= {(e.source_id, e.evidence_unit_id) for e in dst.evidence}
        if not shared.intersection({(e.source_id, e.evidence_unit_id) for e in r.evidence}):
            raise ValueError("relation not grounded in evidence shared by both endpoints")
        if r.status == Status.VERIFIED and (src.status != Status.VERIFIED or dst.status != Status.VERIFIED):
            raise ValueError("verified relationship needs verified endpoints")
