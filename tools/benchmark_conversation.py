"""Reproducible routing-only comparison; no corpus ingestion, holdout tuning or fake models.

Baseline source is read from a fixed git commit, never checked out over user work.
--semantic measures the installed embedding model, using dev exemplars only.
--llm measures the configured real structured fallback (bounded transport).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.contracts import Intent, Route
from ai_core.orchestration.ocop.catalog import EntityCatalog

FIXTURE = ROOT / 'tests/ocop/fixtures/conversation_eval.json'
PRIOR = {'last_query': 'QĐ26/2026 Điều 7 quy định gì?', 'slots': {'document_code': '26/2026', 'article_id': '7'},
         'intent': 'EXACT_LOOKUP', 'capabilities': ['exact_article']}


def baseline(revision):
    source = subprocess.check_output(['git', 'show', revision + ':ai_core/orchestration/ocop/router.py'], cwd=ROOT)
    namespace = {'__name__': 'conversation_baseline'}
    exec(compile(source, '<baseline-router>', 'exec'), namespace)
    return namespace['route_query']


def kind(route):
    if route.intent == Intent.CONVERSATION:
        return 'social'
    if route.needs_clarification:
        return 'clarify'
    if route.intent == Intent.OUT_OF_SCOPE:
        return 'oos'
    return 'business'


def evaluate(router, cases, *, workers=1):
    def one(case):
        split, expected, query, exact, session = case
        started = perf_counter()
        result = router(query, session=session, catalog=EntityCatalog())
        latency = (perf_counter() - started) * 1000
        predicted = kind(result)
        target = 'business' if expected == 'legacy' else expected
        if expected == 'mixed':
            target = ('oos' if query == 'Chào bạn, giá Bitcoin hôm nay bao nhiêu?' else
                      'clarify' if query in ('Ok cảm ơn, hãy mở hồ sơ riêng DOSSIER-123',
                                            'Ok, tính điểm hồ sơ của tôi') else 'business')
        correct = (result.intent.value == exact if exact else
                   (result.dialogue.action in ('rephrase', 'correction', 'sources') or
                    result.slots.get('form_id') == '1') if expected == 'repair' else predicted == target)
        return dict(split=split, group=expected, query=query, intent=result.intent.value, predicted=predicted,
                    expected_kind=target,
                    correct=bool(correct), latency_ms=latency, tools=len(result.required_tools),
                    method=result.dialogue.method)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, cases))
    report = {}
    for split in ('dev', 'holdout', 'legacy', 'all'):
        selected = [r for r in rows if split == 'all' or r['split'] == split]
        if not selected:
            continue
        groups = sorted({r['group'] for r in selected})
        group_accuracy = {g: sum(r['correct'] for r in selected if r['group'] == g) /
                          sum(r['group'] == g for r in selected) for g in groups}
        tp = sum(r['group'] == 'social' and r['predicted'] == 'social' for r in selected)
        social_predictions = sum(r['predicted'] == 'social' for r in selected)
        social_actual = sum(r['group'] == 'social' for r in selected)
        business = [r for r in selected if r['group'] in ('business', 'mixed', 'legacy')]
        latencies = sorted(r['latency_ms'] for r in selected)
        # Macro F1 on processing classes; repair's action is scored separately.
        pairs = [(r['expected_kind'], r['predicted'])
                 for r in selected if r['group'] != 'repair']
        f1 = []
        for label in sorted({a for a, _ in pairs}):
            true = sum(a == label and b == label for a, b in pairs)
            denom = sum(a == label for a, _ in pairs) + sum(b == label for _, b in pairs)
            f1.append(2 * true / denom if denom else 0)
        report[split] = dict(n=len(selected), accuracy=sum(r['correct'] for r in selected)/len(selected),
            group_accuracy=group_accuracy, macro_f1=statistics.mean(f1),
            social_precision=tp/social_predictions if social_predictions else None,
            social_recall=tp/social_actual if social_actual else None,
            false_social_bypass=sum(r['predicted'] == 'social' for r in business)/len(business) if business else None,
            p50_ms=statistics.median(latencies), p95_ms=latencies[min(len(latencies)-1, int(.95*len(latencies)))],
            required_tools=sum(r['tools'] for r in selected), methods=dict(Counter(r['method'] for r in selected)))
    return {'metrics': report, 'rows': rows}


def semantic_router(data, old):
    import numpy as np
    from ai_core.retrieval.ocop.index_pipeline import _load_embedding, _encode
    from ai_core.retrieval.ocop.models_config import DEFAULT_EMBEDDING_MODEL, DEFAULT_EMBEDDING_REVISION, resolve_local_model_path
    started = perf_counter()
    if not resolve_local_model_path(DEFAULT_EMBEDDING_MODEL)[1]:
        raise RuntimeError('Configured embedding model is not present locally; benchmark will not download it')
    model = _load_embedding(DEFAULT_EMBEDDING_MODEL, DEFAULT_EMBEDDING_REVISION)
    exemplars = [(group, q) for group, queries in data['dev'].items() for q in queries if q.strip()]
    vectors = _encode(model, [q for _, q in exemplars], True)
    # Tune threshold on leave-one-out dev only, penalizing social false positives.
    scores = vectors @ vectors.T
    np.fill_diagonal(scores, -1)
    best = None
    for threshold in (.65, .7, .75, .8, .85, .9, .95):
        penalty = 0
        for i, (label, _) in enumerate(exemplars):
            j = int(scores[i].argmax())
            social = scores[i, j] >= threshold and exemplars[j][0] == 'social'
            penalty += (10 if label != 'social' else 1) * (social != (label == 'social'))
        candidate = (penalty, -threshold)
        if best is None or candidate < best[0]:
            best = candidate, threshold
    threshold = best[1]
    def router(query, **kwargs):
        if query.strip():
            vector = _encode(model, [query], True)[0]
            similarities = vectors @ vector
            nearest = int(similarities.argmax())
            if similarities[nearest] >= threshold and exemplars[nearest][0] == 'social':
                return Route(intent=Intent.CONVERSATION, strategy='conversation')
        return old(query, **kwargs)
    return router, {'threshold': threshold, 'startup_ms': (perf_counter()-started)*1000,
                    'model': DEFAULT_EMBEDDING_MODEL, 'revision': DEFAULT_EMBEDDING_REVISION}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline', default='c7ed601')
    ap.add_argument('--semantic', action='store_true')
    ap.add_argument('--llm', action='store_true')
    ap.add_argument('--out', type=Path, default=ROOT/'reports/conversation-routing.json')
    args = ap.parse_args()
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    cases = [(split, group, q, None, PRIOR if group == 'repair' else {})
             for split, groups in data.items() for group, queries in groups.items() for q in queries]
    for line in (ROOT/'tests/ocop/fixtures/ocop_router_eval.jsonl').read_text(encoding='utf-8').splitlines():
        case = json.loads(line)
        cases.append(('legacy', 'legacy', case['query'], case['intent'], case.get('session', {})))
    old = baseline(args.baseline)
    output = {'baseline_commit': args.baseline, 'fixture_sha256': hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
              'baseline': evaluate(old, cases), 'hybrid_offline': evaluate(route_query, cases)}
    if args.semantic:
        try:
            router, metadata = semantic_router(data, old)
            output['semantic'] = {**evaluate(router, cases), 'metadata': metadata}
        except (RuntimeError, ImportError, OSError, ValueError) as exc:
            output['semantic'] = {'blocked': type(exc).__name__, 'reason': str(exc)[:200]}
    if args.llm:
        from ai_core.orchestration.ocop.llm import make_answer_client
        from threading import Lock
        client = make_answer_client()
        client.timeout = 8
        if hasattr(client, 'retries'):
            client.retries = 0
        counter = {'calls': 0, 'failures': 0}
        lock = Lock()
        class Meter:
            def chat_structured(self, *a, **kw):
                with lock:
                    counter['calls'] += 1
                try:
                    return client.chat_structured(*a, **kw)
                except RuntimeError:
                    with lock:
                        counter['failures'] += 1
                    raise
        output['hybrid_llm'] = evaluate(lambda q, **kw: route_query(q, dialogue_client=Meter(), **kw), cases)
        output['hybrid_llm']['model_calls'] = counter
        output['hybrid_llm']['model_identity'] = client.identity()
        output['hybrid_llm']['model_calls_per_turn'] = counter['calls']/len(cases)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({name: value.get('metrics', value) for name, value in output.items()
                      if isinstance(value, dict)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
