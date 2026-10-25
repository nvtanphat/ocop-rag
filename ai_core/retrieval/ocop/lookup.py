"""Exact/source-backed lookup for OCOP evidence and evidence extraction domain candidates.

No embedding/LLM required. Values are *machine candidates* until separately
verified. This is a indexing lookup, not the later legal rule engine.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ai_core.graph.ocop.builder import records as _iter_jsonl
from ai_core.retrieval.ocop.index_pipeline import ROOT


def exact_lookup(
    index_dir: Path,
    *,
    identity: str | None = None,
    source_id: str | None = None,
    pdf_page: int | None = None,
    kind: str | None = None,
    contains: str | None = None,
    include_candidates: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Filter exact evidence by ID, PDF page, document and evidence unit kind.

    Identity may be an evidence unit ID, a fact/candidate ID or a source ID.
    Page numbers are physical PDF pages (1-based), not printed annex labels.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    if pdf_page is not None and pdf_page < 1:
        raise ValueError("pdf_page must be >= 1")
    if not any([identity, source_id, pdf_page, kind, contains]):
        raise ValueError("provide at least one lookup constraint")
    manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
    version = manifest["corpus_version"]
    haystack = (index_dir / "evidence_units.jsonl",)
    if include_candidates:
        haystack += (index_dir / "structured.jsonl",)
    out: list[dict[str, Any]] = []
    for path in haystack:
        for record in _iter_jsonl(path):
            spans = record.get("source_spans") or record.get("spans") or []
            ids = (
                record.get("unit_id"),
                record.get("fact_id"),
                record.get("candidate_id"),
                record.get("source_id"),
                record.get("evidence_unit_id"),
            )
            record_kind = record.get("unit_kind") or record.get("record_kind") or record.get("fact_type")
            if identity and identity not in ids:
                continue
            if source_id and record.get("source_id") != source_id:
                continue
            if pdf_page and not any(s.get("pdf_page") == pdf_page for s in spans):
                continue
            if kind and record_kind != kind:
                continue
            if contains:
                text = " ".join(
                    str(record.get(field) or "")
                    for field in ("text", "evidence_text", "label_candidate", "title", "row_text", "heading")
                )
                if contains.casefold() not in text.casefold():
                    continue
            out.append({**record, "corpus_version": version})
            if len(out) >= limit:
                return out
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Exact source/evidence/criterion candidate lookup")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--index", type=Path, default=Path("data/processed/ocop/index"))
    parser.add_argument("--id", dest="identity")
    parser.add_argument("--source-id")
    parser.add_argument("--pdf-page", type=int)
    parser.add_argument("--kind")
    parser.add_argument("--contains")
    parser.add_argument("--evidence-only", action="store_true")
    parser.add_argument(
        "--include-candidates", action="store_true", help="Explicit offline candidate inspection only"
    )
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    root = args.root.resolve()
    index = args.index if args.index.is_absolute() else root / args.index
    matches = exact_lookup(
        index,
        identity=args.identity,
        source_id=args.source_id,
        pdf_page=args.pdf_page,
        kind=args.kind,
        contains=args.contains,
        include_candidates=args.include_candidates and not args.evidence_only,
        limit=args.limit,
    )
    print(json.dumps(matches, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
