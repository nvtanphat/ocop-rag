"""Measure route, tool, prompt-content and ranking quality on a frozen question set.

    python tools/evaluate_question_sets.py --root <corpus root> --questions questions.json \
        [--lock questions.lock.json] [--mode sparse|hybrid|rerank] [--llm stub|real] [--sealed]

``stub`` records the exact prompt the answer LLM would receive and returns no text, so the numbers isolate
retrieval/context quality from generation. ``--sealed`` (held-out sets) prints totals only and writes the
per-question rows to the output file, which must not be opened while tuning. Question schema: docs/EVALUATION.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_core.orchestration.ocop.workflow import OcopAgent  # noqa: E402

PAGE_LINE = re.compile(r'\[S\d+\][^\n]*?, PDF p\.(\d+)')
FIRST_LINE = re.compile(r'\[S1\][^\n]*?, PDF p\.(\d+)')


def fold_text(text: str) -> str:
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', str(text)).casefold())


class PromptCapture:
    """Answer client that records prompts and returns nothing, so the answer falls back to the raw SOURCE."""
    model = 'capture'

    def __init__(self):
        self.prompts: list[str] = []

    def chat(self, system, user, **kwargs):
        self.prompts.append(user)
        return ''

    chat_structured = chat

    def route(self, question):
        raise ValueError('no llm route in capture mode')


class RecordingClient:
    """Wraps the real answer client and keeps every prompt it is sent, so ``--llm real`` is scored on the
    SOURCE the model actually saw (same fields as PromptCapture) and not on the text it wrote back."""

    def __init__(self, inner):
        self._inner = inner
        self.prompts: list[str] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def chat(self, system, user, **kwargs):
        self.prompts.append(user)
        return self._inner.chat(system, user, **kwargs)

    def chat_structured(self, system, user, **kwargs):
        self.prompts.append(user)
        return self._inner.chat_structured(system, user, **kwargs)


def prompt_pages(prompts: list[str]) -> set[int]:
    return {int(m.group(1)) for prompt in prompts for m in PAGE_LINE.finditer(prompt)}


def first_page(prompts: list[str]) -> int | None:
    for prompt in prompts:
        if m := FIRST_LINE.search(prompt):
            return int(m.group(1))
    return None


def conversation_turns(question: dict, questions: list[dict]) -> list[str]:
    if question.get('turns'):
        return question['turns']
    if question.get('conversation'):
        return [x['query'] for x in questions if x.get('conversation') == question['conversation'] and x['id'] <= question['id']]
    return [question['query']]


def evaluate(root: Path, questions: list[dict], *, mode: str, llm: str) -> list[dict]:
    rows = []
    for q in questions:
        client = PromptCapture() if llm == 'stub' else _real_client()
        agent = OcopAgent(root, llm=client, retrieval_mode='sparse' if mode == 'sparse' else 'hybrid',
                          rerank=mode == 'rerank', allow_partial_debug=True)
        session: dict = {}
        resp = None
        error = None
        started = time.perf_counter()
        try:
            for turn in conversation_turns(q, questions):
                if hasattr(client, 'prompts'):
                    client.prompts.clear()
                resp = agent.ask(turn, session=session).model_dump(mode='json')
                session = {'last_query': turn, 'intent': resp['intent'], 'slots': resp['route']['slots'],
                           'capabilities': resp['route']['capabilities']}
        except Exception as exc:  # a failed question is reported, never hidden
            error = f'{type(exc).__name__}: {str(exc)[:160]}'
        row = {'id': q['id'], 'seconds': round(time.perf_counter() - started, 2), 'error': error}
        if resp:
            row.update(_score(q, resp, getattr(client, 'prompts', [])))
        rows.append(row)
    return rows


def _real_client():
    from ai_core.orchestration.ocop.llm import make_answer_client
    return RecordingClient(make_answer_client())


RAW_EXCERPT_STATUSES = {'citation_verification_failed', 'insufficient_context_for_generation', 'model_unavailable_retrieval_only',
                        'retrieval_only'}


def _answer_layer(resp: dict) -> dict:
    """What the answer gate did with the model's text. ``--llm stub`` has no model text, so nothing is reported."""
    cv = resp.get('claim_verification') or {}
    status = cv.get('answer_status') or resp['status']  # debug corpora overwrite status with partial_debug_corpus
    diag = resp.get('generation_diagnostics') or {}
    rejected = diag.get('rejected') or []
    return {'answer_status': status, 'raw_excerpt': status in RAW_EXCERPT_STATUSES,
            'claims_published': len([c for c in cv.get('claims') or [] if c.get('status') == 'supported']),
            'claims_rejected': len(rejected), 'reject_reasons': sorted({x for r in rejected for x in r.get('reasons', [])}
                                                                       or set(diag.get('reasons') or [])),
            'missing_from_source': diag.get('missing_from_source') or []}


