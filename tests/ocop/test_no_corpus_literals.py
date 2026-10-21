"""Anti-hardcode guard: runtime code must not contain values that belong to the corpus.

Corpus values come from the source registry (configs/ocop_sources.json) and from graph labels captured in
tests/ocop/fixtures/corpus_graph_literals.json. Anything else that identifies a document, article, form,
sheet, locality, product or organisation has to be read from the registry, the built graph/catalog or a
config file. Exceptions are listed in tests/ocop/corpus_literal_allowlist.yaml, each with a reason.
"""
import ast
import json
import re
from pathlib import Path

import yaml

from ai_core.orchestration.ocop.language import fold, get_language

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ['ai_core', 'backend', 'ocr/ocop_ocr', 'ocop_contracts']
# Structural hard-codes that are not names but still depend on the shape of the sample corpus.
STRUCTURAL = {
    'article_number': re.compile(r'(?<![\w])(?:Điều|Dieu)\s*\d', re.I),
    'form_number': re.compile(r'(?<![\w])(?:Mẫu|Mau)\s*(?:số\s*)?\d', re.I),
    'sheet_number': re.compile(r'(?<![\w])(?:phiếu|phieu)\s*(?:số\s*)?\d', re.I),
    'counted_sheets': re.compile(r'\b\d{1,3}\s*(?:phiếu|phieu)\b', re.I),
    'counted_groups': re.compile(r'\b\d{1,2}\s*(?:nhóm|nhom)\b', re.I),
    'rating_ladder_class': re.compile(r'\[[1-5]-[1-5]\]|\[[3-5]\]|\\\*\{\d,\d\}'),
    'star_ladder': re.compile(r'\b[1-5]\s*(?:-|–|đến|den)\s*[1-5]\s*sao\b', re.I),
}


def _allowlist():
    path = Path(__file__).with_name('corpus_literal_allowlist.yaml')
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    for item in data.get('allow', []):
        assert item.get('reason', '').strip(), f'allowlist entry needs a reason: {item}'
    return data.get('allow', [])


def _corpus_literals() -> dict[str, str]:
    lang = get_language()
    nationwide = {fold(x) for x in lang.nationwide_labels}
    found: dict[str, str] = {}
    registry = json.loads((ROOT / 'configs/ocop_sources.json').read_text(encoding='utf-8'))
    for source in registry['sources']:
        found[source['source_id']] = 'source_id'
        for part in source['source_id'].split('.')[1:]:
            if len(part) >= 4 and re.search(r'\d', part) and re.search(r'[A-Za-z]', part):
                found[part] = 'source_id_part'
        if source.get('document_number'):
            found[source['document_number']] = 'document_number'
            core = re.match(r'\d+/\d{4}', source['document_number'])
            if core:
                found[core.group(0)] = 'document_number_core'
        for part in re.split(r'\s+-\s+', str(source.get('jurisdiction') or '')):
            if part.strip() and fold(part) not in nationwide:
                found[part.strip()] = 'jurisdiction'
                for marker in lang.locality_markers:
                    if fold(part).startswith(fold(marker) + ' '):
                        found[part.strip()[len(marker) + 1:]] = 'jurisdiction'
    graph = json.loads((Path(__file__).parent / 'fixtures/corpus_graph_literals.json').read_text(encoding='utf-8'))
    for kind, labels in graph.items():
        for label in labels:
            found[label] = kind.lower()
    return {k: v for k, v in found.items() if len(k) >= 4}


def _plain(value: str) -> str:
    r"""Regex source -> readable text so `Điều\s+3` is seen as `Điều 3`."""
    return re.sub(r'\\[bB]', '', re.sub(r'\\s[+*?]?', ' ', value))


def _string_constants(path: Path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body and \
                isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], 'value', None), ast.Constant):
            docstrings.add(id(node.body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.lineno, node.value


def _violations(root: Path = ROOT, bases=None):
    allow = _allowlist()
    literals = _corpus_literals()
    folded = {fold(k): (k, v) for k, v in literals.items()}
    found = []
    for base in bases or RUNTIME:
        for path in sorted((root / base).rglob('*.py')):
            rel = path.relative_to(root).as_posix()
            for line, value in _string_constants(path):
                if len(value) > 400:
                    continue
                value = _plain(value)
                text = fold(value)
                hits = [f'{kind}:{name}' for key, (name, kind) in folded.items()
                        if re.search(r'(?<![a-z0-9])' + re.escape(key) + r'(?![a-z0-9])', text)]
                hits += [f'structural:{name}' for name, rx in STRUCTURAL.items() if rx.search(value)]
                for hit in hits:
                    if not any(a['path'] == rel and a['literal'] == hit for a in allow):
                        found.append(f'{rel}:{line}: {hit}  <- {value[:70]!r}')
    return found


def test_runtime_code_has_no_corpus_literals():
    violations = _violations()
    assert not violations, 'corpus-specific literals in runtime code:\n' + '\n'.join(violations)


def test_allowlist_entries_are_still_needed():
    allow = _allowlist()
    live = {(v.split(':')[0], v.split(': ', 1)[1].split('  <-')[0]) for v in _violations_ignoring_allowlist()}
    stale = [a for a in allow if (a['path'], a['literal']) not in live]
    assert not stale, f'stale allowlist entries: {stale}'


def _violations_ignoring_allowlist():
    global _allowlist
    original = _allowlist
    _allowlist = lambda: []  # noqa: E731
    try:
        return _violations()
    finally:
        _allowlist = original


PLANTED = r'''
A = "VN.OCOP.QD26.2026"
B = r"Điều\s+4"
C = r"\*{3,5}"
D = "xã Thành Sen"
E = r"\b26 phiếu"
'''


def test_guard_detects_planted_literals(tmp_path):
    (tmp_path / 'pkg').mkdir()
    (tmp_path / 'pkg' / 'bad.py').write_text(PLANTED, encoding='utf-8')
    kinds = ' '.join(_violations(tmp_path, ['pkg']))
    for expected in ('source_id', 'article_number', 'rating_ladder_class', 'jurisdiction', 'counted_sheets'):
        assert expected in kinds, (expected, kinds)
