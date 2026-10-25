"""Run OCOP source-page retrieval + trajectory evaluation and optional gates.

python tools/evaluate_ocop.py --mode sparse --out-dir reports/evaluation
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_core.evaluation.ocop.harness import evaluate_retrieval, evaluate_agent, release_gate  # noqa: E402 - standalone entrypoint establishes the repository import path
from ai_core.evaluation.ocop.faults import evaluate_faults  # noqa: E402 - standalone entrypoint establishes the repository import path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument(
        "--dataset", type=Path, default=Path("data/evaluations/ocop/retrieval_page_gold_seed.jsonl")
    )
    ap.add_argument(
        "--mode",
        nargs="+",
        choices=["sparse", "dense", "hybrid", "sparse_rerank", "dense_rerank", "hybrid_rerank"],
        default=["sparse"],
    )
    ap.add_argument("--out-dir", type=Path, default=Path("reports/evaluation"))
    ap.add_argument("--with-agent", action="store_true")
    ap.add_argument("--with-faults", action="store_true")
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    root = args.root.resolve()
    out = args.out_dir if args.out_dir.is_absolute() else root / args.out_dir
    ds = args.dataset if args.dataset.is_absolute() else root / args.dataset
    if not (root / "data/processed/ocop/index/manifest.json").is_file():
        ap.error("Corpus chưa được dựng. Chạy python tools/cli.py run --build-only trước khi evaluate.")
    report = evaluate_retrieval(root, ds, modes=tuple(args.mode), output_dir=out)
    if args.with_agent:
        report["trajectory"] = evaluate_agent(
            root, root / "data/evaluations/ocop/agent_trajectory_curated.jsonl", output_dir=out
        )
    if args.with_faults:
        report["fault_injection"] = evaluate_faults(root)
    baseline = json.loads(args.baseline.read_text()) if args.baseline else None
    report["release_gate"] = release_gate(report, baseline=baseline)
    # Aggregate artifacts use the same schema as every individual eval run.
    (out / f"{report['run_id']}_complete.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "results"}
            | {
                "metrics": {
                    key: {k: v for k, v in value.items() if k != "cases"}
                    for key, value in report["results"].items()
                }
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    if args.strict and report["release_gate"]["status"] != "pass":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
