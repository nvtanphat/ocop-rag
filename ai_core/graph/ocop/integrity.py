"""Verify a completed graph snapshot before traversal or publication."""
from __future__ import annotations
import json
from pathlib import Path
from ocop_contracts.ids import content_sha256


def validate_graph_snapshot(path: Path, *, allow_legacy: bool = False,
                            allow_partial: bool = False) -> dict:
    manifest_file = path / "manifest.json"
    if not manifest_file.is_file():
        if allow_legacy:
            return {"status": "legacy_unverified"}
        raise ValueError("graph manifest missing")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    status=manifest.get("status")
    if status!="local_ready" and not (allow_partial and status=="partial_debug_not_production"
                                      and manifest.get("source_complete") is False):
        raise ValueError("graph snapshot is not ready")
    expected = manifest.get("file_sha256")
    if not isinstance(expected, dict) or not expected:
        if allow_legacy:
            return manifest
        raise ValueError("graph snapshot lacks integrity hashes")
    required = ('nodes.jsonl', 'edges.jsonl')
    for filename in required:
        actual_file = path / filename
        if not actual_file.is_file() or content_sha256(actual_file.read_bytes()) != expected.get(filename):
            raise ValueError(f"graph snapshot integrity mismatch: {filename}")
    return manifest
