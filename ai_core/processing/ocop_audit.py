"""Audit and lock source PDFs without mutating retrieval indexes.

Usage:
  python tools/cli.py audit-ocop
  python tools/cli.py lock-ocop
  python tools/cli.py audit-ocop -- --output outputs/ocop/audit.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from ai_core.processing.ocop.profiler import profile_pdf
from ai_core.processing.ocop.registry import compare_lock, load_registry, snapshot

ROOT = Path(__file__).resolve().parents[2]


def audit(root: Path, registry_file: Path, lock_file: Path, *, verify_lock: bool = True) -> dict:
    sources = load_registry(registry_file)
    locked = snapshot(root, sources)
    if verify_lock:
        if not lock_file.is_file():
            raise FileNotFoundError("source lock missing; run lock-ocop explicitly")
        compare_lock(locked, json.loads(lock_file.read_text(encoding="utf-8")))
    pages = []
    report_sources = []
    for source in sources:
        page_profiles = profile_pdf(root / source.path, source.source_id)
        pages.extend(page_profiles)
        report_sources.append({
            "source_id": source.source_id,
            "source_kind": source.source_kind.value,
            "document_number": source.document_number,
            "metadata_review": source.metadata_review.value,
            "source_verification": source.source_verification,
            "pages": len(page_profiles),
            "native_text_pages": sum(p["native_chars"] >= 120 for p in page_profiles),
            "needs_ocr_review_pages": sum(p["needs_ocr_review"] for p in page_profiles),
        })
    counts = Counter(p["page_class"] for p in pages)
    return {
        "status": "audited_not_ingested",
        "source_count": len(sources),
        "page_count": len(pages),
        "pages_needing_ocr_review": sum(p["needs_ocr_review"] for p in pages),
        "page_class_counts": dict(sorted(counts.items())),
        "snapshot_sha256": locked["aggregate_sha256"],
        "sources": report_sources,
        "pages": pages,
        "caveat": "Read-only profiling, not OCR, table extraction, text verification or legal validity verification.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="OCOP source PDF audit")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--registry", type=Path, default=Path("configs/ocop_sources.json"))
    parser.add_argument("--lock-file", type=Path, default=Path("configs/ocop_sources.lock.json"))
    parser.add_argument("--output", type=Path, default=Path("outputs/ocop/source_audit.json"))
    parser.add_argument("--write-lock", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    registry_file = args.registry if args.registry.is_absolute() else root / args.registry
    lock_file = args.lock_file if args.lock_file.is_absolute() else root / args.lock_file
    output_file = args.output if args.output.is_absolute() else root / args.output
    sources = load_registry(registry_file)
    if args.write_lock:
        locked = snapshot(root, sources)
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.write_text(json.dumps(locked, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Locked {len(sources)} OCOP sources: {locked['aggregate_sha256'][:16]} -> {lock_file}")
        return
    result = audit(root, registry_file, lock_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Audited {result['source_count']} PDFs / {result['page_count']} pages, "
          f"OCR review candidates: {result['pages_needing_ocr_review']}. "
          f"Report: {output_file}")


if __name__ == "__main__":
    main()
