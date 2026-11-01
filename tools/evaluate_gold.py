"""Run and score the OCOP gold sets in data/evaluations/ocop, page by page.

    python tools/evaluate_gold.py run retrieval --out ../ocop-eval-runs/ret.jsonl [--ids R001,R002 | --sample 5 --seed 7]
        [--llm stub|real] [--real-for followup,aspects,scope] [--resume]
    python tools/evaluate_gold.py score retrieval ../ocop-eval-runs/ret.jsonl [--compare ../ocop-eval-runs/old.jsonl]

Sets: retrieval (100), multihop (25), session (50 turns, run conversation by conversation), abstention (20),
citation (60). The router set has its own tool (tools/evaluate_router.py).

Every row stores the (source_id, pdf_page) of each citation, in answer order, so a run stays scorable after a
rebuild changes the evidence ids. ``stub`` returns no model text: the numbers measure the evidence that reaches the
prompt, not the answer. ``--real-for`` sends only the named model steps to the real model (the follow-up rewrite,
the aspect splitter, the scope tier) and keeps the rest stubbed. A run refuses to start when hybrid search falls back
to sparse, which happens silently when the ocop-qdrant container is down.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GOLD = ROOT / "data/evaluations/ocop"
SETS = {
    "retrieval": "ocop_retrieval_gold_100_natural_final.json",
    "multihop": "ocop_graphrag_multihop_gold_25.json",
    "session": "ocop_session_memory_gold_50.json",
    "abstention": "ocop_abstention_gold_20.json",
    "citation": "ocop_answer_citation_gold_60.json",
}
MARKER = re.compile(r"\[S(\d+)\]")


def questions(name: str) -> list[dict]:
    return json.loads((GOLD / SETS[name]).read_text(encoding="utf-8"))["questions"]


def question_text(q: dict) -> str:
    return q.get("query") or q.get("question") or ""


def page(row: dict) -> tuple[str, int]:
    return row["source_id"], int(row["pdf_page"])


# ---------------------------------------------------------------- running


def _client(llm: str, real_for: list[str]):
    from tools.evaluate_question_sets import PromptCapture, RecordingClient, _real_client

    if llm == "real":
        return RecordingClient(_real_client())
    if not real_for:
        return PromptCapture()
    from ai_core.orchestration.ocop import aspects, followup_model, scope_model

    systems = {"followup": followup_model.SYSTEM, "aspects": aspects.SYSTEM, "scope": scope_model.SYSTEM}
    unknown = set(real_for) - set(systems)
    if unknown:
        raise SystemExit(f"--real-for knows {sorted(systems)}, not {sorted(unknown)}")
    chosen = {systems[step] for step in real_for}
    real = _real_client()

    class Selective(PromptCapture):
        def chat_structured(self, system, user, **kwargs):
            return real.chat_structured(system, user, **kwargs) if system in chosen else super().chat(system, user)

    return Selective()


def _require_hybrid() -> None:
    from ai_core.retrieval.ocop.search import search

    row = search(ROOT / "data/processed/ocop/index", "hạn nộp hồ sơ OCOP", mode="hybrid", top_k=1)[0]
    if row.get("retrieval_mode") != "hybrid":
        raise SystemExit(f"dense retrieval unavailable ({row.get('retrieval_fallback_reason')}): start ocop-qdrant first")


def _row(q: dict, response, started: float) -> dict:
    r = response.model_dump(mode="json")
    citations = [c for c in r.get("citations", []) if isinstance(c, dict) and c.get("source_id")]
    used = [int(n) for n in dict.fromkeys(MARKER.findall(r.get("answer") or ""))]
    return {
        "id": q["id"],
        "ok": True,
        "status": r.get("status"),
        "intent": r.get("intent"),
        "tools": r.get("tools_used"),
        "standalone": r.get("standalone_query"),
        "pages": [list(page(c)) for c in citations],
        "cited_pages": [list(page(citations[n - 1])) for n in used if 0 < n <= len(citations)],
        "answer": (r.get("answer") or "")[:3000],
        "claims": (r.get("claim_verification") or {}).get("claims"),
        "s": round(time.perf_counter() - started, 1),
    }


def run(args) -> None:
    from ai_core.orchestration.ocop.sessions import SessionStore
    from ai_core.orchestration.ocop.workflow import OcopAgent

    _require_hybrid()
    pool = questions(args.set)
    if args.ids:
        wanted = args.ids.split(",")
        pool = [q for q in pool if q["id"] in wanted]
    elif args.sample:
        pool = random.Random(args.seed).sample(pool, min(args.sample, len(pool)))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(line)["id"] for line in out.open(encoding="utf-8")} if args.resume and out.exists() else set()
    agent = OcopAgent(ROOT, llm=_client(args.llm, args.real_for), retrieval_mode="hybrid", rerank=True)
    if args.set == "session":
        # A turn only means something after the turns before it: whole conversations run, in order.
        conversations = {q["conversation_id"] for q in pool}
        pool = sorted(
            (q for q in questions("session") if q["conversation_id"] in conversations),
            key=lambda q: (q["conversation_id"], q["turn_index"]),
        )
    store, conversation = SessionStore(), None
    with out.open("a" if args.resume else "w", encoding="utf-8") as fh:
        for q in pool:
            if args.set == "session" and q["conversation_id"] != conversation:
                store, conversation = SessionStore(), q["conversation_id"]
            if q["id"] in done:
                continue
            started = time.perf_counter()
            try:
                session = store.get("s") if args.set == "session" else {}
                response = agent.ask(question_text(q), session=session)
                if args.set == "session":
                    store.save("s", question_text(q), response)
                row = _row(q, response, started)
            except Exception as exc:  # noqa: BLE001 - one failing question is reported, the run goes on
                row = {"id": q["id"], "ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print(q["id"], row.get("status") or row.get("error"), row.get("s", ""), flush=True)


# ---------------------------------------------------------------- scoring


def _gold_pages(q: dict) -> tuple[set, set]:
    gold = {page(g) for g in q.get("gold_evidence") or q.get("gold_citations") or []}
    return gold, {page(g) for g in q.get("alternative_evidence", [])}


def _rank(row: dict, wanted: set) -> int | None:
    return next((k for k, p in enumerate(row["pages"], 1) if tuple(p) in wanted), None)


def score_question(name: str, q: dict, row: dict) -> dict:
    """The per-question verdicts of one set; pure, so it is unit-tested without running the agent."""
    if not row.get("ok"):
        return {"error": True}
    got = {tuple(p) for p in row["pages"]}
    gold, alternative = _gold_pages(q)
    if name in ("retrieval", "session"):
        if not gold and not alternative:
            return {"no_gold": True}  # a clarification turn has no page to find; it is not scored
        rank = _rank(row, gold | alternative)
        complete = gold <= got or bool(alternative & got)
        return {"any": rank is not None, "all": complete, "top1": rank == 1, "rank": rank}
    if name == "multihop":
        by_unit = {g["evidence_unit_id"]: page(g) for g in q["gold_evidence"]}
        steps = [any(by_unit.get(u) in got for u in s["evidence_unit_ids"]) for s in q["reasoning_steps"]]
        return {"steps": sum(steps), "of": len(steps), "full": all(steps)}
    if name == "abstention":
        # Refused = no answer was published with a citation marker; a stub run never publishes, so judge on a real run.
        refused = not row["cited_pages"]
        return {"expected_abstain": q.get("expected_behavior") == "ABSTAIN", "refused": refused}
    if name == "citation":
        cited = {tuple(p) for p in row["cited_pages"]}
        return {
            "gold_cited": len(gold & cited),
            "gold": len(gold),
            "cited": len(cited),
            "cited_gold": len(cited & gold),
            "claims_supported": sum(1 for c in row.get("claims") or [] if c.get("status") == "supported"),
            "required_claims": len(q.get("required_claims", [])),
        }
    raise ValueError(name)


def totals(name: str, verdicts: list[dict]) -> dict:
    ok = [v for v in verdicts if not v.get("error") and not v.get("no_gold")]
    n = len(ok)
    out = {"questions": len(verdicts), "errors": sum(1 for v in verdicts if v.get("error")), "scored": n}
    if not n:
        return out
    if name in ("retrieval", "session"):
        out |= {k: sum(v[k] for v in ok) for k in ("any", "all", "top1")}
        out["mrr"] = round(sum(1 / v["rank"] for v in ok if v["rank"]) / n, 3)
        for k in (3, 5, 10):
            out[f"recall@{k}"] = round(sum(1 for v in ok if v["rank"] and v["rank"] <= k) / n, 3)
    elif name == "multihop":
        out |= {"steps": sum(v["steps"] for v in ok), "of": sum(v["of"] for v in ok), "full": sum(v["full"] for v in ok)}
    elif name == "abstention":
        expected = [v for v in ok if v["expected_abstain"]]
        out |= {"correct_rejections": sum(v["refused"] for v in expected), "should_refuse": len(expected),
                "false_answers": sum(not v["refused"] for v in expected)}
    elif name == "citation":
        gold, cited = sum(v["gold"] for v in ok), sum(v["cited"] for v in ok)
        out |= {
            "citation_recall": round(sum(v["gold_cited"] for v in ok) / gold, 3) if gold else None,
            "citation_precision": round(sum(v["cited_gold"] for v in ok) / cited, 3) if cited else None,
            "claims_supported": sum(v["claims_supported"] for v in ok),
            "required_claims": sum(v["required_claims"] for v in ok),
        }
    return out


def _load(path: str) -> dict:
    return {row["id"]: row for row in map(json.loads, Path(path).open(encoding="utf-8"))}


def score(args) -> None:
    gold = {q["id"]: q for q in questions(args.set)}
    rows = _load(args.run)
    verdicts = {i: score_question(args.set, gold[i], row) for i, row in rows.items()}
    seconds = [row["s"] for row in rows.values() if row.get("ok")]
    result = totals(args.set, list(verdicts.values()))
    result["avg_seconds"] = round(sum(seconds) / len(seconds), 1) if seconds else None
    print(json.dumps(result, ensure_ascii=False))
    if args.compare:
        before = {i: score_question(args.set, gold[i], row) for i, row in _load(args.compare).items()}
        shared = [i for i in verdicts if i in before]
        print("compared on", len(shared), "questions; before:", json.dumps(totals(args.set, [before[i] for i in shared])))
        for i in shared:
            if verdicts[i] != before[i]:
                print(f"  {i}: {before[i]} -> {verdicts[i]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("set", choices=sorted(SETS))
    r.add_argument("--out", required=True, help="JSONL file for the rows; keep it outside the repo")
    r.add_argument("--ids")
    r.add_argument("--sample", type=int)
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--llm", choices=("stub", "real"), default="stub")
    r.add_argument("--real-for", type=lambda s: [x for x in s.split(",") if x], default=[])
    r.add_argument("--resume", action="store_true")
    s = sub.add_parser("score")
    s.add_argument("set", choices=sorted(SETS))
    s.add_argument("run")
    s.add_argument("--compare")
    args = parser.parse_args()
    run(args) if args.command == "run" else score(args)


if __name__ == "__main__":
    main()
