"""Score the router on a labelled question set: intent, retrieval lane, clarification, scope and slots.

Each question runs through the agent's ``route`` and ``plan`` steps exactly as ``ask`` does, and earlier questions of a
conversation build the session through the same ``next_state`` the API uses. No tool runs and no model is called unless
``--model`` asks for the second routing tier, so the measurement is fast and repeatable.

    python tools/evaluate_router.py                         # all rows, deterministic tier only
    python tools/evaluate_router.py --model                 # with the model tier (needs the answer model)
    python tools/evaluate_router.py --split dev --errors    # only rows marked "split": "dev", list every miss
    python tools/evaluate_router.py --sealed                # totals only, no per-row output

Row format (JSON lines): id, history (earlier user questions of the conversation), question, gold_intent, gold_lane,
in_scope, gold_clarify, gold_slots, tags, and optionally alt_intent (also accepted) and split ("dev" or "sealed").
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_core.orchestration.ocop.contracts import AgentResponse, Intent, Route  # noqa: E402
from ai_core.orchestration.ocop.capabilities import TOOL_REGISTRY  # noqa: E402
from ai_core.orchestration.ocop.language import fold  # noqa: E402
from ai_core.orchestration.ocop.retrieval_strategy import RetrievalPath, choose_retrieval_path  # noqa: E402
from ai_core.orchestration.ocop.sessions import next_state  # noqa: E402
from ai_core.orchestration.ocop.workflow import OcopAgent  # noqa: E402

DEFAULT = ROOT / "data/evaluations/ocop/ocop_router_gold_80.jsonl"
NO_TOOLS = {Intent.CLARIFY.value, Intent.OUT_OF_SCOPE.value, Intent.CONVERSATION.value}
TOOL_GOLD_FIELDS = ("gold_required_tools", "gold_allowed_tools", "gold_forbidden_tools")


def split_of(row: dict) -> str:
    """The row's own "split", else a fixed one by id: odd numbers are for development, even numbers stay sealed."""
    if row.get("split"):
        return row["split"]
    digits = re.sub(r"\D", "", row["id"])
    return "dev" if int(digits or 0) % 2 else "sealed"


