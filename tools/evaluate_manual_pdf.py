"""Run independently PDF-checked questions through the agent.

This evaluator measures source/page retrieval coverage and safe behavior in
no-LLM mode, not answer accuracy. It never builds gold labels from pipeline
output. Gold evidence and SHA-256 values come from manual_pdf_*.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_core.orchestration.ocop.workflow import OcopAgent  # noqa: E402 - standalone entrypoint establishes the repository import path
from ai_core.system.pipeline import OcopSystemPipeline  # noqa: E402 - standalone entrypoint establishes the repository import path
from ocop_contracts.registry import sha256_file  # noqa: E402 - standalone entrypoint establishes the repository import path

DATASET = Path("data/evaluations/ocop/manual_pdf_benchmark.jsonl")
SOURCES = Path("data/evaluations/ocop/manual_pdf_sources.json")


def load_gold(root: Path, dataset: Path = DATASET, sources_file: Path = SOURCES):
    sources = json.loads((root / sources_file).read_text(encoding="utf-8"))
    registry = json.loads((root / "configs/ocop_sources.json").read_text(encoding="utf-8"))["sources"]
    by_filename = {Path(row["path"]).name: row for row in registry}
    mapping = {}
    for doc_id, spec in sources.items():
        filename = spec["filename"]
        if filename not in by_filename:
            raise ValueError(f"Manual benchmark references a PDF absent from corpus: {filename}")
        src = by_filename[filename]
        pdf = root / src["path"]
        if sha256_file(pdf) != spec["sha256"]:
            raise ValueError(f"PDF differs from manually checked source: {filename}")
        mapping[doc_id] = src["source_id"]
    cases = [
        json.loads(line) for line in (root / dataset).read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if len(cases) != len({row["id"] for row in cases}):
        raise ValueError("Duplicate manual benchmark case IDs")
    return cases, mapping


def score_case(gold: dict, citations: list[dict], mapping: dict[str, str]) -> dict:
    expected = {(mapping[c["document_id"]], int(c["pdf_page"])) for c in gold["evidence"]}
    found = {(str(c["source_id"]), int(c["pdf_page"])) for c in citations}
    # A citation is not a verified answer; calculate only supporting-page hits.
    correct = expected & found
    return {
        "page_hit": bool(correct),
        "source_hit": bool({x[0] for x in expected} & {x[0] for x in found}),
        "page_recall": len(correct) / len(expected) if expected else None,
        "page_precision": len(correct) / len(found) if found else None,
        "n_citations": len(found),
    }


def run_evaluation(
    root: Path,
    *,
    split: str = "all",
    max_queries: int | None = None,
    dataset: Path = DATASET,
    sources_file: Path = SOURCES,
):
    status = OcopSystemPipeline(root).status(validate_sources=True)
    if status["state"] != "ready":
        raise RuntimeError("Build the locked corpus first: python tools/cli.py run --build-only")
    gold, mapping = load_gold(root, dataset, sources_file)
    cases = [case for case in gold if split == "all" or case["split"] == split]
    if max_queries is not None:
        if max_queries < 1:
            raise ValueError("--max-queries must be positive")
        cases = cases[:max_queries]
    agent = OcopAgent(root, llm=None, retrieval_mode="sparse")
    results = []
    for item in cases:
        try:
            response = agent.ask(item["question"]).model_dump(mode="json")
            metrics = score_case(item, response.get("citations", []), mapping)
            results.append(
                {
                    "id": item["id"],
                    "split": item["split"],
                    "category": item["category"],
                    "answerability": item["answerability"],
                    "intent": response.get("intent"),
                    "status": response.get("status"),
                    "tools": response.get("tools_used", []),
                    "citations": [
                        {"source_id": x["source_id"], "pdf_page": x["pdf_page"]}
                        for x in response.get("citations", [])
                    ],
                    **metrics,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "id": item["id"],
                    "split": item["split"],
                    "category": item["category"],
                    "error": type(exc).__name__ + ": " + str(exc)[:300],
                }
            )
    answerable = [r for r in results if r.get("answerability") == "answerable"]
    with_evidence = [r for r in answerable if "error" not in r]
    statuses = Counter(r.get("status", "ERROR") for r in results)
    return {
        "scope": "local_sparse_no_llm_retrieval_only",
        "corpus_version": status["corpus_version"],
        "source_documents": status["sources"],
        "pdf_pages": status["pdf_pages"],
        "dataset_origin": "manual_pdf_read_not_pipeline",
        "split": split,
        "cases_run": len(cases),
        "cases_answerable": len(answerable),
        "cases_failed_execution": sum("error" in r for r in results),
        "statuses": dict(statuses),
        "retrieval_metrics": {
            "page_hit_rate": round(sum(r["page_hit"] for r in with_evidence) / len(with_evidence), 4)
            if with_evidence
            else None,
            "source_hit_rate": round(sum(r["source_hit"] for r in with_evidence) / len(with_evidence), 4)
            if with_evidence
            else None,
            "page_recall": round(sum(r["page_recall"] or 0 for r in with_evidence) / len(with_evidence), 4)
            if with_evidence
            else None,
        },
        "answer_metrics": None,
        "answer_metrics_reason": "No generative LLM or expert judgment used; retrieval_only is not a factual answer",
        "unanswerable_statuses": {
            k: v
            for k, v in Counter(
                r.get("status", "ERROR") for r in results if r.get("answerability") != "answerable"
            ).items()
        },
        "per_case": results,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--split", choices=("dev", "test", "all"), default="all")
    ap.add_argument("--max-queries", type=int)
    ap.add_argument("--out", type=Path, default=Path("reports/evaluation/manual_pdf_sparse.json"))
    args = ap.parse_args()
    report = run_evaluation(args.root.resolve(), split=args.split, max_queries=args.max_queries)
    output = args.out if args.out.is_absolute() else args.root / args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {k: v for k, v in report.items() if k != "per_case"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if report["cases_failed_execution"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
