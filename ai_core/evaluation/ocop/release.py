"""Fail-closed release admission from versioned OCOP evaluation artifacts."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
from ai_core.evaluation.ocop.harness import release_gate


def validate_latest(root: Path, *, corpus_version: str | None = None) -> dict:
    root = Path(root)
    reports = sorted((root / "reports/evaluation").glob("EV-*_complete.json"))
    if not reports:
        return {"status": "blocked", "failures": ["no_evaluation_run_manifest"]}
    report = json.loads(reports[-1].read_text(encoding="utf-8"))
    failures = []
    if corpus_version and report.get("corpus_version") != corpus_version:
        failures.append("evaluation_corpus_version_mismatch")
    data = root / "data/evaluations/ocop/retrieval_page_gold_seed.jsonl"
    if not data.is_file() or hashlib.sha256(data.read_bytes()).hexdigest() != report.get("dataset_sha256"):
        failures.append("dataset_hash_mismatch")
    verdict = release_gate(report, production=True)
    return {
        "status": "pass" if verdict["status"] == "pass" and not failures else "blocked",
        "failures": failures + verdict["failures"],
        "run_id": report.get("run_id"),
        "corpus_version": report.get("corpus_version"),
    }
