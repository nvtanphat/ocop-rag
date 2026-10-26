"""Reproducible OCOP offline evaluation; raw PDF backed labels and no synthetic gold.

Gold labels are metadata spans manually inspected on supplied PDF text, NOT
human-validated legal facts. Pending cases are excluded until reviewed.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import time
import math
from pathlib import Path
from typing import Callable
from ai_core.retrieval.ocop.search import search


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    query: str
    label_status: str
    source_id: str | None = None
    pdf_page: int | None = None
    expected_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    notes: str = ""


def load_cases(file: Path, *, only_approved: bool = True) -> list[EvalCase]:
    cases = []
    seen = set()
    for line in file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["case_id"] in seen:
            raise ValueError("Duplicate eval case ID: " + row["case_id"])
        seen.add(row["case_id"])
        case = EvalCase(**row)
        if only_approved and case.label_status not in ("pdf_page_confirmed", "expert_verified"):
            continue
        cases.append(case)
    return cases


def _git_sha(root: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
            check=True,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


def _rr_rank(hits: list[dict], case: EvalCase) -> int | None:
    for i, hit in enumerate(hits, 1):
        if hit.get("source_id") == case.source_id and (
            case.pdf_page is None or hit.get("pdf_page") == case.pdf_page
        ):
            return i
    return None


def evaluate_retrieval(
    root: Path,
    dataset: Path,
    *,
    modes: tuple[str, ...] = ("sparse",),
    top_k: int = 10,
    run_id: str | None = None,
    output_dir: Path | None = None,
    runner: Callable | None = None,
) -> dict:
    root = Path(root)
    dataset = Path(dataset)
    rows = load_cases(dataset)
    if not rows:
        raise ValueError("No independently page-confirmed retrieval labels; review fixtures first")
    index = root / "data/processed/ocop/index"
    manifest = json.loads((index / "manifest.json").read_text(encoding="utf-8"))
    run_id = run_id or datetime.now(timezone.utc).strftime("EV-%Y%m%dT%H%M%SZ")
    results = {}
    for mode in modes:
        details = []
        elapsed = 0.0
        base_mode = mode.removesuffix("_rerank")
        rerank = mode.endswith("_rerank")
        if base_mode not in ("sparse", "dense", "hybrid") or (
            rerank and mode not in ("sparse_rerank", "dense_rerank", "hybrid_rerank")
        ):
            raise ValueError("Unsupported evaluation retrieval mode: " + mode)
        if base_mode in ("dense", "hybrid") and not manifest.get("dense", {}).get("enabled"):
            results[mode] = {"status": "not_run_missing_dense_index", "evaluated": 0}
            continue
        for case in rows:
            started = time.monotonic()
            try:
                options = {"mode": base_mode, "top_k": top_k}
                if rerank:
                    options["rerank"] = True
                hits = (runner or search)(index, case.query, **options)
                error = None
            except (RuntimeError, OSError, ValueError) as exc:
                hits = []
                error = type(exc).__name__ + ": " + str(exc)[:150]
            duration = (time.monotonic() - started) * 1000
            elapsed += duration
            rank = _rr_rank(hits, case)
            details.append(
                {
                    "case_id": case.case_id,
                    "rank": rank,
                    "hit_at_5": rank is not None and rank <= 5,
                    "hit_at_10": rank is not None and rank <= 10,
                    "rr": 1.0 / rank if rank else 0.0,
                    "ndcg_at_10": (1 / math.log2(rank + 1)) if rank and rank <= 10 else 0.0,
                    "latency_ms": round(duration, 2),
                    "error": error,
                    "top_sources": [
                        {"source_id": h.get("source_id"), "pdf_page": h.get("pdf_page")} for h in hits[:5]
                    ],
                }
            )
        n = len(details)
        ordered_latencies = sorted(r["latency_ms"] for r in details)
        p95 = ordered_latencies[max(0, math.ceil(0.95 * n) - 1)]
        results[mode] = {
            "status": "completed" if all(not x["error"] for x in details) else "completed_with_errors",
            "evaluated": n,
            "hit_at_5": round(sum(x["hit_at_5"] for x in details) / n, 4),
            "recall_at_10": round(sum(x["hit_at_10"] for x in details) / n, 4),
            "mrr_at_10": round(sum(x["rr"] for x in details) / n, 4),
            "ndcg_at_10": round(sum(x["ndcg_at_10"] for x in details) / n, 4),
            "mean_latency_ms": round(elapsed / n, 2),
            "p95_latency_ms": p95,
            "error_count": sum(bool(x["error"]) for x in details),
            "cases": details,
        }
    report = {
        "run_id": run_id,
        "label_provenance": "mixed_gold_labels; count expert-verified separately",
        "expert_verified_cases": sum(c.label_status == "expert_verified" for c in rows),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "code_commit": _git_sha(root),
        "corpus_version": manifest.get("corpus_version"),
        "dense_model_fingerprint": (manifest.get("dense") or {}).get("model_fingerprint"),
        "top_k": top_k,
        "results": results,
        "comparison": {},
    }
    if all(m in results and results[m]["evaluated"] for m in ("sparse", "hybrid")):
        report["comparison"]["hybrid_minus_sparse_recall10"] = round(
            results["hybrid"]["recall_at_10"] - results["sparse"]["recall_at_10"], 4
        )
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{run_id}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report


def evaluate_agent(root: Path, dataset: Path, *, agent_factory=None, output_dir: Path | None = None) -> dict:
    """Tool trajectory policy evaluation. No correctness label is inferred from answers."""
    from ai_core.orchestration.ocop.workflow import OcopAgent

    cases = load_cases(dataset, only_approved=False)
    cases = [c for c in cases if c.expected_tools or c.forbidden_tools]
    if not cases:
        raise ValueError("No trajectory labels")
    agent = (agent_factory or OcopAgent)(root)
    scored = []
    for case in cases:
        start = time.monotonic()
        error = None
        try:
            answer = agent.ask(case.query)
            called = answer.tools_used
            status = answer.status
            trace = answer.tool_trace
        except Exception as exc:
            called = []
            status = "error"
            trace = []
            error = type(exc).__name__ + ": " + str(exc)[:100]
        expected = set(case.expected_tools)
        forbidden = set(case.forbidden_tools)
        scored.append(
            {
                "case_id": case.case_id,
                "tool_recall": len(expected & set(called)) / len(expected) if expected else 1.0,
                "forbidden_calls": sorted(forbidden & set(called)),
                "repeated_calls": len(called) - len(set(called)),
                "tool_sequence": called,
                "tool_trace": trace,
                "status": status,
                "error": error,
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }
        )
    report = {
        "evaluated": len(scored),
        "tool_recall": sum(x["tool_recall"] for x in scored) / len(scored),
        "forbidden_calls": sum(len(x["forbidden_calls"]) for x in scored),
        "repeated_calls": sum(x["repeated_calls"] for x in scored),
        "errors": sum(x["error"] is not None for x in scored),
        "cases": scored,
    }
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "agent_trajectory.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
        )
    return report


# Thresholds a production release must meet; override per call, never by editing a report.
GATE_DEFAULTS = {"min_tool_recall": 0.9, "max_agent_errors": 0, "min_claim_publish_rate": 0.5}


def release_gate(
    report: dict,
    *,
    baseline: dict | None = None,
    recall_tolerance: float = 0.03,
    production: bool = True,
    thresholds: dict | None = None,
) -> dict:
    """Fail closed for missing labels/dense measurement, failed agent runs and forbidden actions."""
    limits = GATE_DEFAULTS | (thresholds or {})
    failures = []
    retrieval = report.get("results", {})
    claims = report.get("claim_grounding_evaluation")
    if production:
        if not report.get("expert_verified_cases", 0):
            failures.append("no_domain_expert_gold_labels")
        for required in ("sparse", "dense", "hybrid"):
            if required not in retrieval or retrieval[required].get("status") != "completed":
                failures.append(required + ":integration_not_measured")
        if not report.get("trajectory"):
            failures.append("agent_trajectory_not_measured")
        if not claims or not claims.get("eligible_questions"):
            failures.append("claim_grounding_not_measured")
    if baseline and baseline.get("dataset_sha256") != report.get("dataset_sha256"):
        failures.append("baseline_dataset_hash_mismatch")
    for mode, metrics in retrieval.items():
        if metrics.get("status") != "completed":
            failures.append(mode + ":missing_or_failed_metrics")
        if (
            baseline
            and metrics.get("evaluated")
            and baseline.get("results", {}).get(mode, {}).get("evaluated")
        ):
            old = baseline["results"][mode]["recall_at_10"]
            if metrics.get("recall_at_10", 0) < old - recall_tolerance:
                failures.append(mode + ":recall_regression")
    if not retrieval:
        failures.append("no_retrieval_evaluation")
    traj = report.get("trajectory")
    if traj:
        if traj.get("forbidden_calls"):
            failures.append("forbidden_tool_calls")
        if traj.get("errors", 0) > limits["max_agent_errors"]:
            failures.append("agent_errors")
        if traj.get("tool_recall", 1.0) < limits["min_tool_recall"]:
            failures.append("tool_recall_below_threshold")
        old_recall = (baseline or {}).get("trajectory", {}).get("tool_recall")
        if old_recall is not None and traj.get("tool_recall", 1.0) < old_recall - recall_tolerance:
            failures.append("tool_recall_regression")
    if claims and claims.get("eligible_questions"):
        if claims.get("errors"):
            failures.append("claim_grounding_errors")
        if claims.get("publish_rate", 0.0) < limits["min_claim_publish_rate"]:
            failures.append("claim_grounding_below_threshold")
        old_rate = (baseline or {}).get("claim_grounding_evaluation", {}).get("publish_rate")
        if old_rate is not None and claims.get("publish_rate", 0.0) < old_rate - recall_tolerance:
            failures.append("claim_grounding_regression")
    faults = report.get("fault_injection")
    if production and not faults:
        failures.append("fault_injection_not_measured")
    if faults and faults.get("failed_count"):
        failures.append("fault_injection_unsafe_recovery")
    return {"status": "pass" if not failures else "blocked", "failures": failures}
