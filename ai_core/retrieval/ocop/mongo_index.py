"""Optional OCOP MongoDB staging, isolated by database and immutable corpus version.

Only explicit ``--with-mongo`` may write; this module never switches a live alias.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def _records(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def _batched(source: Iterable[dict], size: int = 500):
    batch = []
    for item in source:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def index_mongo(
    index_dir: Path,
    *,
    corpus_version: str,
    uri: str = "mongodb://127.0.0.1:27017",
    database: str = "ocop_rag",
) -> dict:
    try:
        from pymongo import MongoClient, ReplaceOne
    except ImportError as exc:
        raise RuntimeError("Install pymongo for optional MongoDB indexing") from exc
    if not database.startswith("ocop_"):
        raise ValueError("Mongo database must use the ocop_ namespace")
    sources = {
        "ocop_chunks": ("chunks.jsonl", "chunk_id"),
        "ocop_evidence_units": ("evidence_units.jsonl", "unit_id"),
        "ocop_structured_facts": ("structured.jsonl", "candidate_id"),
    }
    counts = {}
    with MongoClient(uri, serverSelectionTimeoutMS=10000) as client:
        client.admin.command("ping")
        db = client[database]
        for collection_name, (filename, key) in sources.items():
            collection = db[collection_name]
            collection.create_index([("corpus_version", 1), ("source_id", 1)])
            collection.create_index("evidence_unit_id")
            written = 0
            for rows in _batched(_records(index_dir / filename)):
                ops = []
                for item in rows:
                    row_id = item.get(key) or item.get("fact_id")
                    if not row_id:
                        raise ValueError(f"Missing ID ({key} or fact_id) in {filename}")
                    document = {**item, "_id": f"{corpus_version}:{row_id}",
                                "corpus_version": corpus_version}
                    ops.append(ReplaceOne({"_id": document["_id"]}, document, upsert=True))
                collection.bulk_write(ops, ordered=False)
                written += len(ops)
            existing = collection.count_documents({"corpus_version": corpus_version})
            if existing != written:
                raise RuntimeError(
                    f"OCOP Mongo parity failure in {collection_name}: {existing} != {written}"
                )
            counts[collection_name] = existing
        releases = db["ocop_index_releases"]
        releases.replace_one({"_id": corpus_version}, {
            "_id": corpus_version,
            "corpus_version": corpus_version,
            "status": "STAGING",  # never publish automatically
            "counts": counts,
        }, upsert=True)
    return {"enabled": True, "database": database, "counts": counts,
            "status": "STAGING"}
