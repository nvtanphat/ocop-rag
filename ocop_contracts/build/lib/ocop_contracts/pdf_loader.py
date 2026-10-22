"""Source-locked, streaming read-only PDF access."""
from __future__ import annotations

from pathlib import Path

from ocop_contracts.registry import compare_lock, load_registry, snapshot
import json


def checked_sources(root: Path, registry_path: Path, lock_path: Path):
    sources = load_registry(registry_path)
    current = snapshot(root, sources)
    if not lock_path.is_file():
        raise FileNotFoundError(f"source lock missing: {lock_path}")
    compare_lock(current, json.loads(lock_path.read_text(encoding="utf-8")))
    return sources, current
