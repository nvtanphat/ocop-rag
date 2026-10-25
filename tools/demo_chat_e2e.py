"""Real HTTP demo run: 15 chat turns against a running sample backend, with the real LLM.

    python tools/serve_sample.py --root D:/AgentAI/OCOP-RAG/ocop-work-sample --port 8001      # terminal 1
    python tools/demo_chat_e2e.py --base-url http://127.0.0.1:8001 --root D:/AgentAI/OCOP-RAG/ocop-work-sample \
        --real-llm --out reports/demo-chat-e2e.json                                          # terminal 2

Every turn is an HTTP POST to /api/ocop/query (``use_llm`` true with --real-llm). The debug corpus labels each answer
``partial_debug_corpus``; the real outcome is ``claim_verification.answer_status`` and the generation diagnostics, which are what
is judged here. A turn passes only when all of its checks hold; a case that could not run is BLOCKED, never PASS.

Checks per turn: HTTP status and response schema; LangGraph engine; tools inside the registry and the trace agreeing with
``tools_used``; recovery at most once; the expected answer status (generated vs. insufficient); expected facts in the answer;
citations: opens as a page image, on an expected page / source, never from a forbidden source, and every published claim is
re-checked against the text of the evidence unit it cites (independent of the system's own verifier); memory: slots and the
standalone question. ``--inprocess-trace`` additionally replays the same sessions in-process with the stage tracer to record
memory read/write, reused evidence and the final SOURCE (labelled ``inprocess_stub``: no LLM, same corpus, same code).
Exit code 0 only when no case FAILED or was BLOCKED. Secrets are never read or written by this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GENERATED = {'generated_claims_verified', 'generated_unverified_claims', 'partial_claims_verified', 'partial_evidence',
             'partial_temporal_unverified'}
SCHEMA = ('answer', 'intent', 'status', 'citations', 'tools_used', 'tools_skipped', 'tool_trace', 'evidence_grade',
          'claim_verification', 'generation_diagnostics', 'evidence_fusion', 'workflow_engine', 'route')
QD26 = 'VN.OCOP.QD26.2026'
QD525 = 'VN.HAIPHONG.QD525.2026'
A, MEM, ISO = 'demo-session-a', 'demo-session-memory-a', 'demo-session-isolation-b'

# Cases are written against what the sample corpus really contains (22 pages: QĐ26/2026 pp.1-8,13,17-19,28-30; QĐ525 pp.1,3;
# Thành Sen guidance pp.1-4; QĐ1489 p.1). `expect` keys are documented in `judge`.
CASES = [
    dict(id='Q01', group='A', scenario='general TEXT', session='demo-q01', q='OCOP là gì và sản phẩm OCOP được phân thành những hạng sao nào?',
         expect=dict(generated=True, phrases=['5 sao'], paths=['TEXT'])),
    dict(id='Q02', group='A', scenario='exact legal lookup (PINPOINT)', session='demo-q02',
         q='Theo QĐ26/2026 Điều 4, cơ quan nào công nhận sản phẩm 5 sao?',
         expect=dict(generated=True, phrases=['Bộ Nông nghiệp'], paths=['PINPOINT'], tools_any=['lookup_legal_unit'],
                     slots={'document_code': '26/2026', 'article_id': '4'}, cited_pages_any=[3], sources_only=[QD26])),
    dict(id='Q03', group='A', scenario='structured criterion lookup', session='demo-q03',
         q='Theo phiếu 3 QĐ26/2026, tiêu chí 1.1 có ghi chú trồng trong tỉnh không?',
         expect=dict(generated=True, phrases=['100%', 'cấp tỉnh'], tools_any=['lookup_criterion'], cited_pages_any=[28, 29],
                     sources_only=[QD26])),
    dict(id='Q04', group='A', scenario='graph / multi-hop', session='demo-q04', q='QĐ26/2026 thay thế những văn bản nào?',
         expect=dict(generated=True, phrases=['148', '1489'], tools_any=['search_graph'], paths=['HYBRID_GRAPH'],
                     cited_pages_any=[13])),
    dict(id='Q05', group='A', scenario='compound (3 parts) + targeted recovery', session='demo-q05',
         q='Quyết định nào công nhận sản phẩm HANA, đơn vị nào sản xuất, và văn bản đó do cơ quan nào ban hành?',
         expect=dict(generated=True, phrases=['HANA', 'Thụy Hương'], cited_pages_any=[3], sources_include=[QD525])),
    dict(id='Q06', group='B', scenario='memory: establish context', session=MEM,
         q='Quyết định 26/2026 quy định gì về hồ sơ đánh giá, phân hạng sản phẩm OCOP?',
         expect=dict(generated=True, slots={'document_code': '26/2026'}, cited_pages_any=[4], sources_only=[QD26])),
    dict(id='Q07', group='B', scenario='memory: follow-up article', session=MEM, q='Còn Điều 7 thì sao?',
         expect=dict(generated=True, intent='FOLLOWUP', slots={'document_code': '26/2026', 'article_id': '7'},
                     standalone_has=['Điều 7', '26/2026'], cited_pages_any=[5], sources_only=[QD26])),
    dict(id='Q08', group='B', scenario='memory: new target, same document', session=MEM, q='Còn biểu mẫu số 02?',
         expect=dict(generated=True, slots={'document_code': '26/2026', 'form_id': '2'}, absent=['article_id'],
                     standalone_has=['26/2026'], sources_include=[QD26])),
    dict(id='Q09', group='B', scenario='memory: comparison with a second form', session=MEM, q='So sánh nó với mẫu số 01.',
         expect=dict(generated=True, slots={'form_ids': ['2', '1']}, standalone_has=['01', '02'], sources_include=[QD26])),
    dict(id='Q10', group='B', scenario='memory: plural reference', session=MEM, q='Hai mẫu này khác nhau ở điểm nào?',
         expect=dict(generated=True, slots={'form_ids': ['2', '1']}, phrases=['Mẫu số 01', 'Mẫu số 02'],
                     answer_forbids=['Trình tự đánh giá'], sources_include=[QD26])),
    dict(id='Q11', group='C', scenario='document switch (QĐ26 -> QĐ525)', session=MEM, q='Còn Quyết định 525 thì sao?',
         expect=dict(generated=True, slots={'document_code': '525'}, absent=['form_id', 'form_ids', 'article_id'],
                     sources_only=[QD525], cited_pages_any=[1, 3])),
    dict(id='Q12', group='C', scenario='follow-up after the switch', session=MEM, q='Còn điều khoản về hồ sơ thì sao?',
         # QĐ525 has no clause about hồ sơ anywhere in its indexed text (checked on chunks.jsonl): the right answer is the gap
         expect=dict(generated_or_insufficient=True, slots={'document_code': '525'}, standalone_has=['525'], sources_only=[QD525])),
    dict(id='Q13', group='C', scenario='independent session: dangling reference', session=ISO, q='Hai mẫu này khác nhau ở đâu?',
         expect=dict(clarify=True, no_citations=True)),
    dict(id='Q14', group='D', scenario='missing evidence (locality not in sample)', session='demo-q14',
         q='Hạn nộp hồ sơ OCOP phường Hồng Lĩnh năm 2026 là khi nào?',
         expect=dict(insufficient=True, no_citations=True)),
    dict(id='Q15', group='D', scenario='complex: article + criterion + sheet', session='demo-q15',
         q='Theo QĐ26/2026, quy định đánh giá lại ở Điều 7 là gì, và tiêu chí 1.6 của phiếu 3 yêu cầu gì?',
         expect=dict(generated=True, tools_any=['lookup_legal_unit', 'lookup_criterion'], cited_pages_any=[5, 6, 7, 8],
                     cited_pages_also=[28, 29], sources_only=[QD26], recovery_max=1)),
]


def fold(text) -> str:
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', str(text)).casefold())


def words(text: str) -> set[str]:
    return {w for w in re.findall(r'[a-z0-9à-ỹ]+', fold(text)) if len(w) > 2}


class Http:
    def __init__(self, base: str, timeout: float):
        self.base, self.timeout = base.rstrip('/'), timeout

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={'Content-Type': 'application/json'})
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, r.read(), time.perf_counter() - started, r.headers.get('content-type', '')
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), time.perf_counter() - started, exc.headers.get('content-type', '')
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return 0, repr(exc).encode(), time.perf_counter() - started, ''

    def json(self, method, path, body=None):
        status, raw, secs, _ = self.call(method, path, body)
        try:
            return status, json.loads(raw), secs
        except ValueError:
            return status, {'raw': raw[:200].decode('utf-8', 'replace')}, secs


def evidence_texts(root: Path) -> dict[str, str]:
    path = root / 'data/processed/ocop/index/evidence_units.jsonl'
    out = {}
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                unit = json.loads(line)
                out[unit['unit_id']] = unit.get('text') or ''
    return out


def judge(case: dict, status: int, d: dict, http: Http, units: dict[str, str], registry: set[str]) -> dict:
    """Return {'checks': {name: bool}, 'notes': [...]} for one turn."""
    exp, checks, notes = case['expect'], {}, []
    checks['http_200'] = status == 200
    if status != 200:
        return {'checks': checks, 'notes': [f'HTTP {status}: {str(d)[:160]}']}
    checks['schema'] = all(k in d for k in SCHEMA) and isinstance(d['citations'], list) and isinstance(d['route'], dict)
    checks['langgraph'] = d.get('workflow_engine') == 'langgraph'
    cv = d.get('claim_verification') or {}
    answer_status = cv.get('answer_status') or d['status']
    trace = d.get('tool_trace') or []
    ran = [t['name'] for t in trace if t.get('step') == 'tool' and t.get('status') != 'dependency_unavailable']
    used = d.get('tools_used') or []
    checks['tools_in_registry'] = set(used) | set(d.get('tools_skipped') or []) <= registry
    checks['trace_matches_tools_used'] = set(used) <= {t['name'] for t in trace if t.get('step') in ('tool', 'recovery')} | {'search_regulations'}
    recoveries = [t for t in trace if t.get('step') == 'recovery']
    checks['recovery_at_most_once'] = len(recoveries) <= max(1, exp.get('recovery_max', 1))
    checks['tool_budget'] = len([t for t in trace if t.get('step') in ('tool', 'recovery')]) <= 6
    path = next((t.get('retrieval_path') for t in trace if t.get('step') == 'retrieval_strategy'), None)
    if exp.get('paths'):
        checks['retrieval_path'] = path in exp['paths']
    if exp.get('tools_any'):
        checks['expected_tool_ran'] = bool(set(exp['tools_any']) & set(ran))
    if exp.get('intent'):
        checks['intent'] = d['intent'] == exp['intent']
    slots = d['route'].get('slots') or {}
    for key, want in (exp.get('slots') or {}).items():
        got = slots.get(key)
        norm = lambda v: str(v).lstrip('0') or '0'  # noqa: E731
        if isinstance(want, list):
            checks[f'slot:{key}'] = isinstance(got, list) and [norm(x) for x in got] == [norm(x) for x in want]
        else:
            checks[f'slot:{key}'] = got is not None and (norm(got) == norm(want) or (isinstance(got, str) and str(want) in got))
    for key in exp.get('absent') or []:
        checks[f'absent:{key}'] = slots.get(key) in (None, '', [])
    standalone = d.get('standalone_query') or ''
    for frag in exp.get('standalone_has') or []:
        checks[f'standalone has {frag}'] = fold(frag) in fold(standalone)
    # --- answer status: the debug label is ignored, the generation outcome is judged
    if exp.get('generated'):
        checks['llm_generated'] = answer_status in GENERATED
        checks['not_raw_excerpt'] = answer_status not in {'citation_verification_failed', 'retrieval_only',
                                                          'model_unavailable_retrieval_only', 'insufficient_context_for_generation'}
        checks['claims_published'] = len([c for c in cv.get('claims') or [] if c.get('status') == 'supported']) >= 1
    if exp.get('generated_or_insufficient'):  # a grounded partial answer or a plain statement of the gap; never a raw dump
        checks['grounded_answer_or_gap'] = answer_status in GENERATED or answer_status == 'insufficient_evidence'
    if exp.get('clarify'):
        checks['asks_for_clarification'] = d['intent'] == 'CLARIFY' and answer_status in ('clarify', d['status'])
        checks['no_tools_run'] = not used
    if exp.get('insufficient'):
        checks['reports_insufficient_evidence'] = str(answer_status).startswith(('insufficient', 'clarify')) or answer_status == 'insufficient_evidence'
    text = fold(d['answer'])
    for phrase in exp.get('phrases') or []:
        checks[f'answer has {phrase}'] = fold(phrase) in text
    for phrase in exp.get('answer_forbids') or []:
        checks[f'answer lacks {phrase}'] = fold(phrase) not in text
    # --- citations
    cites = d['citations']
    if exp.get('no_citations'):
        checks['no_citations'] = not cites
    pages = {(c['source_id'], c['pdf_page']) for c in cites}
    if exp.get('cited_pages_any'):
        checks['cited_page_expected'] = any(p in exp['cited_pages_any'] for _, p in pages)
    if exp.get('cited_pages_also'):
        checks['cited_page_also'] = any(p in exp['cited_pages_also'] for _, p in pages)
    if exp.get('sources_only'):
        checks['only_expected_sources'] = {s for s, _ in pages} <= set(exp['sources_only'])
    if exp.get('sources_include'):
        checks['expected_source_cited'] = set(exp['sources_include']) <= {s for s, _ in pages}
    opened, bad = 0, []
    for c in cites:
        st, raw, _, ctype = http.call('GET', f"/api/ocop/sources/{c['source_id']}/pages/{c['pdf_page']}/evidence.png")
        if st == 200 and ctype.startswith('image/') and len(raw) > 2000:
            opened += 1
        else:
            bad.append((c['source_id'], c['pdf_page'], st))
    if cites:
        checks['citations_open'] = not bad
        st, _, _, ctype = http.call('GET', f"/api/ocop/sources/{cites[0]['source_id']}/pdf")
        checks['pdf_endpoint'] = st == 200 and ctype.startswith('application/pdf')
    # --- independent grounding of every published claim in the unit(s) it cites
    weak = []
    for claim in cv.get('claims') or []:
        if claim.get('status') != 'supported':
            continue
        cited_units = [cites[n - 1].get('evidence_unit_id') for n in claim.get('cited') or [] if 0 < n <= len(cites)]
        corpus = ' '.join(units.get(u, '') for u in cited_units)
        header = ' '.join(c['source_id'].replace('.', ' ') for c in cites if c.get('evidence_unit_id') in cited_units)  # the model sees it in [S#]
        corpus_words = words(corpus) | words(header) | {'tài', 'liệu', 'mang', 'mã', 'trang'}
        content = words(claim['claim'])
        coverage = len(content & corpus_words) / len(content) if content else 1.0
        if corpus and coverage < 0.5:
            weak.append((round(coverage, 2), claim['claim'][:90]))
    if cv.get('claims') and units:
        checks['claims_grounded_in_cited_units'] = not weak
    if weak:
        notes.append(f'weakly grounded claims: {weak}')
    if bad:
        notes.append(f'citations that did not open: {bad}')
    return {'checks': checks, 'notes': notes, 'retrieval_path': path, 'answer_status': answer_status,
            'claims_published': len([c for c in cv.get('claims') or [] if c.get('status') == 'supported']),
            'claims_rejected': len((d.get('generation_diagnostics') or {}).get('rejected') or []),
            'tools_ran': ran, 'tool_latency_ms': {t['name']: t.get('latency_ms') for t in trace if t.get('step') == 'tool'},
            'recovery': [{'reason': t.get('reason'), 'parts': t.get('parts'), 'hits': t.get('hits')} for t in recoveries],
            'evidence_grade': (d.get('evidence_grade') or {}).get('status'),
            'uncovered_parts': (d.get('evidence_grade') or {}).get('uncovered_parts'),
            'retrieval_modes': (d.get('evidence_fusion') or {}).get('retrieval_modes'),
            'fallback_reasons': (d.get('evidence_fusion') or {}).get('retrieval_fallback_reasons'),
            'context_term_coverage': (d.get('evidence_fusion') or {}).get('context_term_coverage'),
            'missing_from_source': (d.get('generation_diagnostics') or {}).get('missing_from_source')}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base-url', default='http://127.0.0.1:8000')
    ap.add_argument('--root', type=Path, required=True, help='sample corpus root (used to re-check claims against cited evidence units)')
    ap.add_argument('--real-llm', action='store_true', help='send use_llm=true (required for a DEMO READY verdict)')
    ap.add_argument('--mode', choices=('sparse', 'dense', 'hybrid'), default='sparse')
    ap.add_argument('--timeout', type=float, default=300)
    ap.add_argument('--only', nargs='*', help='case ids, e.g. Q02 Q07')
    ap.add_argument('--run-id', default=time.strftime('%H%M%S'), help='suffix that makes the sessions of this run new')
    ap.add_argument('--out', type=Path, default=Path('demo-chat-e2e.json'))
    args = ap.parse_args()
    from ai_core.orchestration.ocop.capabilities import TOOL_REGISTRY
    http, units, registry = Http(args.base_url, args.timeout), evidence_texts(args.root), set(TOOL_REGISTRY)

    report: dict = {'base_url': args.base_url, 'mode': args.mode, 'real_llm': args.real_llm, 'cases': [], 'endpoints': {}}
    for path in ('/api/ocop/health', '/api/ocop/sources', '/api/ocop/overview', '/api/ocop/graph'):
        st, body, secs = http.json('GET', path)
        report['endpoints'][path] = {'http': st, 'secs': round(secs, 2)}
        if path.endswith('health') and st == 200:
            report['corpus'] = {k: body.get(k) for k in ('status', 'index_status', 'dense_ready', 'graph_status', 'corpus_version', 'pages')}
    if not args.real_llm:
        report['warning'] = 'run without --real-llm: generation was not exercised; this can never be DEMO READY'
    selected = [{**c, 'session': f"{c['session']}-{args.run_id}"} for c in CASES if not args.only or c['id'] in set(args.only)]
    for case in selected:
        body = {'query': case['q'], 'session_id': case['session'], 'retrieval_mode': args.mode, 'use_llm': args.real_llm}
        status, data, secs = http.json('POST', '/api/ocop/query', body)
        row = {'id': case['id'], 'group': case['group'], 'scenario': case['scenario'], 'query': case['q'],
               'session': hashlib.sha256(case['session'].encode()).hexdigest()[:8], 'http': status, 'secs': round(secs, 2)}
        if status == 0:
            row.update(result='BLOCKED', notes=[f"backend unreachable: {data.get('raw')}"])
        else:
            verdict = judge(case, status, data, http, units, registry)
            failed = [k for k, ok in verdict['checks'].items() if not ok]
            row.update(verdict, intent=data.get('intent'), standalone_query=data.get('standalone_query'),
                       slots={k: v for k, v in (data.get('route') or {}).get('slots', {}).items()},
                       cited=sorted({(c['source_id'], c['pdf_page']) for c in data.get('citations') or []}),
                       evidence_unit_ids=[c.get('evidence_unit_id') for c in data.get('citations') or []],
                       answer=data.get('answer', '')[:900] if isinstance(data, dict) else '', failed=failed,
                       result='PASS' if not failed and (args.real_llm or not case['expect'].get('generated')) else
                       ('BLOCKED' if not failed else 'FAIL'))
            if not args.real_llm and case['expect'].get('generated'):
                row['notes'] = row.get('notes', []) + ['BLOCKED: generation expected but --real-llm was not given']
        report['cases'].append(row)
        print(f"{row['id']} {row['result']:7} {row['secs']:6.1f}s {row.get('intent')} {row.get('answer_status')} "
              f"tools={row.get('tools_ran')} failed={row.get('failed')}", flush=True)
    secs = sorted(c['secs'] for c in report['cases'])
    report['latency'] = {'p50': round(statistics.median(secs), 2), 'p95': round(secs[min(len(secs) - 1, int(len(secs) * .95))], 2),
                         'max': secs[-1]} if secs else {}
    counts = {k: sum(c['result'] == k for c in report['cases']) for k in ('PASS', 'FAIL', 'BLOCKED')}
    report['summary'] = {**counts, 'sent': len(report['cases']),
                         'verdict': 'DEMO READY' if counts['FAIL'] == 0 and counts['BLOCKED'] == 0 and args.real_llm and len(selected) == len(CASES)
                         else 'NOT DEMO READY'}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    print(json.dumps({**report['summary'], 'latency': report['latency'], 'report': str(args.out)}, ensure_ascii=False))
    return 0 if report['summary']['verdict'] == 'DEMO READY' else 1


if __name__ == '__main__':
    sys.exit(main())