def load(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    intents, lanes = {i.value for i in Intent}, {p.value for p in RetrievalPath}
    seen = set()
    for row in rows:
        problems = []
        if row["id"] in seen:
            problems.append("duplicate id")
        seen.add(row["id"])
        if row["gold_intent"] not in intents or row.get("alt_intent", row["gold_intent"]) not in intents:
            problems.append("unknown intent")
        if row["gold_lane"] not in lanes:
            problems.append("unknown lane")
        if not isinstance(row["history"], list) or not isinstance(row["gold_slots"], dict):
            problems.append("history must be a list and gold_slots an object")
        for field in TOOL_GOLD_FIELDS:
            if field in row and (
                not isinstance(row[field], list)
                or any(not isinstance(name, str) or name not in TOOL_REGISTRY for name in row[field])
            ):
                problems.append(field + " must list registered tool names")
        if problems:
            raise SystemExit(f"{row['id']}: {', '.join(problems)}")
    return rows


def route_turn(agent: OcopAgent, query: str, session: dict) -> tuple[Route, str]:
    """The route a real turn takes: route, then plan unless the turn asks, refuses or chats."""
    state = {"query": query, "session": session, "context": {}, "auth": None}
    state.update(agent.route(state))
    route = Route.model_validate(state["route"])
    if not route.needs_clarification and route.intent.value not in NO_TOOLS:
        state.update(agent.plan(state))
        route = Route.model_validate(state["route"])
    return route, state.get("effective_query", query)


def run_row(agent: OcopAgent, row: dict) -> tuple[Route, str]:
    session: dict = {}
    for earlier in row["history"]:
        route, effective = route_turn(agent, earlier, session)
        reply = AgentResponse(
            answer="", intent=route.intent, status="routed", workflow_engine="eval", route=route,
            standalone_query=effective,
        )
        session = next_state(session, earlier, reply)
    return route_turn(agent, row["question"], session)[0], row["question"]


def _norm(value) -> str:
    return re.sub(r"[^0-9a-z/]", "", fold(str(value)))


def slots_hit(gold: dict, slots: dict) -> tuple[int, int]:
    hit = 0
    for key, wanted in gold.items():
        have = slots.get(key)
        if have is None and key == "document_code":
            have = (slots.get("document_codes") or [None])[0]
        if have is not None and (_norm(have) == _norm(wanted) or _norm(wanted) in _norm(have)):
            hit += 1
    return hit, len(gold)


def score(row: dict, route: Route) -> dict:
    accepted = {row["gold_intent"], row.get("alt_intent")} - {None}
    predicted_clarify = route.needs_clarification or route.intent == Intent.CLARIFY
    hit, total = slots_hit(row["gold_slots"], route.slots)
    primary_lane = choose_retrieval_path(route.required_tools).value
    planned = set(route.required_tools) | set(route.secondary_tools)
    required_gold = set(row.get("gold_required_tools") or [])
    allowed_gold = set(row["gold_allowed_tools"]) if "gold_allowed_tools" in row else None
    return {
        "id": row["id"],
        "question": row["question"],
        "history": row["history"],
        "tags": row["tags"],
        "gold": row["gold_intent"],
        "intent": route.intent.value,
        "gold_lane": row["gold_lane"],
        "lane": route.retrieval_path.value,
        "execution_lane": route.retrieval_path.value,
        "primary_lane": primary_lane,
        "primary_lane_ok": primary_lane == row["gold_lane"],
        "required_tools": list(route.required_tools),
        "secondary_tools": list(route.secondary_tools),
        "planned_tool_count": len(planned),
        "tool_gold": any(field in row for field in TOOL_GOLD_FIELDS),
        "required_tools_hit": len(required_gold & set(route.required_tools)),
        "required_tools_total": len(required_gold),
        "forbidden_tools": sorted(planned & set(row.get("gold_forbidden_tools") or [])),
        "unexpected_tools": sorted(planned - allowed_gold) if allowed_gold is not None else [],
        "intent_ok": route.intent.value in accepted,
        "lane_ok": route.retrieval_path.value == row["gold_lane"],
        "clarify_ok": predicted_clarify == row["gold_clarify"],
        "scope_ok": (route.intent != Intent.OUT_OF_SCOPE) == row["in_scope"],
        "slots_hit": hit,
        "slots_total": total,
        "reasons": route.reason_codes,
    }


def pct(part: int, whole: int) -> str:
    return f"{part}/{whole} ({100 * part / whole:.2f}%)" if whole else "-"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", type=Path, default=DEFAULT)
    parser.add_argument("--split", choices=["dev", "sealed"], help='only rows of this split (a row without one: odd id = dev, even = sealed)')
    parser.add_argument("--model", action="store_true", help="also use the model tier of the router")
    parser.add_argument("--no-semantic", action="store_true", help="switch the embedding tier off (rules only)")
    parser.add_argument("--errors", action="store_true", help="list every row the router got wrong")
    parser.add_argument("--sealed", action="store_true", help="print totals only")
    parser.add_argument("--out", type=Path, help="write the per-row results as JSON lines")
    args = parser.parse_args()

    rows = [r for r in load(args.questions) if not args.split or split_of(r) == args.split]
    if not rows:
        raise SystemExit("no rows selected")
    llm = None
    if args.model:
        from ai_core.orchestration.ocop.llm import make_answer_client

        llm = make_answer_client()
    asked: list[str] = []
    if args.model:
        from ai_core.orchestration.ocop import scope_model

        original = scope_model.propose
        scope_model.propose = lambda model, text: (asked.append(text), original(model, text))[1]
    agent = OcopAgent(ROOT, llm=llm)
    if args.no_semantic:
        agent.semantic_route = None
    results = [score(row, run_row(agent, row)[0]) for row in rows]
    n = len(results)
    total = {k: sum(r[k] for r in results) for k in ("intent_ok", "lane_ok", "clarify_ok", "scope_ok")}
    hits, wanted = sum(r["slots_hit"] for r in results), sum(r["slots_total"] for r in results)
    both = sum(r["intent_ok"] and r["lane_ok"] for r in results)
    tiers = ["rules"] + (["embedding"] if agent.semantic_route else []) + (["model"] if args.model else [])
    print(f"router on {n} questions (tiers: {' + '.join(tiers)})")
    print(f"  intent        {pct(total['intent_ok'], n)}")
    print(f"  lane          {pct(total['lane_ok'], n)}")
    print(f"  intent+lane   {pct(both, n)}")
    print(f"  primary lane  {pct(sum(r['primary_lane_ok'] for r in results), n)}")
    print(f"  intent+primary {pct(sum(r['intent_ok'] and r['primary_lane_ok'] for r in results), n)}")
    print(f"  clarify       {pct(total['clarify_ok'], n)}")
    print(f"  scope         {pct(total['scope_ok'], n)}")
    print(f"  slots         {pct(hits, wanted)}")
    labelled_tools = [r for r in results if r["tool_gold"]]
    if labelled_tools:
        print(f"  tool gold     {len(labelled_tools)}/{n} rows")
        print(f"  required tools {pct(sum(r['required_tools_hit'] for r in labelled_tools), sum(r['required_tools_total'] for r in labelled_tools))}")
        print(f"  forbidden tools {sum(len(r['forbidden_tools']) for r in labelled_tools)} planned")
        print(f"  unexpected tools {sum(len(r['unexpected_tools']) for r in labelled_tools)} planned")
    else:
        print("  tool gold     absent (tool correctness is not scored)")
    if args.model:
        print(f"  model asked   {pct(len(asked), n)} of the questions (the rest the rules and embeddings settled)")
    if args.sealed:
        return 0
    by_intent = collections.defaultdict(lambda: [0, 0])
    for r in results:
        by_intent[r["gold"]][1] += 1
        by_intent[r["gold"]][0] += r["intent_ok"]
    print("\nby gold intent")
    for name, (ok, count) in sorted(by_intent.items(), key=lambda kv: kv[1][0] / kv[1][1]):
        print(f"  {name:24} {pct(ok, count)}")
    by_tag = collections.defaultdict(lambda: [0, 0])
    for r in results:
        for tag in r["tags"]:
            by_tag[tag][1] += 1
            by_tag[tag][0] += r["intent_ok"] and r["lane_ok"]
    weak = [(tag, ok, count) for tag, (ok, count) in by_tag.items() if count >= 2 and ok < count]
    if weak:
        print("\ntags with a miss (intent and lane both right / rows)")
        for tag, ok, count in sorted(weak, key=lambda t: t[1] / t[2]):
            print(f"  {tag:24} {pct(ok, count)}")
    confusion = collections.Counter((r["gold"], r["intent"]) for r in results if not r["intent_ok"])
    if confusion:
        print("\nintent confusions (gold -> predicted)")
        for (gold, got), count in confusion.most_common():
            print(f"  {count}  {gold} -> {got}")
    if args.errors:
        print("\nmisses")
        for r in results:
            if r["intent_ok"] and r["lane_ok"] and r["clarify_ok"] and r["scope_ok"] and r["slots_hit"] == r["slots_total"]:
                continue
            context = f" [after: {' | '.join(r['history'])}]" if r["history"] else ""
            print(f"  {r['id']}  {r['question']}{context}")
            print(f"      intent {r['gold']} -> {r['intent']}   lane {r['gold_lane']} -> {r['lane']}   "
                  f"slots {r['slots_hit']}/{r['slots_total']}   {r['reasons']}")
            if agent.semantic_route:
                proposal = agent.semantic_route(r["question"])
                if proposal:
                    print(f"      embedding: {proposal.intent} score {proposal.score:.2f} margin {proposal.margin:.2f}")
    if args.out:
        args.out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
