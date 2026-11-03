"""indexing: Evidence -> parent-child chunks + BM25 and optional Qdrant dense vectors.

Always builds a usable BM25 index from the evidence extraction evidence. Dense indexing is
opt-in and requires the REAL configured embedding model; never substitute fake
vectors or report a hybrid index where only lexical search was built.
"""

from __future__ import annotations
from functools import lru_cache

import argparse
import gzip
import io
import hashlib
import json
import math
import os
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from ocop_contracts.ids import code_fingerprint, stable_id, content_sha256
from ocop_contracts.models import RetrievalChunk
from ai_core.retrieval.ocop.models_config import (
    DEFAULT_TARGET_CHUNK_TOKENS,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_REVISION,
    get_model_max_tokens,
    load_models_config,
    resolve_local_model_path,
)

ROOT = Path(__file__).resolve().parents[3]
# The chunker and index builder code identify the index format.
INDEX_VERSION = code_fingerprint(
    "retrieval",
    [
        Path(__file__).resolve().parent / name
        for name in ("index_pipeline.py", "structure_chunker.py", "graph_context.py")
    ],
)
WORD_RE = re.compile(r"[^\W_]+(?:[_-][^\W_]+)*", flags=re.UNICODE)


def terms(text: str) -> list[str]:
    return WORD_RE.findall(unicodedata.normalize("NFC", text).casefold())


def _identifier_terms(text: str) -> list[str]:
    folded = _fold_vietnamese(unicodedata.normalize("NFC", text).casefold())
    result = ["__criterion__" + m for m in re.findall(r"(?<![\d.])(\d{1,2}\.\d{1,2})(?!\d)", folded)]
    result += [
        "__criterion__" + a + "." + b for a, b in re.findall(r"(?m)^\s*(\d{1,2}),(\d{1,2})(?!\d)", folded)
    ]
    result += ["__form__" + str(int(m)) for m in re.findall(r"\bmau\s*(?:so\s*)?(\d{1,2})\b", folded)]
    result += ["__document__" + m for m in re.findall(r"\b(?:qd\s*|quyet dinh\s+(?:so\s+)?)(\d+)", folded)]
    result += ["__document__" + number for number in re.findall(r"\b(\d+)/\d{4}/qd\b", folded)]
    result += [
        "__document_version__" + number + "_" + year
        for number, year in re.findall(r"\b(?:qd\s*)?(\d+)/(\d{4})(?:/qd\b)?", folded)
    ]
    return result


def _fold_vietnamese(token: str) -> str:
    """Conservative accent-folded parallel lexical field; original terms survive."""
    plain = "".join(c for c in unicodedata.normalize("NFD", token) if unicodedata.category(c) != "Mn")
    return plain.replace("đ", "d")


def _lexical_terms(text: str) -> list[str]:
    original = terms(text)
    # A reserved prefix keeps the alternate field separate from legal IDs,
    # Vietnamese words and original exact tokens.
    return original + ["__vi_fold__" + _fold_vietnamese(t) for t in original] + _identifier_terms(text)


