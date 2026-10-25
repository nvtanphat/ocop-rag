"""Public, corpus-bound verified reference records. Never exports arbitrary fields."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import fitz
from pydantic import BaseModel, Field, ValidationError

from ocop_contracts.models import SourceSpan


class ReferenceCitation(SourceSpan):
    source_id: str
    evidence_unit_id: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bbox: tuple[float, float, float, float]


class ReferenceItem(BaseModel):
    id: str
    label: str
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
    version = json.loads(manifest.read_text(encoding="utf-8")).get("corpus_version") if manifest.is_file() else None
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
        if (record.get("review_status") not in {"verified", "human_verified"}
                or record.get("visibility") != "public" or record.get("corpus_version") != version
                or any(record.get(k) for k in ("tenant_id", "dossier_id", "private"))):
            continue
        try:
            item = ReferenceItem.model_validate(record)
            if all(_matches(root, c, sources, hashes, units) for c in item.citations):
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
    if not source or not unit or unit.get("source_id") != c.source_id or hashes.get(c.source_id) != c.source_sha256:
        return False
    if not any(s.get("pdf_page") == c.pdf_page and s.get("source_sha256") == c.source_sha256
               and s.get("bbox") == list(c.bbox) for s in unit.get("spans", [])):
        return False
    pdf = (root / source["path"]).resolve()
    if not pdf.is_relative_to((root / "data/raw/ocop").resolve()) or pdf.suffix.lower() != ".pdf":
        return False
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != c.source_sha256:
        return False
    with fitz.open(pdf) as doc:
        if not 1 <= c.pdf_page <= len(doc):
            return False
        box = fitz.Rect(c.bbox)
        return not box.is_empty and doc[c.pdf_page - 1].rect.contains(box)