def _score(q: dict, resp: dict, prompts: list[str]) -> dict:
    pages = prompt_pages(prompts)
    text = fold_text(' '.join(prompts) if prompts else resp['answer'])
    used = resp['tools_used']
    intent = resp['intent'].lower()
    want = set(q.get('required_any_tools', []))
    out = {'intent': intent, 'tools': used, 'status': resp['status'], 'pages_in_prompt': sorted(pages),
           'intent_ok': intent in q['expected_intents'] and intent not in q.get('forbid_intents', []),
           'tool_ok': (bool(want & set(used)) if want else not used) and not (set(q.get('forbid_tools', [])) & set(used))}
    if q.get('pages') and want:
        out['page_in_prompt'] = bool(set(q['pages']) & pages)
        out['top1_page_ok'] = first_page(prompts) in q['pages']
        out['phrases_ok'] = all(fold_text(p) in text for p in q.get('evidence_phrases', []))
        out['content_ok'] = out['page_in_prompt'] and out['phrases_ok']
    out.update(_answer_layer(resp))
    if q.get('trap'):
        out['trap_safe'] = 'sk-' not in resp['answer']
    return out


def _answer_totals(rows: list[dict]) -> dict:
    graded = [r for r in rows if 'answer_status' in r and r['tools']]
    return {'raw_excerpt': sum(r['raw_excerpt'] for r in graded), 'claims_published': sum(r['claims_published'] for r in graded),
            'claims_rejected': sum(r['claims_rejected'] for r in graded)}


def summarize(rows: list[dict]) -> dict:
    def rate(key):
        items = [r for r in rows if key in r]
        return f"{sum(bool(r[key]) for r in items)}/{len(items)}" if items else 'n/a'
    seconds = sorted(r['seconds'] for r in rows)
    return {'questions': len(rows), 'errors': sum(1 for r in rows if r['error']),
            **{k: rate(k) for k in ('intent_ok', 'tool_ok', 'page_in_prompt', 'content_ok', 'top1_page_ok', 'trap_safe')},
            'median_s': seconds[len(seconds) // 2] if seconds else None, 'max_s': seconds[-1] if seconds else None,
            **_answer_totals(rows)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', type=Path, required=True, help='corpus root (configs/ + data/processed/ocop)')
    ap.add_argument('--questions', type=Path, required=True)
    ap.add_argument('--lock', type=Path, help='JSON {file name: sha256}; refuse to run if the questions changed')
    ap.add_argument('--mode', choices=('sparse', 'hybrid', 'rerank'), default='sparse')
    ap.add_argument('--llm', choices=('stub', 'real'), default='stub')
    ap.add_argument('--out', type=Path)
    ap.add_argument('--sealed', action='store_true', help='print totals only')
    args = ap.parse_args()
    if args.lock:
        lock = json.loads(args.lock.read_text(encoding='utf-8'))
        if hashlib.sha256(args.questions.read_bytes()).hexdigest() != lock.get(args.questions.name):
            sys.exit('question set changed after it was frozen')
    questions = json.loads(args.questions.read_text(encoding='utf-8'))
    rows = evaluate(args.root, questions, mode=args.mode, llm=args.llm)
    summary = {'mode': args.mode, 'llm': args.llm, **summarize(rows)}
    if args.llm == 'stub':  # the capture client writes no text: answer-layer counts would only describe the stub
        for key in ('raw_excerpt', 'claims_published', 'claims_rejected'):
            summary.pop(key)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({'summary': summary, 'rows': rows}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    if not args.sealed:
        for r in rows:
            bad = [k for k in ('intent_ok', 'tool_ok', 'page_in_prompt', 'phrases_ok', 'trap_safe') if r.get(k) is False]
            if bad or r['error']:
                print(r['id'], bad, r.get('intent'), r.get('tools'), r.get('status'), r['error'] or '')


if __name__ == '__main__':
    main()
