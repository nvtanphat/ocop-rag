"""Run claim-level generation only on questions whose evidence a human has reviewed.

    python tools/evaluate_reviewed_claims.py --root <corpus root> --questions questions.json [--limit N]

A question is eligible when every page it targets has at least one EvidenceUnit node with ``check: human_verified``
in the current graph (the ledger written by the Human Review API/CLI). The tool never marks anything verified and
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


def reviewed_pages(root: Path) -> dict[str, set[int]]:
    """source_id -> pages that carry at least one human_verified EvidenceUnit node."""
    from ai_core.graph.ocop.builder import records

    graph = root / "data/processed/ocop/graph"
    manifest = json.loads((graph / "manifest.json").read_text(encoding="utf-8"))
    pages: dict[str, set[int]] = {}
    for node in records(graph / "snapshots" / manifest["graph_version"] / "nodes.jsonl"):
        if node.get("node_type") == "EvidenceUnit" and node.get("check") == "human_verified":
            for ref in node.get("citations", []):
                if isinstance(ref.get("pdf_page"), int):
                    pages.setdefault(node["source_id"], set()).add(ref["pdf_page"])
    return pages


def eligible(questions: list[dict], pages: dict[str, set[int]]) -> list[dict]:
    return [
        q
        for q in questions
        if q.get("pages")
        and q.get("source_id")
        and not q.get("turns")
        and set(q["pages"]) <= pages.get(q["source_id"], set())
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--mode", choices=("sparse", "hybrid"), default="sparse")
    args = ap.parse_args()
    root = args.root.resolve()
    pages = reviewed_pages(root)
    chosen = eligible(json.loads(args.questions.read_text(encoding="utf-8")), pages)[: args.limit]
    if not chosen:
        print(
            "No question targets only human-reviewed evidence; nothing to evaluate.\n"
            "Review the EvidenceUnits of the target pages first: python tools/cli.py review queue --root <root> --render",
            file=sys.stderr,
        )
        raise SystemExit(2)
    from ai_core.orchestration.ocop.llm import make_answer_client
    from ai_core.orchestration.ocop.workflow import OcopAgent

    agent = OcopAgent(root, llm=make_answer_client(), retrieval_mode=args.mode, allow_partial_debug=True)
    outcome = {"published": 0, "partial": 0, "blocked": 0}
    for q in chosen:
        response = agent.ask(q["query"]).model_dump(mode="json")
        diagnostics = response.get("generation_diagnostics", {})
        status = response["status"]
        key = (
            "published"
            if status in ("generated_claims_verified", "generated_unverified_claims")
            else "partial"
            if status == "partial_claims_verified"
            else "blocked"
        )
        outcome[key] += 1
        print(
            json.dumps(
                {
                    "id": q["id"],
                    "status": status,
                    "accepted": diagnostics.get("accepted"),
                    "rejected": diagnostics.get("rejected"),
                    "missing": diagnostics.get("missing_from_source"),
                    "reasons": diagnostics.get("reasons"),
                },
                ensure_ascii=False,
            )
        )
    print(json.dumps({"eligible_questions": len(chosen), **outcome}, ensure_ascii=False))


if __name__ == "__main__":
    main()
