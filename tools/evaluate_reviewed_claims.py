"""Run claim-level generation only on questions whose evidence a human has reviewed.

    python tools/evaluate_reviewed_claims.py --root <corpus root> --questions questions.json [--limit N]

A question is eligible when every page it targets has at least one EvidenceUnit node with ``check: human_verified``
in the current graph (the ledger written by the review CLI). The tool never marks anything verified and
never relaxes a gate: it reports, per question, what the unchanged gates published, what they dropped and why, so a
reviewer can see whether grounded paraphrase works once sources are approved. With no reviewed evidence it stops
and says what to review instead of running the model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_core.evaluation.ocop.claims import eligible, evaluate_claim_grounding, reviewed_pages  # noqa: E402 - repository import path is set above

__all__ = ["eligible", "reviewed_pages", "main"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--mode", choices=("sparse", "hybrid"), default="sparse")
    args = ap.parse_args()
    root = args.root.resolve()
    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    if not eligible(questions, reviewed_pages(root)):
        print(
            "No question targets only human-reviewed evidence; nothing to evaluate.\n"
            "Review the EvidenceUnits of the target pages first: python tools/cli.py review queue --root <root> --render",
            file=sys.stderr,
        )
        raise SystemExit(2)
    report = evaluate_claim_grounding(root, questions, mode=args.mode, limit=args.limit)
    for case in report.pop("cases"):
        print(json.dumps(case, ensure_ascii=False))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