def _records_hash(chunks: list[dict]) -> str:
    """Hash all indexed rows, not just IDs, including their evidence scopes."""
    digest = hashlib.sha256()
    for row in chunks:
        digest.update(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _write_json(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _write_jsonl(path: Path, items: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with tmp.open("w", encoding="utf-8") as f:
        for u in items:
            f.write(json.dumps(u, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    os.replace(tmp, path)
    return count


_STRUCTURED_FILES = (
    "domain_facts",
    "criterion_candidates",
    "form_candidates",
    "recognition_candidates",
    "taxonomy_candidates",
    "temporal_candidates",
)


def structured_records(knowledge: Path, units: list[dict]) -> list[dict]:
    """Attach the exact parent PageSpan to all evidence extraction fact/candidate records.

    These records are browseable and lookup-able, but never become verified
    scoring rules solely because they appear in a search index.
    """
    spans_by_id = {u["unit_id"]: u.get("spans", []) for u in units}
    out = []
    for stem in _STRUCTURED_FILES:
        file = knowledge / f"{stem}.jsonl"
        if not file.is_file():
            continue
        with file.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                item = json.loads(line)
                evidence_id = item.get("evidence_unit_id")
                if evidence_id not in spans_by_id:
                    raise ValueError(f"Orphaned evidence extraction structured fact: {evidence_id}")
                out.append(
                    {
                        **item,
                        "record_kind": stem,
                        "source_spans": item.get("spans")
                        or item.get("source_spans")
                        or spans_by_id[evidence_id],
                    }
                )
    return out


def split_units(
    unit: dict, *, max_words: int = 200, overlap: int = 24, token_budget: int = DEFAULT_TARGET_CHUNK_TOKENS
) -> list[str]:
    """Backward-compatible text API; structured child metadata comes from build_chunks."""
    from ai_core.retrieval.ocop.structure_chunker import plan_chunks

    return [
        p.text for p in plan_chunks(unit, max_words=max_words, overlap=overlap, token_budget=token_budget)
    ]


def build_chunks(
    units: Iterable[dict],
    version: str,
    *,
    max_words: int = 200,
    overlap: int = 24,
    token_budget: int = DEFAULT_TARGET_CHUNK_TOKENS,
    source_metadata: dict | None = None,
    counter=None,
) -> list[dict]:
    from ai_core.retrieval.ocop.structure_chunker import plan_chunks

    if token_budget < 64:
        raise ValueError("token_budget must be >= 64")
    result = []
    seen = set()
    source_metadata = source_metadata or {}
    for unit in units:
        if unit["unit_kind"] == "page":
            continue
        meta = source_metadata.get(unit["source_id"]) or {}
        parts = plan_chunks(
            unit,
            max_words=max_words,
            overlap=overlap,
            token_budget=token_budget,
            counter=counter,
            source_metadata=meta,
        )
        for i, part in enumerate(parts):
            chunk_id = stable_id("chunk", unit["source_id"], [unit["unit_id"], i], revision=version)
            if chunk_id in seen:
                raise ValueError("duplicate chunk identity")
            seen.add(chunk_id)
            context = {
                "source_id": unit["source_id"],
                "pdf_page": unit["spans"][0]["pdf_page"],
                "unit_kind": unit["unit_kind"],
            }
            for key in ("document_number", "jurisdiction", "metadata_review"):
                if meta.get(key) is not None:
                    context[key] = meta[key]
            if part.heading:
                context["legal_heading"] = part.heading
            table_id = (unit.get("structured") or {}).get("table_id")
            if table_id:
                context["table_id"] = table_id
            if part.header_inferred:
                context["table_header_inferred"] = True
            ch = RetrievalChunk(
                chunk_id=chunk_id,
                source_id=unit["source_id"],
                evidence_unit_id=unit["unit_id"],
                text_for_embedding=part.text,
                text_for_bm25=part.text,
                corpus_version=version,
                spans=list(part.spans or unit["spans"]),
                review_status=unit["review_status"],
                raw_text=part.raw_text,
                parent_unit_id=unit.get("parent_unit_id"),
                hierarchy_path=unit.get("hierarchy_path") or [],
                context=context,
                char_start=part.char_start,
                char_end=part.char_end,
                row_ids=list(part.row_ids),
                table_headers=list(part.table_headers),
                estimated_tokens=part.token_count,
                token_count_method="model_tokenizer" if counter else "conservative_unicode_estimate",
                over_budget=part.over_budget,
            )
            result.append(ch.model_dump(mode="json"))
    return result


def _write_entity_catalog(index_dir: Path, graph_dir: Path) -> dict:
    """Router entity catalog from the source registry and the checked graph snapshot (never hand-written)."""
    from ai_core.orchestration.ocop.catalog import build_catalog, save_catalog
    from ai_core.graph.ocop.builder import records

    registry = next(
        (
            base / "configs/ocop_sources.json"
            for base in (index_dir.parents[3], ROOT)
            if (base / "configs/ocop_sources.json").is_file()
        ),
        None,
    )
    nodes = []
    header = graph_dir / "manifest.json"
    if header.is_file():
        version = json.loads(header.read_text(encoding="utf8"))["graph_version"]
        nodes = list(records(graph_dir / "snapshots" / version / "nodes.jsonl"))
    return save_catalog(index_dir, build_catalog(registry, nodes)) if registry else {}


def _source_metadata(root: Path = ROOT) -> dict[str, dict]:
    """Only source-catalog facts: no legal applicability claim is inferred."""
    path = root / "configs" / "ocop_sources.json"
    if not path.exists():
        return {}
    content = json.loads(path.read_text(encoding="utf-8"))
    return {
        row["source_id"]: {
            k: row[k]
            for k in ("document_number", "jurisdiction", "metadata_review")
            if row.get(k) is not None
        }
        for row in content.get("sources", [])
    }


def _local_token_counter(path: str):
    """Use only a locally available HF tokenizer. Never download model weights."""
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("Install transformers to use --tokenizer-path") from exc
    tok = AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
    return lambda text: len(tok(text, add_special_tokens=True, truncation=False)["input_ids"])


def create_bm25(chunks: list[dict], path: Path) -> dict:
    """Persist inverted BM25 index; query without Mongo, torch or network."""
    df = defaultdict(int)
    posting = defaultdict(list)
    lengths = []
    for docnum, ch in enumerate(chunks):
        counts = Counter(_lexical_terms(ch["text_for_bm25"]))
        lengths.append(sum(counts.values()))
        for word, cnt in counts.items():
            posting[word].append([docnum, cnt])
            df[word] += 1
    n = len(chunks)
    payload = {
        "schema_version": 2,
        "corpus_hash": content_sha256("\n".join(ch["chunk_id"] for ch in chunks)),
        "records_hash": _records_hash(chunks),
        "n": n,
        "avgdl": sum(lengths) / n if n else 0,
        "lengths": lengths,
        "postings": dict(posting),
        "document_freq": dict(df),
        "k1": 1.5,
        "b": 0.75,
        "tokenizer": "unicode_casefold_vi_folded",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # gzip.open(filename) embeds wall-clock mtime by default, causing the
    # same BM25 corpus to produce different archive hashes on every rebuild.
    # mtime=0 and empty inner filename make byte-for-byte reproducible indices.
    with tmp.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=5, mtime=0) as stream:
            with io.TextIOWrapper(stream, encoding="utf-8") as text_stream:
                json.dump(payload, text_stream, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    return {
        "documents": n,
        "vocabulary_size": len(df),
        "tokenizer": payload["tokenizer"],
        "corpus_hash": payload["corpus_hash"],
        "records_hash": payload["records_hash"],
    }


class BM25Search:
    def __init__(self, path: Path):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            self.data = json.load(f)

    def search(
        self, query: str, top_k: int = 10, allowed_docs: set[int] | None = None
    ) -> list[tuple[int, float]]:
        idx = self.data
        n = idx["n"]
        if not n:
            return []
        scores = defaultdict(float)
        if idx.get("tokenizer") == "unicode_casefold_vi_folded":
            query_terms = {t: 1.0 for t in terms(query)}
            # A question typed without diacritics ("dang ky ocop can giay to gi") matches the accented text only through
            # the folded field, so there that field carries full weight; with diacritics it only backs the exact terms.
            unaccented = _fold_vietnamese(query.casefold()) == query.casefold()
            query_terms.update({"__vi_fold__" + _fold_vietnamese(t): 1.0 if unaccented else 0.35 for t in terms(query)})
            query_terms.update({t: 2.0 for t in _identifier_terms(query)})
        else:
            query_terms = {t: 1.0 for t in set(terms(query))}
        for token, weight in query_terms.items():
            post = idx["postings"].get(token)
            if not post:
                continue
            df = len(post)
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for d, tf in post:
                if allowed_docs is not None and d not in allowed_docs:
                    continue
                length = idx["lengths"][d]
                normal = tf + idx["k1"] * (1 - idx["b"] + idx["b"] * length / max(1, idx["avgdl"]))
                scores[d] += weight * idf * (tf * (idx["k1"] + 1)) / normal
        return sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top_k]


def _require_min_transformers() -> None:
    """Refuse to embed with a library older than the model needs (silent attention fallback otherwise)."""
    minimum = load_models_config().get("embedding", {}).get("min_transformers_version")
    if not minimum:
        return
    try:
        import transformers
        from packaging.version import Version
    except ImportError:
        return  # not installed: the embedding loader reports that itself
    if Version(transformers.__version__) < Version(str(minimum)):
        raise RuntimeError(
            f"transformers>={minimum} is required by the embedding model "
            f"(installed {transformers.__version__}); upgrade and rebuild the dense index"
        )


@lru_cache(maxsize=2)
def _load_embedding(model_id: str, revision: str | None = None):
    os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
    os.environ.setdefault("USE_TF", "0")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("Install sentence-transformers>=5 for actual dense vectors") from exc
    _require_min_transformers()
    resolved, is_local = resolve_local_model_path(model_id)
    options = {"device": "cpu", "trust_remote_code": False, "local_files_only": True}
    if revision and not is_local:
        options["revision"] = revision
    return SentenceTransformer(resolved, **options)


def _encode(model, texts: list[str], is_query: bool):
    method = getattr(model, "encode_query" if is_query else "encode_document", None)
    if method is None:
        raise RuntimeError("Embedding model lacks encode_query/encode_document; incompatible model contract")
    return method(
        texts, normalize_embeddings=True, convert_to_numpy=True, batch_size=8, show_progress_bar=False
    )


def build_dense(
    chunks: list[dict],
    *,
    collection: str,
    model_id: str,
    revision: str | None = None,
    host: str = "localhost",
    port: int = 6333,
    batch: int = 16,
    cache_path: Path | None = None,
) -> dict:
    try:
        from qdrant_client import QdrantClient, models
    except ImportError as exc:
        raise RuntimeError("Install qdrant-client for optional Qdrant indexing") from exc
    model = _load_embedding(model_id, revision)
    probe = _encode(model, ["Kiểm tra định dạng embedding"], False)
    # No embedding truncation is permitted: verify full contextual child input
    # against the *actual* embedding tokenizer before committing to Qdrant.
    tokenizer = getattr(model, "tokenizer", None)
    max_length = getattr(model, "max_seq_length", None)
    if tokenizer is None or not callable(tokenizer) or not isinstance(max_length, int) or max_length < 64:
        raise RuntimeError(
            "Cannot verify dense token budget with the real embedding tokenizer; refusing unsafe indexing"
        )
    for c in chunks:
        if c.get("over_budget"):
            raise RuntimeError(
                f"Over-budget atomic table/word chunk {c['chunk_id']}; review this row before dense indexing"
            )
        try:
            encoded = tokenizer(c["text_for_embedding"], add_special_tokens=True, truncation=False)
            tokens = len(encoded["input_ids"])
        except Exception as exc:
            raise RuntimeError("Cannot verify full embedding token length") from exc
        if tokens > max_length:
            raise RuntimeError(
                f"Embedding input would truncate chunk {c['chunk_id']} ({tokens}>{max_length})"
            )
    dim = int(probe.shape[1])
    client = QdrantClient(host=host, port=port)
    existing = {c.name for c in client.get_collections().collections}
    if collection not in existing:
        client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )
    else:
        info = client.get_collection(collection)
        configured = info.config.params.vectors.size
        if configured != dim:
            raise RuntimeError(f"Existing Qdrant dim={configured}, model dim={dim}")
    # Exact-match filters must be indexed before ingest (Qdrant strict mode
    # can reject unindexed filters, and filter-aware HNSW benefits from early indexes).
    for key in ("source_id", "review_status", "corpus_version", "evidence_unit_id"):
        client.create_payload_index(
            collection_name=collection,
            field_name=key,
            field_schema=models.PayloadSchemaType.KEYWORD,
            wait=True,
        )
    import uuid

    import numpy as np

    # A rebuild that leaves a chunk's embedding input unchanged (a ranking or chunk-id change elsewhere) reuses its
    # vector: the cache is keyed by the exact input text and lives in a file named after the model, so a different
    # model or revision never reads it. Re-embedding all chunks on CPU was most of a rebuild's time.
    keys = [hashlib.sha256(c["text_for_embedding"].encode("utf-8")).hexdigest() for c in chunks]
    known: dict[str, object] = {}
    if cache_path is not None and cache_path.is_file():
        with np.load(cache_path) as saved:
            known = dict(zip(saved["keys"].tolist(), saved["vectors"]))
    todo = [i for i, key in enumerate(keys) if key not in known]
    for start in range(0, len(todo), batch):
        part = todo[start : start + batch]
        for i, vector in zip(part, _encode(model, [chunks[i]["text_for_embedding"] for i in part], False), strict=True):
            known[keys[i]] = vector
    if cache_path is not None and todo:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        current = list(dict.fromkeys(keys))
        np.savez(cache_path, keys=np.array(current), vectors=np.stack([known[k] for k in current]))
    for start in range(0, len(chunks), batch):
        part = chunks[start : start + batch]
        vectors = [known[k] for k in keys[start : start + batch]]
        points = [
            models.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_DNS, c["chunk_id"])),
                vector=v.tolist(),
                payload={
                    "chunk_id": c["chunk_id"],
                    "source_id": c["source_id"],
                    "evidence_unit_id": c["evidence_unit_id"],
                    "corpus_version": c["corpus_version"],
                    "review_status": c["review_status"],
                    "pdf_page": c["spans"][0]["pdf_page"],
                },
            )
            for c, v in zip(part, vectors, strict=True)
        ]
        client.upsert(collection_name=collection, points=points, wait=True)
    count = client.count(collection_name=collection, exact=True).count
    if count != len(chunks):
        raise RuntimeError(f"Qdrant point-count mismatch: {count} != {len(chunks)}")
    return {
        "enabled": True,
        "collection": collection,
        "model_id": model_id,
        "revision": revision,
        "dimension": dim,
        "points": count,
        "host": host,
        "port": port,
    }


def build_index(
    *,
    knowledge: Path,
    index_dir: Path,
    max_words: int = 200,
    overlap: int = 24,
    with_dense: bool = False,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    embedding_revision: str | None = DEFAULT_EMBEDDING_REVISION,
    qdrant_host: str = "localhost",
    qdrant_port: int = 6333,
    token_budget: int = DEFAULT_TARGET_CHUNK_TOKENS,
    tokenizer_path: str | None = None,
    model_max_tokens: int | None = None,
    allow_partial: bool = False,
    graph_dir: Path | None = None,
) -> dict:
    src = json.loads((knowledge / "manifest.json").read_text(encoding="utf-8"))
    source_complete = bool(src.get("complete"))
    if not source_complete and not allow_partial:
        raise RuntimeError("evidence extraction corpus incomplete: refusing production index")
    units = []
    pages_with_kids = set()
    with (knowledge / "evidence_units.jsonl").open(encoding="utf-8") as f:
        for line in f:
            u = json.loads(line)
            units.append(u)
            if u["unit_kind"] != "page":
                pages_with_kids.add((u["source_id"], u["spans"][0]["pdf_page"]))
    # Index page-root only if that page yielded no other evidence units.
    selected = [
        u
        for u in units
        if u["unit_kind"] != "page" or (u["source_id"], u["spans"][0]["pdf_page"]) not in pages_with_kids
    ]
    for u in selected:
        if u["unit_kind"] == "page":
            u["unit_kind"] = "page_fallback"
    metadata = _source_metadata()
    # Include source catalog fingerprint: a legal context change must rebuild the index.
    metadata_hash = content_sha256(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
    tokenizer_fingerprint = tokenizer_path or "estimate"
    graph_dir = graph_dir or index_dir.parent / "graph"
    graph_header = (
        json.loads((graph_dir / "manifest.json").read_text(encoding="utf8"))
        if (graph_dir / "manifest.json").is_file()
        else {}
    )
    corpus_version = hashlib.sha256(
        (
            INDEX_VERSION
            + "|"
            + src["corpus_version"]
            + f"|{max_words}|{overlap}|{token_budget}|{tokenizer_fingerprint}|{metadata_hash}|{graph_header.get('graph_version', '')}"
        ).encode()
    ).hexdigest()[:20]
    model_limit = model_max_tokens or get_model_max_tokens()
    counter = _local_token_counter(tokenizer_path) if tokenizer_path else None
    chunks = build_chunks(
        selected,
        corpus_version,
        max_words=max_words,
        overlap=overlap,
        token_budget=token_budget,
        source_metadata=metadata,
        counter=counter,
    )
    graph_version = None
    if (graph_dir / "manifest.json").is_file():
        from ai_core.retrieval.ocop.graph_context import enrich_chunks

        gm = json.loads((graph_dir / "manifest.json").read_text(encoding="utf8"))
        if gm.get("source_knowledge_version") != src["corpus_version"]:
            raise ValueError("graph/index knowledge version mismatch")
        chunks = enrich_chunks(chunks, graph_dir, allow_partial_debug=allow_partial, counter=counter)
        graph_version = gm["graph_version"]
        from ai_core.retrieval.ocop.structure_chunker import estimated_tokens

        for chunk in chunks:
            chunk["estimated_tokens"] = (counter or estimated_tokens)(chunk["text_for_embedding"])
            chunk["over_budget"] = chunk["estimated_tokens"] > model_limit
    if not chunks:
        raise RuntimeError("No indexable OCOP chunks")
    index_dir.mkdir(parents=True, exist_ok=True)
    count = _write_jsonl(index_dir / "chunks.jsonl", chunks)
    # Keep evidence and structured facts independently addressable; they are
    # NOT converted into unverified legal rules or official star ratings.
    evidence_count = _write_jsonl(index_dir / "evidence_units.jsonl", units)
    structured_count = _write_jsonl(index_dir / "structured.jsonl", structured_records(knowledge, units))
    bm25 = create_bm25(chunks, index_dir / "bm25.json.gz")
    dense = {"enabled": False, "reason": "model_not_loaded; pass --with-dense to build REAL vectors"}
    manifest = {
        "status": "sparse_ready",
        "index_version": INDEX_VERSION,
        "source_knowledge_version": src["corpus_version"],
        "corpus_version": corpus_version,
        "structural_graph_version": graph_version,
        "source_complete": source_complete,
        "counts": {
            "chunks": count,
            "evidence_units": evidence_count,
            "structured_records": structured_count,
            "source_pages": src["counts"]["pages"],
        },
        "bm25": bm25,
        "dense": dense,
        "chunking": {
            "method": "structure_aware_contextual_parent_child",
            "token_count_method": "model_tokenizer" if counter else "conservative_unicode_estimate",
            "over_budget_chunks": sum(bool(c["over_budget"]) for c in chunks),
            "max_estimated_tokens": max(c["estimated_tokens"] for c in chunks),
        },
        "config": {
            "max_words": max_words,
            "overlap": overlap,
            "token_budget": token_budget,
            "model_max_tokens": model_limit,
            "tokenizer_path": tokenizer_path,
        },
    }
    manifest["entity_catalog"] = _write_entity_catalog(index_dir, graph_dir)
    _write_json(index_dir / "manifest.json", manifest)
    if with_dense:
        # Do not mark as dense_ready until indexing Qdrant succeeds.
        # Different embedding spaces MUST NOT share a Qdrant collection, even
        # when their dimensions are identical (e.g. two unrelated 768d models).
        fingerprint = hashlib.sha256(
            (embedding_model + "|" + (embedding_revision or "UNPINNED")).encode()
        ).hexdigest()[:12]
        collection = "ocop_" + corpus_version + "_" + fingerprint
        dense = build_dense(
            chunks,
            collection=collection,
            model_id=embedding_model,
            revision=embedding_revision,
            host=qdrant_host,
            port=qdrant_port,
            cache_path=Path(knowledge).parent / "cache" / f"embeddings-{fingerprint}.npz",
        )
        manifest["dense"] = dense
        manifest["status"] = "hybrid_ready"
        _write_json(index_dir / "manifest.json", manifest)
    if allow_partial:
        manifest["status"] = "partial_debug_not_production"
        _write_json(index_dir / "manifest.json", manifest)
    return manifest


def main():
    p = argparse.ArgumentParser(description="indexing: build OCOP BM25 and optional real dense vectors")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--knowledge", type=Path, default=Path("data/processed/ocop/knowledge"))
    p.add_argument("--output", type=Path, default=Path("data/processed/ocop/index"))
    p.add_argument("--max-words", type=int, default=200)
    p.add_argument("--overlap", type=int, default=24)
    p.add_argument(
        "--token-budget",
        type=int,
        default=DEFAULT_TARGET_CHUNK_TOKENS,
        help="Target retrieval chunk token budget; estimated unless tokenizer path supplied",
    )
    p.add_argument(
        "--model-max-tokens",
        type=int,
        default=None,
        help="Hard maximum token limit for embedding model (defaults to configs/ocop_models.yaml)",
    )
    p.add_argument(
        "--tokenizer-path",
        default=None,
        help="Optional local HF tokenizer directory (no downloads); requires transformers",
    )
    p.add_argument(
        "--allow-partial",
        action="store_true",
        help="Debug-only: index incomplete evidence and mark output non-production",
    )
    p.add_argument("--with-dense", action="store_true")
    p.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    p.add_argument(
        "--embedding-revision",
        default=DEFAULT_EMBEDDING_REVISION,
        help="Pinned Hugging Face model commit; recommended for repeatable index releases",
    )
    p.add_argument("--qdrant-host", default="localhost")
    p.add_argument("--qdrant-port", type=int, default=6333)
    args = p.parse_args()
    root = args.root.resolve()

    def local(p):
        return p if p.is_absolute() else root / p

    out = build_index(
        knowledge=local(args.knowledge),
        index_dir=local(args.output),
        max_words=args.max_words,
        overlap=args.overlap,
        with_dense=args.with_dense,
        embedding_model=args.embedding_model,
        embedding_revision=args.embedding_revision,
        qdrant_host=args.qdrant_host,
        qdrant_port=args.qdrant_port,
        token_budget=args.token_budget,
        tokenizer_path=args.tokenizer_path,
        model_max_tokens=args.model_max_tokens,
        allow_partial=args.allow_partial,
    )
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
