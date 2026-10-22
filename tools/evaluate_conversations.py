"""Multi-turn evaluation: does the conversation keep the right scope, resolve references and show the right evidence?

    python tools/evaluate_conversations.py --root <corpus root> --conversations data/evaluations/ocop/conversation_questions.json \
        [--mode sparse|hybrid] [--llm stub|real] [--out result.json] [--set context.key=value]

Turns run through the same ``SessionStore`` the API uses (get -> ask -> save), so whatever memory the product keeps is what
is measured. Per turn: ``expect_slots`` (scope the turn must resolve to), ``absent_slots`` / ``forbid_slot_values`` (stale
scope that must not survive), ``coref`` (the turn only makes sense through a reference). The last turn is also scored on
the prompt the model would receive: gold pages/phrases in SOURCE, and ``forbid_sources`` that must not appear.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.evaluate_question_sets import PromptCapture, RecordingClient, _real_client, fold_text  # noqa: E402

SOURCE_LINE = re.compile(r'\[S\d+\] (\S+), PDF p\.(\d+)')


def norm(value):
    if isinstance(value, list):
        return [norm(v) for v in value]
    text = str(value)
    return (text.lstrip('0') or '0') if text.isdigit() else fold_text(text)


def _matches(got, want) -> bool:
    if norm(got if got is not None else '') == norm(want):
        return True
    return isinstance(want, str) and isinstance(got, str) and norm(want) in norm(got)


def score_turn(turn: dict, slots: dict) -> dict:
    out = {}
    expect = turn.get('expect_slots') or {}
    if expect:
        wrong = {k: slots.get(k) for k, v in expect.items() if not _matches(slots.get(k), v)}
        out['slots_ok'] = not wrong
        out['slots_wrong'] = wrong
    if turn.get('absent_slots') or turn.get('forbid_slot_values'):
        stale = [k for k in turn.get('absent_slots') or [] if slots.get(k) not in (None, '', [])]
        stale += [f'{k}={v}' for k, banned in (turn.get('forbid_slot_values') or {}).items() for v in banned
                  if v in (slots.get(k) or [])]
        out['stale_free'] = not stale
        out['stale'] = stale
    return out


def run(root: Path, conversations: list[dict], *, mode: str, llm: str, memory: bool = True) -> list[dict]:
    from ai_core.orchestration.ocop.sessions import SessionStore
    from ai_core.orchestration.ocop.workflow import OcopAgent
    rows = []
    for conv in conversations:
        client = PromptCapture() if llm == 'stub' else RecordingClient(_real_client())
        agent = OcopAgent(root, llm=client, retrieval_mode='sparse' if mode == 'sparse' else 'hybrid', allow_partial_debug=True)
        store = SessionStore()
        turns, started, final_prompts = [], time.perf_counter(), []
        for turn in conv['turns']:
            client.prompts.clear()
            resp = agent.ask(turn['q'], session=store.get('s') if memory else {})
            store.save('s', turn['q'], resp)
            slots = resp.route.slots
            turns.append({'q': turn['q'], 'intent': resp.intent.value, 'slots': slots, 'coref': bool(turn.get('coref')),
                          **score_turn(turn, slots)})
            final_prompts = list(client.prompts)
        final = conv.get('final') or {}
        text = fold_text(' '.join(final_prompts))
        cited = {(m.group(1), int(m.group(2))) for p in final_prompts for m in SOURCE_LINE.finditer(p)}
        gold = {}
        if final.get('pages'):
            gold['page_in_prompt'] = any(pg in set(final['pages']) for _, pg in cited)
        if final.get('evidence_phrases'):
            gold['phrases_ok'] = all(fold_text(p) in text for p in final['evidence_phrases'])
            gold['content_ok'] = gold.get('page_in_prompt', True) and gold['phrases_ok']
        if final.get('forbid_sources'):
            gold['stale_evidence_free'] = not any(s in final['forbid_sources'] for s, _ in cited)
        gold['prompt_chars'] = sum(map(len, final_prompts))
        rows.append({'id': conv['id'], 'note': conv.get('note'), 'seconds': round(time.perf_counter() - started, 2),
                     'turns': turns, 'final': gold})
    return rows


def summarize(rows: list[dict]) -> dict:
    turns = [t for r in rows for t in r['turns']]

    def rate(items, key):
        items = [t for t in items if key in t]
        return f"{sum(bool(t[key]) for t in items)}/{len(items)}" if items else 'n/a'

    finals = [r['final'] for r in rows]
    chars = sorted(f['prompt_chars'] for f in finals)
    return {'conversations': len(rows), 'turns': len(turns), 'scope_resolution': rate(turns, 'slots_ok'),
            'coreference': rate([t for t in turns if t['coref']], 'slots_ok'), 'stale_scope_free': rate(turns, 'stale_free'),
            'final_page_in_prompt': rate(finals, 'page_in_prompt'), 'final_content_ok': rate(finals, 'content_ok'),
            'final_stale_evidence_free': rate(finals, 'stale_evidence_free'), 'final_prompt_chars_median': chars[len(chars) // 2]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--conversations', type=Path, required=True)
    ap.add_argument('--mode', choices=('sparse', 'hybrid'), default='hybrid')
    ap.add_argument('--llm', choices=('stub', 'real'), default='stub')
    ap.add_argument('--set', nargs='*', default=[])
    ap.add_argument('--no-memory', action='store_true', help='every turn is asked without the session (ablation)')
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    from ai_core.retrieval.ocop.settings import override_settings
    override_settings(args.set)
    rows = run(args.root, json.loads(args.conversations.read_text(encoding='utf-8')), mode=args.mode, llm=args.llm, memory=not args.no_memory)
    summary = {'mode': args.mode, 'llm': args.llm, 'memory': not args.no_memory, **summarize(rows)}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({'summary': summary, 'rows': rows}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    for r in rows:
        bad = [(t['q'], t.get('slots_wrong') or t.get('stale')) for t in r['turns']
               if t.get('slots_ok') is False or t.get('stale_free') is False]
        flags = [k for k, v in r['final'].items() if v is False]
        if bad or flags:
            print(r['id'], flags, bad)


if __name__ == '__main__':
    main()
