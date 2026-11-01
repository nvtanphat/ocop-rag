"""indexing runnable OCOP lookup: BM25 today, genuine RRF hybrid when dense built."""

from __future__ import annotations

import argparse
import json
import os
from collections import OrderedDict
from functools import lru_cache
from ai_core.system.telemetry import traced
from pathlib import Path
from ocop_contracts.ids import content_sha256
from ai_core.retrieval.ocop.models_config import (
    DEFAULT_RERANKER_MODEL,
    DEFAULT_RERANKER_REVISION,
    get_pair_token_budget,
    resolve_local_model_path,
)
from ai_core.retrieval.ocop.settings import get_settings
from ai_core.retrieval.ocop import model_runtime
from ai_core.retrieval.ocop.index_pipeline import (
    ROOT,
    BM25Search,
    _load_embedding,
    _encode,
    _records_hash,
    terms,
    _fold_vietnamese,
)


def _fit_query(model, query: str) -> tuple[str, dict]:
    """Count query tokens with the real tokenizer; never cut silently (the cut is explicit and reported)."""
    tokenizer = getattr(model, "tokenizer", None)
    limit = getattr(model, "max_seq_length", None)
    max_chars = get_settings().retrieval.query_max_chars
    meta = {"query_truncated": False}
    if len(query) > max_chars:
        query = query[:max_chars].rsplit(" ", 1)[0]
        meta["query_truncated"] = True
    if tokenizer is None or not callable(tokenizer) or not isinstance(limit, int):
        return query, meta

    def tokens(text: str) -> int:
        return len(tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"])

    meta["query_tokens"] = tokens(query)
    meta["query_token_limit"] = limit
    words = query.split()
    while meta["query_tokens"] > limit and len(words) > 1:
        words = words[: max(1, int(len(words) * 0.85))]
        query = " ".join(words)
        meta["query_truncated"] = True
        meta["query_tokens"] = tokens(query)
    return query, meta


def _dense_hits(
    query: str,
    manifest: dict,
    limit: int,
    *,
    source_id: str | None = None,
    include_needs_review: bool = True,
    evidence_unit_ids: set[str] | None = None,
) -> tuple[list[tuple[str, float]], dict]:
    dense = manifest.get("dense") or {}
    if not dense.get("enabled"):
        raise RuntimeError("Dense index not built. Run index-ocop -- --with-dense first")
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:
        raise RuntimeError("qdrant-client is required for dense/hybrid query") from exc
    with model_runtime.inference():
        with model_runtime.tensor_reader():
            model = _load_embedding(dense["model_id"], dense.get("revision"))
        query, meta = _fit_query(model, query)
        vector = _encode(model, [query], True)[0]
    if len(vector) != dense["dimension"]:
        raise RuntimeError("Embedding dimension mismatch")
    client = QdrantClient(host=dense["host"], port=dense["port"])
    from qdrant_client import models

    conditions = []
    if source_id:
        conditions.append(models.FieldCondition(key="source_id", match=models.MatchValue(value=source_id)))
    if evidence_unit_ids is not None:
        conditions.append(
            models.FieldCondition(
                key="evidence_unit_id", match=models.MatchAny(any=sorted(evidence_unit_ids))
            )
        )
    if not include_needs_review:
        conditions.append(
            models.FieldCondition(key="review_status", match=models.MatchValue(value="verified"))
        )
    if manifest.get("corpus_version"):
        conditions.append(
            models.FieldCondition(
                key="corpus_version", match=models.MatchValue(value=manifest["corpus_version"])
            )
        )
    query_filter = models.Filter(must=conditions) if conditions else None
    if hasattr(client, "query_points"):
        response = client.query_points(
            collection_name=dense["collection"],
            query=vector.tolist(),
            limit=limit,
            with_payload=True,
            query_filter=query_filter,
        )
        points = response.points
    else:
        points = client.search(
            collection_name=dense["collection"],
            query_vector=vector.tolist(),
            limit=limit,
            with_payload=True,
            query_filter=query_filter,
        )
    return [(p.payload["chunk_id"], float(p.score)) for p in points], meta


def rrf(ranks: list[list[str]], k: int | None = None, weights: list[float] | None = None) -> dict[str, float]:
    """Weighted reciprocal-rank fusion; k and the default weights come from configs/ocop_retrieval.yaml."""
    cfg = get_settings().retrieval
    k = cfg.rrf_k if k is None else k
    weights = weights or [1.0] * len(ranks)
    merged = {}
    for weight, lst in zip(weights, ranks, strict=True):
        for i, uid in enumerate(lst):
            merged[uid] = merged.get(uid, 0.0) + weight / (k + i + 1)
    return merged


@model_runtime.model_loader
@lru_cache(maxsize=1)
def _load_reranker(model_id: str, revision: str | None = None):
    os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
    os.environ.setdefault("USE_TF", "0")
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise RuntimeError("sentence-transformers required for --rerank") from exc
    resolved, is_local = resolve_local_model_path(model_id)
    # Avoid executing arbitrary Python from a remote repository. A revision
    # alone is not an approval to execute reviewed custom code.
    kwargs = {"device": "cpu", "trust_remote_code": False, "local_files_only": True}
    if revision and not is_local:
        kwargs["revision"] = revision
    return CrossEncoder(resolved, **kwargs)


def _check_index(index_dir: Path, manifest: dict, rows: list[dict], bm25: BM25Search) -> None:
    """Reject stale postings, altered content and mismatched release manifests."""
    data = bm25.data
    ids = [r.get("chunk_id") for r in rows]
    if not all(isinstance(cid, str) and cid for cid in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("Index mismatch: duplicate or invalid chunk IDs")
    if data.get("n") != len(rows) or data.get("corpus_hash") != content_sha256("\n".join(ids)):
        raise RuntimeError("Corpus/index mismatch: BM25 postings do not match chunk order")
    recorded = data.get("records_hash")
    if recorded is not None and recorded != _records_hash(rows):
        raise RuntimeError("Corpus/index mismatch: indexed chunk content or metadata modified")
    declared = manifest.get("bm25") or {}
    if declared.get("corpus_hash") not in (None, data["corpus_hash"]):
        raise RuntimeError("Corpus/index mismatch: manifest chunk hash")
    if declared.get("records_hash") not in (None, recorded):
        raise RuntimeError("Corpus/index mismatch: manifest records hash")
    if manifest.get("counts", {}).get("chunks", len(rows)) != len(rows):
        raise RuntimeError("Corpus/index mismatch: manifest row count")
    for row in rows:
        if row.get("corpus_version") != manifest.get("corpus_version"):
            raise RuntimeError("Corpus/index mismatch: chunk version does not match manifest")


def _read_checked_index(index_dir: Path) -> tuple[dict, list[dict], dict, BM25Search]:
    manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
    ordered = []
    chunks = {}
    with (index_dir / "chunks.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            ordered.append(row)
            chunks[row["chunk_id"]] = row
    bm25 = BM25Search(index_dir / "bm25.json.gz")
    _check_index(index_dir, manifest, ordered, bm25)
    return manifest, ordered, chunks, bm25


# Function words in question syntax should not dilute coverage of the content
# phrases. These are deliberately language-level stopwords, not OCOP terms.
_SCOPE_STOPWORDS = frozenset(
    _fold_vietnamese(token)
    for token in terms(
        "ai cái các có của để gì gồm không là mà mỗi nào như những phải sao thì "
        "và về với ở tại trong ngoài cần được này đó hôm nay tuần bên thế cùng "
        "một số hãy"
    )
)


def _scope_bigrams(text: str) -> frozenset[tuple[str, str]]:
    tokens = tuple(_fold_vietnamese(token) for token in terms(text))
    return frozenset(
        (left, right)
        for left, right in zip(tokens, tokens[1:])
        if left not in _SCOPE_STOPWORDS and right not in _SCOPE_STOPWORDS
    )


@lru_cache(maxsize=4)
def _indexed_scope_tokens(
    index_dir: str, signature: tuple[tuple[int, int], ...]
) -> tuple[tuple[str, ...], ...]:
    # Validate the BM25 postings, manifest and chunk content before using the
    # index to reopen a query that the deterministic scope gate rejected.
    _, ordered, _, _ = _read_checked_index(Path(index_dir))
    return tuple(
        tuple(_fold_vietnamese(token) for token in terms(row.get("text_for_bm25", ""))) for row in ordered
    )


def query_content_bigram_coverage(index_dir: Path, query: str) -> float | None:
    """Return max accent-folded content-bigram coverage in one checked chunk.

    A missing or invalid local index returns ``None`` so the caller keeps the
    normal fail-closed out-of-scope decision. At least two informative query
    bigrams are required to avoid reopening on a single generic phrase; a shorter query also returns ``None``
    (it cannot be measured), so a number always means "measured against the corpus".
    """
    index_dir = Path(index_dir).resolve()
    files = (index_dir / "manifest.json", index_dir / "chunks.jsonl", index_dir / "bm25.json.gz")
    try:
        signature = tuple((item.stat().st_mtime_ns, item.stat().st_size) for item in files)
    except OSError:
        return None
    query_bigrams = _scope_bigrams(query)
    if len(query_bigrams) < 2:
        return None  # too short to measure: a fragment, not evidence of being off-corpus
    try:
        corpus_tokens = _indexed_scope_tokens(str(index_dir), signature)
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError):
        return None
    best = 0.0
    for tokens in corpus_tokens:
        chunk_bigrams = _scope_bigrams_from_tokens(tokens)
        if not chunk_bigrams:
            continue
        best = max(best, len(query_bigrams & chunk_bigrams) / len(query_bigrams))
        if best >= 1.0:
            break
    return best


def _scope_bigrams_from_tokens(tokens: tuple[str, ...]) -> frozenset[tuple[str, str]]:
    return frozenset(
        (left, right)
        for left, right in zip(tokens, tokens[1:])
        if left not in _SCOPE_STOPWORDS and right not in _SCOPE_STOPWORDS
    )


_RERANK_CACHE: "OrderedDict[tuple,float]" = OrderedDict()


def _cached_scores(keys: list[tuple]) -> list[float | None]:
    return [_RERANK_CACHE.get(k) for k in keys]


def _remember(key: tuple, score: float, limit: int) -> None:
    if limit <= 0:
        return
    _RERANK_CACHE[key] = score
    _RERANK_CACHE.move_to_end(key)
    while len(_RERANK_CACHE) > limit:
        _RERANK_CACHE.popitem(last=False)


@model_runtime.inference()
def _rerank(
    query: str,
    candidates: list[dict],
    model_id: str,
    revision: str | None = None,
    pair_token_budget: int | None = None,
):
    """Cross-encode (query, passage) pairs on CPU within a fixed budget.

    Budgeting: at most `rerank_candidates` pairs (caller), `max_length`=pair budget so an oversized pair is cut
    by the tokenizer and *flagged* (never an error), batches of `rerank_batch_size`, torch threads from config,
    and an LRU score cache keyed by model/query/passage so repeated questions cost nothing.
    """
    cfg = get_settings().retrieval
    budget = pair_token_budget or get_pair_token_budget()
    reranker = _load_reranker(model_id, revision)
    reranker.max_length = budget
    keys = [(model_id, revision, budget, query, item.get("chunk_id"), hash(item["text"])) for item in candidates]
    scores = _cached_scores(keys)
    tokenizer = getattr(reranker, "tokenizer", None)
    if tokenizer is not None and callable(tokenizer):
        for row in candidates:
            if len(tokenizer(query, row["text"], add_special_tokens=True, truncation=False)["input_ids"]) > budget:
                row["rerank_input_truncated"] = True
            else:
                row.pop("rerank_input_truncated", None)
    todo = [i for i, score in enumerate(scores) if score is None]
    if todo:
        pairs = [(query, candidates[i]["text"]) for i in todo]
        fresh = reranker.predict(pairs, batch_size=cfg.rerank_batch_size, show_progress_bar=False)
        for i, score in zip(todo, fresh, strict=True):
            scores[i] = float(score)
            _remember(keys[i], scores[i], cfg.rerank_cache_entries)
    for row, score in zip(candidates, scores, strict=True):
        row["reranker_score"] = float(score)
        row["ranking_reason"] = "local_reranker"
    candidates.sort(key=lambda r: -r["reranker_score"])
    return candidates


_SENTENCE_END = (".", ";", ":", "!", "?")


def _with_following_chunks(
    results: list[dict],
    ordered: list[dict],
    chunks: dict,
    allowed,
    limit: int,
    mode: str,
    requested_mode: str,
) -> list[dict]:
    """Add the chunk that continues a top hit cut mid-sentence (sliding-window / parent-child expansion).

    The continuation is a real indexed chunk of the same evidence unit with its own spans and citation, placed right
    after the hit; nothing outside retrieved chunks is shown. Only the first `limit` hits are considered.
    """
    if limit <= 0:
        return results
    present = {r["chunk_id"] for r in results}
    by_unit: dict[str, list[dict]] = {}
    for ch in ordered:
        by_unit.setdefault(ch["evidence_unit_id"], []).append(ch)
    out = []
    for rank, row in enumerate(results):
        out.append(row)
        raw = str(row.get("raw_text") or "").rstrip()
        if (
            rank >= limit
            or not raw
            or raw.endswith(_SENTENCE_END)
            or row.get("char_end") is None
            or row.get("row_ids")
        ):
            continue
        following = [
            c
            for c in by_unit.get(row["evidence_unit_id"], [])
            if c.get("char_start") is not None
            and row["char_start"] < c["char_start"] <= row["char_end"]
            and c["chunk_id"] not in present
            and allowed(c["chunk_id"])
        ]
        if not following:
            continue
        ch = min(following, key=lambda c: c["char_start"])
        present.add(ch["chunk_id"])
        out.append(
            {
                "chunk_id": ch["chunk_id"],
                "evidence_unit_id": ch["evidence_unit_id"],
                "source_id": ch["source_id"],
                "pdf_page": ch["spans"][0]["pdf_page"],
                "source_spans": ch["spans"],
                "review_status": ch["review_status"],
                "corpus_version": ch["corpus_version"],
                "score": 0.0,
                "text": ch["text_for_bm25"],
                "raw_text": ch.get("raw_text", ch["text_for_bm25"]),
                "context": ch.get("context", {}),
                "row_ids": ch.get("row_ids", []),
                "table_headers": ch.get("table_headers", []),
                "char_start": ch.get("char_start"),
                "char_end": ch.get("char_end"),
                "over_budget": ch.get("over_budget", False),
                "retrieval_mode": mode,
                "requested_retrieval_mode": requested_mode,
                "continues_chunk": row["chunk_id"],
                "ranking_reason": "continuation_of_previous_hit",
            }
        )
    return out


@traced("ocop.retrieval.search")
def _title_seeds(query: str, ordered: list[dict], allowed) -> list[str]:
    """Passages whose own heading the question names ("hiệu lực thi hành"), best match first.

    The heading's title is the text after its label number ("Điều 3." / "Phụ lục II"); a passage is seeded when enough of
    the title's words appear in the question. Seeds are one more ranked list for fusion, never a final answer.
    """
    import re

    from ai_core.orchestration.ocop.language import fold

    settings = get_settings().retrieval
    if settings.title_seed_max < 1:
        return []
    asked = set(re.findall(r"[a-z0-9]+", fold(query)))
    scored = []
    for chunk in ordered:
        heading = (chunk.get("context") or {}).get("legal_heading")
        if not heading or not allowed(chunk["chunk_id"]):
            continue
        match = re.match(r"^\D*?(?:\d+[a-z]?|[IVXLC]+)\b[.:)]?\s*(?P<title>\S.*)$", str(heading).strip())
        title = match["title"] if match else _title_line_after(chunk, str(heading))
        words = {w for w in re.findall(r"[a-z0-9]+", fold(title)) if not w.isdigit()}
        if len(words) < 2:
            continue
        share = len(words & asked) / len(words)
        if share >= settings.title_seed_min_share:
            scored.append((-share, -len(words), chunk["chunk_id"]))
    return [cid for _, _, cid in sorted(scored)[: settings.title_seed_max]]


def _title_line_after(chunk: dict, heading: str) -> str:
    """The name of a heading that is only a label ("Phụ lục III"): the next non-empty line of the passage."""
    lines = [line.strip() for line in str(chunk.get("raw_text") or "").splitlines()]
    if heading.strip() not in lines:
        return ""
    after = lines[lines.index(heading.strip()) + 1:]
    return next((line for line in after if line), "")[:200]


def search(
    index_dir: Path,
    query: str,
    *,
    mode: str = "sparse",
    top_k: int = 8,
    source_id: str | None = None,
    include_needs_review: bool = True,
    rerank: bool = False,
    reranker_model: str = DEFAULT_RERANKER_MODEL,
    reranker_revision: str | None = DEFAULT_RERANKER_REVISION,
    expand_parent: bool = False,
    parent_max_chars: int = 2400,
    rerank_candidates: int | None = None,
    pair_token_budget: int | None = None,
    evidence_unit_ids: set[str] | None = None,
    with_continuations: bool = False,
) -> list[dict]:
    if mode not in ("sparse", "hybrid", "dense"):
        raise ValueError("mode must be sparse, dense or hybrid")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    settings = get_settings().retrieval
    rerank_candidates = settings.rerank_candidates if rerank_candidates is None else rerank_candidates
    if rerank_candidates < 1 or rerank_candidates > 200:
        raise ValueError("rerank_candidates must be between 1 and 200")
    if expand_parent and parent_max_chars < 100:
        raise ValueError("parent_max_chars must be >=100")
    manifest, ordered, chunks, bm25 = _read_checked_index(index_dir)
    requested_mode = mode
    fallback_reason = None
    if mode != "sparse" and not manifest.get("dense", {}).get("enabled"):
        mode = "sparse"
        fallback_reason = "dense_not_built"

    def allowed(cid):
        return (
            (source_id is None or chunks[cid]["source_id"] == source_id)
            and (evidence_unit_ids is None or chunks[cid]["evidence_unit_id"] in evidence_unit_ids)
            and (include_needs_review or chunks[cid]["review_status"] == "verified")
        )

    # Determine admissible postings before scoring/ranking; top-K oversampling
    # cannot guarantee that a rare target document survives global ranking.
    allowed_positions = {i for i, ch in enumerate(ordered) if allowed(ch["chunk_id"])}
    if not allowed_positions:
        return []
    pool_size = max(top_k, rerank_candidates if rerank else top_k)
    pool_floor = max(settings.candidate_pool_min, pool_size * 2)
    sparse = []
    sparse_scores = {}
    dense_meta = {}
    if mode in ("sparse", "hybrid"):
        for pos, score in bm25.search(query, top_k=pool_floor, allowed_docs=allowed_positions):
            cid = ordered[pos]["chunk_id"]
            if allowed(cid):
                sparse.append(cid)
                sparse_scores[cid] = score
    dense = []
    dense_scores = {}
    if mode in ("dense", "hybrid"):
        scope = {"evidence_unit_ids": evidence_unit_ids} if evidence_unit_ids is not None else {}
        try:
            hits, dense_meta = _dense_hits(
                query,
                manifest,
                pool_floor,
                source_id=source_id,
                include_needs_review=include_needs_review,
                **scope,
            )
            for cid, score in hits:
                if cid in chunks and allowed(cid):
                    dense.append(cid)
                    dense_scores[cid] = score
        except (
            Exception
        ) as exc:  # any model/backend failure degrades to sparse with a visible reason (RET-01)
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            mode = "sparse"
            fallback_reason = "dense_unavailable:" + type(exc).__name__
            if not sparse:
                for pos, score in bm25.search(query, top_k=pool_floor, allowed_docs=allowed_positions):
                    cid = ordered[pos]["chunk_id"]
                    sparse.append(cid)
                    sparse_scores[cid] = score
    lists, weights = (
        ([sparse, dense], [settings.rrf_weight_sparse, settings.rrf_weight_dense]) if mode == "hybrid"
        else ([sparse], [1.0]) if mode == "sparse" else ([dense], [1.0])
    )
    seeds = _title_seeds(query, ordered, allowed)
    if seeds:
        lists, weights = [*lists, seeds], [*weights, settings.rrf_weight_title]
    fused = rrf(lists, weights=weights) if len(lists) > 1 else (dict(sparse_scores) if mode == "sparse" else dense_scores)
    items = sorted(fused.items(), key=lambda x: (-x[1], x[0]))[:pool_size]

    def make_row(cid, score):
        ch = chunks[cid]
        row = {
            "chunk_id": cid,
            "evidence_unit_id": ch["evidence_unit_id"],
            "source_id": ch["source_id"],
            "pdf_page": ch["spans"][0]["pdf_page"],
            "source_spans": ch["spans"],
            "review_status": ch["review_status"],
            "corpus_version": ch["corpus_version"],
            "score": round(float(score), 6),
            "text": ch["text_for_bm25"],
            "raw_text": ch.get("raw_text", ch["text_for_bm25"]),
            "context": ch.get("context", {}),
            "row_ids": ch.get("row_ids", []),
            "table_headers": ch.get("table_headers", []),
            "char_start": ch.get("char_start"),
            "char_end": ch.get("char_end"),
            "over_budget": ch.get("over_budget", False),
        }
        row["retrieval_mode"] = mode
        row["requested_retrieval_mode"] = requested_mode
        if fallback_reason:
            row["retrieval_fallback_reason"] = fallback_reason
        row.update(dense_meta)
        return row

    results = [make_row(cid, score) for cid, score in items]
    if rerank and results and settings.rerank_skip_on_agreement and sparse and dense and sparse[0] == dense[0]:
        for row in results:
            row["ranking_reason"] = "deterministic_" + mode + "_order; reranker_skipped_first_stage_agrees"
        rerank = False
    if rerank and results:
        try:
            first_stage = [row["chunk_id"] for row in results[:rerank_candidates]]
            head = _rerank(
                query,
                results[:rerank_candidates],
                reranker_model,
                reranker_revision,
                pair_token_budget=pair_token_budget,
            )
            if settings.rerank_first_stage_weight > 0:
                # The cross-encoder promotes what it is given but must not veto strong first-stage evidence: merge the two
                # orders (it re-scored `head` in its own order, best first).
                merged = rrf(
                    [first_stage, [row["chunk_id"] for row in head]],
                    weights=[settings.rerank_first_stage_weight, 1.0],
                )
                head.sort(key=lambda row: (-merged[row["chunk_id"]], row["chunk_id"]))
            results = head + results[rerank_candidates:]
        except Exception as exc:  # the reranker is optional: report why and keep the deterministic order
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            reason = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            for row in results:
                row["rerank_unavailable"] = True
                row["ranking_reason"] = f"rerank_unavailable: {reason}; deterministic_{mode}_order"
    for row in results:
        row.setdefault(
            "ranking_reason",
            "local_reranker"
            if "reranker_score" in row
            else "deterministic_" + mode + "_order; reranker_not_requested",
        )
    results = results[:top_k]
    results = _with_following_chunks(
        results,
        ordered,
        chunks,
        allowed,
        settings.neighbor_chunks if with_continuations else 0,
        mode,
        requested_mode,
    )
    if expand_parent and results:
        wanted = {r["evidence_unit_id"] for r in results}
        parents = {}
        path = index_dir / "evidence_units.jsonl"
        if path.is_file():
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    unit = json.loads(line)
                    if unit["unit_id"] in wanted:
                        parents[unit["unit_id"]] = unit
        for row in results:
            unit = parents.get(row["evidence_unit_id"])
            if not unit or unit.get("source_id") != row["source_id"]:
                continue  # never cross sources on parent expansion
            if not include_needs_review and unit.get("review_status") != "verified":
                continue
            source = unit.get("text") or ""
            if len(source) > parent_max_chars:
                start = row.get("char_start")
                end = row.get("char_end")
                if start is not None and end is not None:
                    left = max(
                        0, min(len(source) - parent_max_chars, (start + end) // 2 - parent_max_chars // 2)
                    )
                else:
                    left = 0
                context = source[left : left + parent_max_chars]
            else:
                context = source
            row["parent_context"] = context
            row["parent_evidence_unit_id"] = unit["unit_id"]
            row["parent_source_spans"] = unit.get("spans", [])
    return results


def main():
    ap = argparse.ArgumentParser(description="indexing: search indexed OCOP evidence")
    ap.add_argument("query")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--index", type=Path, default=Path("data/processed/ocop/index"))
    ap.add_argument("--mode", choices=("sparse", "dense", "hybrid"), default="sparse")
    ap.add_argument("--top-k", type=int, default=8)
    ap.add_argument("--expand-parent", action="store_true")
    ap.add_argument("--parent-max-chars", type=int, default=2400)
    ap.add_argument("--source-id")
    ap.add_argument("--verified-only", action="store_true")
    ap.add_argument("--rerank", action="store_true")
    ap.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    ap.add_argument("--reranker-revision", default=DEFAULT_RERANKER_REVISION)
    ap.add_argument("--rerank-candidates", type=int, default=40)
    ap.add_argument("--pair-token-budget", type=int, default=None)
    args = ap.parse_args()
    root = args.root.resolve()
    out = search(
        args.index if args.index.is_absolute() else root / args.index,
        args.query,
        mode=args.mode,
        top_k=args.top_k,
        source_id=args.source_id,
        include_needs_review=not args.verified_only,
        rerank=args.rerank,
        reranker_model=args.reranker_model,
        reranker_revision=args.reranker_revision,
        rerank_candidates=args.rerank_candidates,
        pair_token_budget=args.pair_token_budget,
        expand_parent=args.expand_parent,
        parent_max_chars=args.parent_max_chars,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
