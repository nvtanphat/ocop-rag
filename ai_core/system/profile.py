"""Deployment retrieval profile: which retrieval modes a running instance promises to serve.

``sparse`` serves BM25 only. ``hybrid`` additionally requires the dense dependencies, a built dense index
and a reachable Qdrant; any gap makes the instance not ready instead of silently degrading to BM25.
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
from pathlib import Path
from typing import Mapping

PROFILES = ("sparse", "hybrid")
HYBRID_MODULES = ("sentence_transformers", "qdrant_client")
CONNECT_TIMEOUT_S = 0.5


def configured_profile(env: Mapping[str, str] | None = None) -> str:
    value = (env if env is not None else os.environ).get("OCOP_RETRIEVAL_PROFILE", "sparse").strip().lower()
    if value not in PROFILES:
        raise ValueError(f"OCOP_RETRIEVAL_PROFILE must be one of {PROFILES}, got {value!r}")
    return value


def profile_status(root: Path, env: Mapping[str, str] | None = None) -> dict:
    """{profile, ready, missing[]} - ``missing`` names every unmet requirement of the profile."""
    profile = configured_profile(env)
    missing: list[str] = []
    if profile == "hybrid":
        missing += [f"dependency:{m}" for m in HYBRID_MODULES if importlib.util.find_spec(m) is None]
        manifest_path = Path(root) / "data" / "processed" / "ocop" / "index" / "manifest.json"
        try:
            dense = json.loads(manifest_path.read_text(encoding="utf-8")).get("dense") or {}
        except (OSError, ValueError):
            dense = {}
        if not dense.get("enabled"):
            missing.append("dense_index_not_built")
        else:
            try:
                socket.create_connection((dense["host"], int(dense["port"])), CONNECT_TIMEOUT_S).close()
            except (OSError, KeyError, ValueError):
                missing.append("qdrant_unreachable")
    return {"profile": profile, "ready": not missing, "missing": missing}
