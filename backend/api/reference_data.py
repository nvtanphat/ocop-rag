"""Public, corpus-bound verified reference records. Never exports arbitrary fields."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

import fitz
from pydantic import BaseModel, Field, ValidationError

from ocop_contracts.models import SourceSpan
from ai_core.orchestration.ocop.verification import check_sensitive_claims, verify_claims


class ReferenceCitation(SourceSpan):
    source_id: str
    evidence_unit_id: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bbox: tuple[float, float, float, float]


class ReferenceItem(BaseModel):
    id: str
    label: str
    group: str | None = None  # the product set a criterion scores
    points: float | None = None  # a criterion's maximum, as its cited row writes it
    citations: list[ReferenceCitation] = Field(min_length=1)


class ReferenceResponse(BaseModel):
    corpus_version: str | None
    status: Literal["verified", "no_verified_data"]
    items: list[ReferenceItem]


def read_references(root: Path, kind: Literal["criteria", "products"], *, ready: bool) -> ReferenceResponse:
    """Only server-owned verified files for the active, coherent corpus are eligible.

    File records have id, label, corpus_version, review_status, visibility and
    citations. Every citation must match an existing evidence span and locked PDF.
    An allowlist response prevents tenant metadata or private fields leaking out.
    """
    data = root / "data/processed/ocop"
    manifest = data / "index/manifest.json"
    version = (
        json.loads(manifest.read_text(encoding="utf-8")).get("corpus_version") if manifest.is_file() else None
    )
    result = ReferenceResponse(corpus_version=version, status="no_verified_data", items=[])
    path = data / "knowledge" / f"verified_{kind}.jsonl"
    if not ready or not version or not path.is_file():
        return result
    registry = json.loads((root / "configs/ocop_sources.json").read_text(encoding="utf-8"))["sources"]
    sources = {r["source_id"]: r for r in registry}
    lock = json.loads((root / "configs/ocop_sources.lock.json").read_text(encoding="utf-8"))
    hashes = {r["source_id"]: r["sha256"] for r in lock["sources"]}
    units = {r["unit_id"]: r for r in _records(data / "knowledge/evidence_units.jsonl")}
    for record in _records(path):
        if (
            record.get("review_status") != "verified"
            or record.get("visibility") != "public"
            or record.get("corpus_version") != version
            or any(record.get(k) for k in ("tenant_id", "dossier_id", "private"))
        ):
            continue
        try:
            item = ReferenceItem.model_validate(record)
            matching = all(_matches(root, c, sources, hashes, units) for c in item.citations)
            support = [
                {**units[c.evidence_unit_id], "review_status": "verified"}
                for c in item.citations
                if c.evidence_unit_id in units
            ]
            sensitive = check_sensitive_claims(item.label, support)
            safe = not sensitive["unsupported_score_or_star_claims"]
            if safe and sensitive["sensitive_claim_count"]:
                marked = item.label + " " + " ".join(f"[S{i}]" for i in range(1, len(item.citations) + 1))
                verdict = verify_claims(marked, [c.model_dump(mode="json") for c in item.citations], support)
                safe = verdict["status"] == "verified"
            if matching and safe:
                result.items.append(item)
        except (ValidationError, KeyError, ValueError):
            continue
    if result.items:
        result.status = "verified"
    return result


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _matches(root: Path, c: ReferenceCitation, sources: dict, hashes: dict, units: dict) -> bool:
    source = sources.get(c.source_id)
    unit = units.get(c.evidence_unit_id)
    # Verification of the record is attested by the exporter from the checked graph; the evidence unit only has to
    # exist for this source and cover the cited page. The cited box (a table cell or row) lies inside that page.
    if (
        not source
        or not unit
        or unit.get("source_id") != c.source_id
        or hashes.get(c.source_id) != c.source_sha256
    ):
        return False
    if not any(
        s.get("pdf_page") == c.pdf_page and s.get("source_sha256") == c.source_sha256
        for s in unit.get("spans", [])
    ):
        return False
    pdf = (root / source["path"]).resolve()
    if not pdf.is_relative_to((root / "data/raw/ocop").resolve()) or pdf.suffix.lower() != ".pdf":
        return False
    digest, pages = _pdf_facts(str(pdf), pdf.stat().st_mtime_ns)
    if digest != c.source_sha256 or not 1 <= c.pdf_page <= len(pages):
        return False
    box = fitz.Rect(c.bbox)
    return not box.is_empty and pages[c.pdf_page - 1].contains(box)


@lru_cache(maxsize=32)
def _pdf_facts(path: str, mtime_ns: int) -> tuple[str, tuple[fitz.Rect, ...]]:
    """SHA-256 and page rectangles of a locked PDF, computed once per file version rather than once per citation."""
    data = Path(path).read_bytes()
    with fitz.open(stream=data, filetype="pdf") as doc:
        return hashlib.sha256(data).hexdigest(), tuple(page.rect for page in doc)
