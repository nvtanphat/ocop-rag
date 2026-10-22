"""Chunk audit on the real index: does a chunk keep a complete unit of information?

    python tools/audit_chunks.py --root <corpus root> [--out audit.json] [--show 5]

Reads ``chunks.jsonl`` / ``evidence_units.jsonl`` as written by the production indexer. Checks, per chunk and per unit:

* ``split_units``        evidence units cut into several chunks (the answer may straddle a boundary);
* ``mid_sentence_start`` a continuation chunk that begins in lower case / without a sentence start;
* ``orphan_exception``   a chunk that opens with an exception or condition word (trừ, ngoại trừ, nếu, không, trường hợp …)
                         while its main clause sits in the previous chunk;
* ``headerless_table``   table chunks with no column header;
* ``no_context``         chunks whose indexed text names neither the document nor a structural parent;
* size distribution and ``over_budget`` chunks.

A finding is a place to look, not a verdict: the audit says where information can be separated from what qualifies it.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_core.orchestration.ocop.language import fold  # noqa: E402

QUALIFIER_OPEN = re.compile(r'^(?:tru|ngoai tru|neu|truong hop|khong|tuy nhien|trong truong hop|co the|duoc mien|mien)\b')


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.is_file() else []


def page(row: dict):
    return next((s.get('pdf_page') for s in row.get('spans', []) if isinstance(s, dict)), None)


def audit(root: Path, show: int = 5) -> dict:
    folder = root / 'data/processed/ocop/index'
    chunks = read_jsonl(folder / 'chunks.jsonl')
    units = {u['unit_id']: u for u in read_jsonl(folder / 'evidence_units.jsonl')}
    by_unit: dict[str, list[dict]] = defaultdict(list)
    for c in chunks:
        by_unit[c['evidence_unit_id']].append(c)
    findings: dict[str, list[dict]] = defaultdict(list)

    def note(kind, c, **extra):
        findings[kind].append({'chunk_id': c['chunk_id'], 'source_id': c['source_id'], 'pdf_page': page(c),
                               'start': c['raw_text'][:90].replace('\n', ' | '), **extra})

    split = {uid: cs for uid, cs in by_unit.items() if len(cs) > 1}
    for uid, cs in split.items():
        ordered = sorted(cs, key=lambda c: c.get('char_start') or 0)
        for prev, c in zip(ordered, ordered[1:]):
            head = c['raw_text'].lstrip()
            if head and (head[0].islower() or not re.match(r'[\wÀ-ỹ(\[“"•\-–]', head[0])):
                note('mid_sentence_start', c, unit=uid)
            if QUALIFIER_OPEN.match(fold(head)):
                note('orphan_exception', c, unit=uid, previous_end=prev['raw_text'][-80:].replace('\n', ' | '))
    for c in chunks:
        table = any(isinstance(s, dict) and s.get('table_id') for s in c.get('spans', []))
        if table and not c.get('table_headers'):
            note('headerless_table', c)
        # indexed text carries "văn bản: <số hiệu>" (document) and/or "Ngữ cảnh ..." (structure); neither = a bare passage
        if 'văn bản:' not in c['text_for_bm25'] and 'Ngữ cảnh' not in c['text_for_bm25']:
            note('no_context', c)
    tokens = sorted(c.get('estimated_tokens', 0) for c in chunks)
    summary = {
        'chunks': len(chunks), 'units': len(units), 'units_split': len(split),
        'split_share': round(len(split) / max(1, len(units)), 3),
        'chunks_over_budget': sum(bool(c.get('over_budget')) for c in chunks),
        'table_chunks': sum(any(isinstance(s, dict) and s.get('table_id') for s in c.get('spans', [])) for c in chunks),
        'tokens_p50': tokens[len(tokens) // 2] if tokens else None, 'tokens_p90': tokens[int(len(tokens) * .9)] if tokens else None,
        'tokens_max': tokens[-1] if tokens else None, 'tokens_mean': round(statistics.mean(tokens), 1) if tokens else None,
        **{kind: len(items) for kind, items in findings.items()},
    }
    return {'summary': summary, 'examples': {k: v[:show] for k, v in findings.items()}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--out', type=Path)
    ap.add_argument('--show', type=int, default=5)
    args = ap.parse_args()
    report = audit(args.root, args.show)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False))
    for kind, items in report['examples'].items():
        for item in items:
            print(kind, item)


if __name__ == '__main__':
    main()
