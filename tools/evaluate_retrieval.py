"""Ranking quality of the production ``search()`` per mode, against page-level gold.

    python tools/evaluate_retrieval.py --root <corpus root> --questions questions.json [--modes sparse dense hybrid rerank]
        [--scoped] [--out result.json] [--rerank-candidates 12]

For every question with gold pages (and a tool that retrieves text) the question is searched directly by ``search()`` -
the function the agent's tools call - and the ranked chunks are scored by the page they come from:

    Recall@5 / Recall@10   share of gold pages that appear in the top-K chunks
    Hit@1                  the first chunk is on a gold page
    MRR                    1 / rank of the first chunk on a gold page
    nDCG@10                binary relevance (chunk on a gold page), log2 discount

``--scoped`` restricts the search to the question's ``source_id`` (what the tools do when the question names a document);
without it the whole corpus competes. A question set's gold is page-level, so this measures where the right page is,
not whether the right sentence reached the prompt: use tools/trace_evidence.py for that.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')


def metrics(ranked_pages: list[int], gold: set[int]) -> dict:
    hits = [p in gold for p in ranked_pages]
    first = next((i for i, h in enumerate(hits, 1) if h), None)
    seen: set[int] = set()  # a gold page counts once, however many of its chunks are retrieved
    gains = []
    for page in ranked_pages[:10]:
        gains.append(page in gold and page not in seen)
        seen.add(page)
    dcg = sum(1 / math.log2(i + 1) for i, g in enumerate(gains, 1) if g)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(gold), 10) + 1))
    return {'recall@5': len(gold & set(ranked_pages[:5])) / len(gold), 'recall@10': len(gold & set(ranked_pages[:10])) / len(gold),
            'hit@1': bool(hits and hits[0]), 'mrr': 1 / first if first else 0.0, 'ndcg@10': dcg / ideal if ideal else 0.0}


def evaluate(root: Path, questions: list[dict], modes: list[str], *, scoped: bool, rerank_candidates: int) -> dict:
    from ai_core.retrieval.ocop.search import search
    index = root / 'data/processed/ocop/index'
    gold_questions = [q for q in questions if q.get('pages') and q.get('required_any_tools') and
                      set(q['required_any_tools']) & {'search_regulations', 'lookup_legal_unit', 'lookup_recognition'}]
    out = {}
    for mode in modes:
        rows = []
        for q in gold_questions:
            query = (q.get('turns') or [q['query']])[-1] if not q.get('conversation') else q['query']
            kwargs = dict(mode='sparse' if mode == 'sparse' else 'dense' if mode == 'dense' else 'hybrid', top_k=10,
                          source_id=q.get('source_id') if scoped else None, rerank=mode == 'rerank')
            if mode == 'rerank':
                kwargs['rerank_candidates'] = rerank_candidates
            hits = search(index, query, **kwargs)
            rows.append({'id': q['id'], **metrics([h['pdf_page'] for h in hits], set(q['pages']))})
        n = len(rows)
        out[mode] = {'questions': n, **{k: round(sum(r[k] for r in rows) / n, 3) for k in
                                         ('recall@5', 'recall@10', 'hit@1', 'mrr', 'ndcg@10')}, 'rows': rows}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--questions', type=Path, required=True)
    ap.add_argument('--modes', nargs='*', default=['sparse', 'dense', 'hybrid'], choices=('sparse', 'dense', 'hybrid', 'rerank'))
    ap.add_argument('--scoped', action='store_true')
    ap.add_argument('--rerank-candidates', type=int, default=12)
    ap.add_argument('--set', nargs='*', default=[], metavar='section.key=value')
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    from ai_core.retrieval.ocop.settings import override_settings
    override_settings(args.set)
    result = evaluate(args.root, json.loads(args.questions.read_text(encoding='utf-8')), args.modes, scoped=args.scoped,
                      rerank_candidates=args.rerank_candidates)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    for mode, r in result.items():
        print(mode, {k: v for k, v in r.items() if k != 'rows'})


if __name__ == '__main__':
    main()
