"""Retrieval-to-Prompt Evidence Tracer: where does the evidence for a question get lost?

    python tools/trace_evidence.py --root <corpus root> --questions questions.json [--ids 4 9] [--mode hybrid|sparse|rerank]
        [--llm stub|real] [--out trace.json] [--html trace.html]
    python tools/trace_evidence.py --root <corpus root> --query "Hạn nộp hồ sơ ..." --pages 3 --phrases "15/10/2026"

The question is answered by the production OcopAgent. Every stage reports through ``ai_core.system.stage_trace``
(search pools, fusion, rerank, tool output, context packing, token budget) and the answer client is wrapped so the
prompt that really reached the model is kept. Gold evidence (page + phrases a human wrote) is then looked up at each
stage with the same folded-text comparison, which names the first stage that lost it:

    evidence_unit -> chunk -> candidate pool -> fusion -> rerank -> returned -> tool output
        -> context candidates -> merged -> deduped -> packed -> budgeted excerpt -> final prompt

Nothing here re-implements a stage; the verdict is only as good as the events the production code emits.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_core.retrieval.ocop.structure_chunker import estimated_tokens  # noqa: E402
from ai_core.system import stage_trace  # noqa: E402

STAGES = ['evidence_unit', 'chunk', 'pool', 'fused', 'reranked', 'returned', 'tool_output',
          'ctx_candidates', 'ctx_merged', 'ctx_deduped', 'ctx_packed', 'ctx_budgeted', 'prompt']
VERDICT = {  # first stage that lost gold evidence -> what to look at
    'evidence_unit': 'source_evidence_lacks_content (OCR / extraction: the EvidenceUnit does not hold the gold phrase)',
    'chunk': 'chunking_lost_context (a unit holds the phrase but no single chunk does)',
    'pool': 'retrieval_miss (gold chunk is in the index but neither BM25 nor dense produced it)',
    'fused': 'fusion_cut (gold chunk was in a pool and dropped by RRF/pool size)',
    'reranked': 'rerank_pushed_out (gold chunk fell out of the reranked head)',
    'returned': 'top_k_cut (gold chunk ranked below top_k)',
    'tool_output': 'tool_aggregation_lost (search returned it, the tool result did not carry it)',
    'ctx_candidates': 'context_input_dropped (unusable provenance / conflicting duplicate)',
    'ctx_merged': 'continuation_merge_lost',
    'ctx_deduped': 'dedup_removed_gold (same-page repeat removal)',
    'ctx_packed': 'context_selection_dropped (max_source_blocks / coverage packing)',
    'ctx_budgeted': 'token_budget_cut (window or row removed to fit the prompt budget)',
    'prompt': 'prompt_assembly_lost',
}


def fold(text) -> str:
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', str(text)).casefold())


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


class Gold:
    """Pages and phrases a human wrote down; a stage 'has' the gold when its text holds every phrase."""

    def __init__(self, pages, phrases):
        self.pages = set(pages or [])
        self.phrases = [fold(p) for p in phrases or []]

    def phrase_hits(self, text: str) -> int:
        folded = fold(text)
        return sum(p in folded for p in self.phrases)

    def has(self, items: list[dict]) -> dict:
        """items: [{'pdf_page', 'text'}]; page_hit is page-level, content_hit needs the phrases (all of them)."""
        on_page = [i for i in items if not self.pages or i.get('pdf_page') in self.pages]
        joined = '\n'.join(str(i.get('text') or '') for i in on_page)
        return {'items': len(items), 'page_hit': bool(on_page) and bool(self.pages),
                'phrases_found': self.phrase_hits(joined), 'phrases_total': len(self.phrases),
                'content_hit': bool(on_page) and (not self.phrases or self.phrase_hits(joined) == len(self.phrases)),
                'tokens': sum(estimated_tokens(str(i.get('text') or '')) for i in items)}


class RecordingClient:
    """Keeps system+user of every call; ``real`` forwards to the configured model, ``stub`` returns no text."""

    def __init__(self, inner=None):
        self.inner, self.calls, self.model = inner, [], getattr(inner, 'model', 'capture')

    def _go(self, kind, system, user, **kw):
        self.calls.append({'kind': kind, 'system': system, 'user': user, 'options': {k: v for k, v in kw.items() if k != 'schema'}})
        if self.inner is None:
            return ''
        out = getattr(self.inner, kind)(system, user, **kw)
        self.calls[-1]['output'] = out
        return out

    def chat(self, system, user, **kw):
        return self._go('chat', system, user, **kw)

    def chat_structured(self, system, user, **kw):
        return self._go('chat_structured', system, user, **kw)

    def route(self, question):
        if self.inner is None:
            raise ValueError('no llm route in capture mode')
        return self.inner.route(question)


def index_stages(root: Path, gold: Gold) -> dict:
    """The two stages before retrieval, read from the production index files."""
    folder = root / 'data/processed/ocop/index'
    units = [{'pdf_page': next((s.get('pdf_page') for s in u.get('spans', []) if isinstance(s, dict)), None), 'text': u.get('text')}
             for u in read_jsonl(folder / 'evidence_units.jsonl')]
    chunks = [{'pdf_page': next((s.get('pdf_page') for s in c.get('spans', []) if isinstance(s, dict)), None),
               'text': c.get('raw_text') or c.get('text_for_bm25')} for c in read_jsonl(folder / 'chunks.jsonl')]
    on = lambda rows: [r for r in rows if r['pdf_page'] in gold.pages]  # noqa: E731
    out = {'evidence_unit': gold.has(on(units)), 'chunk': gold.has(on(chunks))}
    # one unit holds all phrases but no chunk does -> the chunker cut across the answer
    out['chunk']['split_by_chunking'] = bool(gold.phrases) and out['evidence_unit']['content_hit'] and not any(
        gold.has([c])['content_hit'] for c in on(chunks))
    return out


def chunk_texts(root: Path) -> dict:
    return {c['chunk_id']: {'pdf_page': next((s.get('pdf_page') for s in c.get('spans', []) if isinstance(s, dict)), None),
                            'text': c.get('raw_text') or c.get('text_for_bm25')}
            for c in read_jsonl(root / 'data/processed/ocop/index/chunks.jsonl')}


def stage_view(events: list[dict], chunks: dict) -> dict:
    """Group events by stage into [{'pdf_page','text','chunk_id'}] lists (several searches/tools accumulate)."""
    view = {k: [] for k in STAGES if k not in ('evidence_unit', 'chunk')}

    def from_ids(rows):
        return [{**chunks[r['chunk_id']], 'chunk_id': r['chunk_id']} for r in rows if r.get('chunk_id') in chunks]

    for ev in events:
        st = ev['stage']
        if st == 'search.pools':
            view['pool'] += from_ids(ev['sparse'] + ev['dense'])
        elif st == 'search.fused':
            view['fused'] += from_ids(ev['items'])
        elif st == 'search.reranked':
            view['reranked'] += from_ids(ev['order'])
        elif st == 'search.returned':
            view['returned'] += [{'pdf_page': i['pdf_page'], 'text': i['raw_text'], 'chunk_id': i['chunk_id']} for i in ev['items']]
        elif st == 'tool.output':
            view['tool_output'] += [{**chunks.get(r.get('chunk_id'), {'pdf_page': r.get('pdf_page'), 'text': ''}), 'chunk_id': r.get('chunk_id')}
                                    for r in ev['rows']]
        elif st in ('context.candidates', 'context.merged', 'context.deduped', 'context.packed'):
            name = {'context.candidates': 'ctx_candidates', 'context.merged': 'ctx_merged', 'context.deduped': 'ctx_deduped',
                    'context.packed': 'ctx_packed'}[st]
            view[name] = [{'pdf_page': i['pdf_page'], 'text': i['raw_text'], 'chunk_id': i['chunk_id']} for i in ev['items']]
        elif st == 'context.budget':
            view['ctx_budgeted'] = [{'pdf_page': i['pdf_page'], 'text': i.get('display', ''), 'chunk_id': i['chunk_id']}
                                    for i in ev['items'] if not i['dropped']]
    if not view['reranked']:
        view.pop('reranked')
    return view


def source_part(prompt: str) -> list[dict]:
    """SOURCE blocks of a prompt: [{'pdf_page','text'}] split on the [S#] headers."""
    blocks = re.split(r'(?m)^(?=\[S\d+\] )', prompt.split('SOURCE:', 1)[-1])
    out = []
    for block in blocks:
        m = re.match(r'\[S\d+\][^\n]*?, PDF p\.(\d+)', block)
        if m:
            out.append({'pdf_page': int(m.group(1)), 'text': block})
    return out


def diagnose(stages: dict) -> dict:
    """First stage whose predecessor still held the gold content but which no longer does."""
    held = None
    for name in STAGES:
        if name not in stages:
            continue
        hit = stages[name]['content_hit']
        if hit:
            held = name
        elif held is not None and name not in ('evidence_unit',):
            return {'lost_at': name, 'last_held': held, 'verdict': VERDICT[name]}
        elif held is None and name in ('evidence_unit', 'chunk'):
            return {'lost_at': name, 'last_held': None, 'verdict': VERDICT[name]}
    if held == 'prompt':
        return {'lost_at': None, 'last_held': 'prompt', 'verdict': 'llm_received_gold_evidence (a wrong answer is generation, not retrieval)'}
    if held is None:
        return {'lost_at': 'pool', 'last_held': None, 'verdict': VERDICT['pool']}
    return {'lost_at': None, 'last_held': held, 'verdict': 'gold_survived_to_' + held}


def _memory_reuse(events: list[dict], gold: Gold) -> dict | None:
    """Reused evidence references: how many reached the prompt and how many of those are on a gold page."""
    ev = next((e for e in events if e['stage'] == 'memory.evidence'), None)
    if ev is None:
        return None
    budget = next((e for e in events if e['stage'] == 'context.budget'), {'items': []})
    shown = {i['chunk_id']: i['pdf_page'] for i in budget['items'] if not i['dropped']}
    reused = ev['reused']
    in_prompt = [c for c in reused if c in shown]
    return {'kept_refs': len(ev['kept']), 'dropped_refs': len(ev['dropped']), 'reused_rows': len(reused), 'in_prompt': len(in_prompt),
            'on_gold_page': sum(1 for c in in_prompt if shown[c] in gold.pages)}


def trace_question(agent_factory, root: Path, q: dict, chunks: dict, mode: str, client_factory, turns_of) -> dict:
    gold = Gold(q.get('pages'), q.get('evidence_phrases'))
    client = client_factory()
    agent = agent_factory(client)
    from ai_core.orchestration.ocop.sessions import SessionStore
    store = SessionStore()  # the store the API uses, so memory (referents, evidence references) is traced as it is served
    events: list[dict] = []
    resp = None
    memory_out = None
    for turn in turns_of(q):
        client.calls.clear()
        with stage_trace.tracing() as ev:
            answer = agent.ask(turn, session=store.get('s'))
        events = ev  # only the last turn is scored; earlier turns only build the memory
        store.save('s', turn, answer)
        resp = answer.model_dump(mode='json')
        memory_out = store.get('s').get('memory')
    view = stage_view(events, chunks)
    prompt_calls = [c for c in client.calls if c['kind'] == 'chat_structured' or c['kind'] == 'chat']
    answer_prompt = next((c for c in prompt_calls if 'SOURCE:' in c['user']), None)
    view['prompt'] = source_part(answer_prompt['user']) if answer_prompt else []
    stages = {}
    if gold.pages:
        stages.update(index_stages(root, gold))
    for name in STAGES:
        if name in view:
            stages[name] = gold.has(view[name]) if gold.pages else {'items': len(view[name]), 'tokens': sum(
                estimated_tokens(str(i.get('text') or '')) for i in view[name])}
    report = {
        'id': q.get('id'), 'query': q.get('query') or turns_of(q)[-1], 'turns': turns_of(q), 'gold': {'pages': sorted(gold.pages), 'phrases': q.get('evidence_phrases', [])},
        'memory': {'read': next((e for e in events if e['stage'] == 'memory.read'), None), 'written': memory_out,
                   'evidence': next((e for e in events if e['stage'] == 'memory.evidence'), None)},
        'route': {'intent': resp['intent'], 'tools': resp['tools_used'], 'retrieval_path': next(
            (t.get('retrieval_path') for t in resp['tool_trace'] if t.get('step') == 'retrieval_strategy'), None)},
        'searches': [{'query': e['query'], 'mode': e['mode'], 'fallback': e['fallback_reason'], 'admissible_chunks': e['admissible_chunks'],
                      'sparse': len(e['sparse']), 'dense': len(e['dense'])} for e in events if e['stage'] == 'search.pools'],
        'stages': stages,
        'context': {'budget': next((e for e in events if e['stage'] == 'context.budget'), None),
                    'input': next((e for e in events if e['stage'] == 'context.input'), None)},
        'prompt': None if answer_prompt is None else {
            'system': answer_prompt['system'], 'user': answer_prompt['user'],
            'estimated_tokens': estimated_tokens(answer_prompt['system']) + estimated_tokens(answer_prompt['user']),
            'source_blocks': len(view['prompt'])},
        'memory_reuse': _memory_reuse(events, gold),
        'answer_status': (resp['claim_verification'] or {}).get('answer_status') or resp['status'],
        'uncovered_parts': (resp.get('evidence_grade') or {}).get('uncovered_parts', []),
    }
    if gold.pages:
        report['diagnosis'] = diagnose(stages)
    return report


def summarize(reports: list[dict]) -> dict:
    """Survival of gold evidence per stage, context precision and prompt cost over the questions that have gold."""
    gold = [r for r in reports if r['gold']['pages']]
    survive = {name: sum(1 for r in gold if r['stages'].get(name, {}).get('content_hit')) for name in STAGES}
    answered = [r for r in gold if r['prompt']]
    # a prompt block is useful when it is on a gold page; precision = useful blocks / blocks
    useful = sum(r['stages']['prompt']['page_hit'] and sum(1 for b in source_part(r['prompt']['user'])
                                                          if b['pdf_page'] in r['gold']['pages']) for r in answered if 'prompt' in r['stages'])
    blocks = sum(r['prompt']['source_blocks'] for r in answered)
    tokens = sorted(r['prompt']['estimated_tokens'] for r in answered)
    reuse = [r['memory_reuse'] for r in reports if r.get('memory_reuse')]
    memory = {'turns_with_reuse': len(reuse), 'reused_rows': sum(r['reused_rows'] for r in reuse),
              'in_prompt': sum(r['in_prompt'] for r in reuse), 'on_gold_page': sum(r['on_gold_page'] for r in reuse)} if reuse else None
    return {'memory_reuse': memory, 'gold_questions': len(gold), 'gold_survives_to': survive,
            'context_precision': round(useful / blocks, 3) if blocks else None,
            'prompt_tokens_median': tokens[len(tokens) // 2] if tokens else None, 'prompt_tokens_max': tokens[-1] if tokens else None,
            'source_blocks_mean': round(blocks / len(answered), 2) if answered else None}


def render_html(reports: list[dict]) -> str:
    def cell(stage):
        if stage is None:
            return '<td class="na">·</td>'
        ok = stage.get('content_hit', stage.get('items', 0) > 0)
        tip = f"{stage.get('phrases_found', '')}/{stage.get('phrases_total', '')} cụm · {stage.get('items', 0)} mục · {stage.get('tokens', 0)} token"
        return f'<td class="{"ok" if ok else "bad"}" title="{html.escape(tip)}">{"✓" if ok else "✗"}</td>'

    head = ''.join(f'<th>{s}</th>' for s in STAGES)
    rows = []
    for r in reports:
        d = r.get('diagnosis', {})
        rows.append(f'<tr><td>{r["id"]}</td><td class="q">{html.escape(str(r["query"]))[:90]}</td>' +
                    ''.join(cell(r['stages'].get(s)) for s in STAGES) +
                    f'<td>{html.escape(str(d.get("lost_at") or "—"))}</td></tr>')
    details = ''.join(
        f'<details><summary>#{r["id"]} {html.escape(str(r["query"]))[:80]} — {html.escape(r.get("diagnosis", {}).get("verdict", ""))}</summary>'
        f'<pre>{html.escape(json.dumps({k: r[k] for k in ("memory", "route", "searches", "uncovered_parts", "answer_status")}, ensure_ascii=False, indent=1, default=str))}</pre>'
        f'<h4>Prompt gửi tới mô hình</h4><pre>{html.escape((r["prompt"] or {}).get("user", "(không có lời gọi sinh câu trả lời)"))}</pre></details>'
        for r in reports)
    return ('<!doctype html><meta charset="utf-8"><title>Evidence trace</title><style>body{font:13px system-ui;margin:20px}'
            'table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:3px 6px;text-align:center}.q{text-align:left;max-width:360px}'
            '.ok{background:#e4f3e4}.bad{background:#f8dcdc}.na{color:#aaa}th{font-size:11px}pre{white-space:pre-wrap;background:#f6f6f6;padding:8px}'
            f'</style><h1>Retrieval-to-Prompt trace</h1><table><tr><th>id</th><th>câu hỏi</th>{head}<th>mất ở</th></tr>{"".join(rows)}</table>{details}')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--questions', type=Path)
    ap.add_argument('--conversations', type=Path, help='multi-turn file (evaluate_conversations format); the last turn is traced')
    ap.add_argument('--ids', type=int, nargs='*')
    ap.add_argument('--query')
    ap.add_argument('--pages', type=int, nargs='*', default=[])
    ap.add_argument('--phrases', nargs='*', default=[])
    ap.add_argument('--mode', choices=('sparse', 'hybrid', 'rerank'), default='hybrid')
    ap.add_argument('--llm', choices=('stub', 'real'), default='stub')
    ap.add_argument('--set', nargs='*', default=[], metavar='section.key=value', help='override a retrieval setting for this run, e.g. context.fill_min_blocks=6')
    ap.add_argument('--out', type=Path)
    ap.add_argument('--html', type=Path)
    args = ap.parse_args()
    if args.query:
        questions = [{'id': 0, 'query': args.query, 'pages': args.pages, 'evidence_phrases': args.phrases}]
    elif args.conversations:
        questions = [{'id': c['id'], 'query': c['turns'][-1]['q'], 'turns': [t['q'] for t in c['turns']],
                      'pages': (c.get('final') or {}).get('pages', []), 'evidence_phrases': (c.get('final') or {}).get('evidence_phrases', [])}
                     for c in json.loads(args.conversations.read_text(encoding='utf-8'))]
    elif args.questions:
        questions = json.loads(args.questions.read_text(encoding='utf-8'))
    else:
        ap.error('give --query, --questions or --conversations')
    all_questions = questions
    if args.ids:
        questions = [q for q in questions if q['id'] in set(args.ids)]

    from ai_core.orchestration.ocop.workflow import OcopAgent
    from ai_core.retrieval.ocop.settings import override_settings
    override_settings(args.set)

    def turns_of(q):
        if q.get('turns'):
            return q['turns']
        if q.get('conversation'):
            return [x['query'] for x in all_questions if x.get('conversation') == q['conversation'] and x['id'] <= q['id']]
        return [q['query']]

    def client_factory():
        if args.llm == 'real':
            from ai_core.orchestration.ocop.llm import make_answer_client
            return RecordingClient(make_answer_client())
        return RecordingClient()

    chunks = chunk_texts(args.root)
    reports = []
    for q in questions:
        reports.append(trace_question(
            lambda client: OcopAgent(args.root, llm=client, retrieval_mode='sparse' if args.mode == 'sparse' else 'hybrid',
                                     rerank=args.mode == 'rerank', allow_partial_debug=True),
            args.root, q, chunks, args.mode, client_factory, turns_of))
        d = reports[-1].get('diagnosis') or {}
        print(f"#{q['id']} lost_at={d.get('lost_at')} held={d.get('last_held')} :: {d.get('verdict', '')}", flush=True)
    summary = summarize(reports)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({'summary': summary, 'reports': reports}, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        args.html.write_text(render_html(reports), encoding='utf-8')
    tally: dict[str, int] = {}
    for r in reports:
        key = (r.get('diagnosis') or {}).get('verdict')
        if key:
            tally[key] = tally.get(key, 0) + 1
    print(json.dumps({'questions': len(reports), 'verdicts': tally, **summary}, ensure_ascii=False))


if __name__ == '__main__':
    main()
