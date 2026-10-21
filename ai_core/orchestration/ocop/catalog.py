"""Entity catalog for the router, generated from the source registry and the checked graph.

Nothing here is written by hand: documents, localities, products, organisations, authorities,
sheets and forms are read from ``configs/ocop_sources.json`` and the graph snapshot at index
build time and stored next to the index. The router only matches what the catalog contains, so a
new document or product becomes routable after a rebuild, with no code change.

Matching policy: if the user typed accents, an entity is matched on its accented form (so
"đánh giá lại" is never the locality "Gia Lai"); accent-free queries match accent-folded labels.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ai_core.orchestration.ocop.language import Language, fold, get_language, has_diacritics

CATALOG_FILE = 'entity_catalog.json'
KINDS = ('document', 'region', 'product', 'product_group', 'organization', 'authority', 'sheet', 'form')
_ENTITY_NODE_KINDS = {'Product': 'product', 'ProductGroup': 'product_group', 'ProductSubgroup': 'product_group',
                      'Organization': 'organization', 'Authority': 'authority'}
MIN_LABEL_CHARS = 3


def _digits(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r'\d+', value))


def _document_type(number: str, lang: Language) -> str | None:
    letters = {fold(x) for x in re.findall(r'[^\W\d_]+', number)}
    for kind, markers in lang.document_number_markers.items():
        if letters & {fold(m) for m in markers}:
            return kind
    return None


def _document_year(number: str, source_id: str) -> str | None:
    years = re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', number) or re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', source_id)
    return years[0] if years else None


def _region_labels(jurisdiction: str, lang: Language) -> list[str]:
    nationwide = {fold(x) for x in lang.nationwide_labels}
    labels = []
    for part in re.split(r'\s+-\s+', jurisdiction or ''):
        part = part.strip()
        if not part or fold(part) in nationwide:
            continue
        labels.append(part)
        stripped = re.sub(r'^(?:' + '|'.join(re.escape(m) for m in sorted(lang.locality_markers, key=len, reverse=True))
                          + r')\s+', '', part, flags=re.I).strip()
        if stripped and stripped != part:
            labels.append(stripped)
    return labels


def build_catalog(registry_path: Path, nodes: list[dict], *, language: Language | None = None) -> dict:
    lang = language or get_language()
    sources = json.loads(Path(registry_path).read_text(encoding='utf-8')).get('sources', [])
    entries: dict[str, dict[str, dict]] = {kind: {} for kind in KINDS}

    def add(kind: str, label: str, *, source_id: str | None = None, **extra):
        label = re.sub(r'\s+', ' ', str(label)).strip()
        if len(label) < MIN_LABEL_CHARS:
            return
        slot = entries[kind].setdefault(fold(label), {'label': label, 'source_ids': []})
        if source_id and source_id not in slot['source_ids']:
            slot['source_ids'].append(source_id)
        for key, value in extra.items():
            if value:
                slot.setdefault(key, value)

    for source in sources:
        number = source.get('document_number')
        if number:
            add('document', number, source_id=source['source_id'], digits=list(_digits(number)),
                type=_document_type(number, lang), year=_document_year(number, source['source_id']))
        for label in _region_labels(str(source.get('jurisdiction') or ''), lang):
            add('region', label, source_id=source['source_id'])
    for node in nodes:
        if node.get('check') not in {'passed', 'human_verified'}:
            continue
        kind = _ENTITY_NODE_KINDS.get(node['node_type'])
        if kind:
            add(kind, node['label'], source_id=node.get('source_id'))
        elif node['node_type'] == 'CriterionSheet':
            props = node.get('properties') or {}
            add('sheet', node['label'], source_id=node.get('source_id'), number=str(props.get('sheet_number') or ''))
        elif node['node_type'] == 'FormTemplate':
            props = node.get('properties') or {}
            add('form', node['label'], source_id=node.get('source_id'), number=str(props.get('form_number') or ''))
    return {'schema_version': 1,
            'entities': {kind: sorted(items.values(), key=lambda e: e['label']) for kind, items in entries.items()}}


def save_catalog(index_dir: Path, catalog: dict) -> dict:
    body = json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=1)
    (Path(index_dir) / CATALOG_FILE).write_text(body, encoding='utf-8')
    return {'sha256': hashlib.sha256(body.encode('utf-8')).hexdigest(),
            'counts': {kind: len(items) for kind, items in catalog['entities'].items()}}


@dataclass(frozen=True)
class Match:
    kind: str
    label: str
    source_ids: tuple[str, ...]
    start: int
    end: int
    extra: dict = field(default_factory=dict, compare=False, hash=False)


class EntityCatalog:
    def __init__(self, data: dict | None = None):
        self._items: dict[str, list[dict]] = (data or {}).get('entities', {}) if data else {}
        self._patterns: dict[tuple[str, bool], list[tuple[re.Pattern, dict]]] = {}

    @property
    def empty(self) -> bool:
        return not any(self._items.values())

    def labels(self, kind: str) -> list[str]:
        return [item['label'] for item in self._items.get(kind, [])]

    def _compiled(self, kind: str, accented: bool):
        key = (kind, accented)
        if key not in self._patterns:
            compiled = []
            for item in sorted(self._items.get(kind, []), key=lambda e: -len(e['label'])):
                text = item['label'] if accented else fold(item['label'])
                body = r'\s+'.join(re.escape(w) for w in text.split())
                flags = re.IGNORECASE if accented else 0
                compiled.append((re.compile(r'(?<![\w])' + body + r'(?![\w])', flags), item))
            self._patterns[key] = compiled
        return self._patterns[key]

    def find(self, kind: str, query: str) -> list[Match]:
        """Non-overlapping catalog mentions of `kind`, longest first (accent policy above)."""
        accented = has_diacritics(query)
        text = unicodedata_nfc(query) if accented else fold(query)
        taken: list[tuple[int, int]] = []
        found = []
        for pattern, item in self._compiled(kind, accented):
            for m in pattern.finditer(text):
                if any(m.start() < e and s < m.end() for s, e in taken):
                    continue
                taken.append((m.start(), m.end()))
                found.append(Match(kind, item['label'], tuple(item.get('source_ids') or ()), m.start(), m.end(),
                                   {k: v for k, v in item.items() if k not in ('label', 'source_ids')}))
        return sorted(found, key=lambda x: x.start)

    def document_by_type_year(self, kind: str, year: str) -> str | None:
        """Number of the only catalogued document of this type and year (None when absent or ambiguous)."""
        found = [d['label'] for d in self._items.get('document', []) if d.get('type') == kind and d.get('year') == year]
        return found[0] if len(found) == 1 else None

    def mentions(self, query: str) -> dict[str, list[Match]]:
        return {kind: found for kind in KINDS if (found := self.find(kind, query))}


def unicodedata_nfc(value: str) -> str:
    import unicodedata
    return unicodedata.normalize('NFC', value)


def load_catalog(index_dir: Path, manifest: dict | None = None) -> EntityCatalog:
    """Load the catalog; if absent or its hash does not match the index manifest, return empty."""
    path = Path(index_dir) / CATALOG_FILE
    if not path.is_file():
        return EntityCatalog()
    body = path.read_text(encoding='utf-8')
    if manifest is None:
        mpath = Path(index_dir) / 'manifest.json'
        manifest = json.loads(mpath.read_text(encoding='utf-8')) if mpath.is_file() else {}
    expected = (manifest.get('entity_catalog') or {}).get('sha256')
    if expected and expected != hashlib.sha256(body.encode('utf-8')).hexdigest():
        return EntityCatalog()
    return EntityCatalog(json.loads(body))
