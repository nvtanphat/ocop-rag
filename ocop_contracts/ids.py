"""Stable, domain-scoped identifiers for OCOP evidence and index artifacts.

Identity does not depend on model output or database sequence counters. The
stable logical path is kept separate from the exact content fingerprint so a
source revision can be detected without silently merging two corpus versions.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from pathlib import Path


def stable_id(kind: str, source_id: str, path: Sequence[str | int], *, revision: str = "") -> str:
    """Return a deterministic identifier for one source-owned logical unit.

    ``revision`` is an explicit parser/corpus revision, not the current date.
    If the referenced content is versioned, include that version in ``revision``.
    """
    if not kind or not source_id or not path:
        raise ValueError("kind, source_id and path are required")
    if any(str(part).strip() == "" for part in path):
        raise ValueError("empty path component")
    payload = json.dumps(
        [kind, source_id, [str(part) for part in path], revision],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"ocop:{kind}:{hashlib.sha256(payload).hexdigest()[:24]}"


def code_fingerprint(kind: str, files: Iterable[Path]) -> str:
    """Identify a pipeline stage by the source code that produces its output.

    Replaces hand-written version labels: any change to these files yields a new identifier, so caches
    and lineage checks follow the code without anyone remembering to bump a label. Line endings are
    normalized so a CRLF checkout fingerprints the same as an LF one.
    """
    digest = hashlib.sha256()
    for path in sorted(Path(p) for p in files):
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return f"ocop-{kind}-{digest.hexdigest()[:12]}"


def content_sha256(content: str | bytes) -> str:
    """Fingerprint the exact canonical unit body, independently of its ID."""
    value = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(value).hexdigest()
