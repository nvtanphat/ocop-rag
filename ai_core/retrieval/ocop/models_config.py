"""OCOP local model configuration and token budgets.

Loads declarative limits and pinned model identifiers from configs/ocop_models.yaml.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_TARGET_CHUNK_TOKENS = 512
DEFAULT_MODEL_MAX_TOKENS = 2048
DEFAULT_PAIR_TOKEN_BUDGET = 1024

DEFAULT_EMBEDDING_MODEL = "google/embeddinggemma-300m"
DEFAULT_EMBEDDING_REVISION = "57c266a740f537b4dc058e1b0cda161fd15afa75"

DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
DEFAULT_RERANKER_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"


def load_models_config(root: Path | None = None) -> dict[str, Any]:
    base = Path(root).resolve() if root else _ROOT
    candidates = [
        base / "configs" / "ocop_models.yaml",
        _ROOT / "configs" / "ocop_models.yaml",
    ]
    for parent in [base, *base.parents]:
        candidates.append(parent / "configs" / "ocop_models.yaml")
    for cfg in candidates:
        if cfg.is_file():
            try:
                return yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            except Exception:
                return {}
    return {}


def get_model_max_tokens(root: Path | None = None) -> int:
    cfg = load_models_config(root)
    val = cfg.get("embedding", {}).get("model_max_tokens")
    if isinstance(val, int) and val > 0:
        return val
    return DEFAULT_MODEL_MAX_TOKENS


def get_pair_token_budget(root: Path | None = None) -> int:
    cfg = load_models_config(root)
    val = cfg.get("reranker", {}).get("pair_token_budget")
    if isinstance(val, int) and val > 0:
        return val
    return DEFAULT_PAIR_TOKEN_BUDGET


def resolve_local_model_path(model_id: str, root: Path | None = None) -> tuple[str, bool]:
    """Resolve model_id to local directory if downloaded locally, returning (path_or_id, is_local_dir)."""
    p = Path(model_id)
    if p.is_dir():
        return str(p), True
    short_name = model_id.split("/")[-1]
    candidates = [
        Path("D:/AgentAI/OCOP-RAG/models") / short_name,
        Path("D:/AgentAI/OCOP-RAG/models") / model_id,
        Path(os.environ.get("OCOP_MODELS_DIR", "")) / short_name,
    ]
    if root:
        candidates.append(Path(root) / "models" / short_name)
    for c in candidates:
        if c.is_dir():
            return str(c), True
    return model_id, False
