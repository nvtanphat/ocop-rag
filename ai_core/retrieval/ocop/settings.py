"""Retrieval/context parameters from configs/ocop_retrieval.yaml (defaults documented in docs/CONFIGURATION.md)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

_ROOT = Path(__file__).resolve().parents[3]


class ContextSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_token_budget: int = Field(5200, ge=512)
    output_reserve_tokens: int = Field(1024, ge=128)
    excerpt_max_chars: int = Field(1500, ge=200)
    table_excerpt_max_chars: int = Field(5000, ge=200)
    parent_chain_max_tokens: int = Field(40, ge=0)
    parent_label_max_chars: int = Field(90, ge=20)
    min_term_coverage: float = Field(0.25, ge=0, le=1)
    max_source_blocks: int = Field(12, ge=1)
    max_table_siblings: int = Field(3, ge=0)
    max_link_blocks: int = Field(3, ge=0)
    max_enrichment_blocks: int = Field(3, ge=0)
    max_blocks_per_document: int = Field(3, ge=1)
    grounding_min_term_coverage: float = Field(0.8, ge=0, le=1)
    min_quote_chars: int = Field(15, ge=5)  # a quote shorter than this proves nothing about the claim it backs
    max_quote_parts: int = Field(4, ge=1, le=8)  # lines of one quote: one passage per cited source of a comparison


class RetrievalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top_k: int = Field(8, ge=1)
    max_hits_per_document: int = Field(3, ge=1)
    part_new_pages: int = Field(4, ge=1)
    candidate_pool_min: int = Field(40, ge=1)
    rrf_k: int = Field(60, ge=1)
    rrf_weight_sparse: float = Field(1.0, gt=0)
    rrf_weight_dense: float = Field(1.0, gt=0)
    rrf_weight_title: float = Field(1.0, gt=0)
    rrf_tool_weights: dict[str, float] = Field(default_factory=dict)
    title_seed_min_share: float = Field(0.5, gt=0, le=1)
    title_seed_max: int = Field(3, ge=0)
    rerank_candidates: int = Field(12, ge=1, le=200)
    # Weight of the first-stage rank when the cross-encoder's order is merged with it (reciprocal-rank fusion); 0 = the
    # cross-encoder alone decides the order of the candidates it re-scored.
    rerank_first_stage_weight: float = Field(0.0, ge=0)
    # The cross-encoder is skipped when sparse and dense retrieval put the same chunk first and no other candidate is
    # ranked near the top of both: it re-scores what the first stage already agrees on, at ~0.7 s per candidate on CPU.
    rerank_skip_on_agreement: bool = False
    rerank_batch_size: int = Field(4, ge=1)
    rerank_threads: int = Field(6, ge=1)
    tensor_reader_backend: Literal["auto", "mmap", "pread"] = "auto"
    rerank_cache_entries: int = Field(512, ge=0)
    query_max_chars: int = Field(1500, ge=50)
    neighbor_chunks: int = Field(2, ge=0, le=8)


class AgentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    graph_definition_max_words: int = Field(12, ge=1)
    max_tool_calls: int = Field(5, ge=1, le=8)
    lookup_max_rows: int = Field(15, ge=1)
    compound_pair_min_share: float = Field(0.01, ge=0, le=1)
    link_word_max_share: float = Field(0.05, ge=0, le=1)
    grader_min_relevance: float = Field(0.13, ge=0, le=1)
    scope_min_bigram_coverage: float = Field(0.60, ge=0, le=1)
    part_min_coverage: float = Field(0.34, ge=0, le=1)  # share of a question part's words one evidence row must hold
    source_agreement_share: float = Field(0.60, ge=0, le=1)  # share of earlier rows from one source to pin that source
    rule_confident_score: int = Field(60, ge=0, le=100)  # router: a rule scoring below this is a weak guess the embeddings may overrule
    semantic_min_score: float = Field(0.55, ge=0, le=1)  # router: closest example of an intent must be at least this similar
    semantic_min_margin: float = Field(0.03, ge=0, le=1)  # router: and lead the best example of any other intent by this much
    graph_hops: int = Field(2, ge=1, le=4)
    graph_node_limit: int = Field(75, ge=1)
    graph_max_facts: int = Field(32, ge=1)
    graph_entry_nodes: int = Field(8, ge=1)
    graph_document_seed_nodes: int = Field(1, ge=0)
    graph_pagerank: bool = True
    graph_pagerank_damping: float = Field(0.85, gt=0, lt=1)
    graph_pagerank_iterations: int = Field(30, ge=1, le=200)
    graph_pagerank_tolerance: float = Field(0.000001, gt=0)
    graph_secondary: bool = True
    graph_facts_per_relation: int = Field(5, ge=1)
    memory_evidence_reuse: bool = True  # follow-ups re-read evidence the conversation already cited


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    context: ContextSettings = ContextSettings()
    retrieval: RetrievalSettings = RetrievalSettings()
    agent: AgentSettings = AgentSettings()


@lru_cache(maxsize=4)
def _load(path: str, mtime: int) -> Settings:
    return Settings.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})


def get_settings(root: Path | None = None) -> Settings:
    base = Path(root).resolve() if root else _ROOT
    for parent in [base, *base.parents, _ROOT]:
        candidate = parent / "configs" / "ocop_retrieval.yaml"
        if candidate.is_file():
            return _load(str(candidate), candidate.stat().st_mtime_ns)
    return Settings()
