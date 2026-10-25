"""Retrieval/context parameters from configs/ocop_retrieval.yaml (defaults documented in docs/CONFIGURATION.md)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

_ROOT = Path(__file__).resolve().parents[3]


class ContextSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    prompt_token_budget: int = Field(5200, ge=512)
    output_reserve_tokens: int = Field(1024, ge=128)
    excerpt_max_chars: int = Field(1500, ge=200)
    table_excerpt_max_chars: int = Field(5000, ge=200)
    parent_chain_max_tokens: int = Field(40, ge=0)
    parent_label_max_chars: int = Field(90, ge=20)
    min_term_coverage: float = Field(0.25, ge=0, le=1)
    max_source_blocks: int = Field(12, ge=1)
    grounding_min_term_coverage: float = Field(0.8, ge=0, le=1)


class RetrievalSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    top_k: int = Field(8, ge=1)
    candidate_pool_min: int = Field(40, ge=1)
    rrf_k: int = Field(60, ge=1)
    rrf_weight_sparse: float = Field(1.0, gt=0)
    rrf_weight_dense: float = Field(1.0, gt=0)
    rerank_candidates: int = Field(12, ge=1, le=200)
    rerank_batch_size: int = Field(4, ge=1)
    rerank_threads: int = Field(6, ge=1)
    rerank_cache_entries: int = Field(512, ge=0)
    query_max_chars: int = Field(1500, ge=50)
    neighbor_chunks: int = Field(2, ge=0, le=8)


class AgentSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    max_tool_calls: int = Field(5, ge=1, le=8)
    grader_min_relevance: float = Field(0.13, ge=0, le=1)
    scope_min_bigram_coverage: float = Field(0.60, ge=0, le=1)
    graph_hops: int = Field(2, ge=1, le=4)
    graph_node_limit: int = Field(75, ge=1)
    graph_max_facts: int = Field(32, ge=1)
    memory_evidence_reuse: bool = True  # follow-ups re-read evidence the conversation already cited


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: int = 1
    context: ContextSettings = ContextSettings()
    retrieval: RetrievalSettings = RetrievalSettings()
    agent: AgentSettings = AgentSettings()


@lru_cache(maxsize=4)
def _load(path: str, mtime: int) -> Settings:
    return Settings.model_validate(yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {})


def get_settings(root: Path | None = None) -> Settings:
    base = Path(root).resolve() if root else _ROOT
    for parent in [base, *base.parents, _ROOT]:
        candidate = parent / 'configs' / 'ocop_retrieval.yaml'
        if candidate.is_file():
            return _load(str(candidate), candidate.stat().st_mtime_ns)
    return Settings()
