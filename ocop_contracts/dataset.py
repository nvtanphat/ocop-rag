"""Fail-closed reader for the durable OCR → RAG dataset boundary."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil

from .models import PageArtifact
from .registry import sha256_file

SCHEMA_VERSION = 1
DEFAULT_DATASET = Path(os.environ.get("OCOP_OCR_DATASET", "data/ocr-dataset"))


def digest_json(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def dataset_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"dataset path escapes root: {relative}")
    return path


def read_dataset(root: Path, locked: dict, *, require_complete: bool = True) -> tuple[dict, list[dict]]:
    """Validate manifest, exact page inventory, source hashes and artifact digests."""
    if (root / ".pending-import.json").exists():
        raise ValueError("OCR import interrupted; run OCR import again to recover before reading")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported OCR dataset schema_version")
    if require_complete and manifest.get("complete") is not True:
        raise ValueError("OCR dataset is not complete")
    if locked.get("aggregate_sha256") and manifest.get("input_snapshot_sha256") != locked["aggregate_sha256"]:
        raise ValueError("OCR dataset source snapshot differs from approved lock")
    approved = {s["source_id"]: s["sha256"] for s in locked["sources"]}
    seen_sources = set()
    seen_pages = set()
    pages = []
    for source in manifest["sources"]:
        sid = source["source_id"]
        if sid in seen_sources or approved.get(sid) != source["source_sha256"]:
            raise ValueError(f"OCR dataset source SHA/identity mismatch: {sid}")
        seen_sources.add(sid)
        path = dataset_file(root, source["artifact"])
        if sha256_file(path) != source["artifact_sha256"]:
            raise ValueError(f"OCR artifact digest mismatch: {path}")
        source_pages = []
        for line in path.read_text(encoding="utf-8").splitlines():
            page = json.loads(line)
            PageArtifact.model_validate({k: v for k, v in page.items() if k in PageArtifact.model_fields})
            key = (sid, page["pdf_page"])
            if (
                page["source_id"] != sid
                or page.get("source_sha256") != approved[sid]
                or key in seen_pages
                or page.get("quarantined")
            ):
                raise ValueError(f"invalid OCR page provenance: {key}")
            seen_pages.add(key)
            source_pages.append(page["pdf_page"])
            pages.append(page)
        if source_pages != source["pages"]:
            raise ValueError(f"OCR page inventory mismatch: {sid}")
        if require_complete and source_pages != list(range(1, source["page_count_expected"] + 1)):
            raise ValueError(f"OCR dataset missing pages: {sid}")
    if require_complete and seen_sources != set(approved):
        raise ValueError("OCR dataset missing approved sources")
    corrections = dataset_file(root, "review/corrections.jsonl")
    actual = sha256_file(corrections) if corrections.is_file() else hashlib.sha256(b"").hexdigest()
    if actual != manifest["corrections_sha256"]:
        raise ValueError("OCR corrections digest mismatch")
    expected = manifest.get("dataset_digest")
    if expected != digest_json({k: v for k, v in manifest.items() if k != "dataset_digest"}):
        raise ValueError("OCR dataset manifest digest mismatch")
    return manifest, pages


def materialize_dataset(root: Path, destination: Path, manifest: dict) -> dict:
    """Copy only validated page artifacts and manifest, never review images."""
    destination.mkdir(parents=True, exist_ok=True)
    for source in manifest["sources"]:
        origin = dataset_file(root, source["artifact"])
        target = dataset_file(destination, source["artifact"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, target)
        if sha256_file(target) != source["artifact_sha256"]:
            raise ValueError("OCR dataset changed while copying")
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest
