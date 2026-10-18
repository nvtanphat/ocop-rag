"""Reviewed source registry — do not infer legal effects from filenames."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ai_core.domain.ocop_models import SourceDocument
def sha256_file(path: Path) -> str:
    """SHA-256 of the original OCOP PDF bytes, read without altering source files."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_registry(path: Path) -> list[SourceDocument]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported OCOP source registry schema")
    result = [SourceDocument.model_validate(record) for record in payload["sources"]]
    ids = [s.source_id.casefold() for s in result]
    paths = [s.path.casefold() for s in result]
    if len(set(ids)) != len(ids) or len(set(paths)) != len(paths):
        raise ValueError("duplicate source ID or path")
    return result


def snapshot(root: Path, sources: list[SourceDocument]) -> dict:
    items = []
    root = root.resolve()
    for source in sources:
        file = (root / source.path).resolve()
        if not file.is_relative_to(root):
            raise ValueError("source path escapes project root")
        if not file.is_file():
            raise FileNotFoundError(f"missing approved source: {source.path}")
        digest = sha256_file(file)
        if source.file_sha256 is not None and source.file_sha256 != digest:
            raise ValueError(f"approved hash mismatch: {source.source_id}")
        items.append({
            "source_id": source.source_id,
            "path": source.path,
            "bytes": file.stat().st_size,
            "sha256": digest,
        })
    # Fail closed on extra PDFs. Otherwise adding a source to raw/ without
    # registering it looks like a successful full-corpus audit but silently
    # leaves that source out of the knowledge base.
    raw_root = root / "data" / "raw" / "ocop"
    if raw_root.is_dir():
        listed = {item["path"].casefold() for item in items}
        discovered = {
            p.relative_to(root).as_posix().casefold()
            for p in raw_root.rglob("*")
            if p.is_file() and p.suffix.casefold() == ".pdf"
        }
        unexpected = discovered - listed
        if unexpected:
            raise ValueError(f"unregistered OCOP PDF(s): {sorted(unexpected)}")

    items.sort(key=lambda item: item["source_id"])
    aggregate = hashlib.sha256()
    for item in items:
        aggregate.update(json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        aggregate.update(b"\n")
    return {"schema_version": 1, "algorithm": "sha256", "aggregate_sha256": aggregate.hexdigest(), "sources": items}


def compare_lock(current: dict, locked: dict) -> None:
    if current != locked:
        raise RuntimeError("OCOP dataset snapshot differs from approved lock; run explicit lock-ocop after source review")
