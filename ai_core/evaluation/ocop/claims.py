"""Claim-level grounding evaluation over questions whose evidence a human has reviewed.

A question is eligible when every page it targets has at least one EvidenceUnit node with
``check: human_verified`` in the current graph (the ledger written by the review CLI). The evaluation never
marks anything verified and never relaxes a gate: it reports, per question, what the unchanged gates
published, what they dropped and why.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

PUBLISHED = ("generated_claims_verified", "generated_unverified_claims")
PARTIAL = "partial_claims_verified"


def reviewed_pages(root: Path) -> dict[str, set[int]]:
    """source_id -> pages that carry at least one human_verified EvidenceUnit node."""
    from ai_core.graph.ocop.builder import records

    graph = Path(root) / "data/processed/ocop/graph"
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


def evaluate_claim_grounding(
    root: Path,
    questions: list[dict],
    *,
    agent_factory: Callable | None = None,
    mode: str = "sparse",
    limit: int | None = None,
    output_dir: Path | None = None,
) -> dict:
    """Run the unchanged claim gates on reviewed-evidence questions and summarise the outcome."""
    root = Path(root).resolve()
    chosen = eligible(questions, reviewed_pages(root))[:limit]
    report: dict = {
        "eligible_questions": len(chosen),
        "published": 0,
        "partial": 0,
        "blocked": 0,
        "errors": 0,
        "cases": [],
    }
    if chosen:
        if agent_factory is None:
            from ai_core.orchestration.ocop.llm import make_answer_client
            from ai_core.orchestration.ocop.workflow import OcopAgent

            def agent_factory(path):
                return OcopAgent(path, llm=make_answer_client(), retrieval_mode=mode, allow_partial_debug=True)

        agent = agent_factory(root)
        for question in chosen:
            try:
                response = agent.ask(question["query"]).model_dump(mode="json")
            except Exception as exc:  # a failed run is recorded, never counted as a pass
                report["errors"] += 1
                report["cases"].append(
                    {"id": question["id"], "status": "error", "error": type(exc).__name__ + ": " + str(exc)[:100]}
                )
                continue
            diagnostics = response.get("generation_diagnostics", {})
            status = response["status"]
            key = "published" if status in PUBLISHED else "partial" if status == PARTIAL else "blocked"
            report[key] += 1
            report["cases"].append(
                {
                    "id": question["id"],
                    "status": status,
                    "accepted": diagnostics.get("accepted"),
                    "rejected": diagnostics.get("rejected"),
                    "missing": diagnostics.get("missing_from_source"),
                    "reasons": diagnostics.get("reasons"),
                }
            )
    report["publish_rate"] = (
        round((report["published"] + report["partial"]) / len(chosen), 4) if chosen else 0.0
    )
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "claim_grounding.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report
