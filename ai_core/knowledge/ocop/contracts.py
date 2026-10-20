"""Business-grade, source-grounded graph/rule contracts.

An OCR extraction is a CANDIDATE, never a legal fact or executable scoring rule.
IDs are stable and review is an explicit operation separate from extraction.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)


class Status(str, Enum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    REJECTED = "rejected"


class EntityType(str, Enum):
    SOURCE_DOCUMENT = "SourceDocument"
    ARTICLE = "Article"
    CLAUSE = "Clause"
    POINT = "Point"
    STAR_LEVEL = "StarLevel"
    CRITERION_SHEET = "CriterionSheet"
    AUTHORITY = "Authority"
    PROCEDURE_STEP = "ProcedureStep"
    LOCAL_GUIDANCE = "LocalGuidance"
    ADMINISTRATIVE_AREA = "AdministrativeArea"
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


# Descriptive features only; numeric scoring and legal interpretation are not LLM features.
ENTITY_ATTRIBUTE_KEYS = {
    'Product': ('product_type', 'brand', 'packaging', 'raw_material', 'origin_area'),
    'Organization': ('organization_form', 'address', 'representative'),
    'Criterion': ('code',), 'EvidenceType': ('issuer', 'copies', 'format'),
    'ProductGroup': ('code',), 'ProductSubgroup': ('code',), 'Condition': ('subject',),
}


# Only relationships with explicitly checked endpoints can enter the business graph.
RELATION_TYPES = {
    "HAS_ARTICLE": (EntityType.SOURCE_DOCUMENT, EntityType.ARTICLE),
    "HAS_CLAUSE": (EntityType.ARTICLE, EntityType.CLAUSE),
    "HAS_POINT": (EntityType.CLAUSE, EntityType.POINT),
    "MINIMUM_FOR": (EntityType.SCORE_OPTION, EntityType.STAR_LEVEL),
    "DEFINES_GROUP": (EntityType.SOURCE_DOCUMENT, EntityType.PRODUCT_GROUP),
    "USES_SHEET": (EntityType.PRODUCT_SUBGROUP, EntityType.CRITERION_SHEET),
    "HAS_CRITERION": (EntityType.CRITERION_SHEET, EntityType.CRITERION),
    "RESPONSIBLE_FOR": (EntityType.AUTHORITY, EntityType.PROCEDURE_STEP),
    "APPLIES_IN": (EntityType.LOCAL_GUIDANCE, EntityType.ADMINISTRATIVE_AREA),
    "OWNED_BY": (EntityType.PRODUCT, EntityType.ORGANIZATION),
    "BASED_ON": (EntityType.RECOGNITION_DECISION, EntityType.SOURCE_DOCUMENT),
    "AMENDS": (EntityType.SOURCE_DOCUMENT, EntityType.SOURCE_DOCUMENT),
    "REPLACES": (EntityType.SOURCE_DOCUMENT, EntityType.SOURCE_DOCUMENT),
    "SUSPENDS": (EntityType.SOURCE_DOCUMENT, EntityType.SOURCE_DOCUMENT),
    "HAS_RECORD": (EntityType.RECOGNITION_DECISION, EntityType.RECOGNITION_RECORD),
    "RECOGNIZES": (EntityType.RECOGNITION_RECORD, EntityType.PRODUCT),
    "DECLARED_BY": (EntityType.RECOGNITION_RECORD, EntityType.ORGANIZATION),
    "HAS_FIELD": (EntityType.FORM_TEMPLATE, EntityType.FORM_FIELD),
    "HAS_SUBCRITERION": (EntityType.CRITERION, EntityType.CRITERION),
    "HAS_OPTION": (EntityType.CRITERION, EntityType.SCORE_OPTION),
    "HAS_CONDITION": (EntityType.CRITERION, EntityType.CONDITION),
    "REQUIRES_EVIDENCE": (frozenset({EntityType.CRITERION,EntityType.PROCEDURE_STEP}), EntityType.EVIDENCE_TYPE),
    "HAS_SUBGROUP": (EntityType.PRODUCT_GROUP, EntityType.PRODUCT_SUBGROUP),
}


class EvidenceRef(Strict):
    source_id: str = Field(min_length=3)
    evidence_unit_id: str = Field(min_length=5)
    pdf_page: int = Field(ge=1)
    source_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
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


class AttributeClaim(Strict):
    """An observed feature with its own proof; alignment does not verify meaning."""
    attribute: str = Field(min_length=1)
    value: str = Field(min_length=1)
    evidence: list[EvidenceRef] = Field(min_length=1)
    status: Literal['candidate'] = 'candidate'
    extraction_method: str = Field(min_length=1)


class BusinessEntity(Strict):
    entity_id: str = Field(min_length=5)
    kind: EntityType
    label: str = Field(min_length=1)
    source_id: str
    evidence: list[EvidenceRef] = Field(min_length=1)
    status: Status = Status.CANDIDATE
    attributes: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    extraction_method: str = "deterministic_from_structure"
    attribute_claims: list[AttributeClaim] = Field(default_factory=list)

    @model_validator(mode='after')
    def claims_have_entity_provenance(self):
        for claim in self.attribute_claims:
            if (not claim.attribute.endswith('_candidate') or
                claim.attribute.removesuffix('_candidate') not in ENTITY_ATTRIBUTE_KEYS.get(self.kind.value, ())):
                raise ValueError('machine attribute claim must be a candidate')
            if any(ref not in self.evidence for ref in claim.evidence):
                raise ValueError('attribute claim proof must be included in entity evidence')
        return self


class BusinessRelation(Strict):
    relation_id: str = Field(min_length=5)
    relation_type: str
    source_entity_id: str
    target_entity_id: str
    evidence: list[EvidenceRef] = Field(min_length=1)
    status: Status = Status.CANDIDATE
    attributes: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
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


def contains_document_number(text: str, number: str) -> bool:
    """A whole legal number, never a suffix of another number or jurisdiction."""
    return bool(re.search(r'(?<![\w/])' + re.escape(number) + r'(?![\w/-])', text, re.I))


def validate_business_graph(entities: list[BusinessEntity], relations: list[BusinessRelation],
                            *, source_registry: dict[str, dict] | None = None) -> None:
    """Fail closed for missing, mistyped, cross-source or ungrounded relations."""
    by_id = {x.entity_id: x for x in entities}
    if len(by_id) != len(entities):
        raise ValueError("duplicate business entity id")
    for entity in entities:
        foreign = {e.source_id for e in entity.evidence if e.source_id != entity.source_id}
        if not foreign:
            continue
        number = (source_registry or {}).get(entity.source_id, {}).get('document_number')
        if (entity.kind != EntityType.SOURCE_DOCUMENT or not number or
            entity.attributes.get('registry_source_id') != entity.source_id or any(
                not any(e.source_id == sid and contains_document_number(e.quote, number)
                        for e in entity.evidence) for sid in foreign)):
            raise ValueError('business entity evidence source mismatch; cross-document identity needs explicit resolution')
    relation_ids = set()
    for r in relations:
        if r.relation_id in relation_ids:
            raise ValueError("duplicate business relation id")
        relation_ids.add(r.relation_id)
        src, dst = by_id.get(r.source_entity_id), by_id.get(r.target_entity_id)
        if src is None or dst is None:
            raise ValueError("business relation missing endpoint")
        expected_src,expected_dst=RELATION_TYPES[r.relation_type]
        if (src.kind not in (expected_src if isinstance(expected_src,frozenset) else {expected_src}) or
            dst.kind not in (expected_dst if isinstance(expected_dst,frozenset) else {expected_dst})):
            raise ValueError("business relation endpoint type mismatch")
        if src.source_id != dst.source_id:
            registered = (source_registry or {}).get(dst.source_id, {}).get('document_number')
            if (r.relation_type not in {'AMENDS','REPLACES','SUSPENDS','BASED_ON'} or
                dst.kind != EntityType.SOURCE_DOCUMENT or not registered or
                dst.attributes.get('registry_source_id') != dst.source_id or
                not any(e.source_id == src.source_id and contains_document_number(e.quote,registered)
                        for e in r.evidence)):
                raise ValueError("cross-document relation needs explicit resolution")
        shared = {(e.source_id, e.evidence_unit_id) for e in src.evidence}
        shared &= {(e.source_id, e.evidence_unit_id) for e in dst.evidence}
        if not shared.intersection({(e.source_id, e.evidence_unit_id) for e in r.evidence}):
            raise ValueError("relation not grounded in evidence shared by both endpoints")
        if r.status == Status.VERIFIED and (src.status != Status.VERIFIED or dst.status != Status.VERIFIED):
            raise ValueError("verified relationship needs verified endpoints")
