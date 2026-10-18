"""OCOP knowledge contracts for evidence, criteria and document provenance."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SourceKind(str, Enum):
    OCOP_FRAMEWORK = "ocop_framework"
    OCOP_HISTORICAL = "ocop_historical"
    OCOP_AMENDMENT = "ocop_amendment"
    FOOD_SAFETY_LAW = "food_safety_law"
    FOOD_SAFETY_DECREE = "food_safety_decree"
    FOOD_SAFETY_RESOLUTION = "food_safety_resolution"
    LABELING_DECREE = "labeling_decree"
    LABELING_AMENDMENT = "labeling_amendment"
    COOPERATIVE_LAW = "cooperative_law"
    LOCAL_GUIDANCE = "local_guidance"
    RECOGNITION_DECISION = "recognition_decision"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    MACHINE_EXTRACTED = "machine_extracted"
    NEEDS_REVIEW = "needs_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


class SourceDocument(StrictModel):
    source_id: str = Field(min_length=3)
    path: str = Field(min_length=1)  # relative to repository root
    source_kind: SourceKind
    file_sha256: str | None = None
    page_count: int | None = Field(default=None, gt=0)
    document_number: str | None = None
    source_url: str | None = None
    source_verification: str = "provided_copy_unverified_signature"
    metadata_review: ReviewStatus = ReviewStatus.PENDING
    issued_at: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None  # first day no longer applicable, when known
    jurisdiction: str | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        from pathlib import PurePosixPath

        if "\\" in value or value.startswith("/") or ".." in PurePosixPath(value).parts:
            raise ValueError("source path must be safe relative POSIX path")
        if not value.lower().endswith(".pdf"):
            raise ValueError("OCOP source must be a PDF")
        return value

    @field_validator("file_sha256")
    @classmethod
    def validate_hash(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
            raise ValueError("file_sha256 must be lowercase hex sha256")
        return value

    @model_validator(mode="after")
    def validate_period(self):
        if self.effective_from and self.effective_to and self.effective_from > self.effective_to:
            raise ValueError("effective_from cannot exceed effective_to")
        return self


class SourceSpan(StrictModel):
    pdf_page: int = Field(ge=1)
    printed_page: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    table_bbox: tuple[float, float, float, float] | None = None
    block_id: str | None = None
    table_id: str | None = None
    cell_id: str | None = None
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("bbox", "table_bbox")
    @classmethod
    def bbox_order(cls, value):
        if value is not None:
            if not all(math.isfinite(part) for part in value):
                raise ValueError("bbox coordinates must be finite")
            if value[0] > value[2] or value[1] > value[3]:
                raise ValueError("invalid bbox ordering")
        return value


class PageArtifact(StrictModel):
    source_id: str
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    pdf_page: int = Field(ge=1)
    width_pt: float = Field(gt=0)
    height_pt: float = Field(gt=0)
    extracted_text: str = ""
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    extraction_method: str = "unprocessed"
    review_status: ReviewStatus = ReviewStatus.PENDING


class EvidenceUnit(StrictModel):
    unit_id: str
    source_id: str
    unit_kind: str
    parent_unit_id: str | None = None
    hierarchy_path: list[str] = Field(default_factory=list)
    text: str
    structured: dict[str, Any] = Field(default_factory=dict)
    spans: list[SourceSpan] = Field(min_length=1)
    extractor_version: str
    review_status: ReviewStatus = ReviewStatus.MACHINE_EXTRACTED
    confidence: float | None = Field(default=None, ge=0, le=1)
    unit_hash: str | None = None


class ScoreOption(StrictModel):
    option_id: str
    description: str
    points: Decimal = Field(ge=0)
    spans: list[SourceSpan] = Field(min_length=1)
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW


class Criterion(StrictModel):
    criterion_id: str
    sheet_id: str
    title: str
    max_points: Decimal = Field(ge=0)
    score_options: list[ScoreOption] = Field(default_factory=list)
    evidence_unit_id: str
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW


class FormField(StrictModel):
    field_id: str
    form_id: str
    label: str
    required: bool | None = None  # None unless source establishes requirement
    spans: list[SourceSpan] = Field(min_length=1)


class ProductGroup(StrictModel):
    group_id: str
    name: str
    evidence_unit_id: str
    parent_id: str | None = None
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW


class CriterionSheet(StrictModel):
    sheet_id: str
    source_id: str
    group_id: str
    title: str
    max_points: Decimal | None = Field(default=None, ge=0)
    evidence_unit_id: str
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW


class StarRequirement(StrictModel):
    criterion_id: str
    star_level: int = Field(ge=1, le=5)
    condition_text: str | None = None
    spans: list[SourceSpan] = Field(min_length=1)
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW


class FormTemplate(StrictModel):
    form_id: str
    title: str
    source_id: str
    evidence_unit_id: str
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW


class EvidenceRequirement(StrictModel):
    requirement_id: str
    description: str
    evidence_unit_id: str
    criterion_id: str | None = None
    required_when: str | None = None
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW


class RecognitionRecord(StrictModel):
    record_id: str
    decision_source_id: str
    product_name: str
    organization_name: str | None = None
    star_rating: int | None = Field(default=None, ge=1, le=5)
    evaluation_year: int | None = None
    spans: list[SourceSpan] = Field(min_length=1)


class RetrievalChunk(StrictModel):
    chunk_id: str
    source_id: str
    evidence_unit_id: str
    text_for_embedding: str
    text_for_bm25: str
    corpus_version: str
    spans: list[SourceSpan] = Field(min_length=1)
    review_status: ReviewStatus
    # Evidence model extensions: no model-generated provenance, and no unverified
    # legal claims. Optional fields preserve read compatibility with older fixtures.
    raw_text: str = ""
    parent_unit_id: str | None = None
    hierarchy_path: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    row_ids: list[int] = Field(default_factory=list)
    table_headers: list[str] = Field(default_factory=list)
    estimated_tokens: int = Field(default=0, ge=0)
    token_count_method: str = "conservative_unicode_estimate"
    over_budget: bool = False


class CorpusRelease(StrictModel):
    version: str
    snapshot_sha256: str
    source_count: int = Field(ge=0)
    page_count: int = Field(ge=0)
    status: str = "staging"


class RouteDecision(StrictModel):
    intent: str
    strategy: str
    required_tools: list[str] = Field(default_factory=list)
    slots: dict[str, Any] = Field(default_factory=dict)
    needs_clarification: bool = False
    missing_slots: list[str] = Field(default_factory=list)


def cell_display_text(cell: dict) -> str:
    """Cell text for indexing; a blank cell shows any OCR candidate labelled as unverified."""
    text = str(cell.get("text") or "").strip()
    if text:
        return text
    candidates = [str(c.get("text") or "").strip() for c in cell.get("score_ocr_candidates") or []]
    candidates = [c for c in candidates if c]
    return f"[ứng viên OCR chưa xác minh: {' / '.join(candidates)}]" if candidates else ""
