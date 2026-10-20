"""Opt-in LLM proposer for candidate entities, attributes, relations and rules.

Design follows schema-constrained, source-grounded extractors (Google LangExtract,
LlamaIndex SchemaLLMPathExtractor strict mode, Microsoft GraphRAG entity merging):

- the LLM is NEVER a fact authority: every entity, attribute value, relation proof
  and rule must be a verbatim substring of one EvidenceUnit, located by character
  offset and mapped to its own PDF page/bbox/SHA; anything else is dropped and counted;
- only whitelisted entity kinds, attribute keys and ontology-checked relation
  triples are accepted; score/star values are never taken from the LLM;
- long units are chunked with overlap instead of truncated; calls may run in
  parallel but results merge in unit order, and responses are cached by
  (model, prompt version, chunk text) so reruns are reproducible.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Protocol
from ai_core.domain.ocop_citations import quote_bbox
from ai_core.domain.ocop_ids import stable_id
from .contracts import (
    BusinessEntity, BusinessRelation, BusinessRule, EvidenceRef,
    EntityType, RELATION_TYPES, validate_business_graph,
)

PROMPT_VERSION = "ocop-llm-extract-7"
CHUNK_CHARS = 2500
CHUNK_OVERLAP = 200


class StructuredLLM(Protocol):
    model: str
    def chat(self, system: str, user: str, *, format_json: bool = False, max_tokens: int = 1024) -> str: ...


PERMITTED_KINDS = ('Criterion', 'EvidenceType', 'ProductGroup', 'ProductSubgroup',
                   'Condition', 'Product', 'Organization')
# Descriptive features only. Points, stars and ranks stay with deterministic/human review.
ATTRIBUTE_KEYS = {
    'Product': ('product_type', 'brand', 'packaging', 'raw_material', 'origin_area'),
    'Organization': ('organization_form', 'address', 'representative'),
    'Criterion': ('code',),

    'EvidenceType': ('issuer', 'copies', 'format'),
    'ProductGroup': ('code',),
    'ProductSubgroup': ('code',),
    'Condition': ('subject',),
}
FORBIDDEN_ATTRIBUTE_HINTS = ('point', 'score', 'star', 'rank', 'diem', 'sao', 'hang')
# Entity-type definitions in the prompt (GraphRAG/LangExtract style) plus a context gate
# (LlamaIndex strict schema): scoring-sheet kinds only come from table units.
KIND_DEFINITIONS = {
    'Criterion': 'a numbered/lettered criterion row of an OCOP scoring sheet (phiếu đánh giá) table, listed ONLY '
                 'as the source of a HAS_CONDITION or REQUIRES_EVIDENCE relation (the sheet tree itself is '
                 'already extracted); '
                 'NOT a procedure heading, dossier name or legal article title',
    'Condition': 'a NOTE printed under a scoring-sheet criterion (Ghi chú / Yêu cầu / Chú ý / Chỉ áp dụng / '
                 'an explanatory parenthesis); NOT an answer option (rows starting with □), NOT eligibility '
                 'of applicants',
    'EvidenceType': 'a named document/paper that must be submitted or kept as proof',
    'ProductGroup': 'one of the six OCOP product groups (ngành/nhóm sản phẩm), copied whole: '
                    '"dịch vụ du lịch cộng đồng, du lịch sinh thái và điểm du lịch" is ONE group; '
                    'NOT a "Bộ sản phẩm" (criterion sheet) name and NOT a fragment of a group name',
    'ProductSubgroup': 'a product subgroup printed after "Nhóm:" in a sheet heading; '
                       'NOT a "Bộ sản phẩm" (criterion sheet) name',
    'Product': 'a specific named product, not generic words such as "sản phẩm OCOP"',
    'Organization': 'a specific producing/business entity (HTX, công ty, hộ kinh doanh, tổ hợp tác); '
                    'NOT a state agency (UBND, Sở, Bộ, Phòng, Cục), NOT a person, NOT a generic group',
}
TABLE_ONLY_KINDS = {'Criterion', 'Condition'}
TABLE_UNIT_KINDS = {'table', 'criterion_table_candidate'}
_STATE_AGENCY = re.compile(r'^\s*(?:(?:ủy|uỷ)\s+ban|ubnd|sở|bộ|phòng|cục|chi\s+cục|hội\s+đồng|chủ\s+tịch|'
                           r'trung\s+tâm|văn\s+phòng)(?:\s|$)', re.I)
_GENERIC_LABEL = re.compile(r'^\s*(?:các|những|mọi)\s', re.I)
RULE_KINDS = ('obligation', 'prohibition', 'permission', 'exemption', 'scoring', 'temporal')


# Group/subgroup hierarchy comes from sheet headings (deterministic); prose lists mislead the LLM.
# Scoring-sheet tree (options, sub-criteria) is extracted deterministically and arithmetic-checked;
# asking the LLM to restate it only multiplies output tokens.
LLM_EXCLUDED_RELATIONS = {'HAS_SUBGROUP', 'HAS_OPTION', 'HAS_SUBCRITERION'}


def _allowed_triples() -> dict[str, tuple[set[str], set[str]]]:
    def kinds(value):
        return {k.value for k in (value if isinstance(value, frozenset) else {value})}
    out = {}
    for name, (src, dst) in RELATION_TYPES.items():
        s, d = kinds(src) & set(PERMITTED_KINDS), kinds(dst) & set(PERMITTED_KINDS)
        if s and d and name not in LLM_EXCLUDED_RELATIONS:
            out[name] = (s, d)
    return out


ALLOWED_TRIPLES = _allowed_triples()

_EXAMPLE_INPUT = ("2.1. Bao bì sản phẩm\n- Bao bì đẹp, có nhãn đúng quy định\n"
                  "Hồ sơ gồm: Phiếu kiểm nghiệm do đơn vị được công nhận cấp\n"
                  "Sản phẩm: Mật ong hoa nhãn, đóng chai thủy tinh, chủ thể: HTX Ong Mật Bình Minh")
_EXAMPLE_OUTPUT = {
    "entities": [
        {"kind": "Criterion", "anchor": "Bao bì sản phẩm", "attributes": {"code": "2.1"}},
        {"kind": "EvidenceType", "anchor": "Phiếu kiểm nghiệm",
         "attributes": {"issuer": "đơn vị được công nhận"}},
        {"kind": "Product", "anchor": "Mật ong hoa nhãn", "attributes": {"packaging": "chai thủy tinh"}},
        {"kind": "Organization", "anchor": "HTX Ong Mật Bình Minh", "attributes": {"organization_form": "HTX"}},
    ],
    "relations": [
        {"type": "REQUIRES_EVIDENCE", "source": 0, "target": 1},
        {"type": "OWNED_BY", "source": 2, "target": 3},
    ],
    "rules": [],
}


def _system_prompt() -> str:
    attrs = "; ".join(f"{k}: {', '.join(v) or '(none)'}" for k, v in ATTRIBUTE_KEYS.items())
    triples = "; ".join(f"{name}: {'|'.join(sorted(s))} -> {'|'.join(sorted(d))}"
                        for name, (s, d) in sorted(ALLOWED_TRIPLES.items()))
    return (
        "You extract OCOP facts ONLY from the quoted Vietnamese source (OCR text, may contain errors). "
        "Do not use external knowledge and never correct OCR spelling.\n"
        "Return ONE JSON object with arrays: entities, relations, rules.\n"
        "Copy anchors character-for-character, including OCR errors. A name may continue across a line "
        "break: copy the WHOLE name. Extract EVERY qualifying entity and EVERY relation the passage states "
        "(for example each product with its producer), not only the first ones.\n"
        "Entity kinds: " + "; ".join(f"{k} = {v}" for k, v in KIND_DEFINITIONS.items()) + ".\n"
        f"Entity: {{\"kind\": one of {'|'.join(PERMITTED_KINDS)}, \"anchor\": VERBATIM substring, "
        "\"attributes\": {key: VERBATIM substring}}.\n"
        f"Allowed attribute keys per kind: {attrs}. Omit a key when the source does not state it.\n"
        "Relation: {\"type\", \"source\": index of the source entity in your entities array, "
        "\"target\": index of the target entity}; only when the source text directly states it. "
        "Do not copy text into relations.\n"
        f"Allowed relation types (source kind -> target kind): {triples}.\n"
        f"Rule: {{\"kind\": one of {'|'.join(RULE_KINDS)}, \"anchor\": VERBATIM rule sentence}}.\n"
        "Never output point scores, star levels, legal dates, producers or evidence types that are not "
        "written in the source. List items in order of appearance. Output only JSON.\n"
        f"Example input:\n{_EXAMPLE_INPUT}\nExample output:\n{json.dumps(_EXAMPLE_OUTPUT, ensure_ascii=False)}"
    )


SYSTEM = _system_prompt()


GLEANING_PROMPT = ("MANY entities and relations were missed in the previous extraction (shown below). "
                   "Return ONE JSON object with the same arrays containing ONLY additional items that "
                   "satisfy all rules above; return empty arrays if nothing was missed. Relation indices "
                   "refer to the PREVIOUS entities followed by your new entities.")


def semantic_profile(model: str, max_units: int, gleanings: int = 1) -> str:
    """Identity of an LLM extraction run; changes invalidate reused knowledge."""
    return f"{model}:{PROMPT_VERSION}:g{gleanings}:{max_units}"


def norm_label(text: str) -> str:
    """Merge key only (case and whitespace); stored quotes stay verbatim."""
    return ' '.join(str(text).split()).casefold()


def _align(text: str, anchor, min_len: int = 3) -> list[tuple[int, int]]:
    """Exact matches, else matches that differ only in whitespace (LangExtract-style alignment).
    Characters are never fuzzed, so OCR text is not corrected."""
    if not isinstance(anchor, str) or len(anchor.strip()) < min_len:
        return []
    hits, pos = [], text.find(anchor)
    while pos >= 0:
        hits.append((pos, pos + len(anchor)))
        pos = text.find(anchor, pos + 1)
    if hits:
        return hits
    pattern = r'\s+'.join(re.escape(tok) for tok in anchor.split())
    return [m.span() for m in re.finditer(pattern, text)]


def _chunks(text: str) -> list[tuple[int, str]]:
    if len(text) <= CHUNK_CHARS:
        return [(0, text)]
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):
            cut = text.rfind('\n', start + CHUNK_CHARS // 2, end)
            end = cut + 1 if cut > 0 else end
        out.append((start, text[start:end]))
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return out


class _Cache:
    def __init__(self, directory: Path | None):
        self.dir = directory
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=True)

    def key(self, model: str, text: str) -> str:
        return hashlib.sha256(f"{model}|{PROMPT_VERSION}|{text}".encode()).hexdigest()

    def get(self, key: str) -> str | None:
        if self.dir is None:
            return None
        path = self.dir / f"{key}.json"
        return json.loads(path.read_text(encoding='utf-8'))['response'] if path.is_file() else None

    def put(self, key: str, response: str) -> None:
        if self.dir is None:
            return
        tmp = self.dir / f"{key}.json.tmp"
        tmp.write_text(json.dumps({'response': response}, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, self.dir / f"{key}.json")


def _page_of(unit: dict, start: int, end: int) -> int | None:
    """PDF page of text[start:end]; None if it spans pages or cannot be located."""
    text = unit.get('text') or ''
    spans = unit.get('spans') or []
    pages = {int(s['pdf_page']) for s in spans}
    if len(pages) == 1:
        return next(iter(pages))
    lines = text.splitlines()
    first, last = text.count('\n', 0, start), text.count('\n', 0, max(start, end - 1))
    geometry = unit.get('structured', {}).get('quote_lines', [])
    rows = geometry if len(geometry) == len(lines) else spans if len(spans) == len(lines) else None
    if rows is None:
        return None
    found = {int(rows[i]['pdf_page']) for i in range(first, last + 1)}
    return found.pop() if len(found) == 1 else None


class _Grounder:
    def __init__(self, unit: dict):
        self.unit = unit
        self.text = unit.get('text') or ''
        self.sha = {int(s['pdf_page']): s.get('source_sha256') for s in unit.get('spans') or []}

    def locate(self, anchor, min_len: int = 3) -> str | None:
        """Verbatim source substring for an anchor, or None if absent."""
        hits = _align(self.text, anchor, min_len)
        return self.text[hits[0][0]:hits[0][1]] if hits else None

    def ref(self, anchor) -> EvidenceRef | None:
        hits = _align(self.text, anchor)
        if not hits:
            return None
        quote = self.text[hits[0][0]:hits[0][1]]
        pages = {_page_of(self.unit, s, e) for s, e in hits}
        if len(pages) != 1 or None in pages:
            return None
        page = pages.pop()
        return EvidenceRef(source_id=self.unit['source_id'], evidence_unit_id=self.unit['unit_id'],
                           pdf_page=page, source_sha256=self.sha.get(page),
                           bbox=quote_bbox(self.unit, page, quote), quote=quote)


MAX_PROOF_CHARS = 700


def _covering_span(text: str, first: str, second: str) -> str | None:
    """Shortest substring of text containing both anchors, or None if longer than MAX_PROOF_CHARS."""
    best = None
    for a0, a1 in _align(text, first, 1):
        for b0, b1 in _align(text, second, 1):
            start, end = min(a0, b0), max(a1, b1)
            if best is None or end - start < best[1] - best[0]:
                best = (start, end)
    if best is None or best[1] - best[0] > MAX_PROOF_CHARS:
        return None
    return text[best[0]:best[1]]


def _kind_allowed(kind, anchor, unit: dict) -> bool:
    if kind not in PERMITTED_KINDS or not isinstance(anchor, str):
        return False
    if kind in TABLE_ONLY_KINDS and unit.get('unit_kind') not in TABLE_UNIT_KINDS:
        return False
    if _GENERIC_LABEL.match(anchor):
        return False
    return not (kind == 'Organization' and _STATE_AGENCY.match(anchor))


def _attributes(kind: str, raw, grounder: "_Grounder", stats: dict) -> dict[str, str]:
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        found = (grounder.locate(value, min_len=2) if isinstance(value, str) and len(value) <= 200
                 and key in ATTRIBUTE_KEYS.get(kind, ())
                 and not any(h in str(key).lower() for h in FORBIDDEN_ATTRIBUTE_HINTS) else None)
        if found is None:
            stats['dropped_attributes'] += 1
            continue
        out[f"{key}_candidate"] = ' '.join(found.split())
    return out


def _ask(client: StructuredLLM, cache: _Cache, prompt: str) -> dict:
    key = cache.key(client.model, prompt)
    raw = cache.get(key)
    fresh = raw is None
    if fresh:
        raw = client.chat(SYSTEM, prompt, format_json=True, max_tokens=1600)
    response = json.loads(raw)
    if not isinstance(response, dict):
        raise ValueError('not an object')
    if fresh:
        cache.put(key, raw)
    return response


def _call(client: StructuredLLM, cache: _Cache, body: str, gleanings: int = 0) -> dict:
    """First pass plus GraphRAG-style gleaning passes that ask only for missed items."""
    merged = _ask(client, cache, body)
    for _ in range(gleanings):
        previous = {k: merged.get(k) or [] for k in ('entities', 'relations', 'rules')}
        extra = _ask(client, cache, f"{body}\n\n{GLEANING_PROMPT}\nPREVIOUS EXTRACTION:\n"
                                    f"{json.dumps(previous, ensure_ascii=False)}")
        added = 0
        for k in ('entities', 'relations', 'rules'):
            items = extra.get(k) if isinstance(extra.get(k), list) else []
            merged[k] = list(merged.get(k) or []) + items
            added += len(items)
        if not added:
            break
    return merged


def propose(units: list[dict], client: StructuredLLM, *, max_units: int = 50,
            cache_dir: Path | None = None, max_workers: int = 1, gleanings: int = 0) -> dict:
    if not (0 <= max_units <= 500):
        raise ValueError('max_units must be 0..500')
    if not (1 <= max_workers <= 16):
        raise ValueError('max_workers must be 1..16')
    cache = _Cache(cache_dir)
    target_units = [u for u in units if u.get('unit_kind') in ('article', 'paragraph', 'section', 'table', 'criterion_table_candidate')
                    and u.get('text', '').strip()][:max_units]
    jobs = [(u, body) for u in target_units for _, body in _chunks(u['text'])]

    def run(job):
        try:
            return _call(client, cache, job[1], gleanings), None
        except (RuntimeError, ValueError, TypeError, KeyError, IndexError, OSError) as exc:
            return None, type(exc).__name__ + (f': {exc}' if isinstance(exc, RuntimeError) else '')

    if max_workers == 1:
        results = [run(job) for job in jobs]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            results = list(pool.map(run, jobs))

    stats = {'dropped_entities': 0, 'dropped_attributes': 0, 'dropped_relations': 0, 'dropped_rules': 0}
    ent: dict[str, BusinessEntity] = {}
    rel: dict[str, BusinessRelation] = {}
    rules: dict[str, BusinessRule] = {}
    failures, ok_units, failed_units = [], set(), set()
    method = f'llm_candidate:{client.model}'
    for (unit, _body), (response, error) in zip(jobs, results):
        sid, uid = unit['source_id'], unit['unit_id']
        if response is None:
            failures.append({'evidence_unit_id': uid, 'error_type': error})
            failed_units.add(uid)
            continue
        ok_units.add(uid)
        grounder = _Grounder(unit)
        by_anchor: dict[tuple[str, str], str] = {}
        by_index: dict[int, tuple[str, str, str]] = {}
        for index, obj in enumerate((response.get('entities') or [])[:80]):
            if not isinstance(obj, dict):
                stats['dropped_entities'] += 1
                continue
            kind, anchor = obj.get('kind'), obj.get('anchor')
            ev = grounder.ref(anchor) if _kind_allowed(kind, anchor, unit) else None
            if ev is None:
                stats['dropped_entities'] += 1
                continue
            # GraphRAG-style merge: one entity per (source, kind, normalized label), evidence accumulated.
            key = norm_label(ev.quote)
            # Scoring-sheet rows repeat verbatim across sheets: never merge them across units.
            scope = [uid] if kind in TABLE_ONLY_KINDS else []
            entity_id = stable_id('llm_entity', sid, [kind, key, *scope], revision='business')
            attrs = _attributes(kind, obj.get('attributes'), grounder, stats)
            if entity_id in ent:
                old = ent[entity_id]
                merged = dict(old.attributes)
                for k, v in attrs.items():
                    if k in merged and merged[k] != v:
                        merged[k] = None  # conflicting OCR readings: keep none, flag for review
                        merged[k.replace('_candidate', '_conflict')] = True
                    elif k not in merged:
                        merged[k] = v
                evidence = old.evidence + [e for e in [ev] if e not in old.evidence]
                ent[entity_id] = old.model_copy(update={'evidence': evidence, 'attributes': merged})
            else:
                ent[entity_id] = BusinessEntity(entity_id=entity_id, kind=EntityType(kind), label=' '.join(ev.quote.split()),
                                                source_id=sid, evidence=[ev], attributes=attrs,
                                                extraction_method=method)
            by_anchor[(kind, key)] = entity_id
            by_index[index] = (entity_id, kind, ev.quote)
        for obj in (response.get('relations') or [])[:80]:
            if not isinstance(obj, dict) or obj.get('type') not in ALLOWED_TRIPLES:
                stats['dropped_relations'] += 1
                continue
            relation_type = obj['type']
            src_kinds, dst_kinds = ALLOWED_TRIPLES[relation_type]

            def resolve(kinds, ref, anchor):
                # Index into the entities array (compact format); anchor text accepted for older responses.
                if isinstance(ref, int) and not isinstance(ref, bool) and ref in by_index:
                    entity_id, kind, quote = by_index[ref]
                    return (entity_id, quote) if kind in kinds else (None, None)
                if not isinstance(anchor, str):
                    return None, None
                matches = {by_anchor[(k, norm_label(anchor))] for k in kinds if (k, norm_label(anchor)) in by_anchor}
                return (next(iter(matches)), anchor) if len(matches) == 1 else (None, None)
            src, src_text = resolve(src_kinds, obj.get('source'), obj.get('source_anchor'))
            dst, dst_text = resolve(dst_kinds, obj.get('target'), obj.get('target_anchor'))
            # Proof is the shortest verbatim source span holding both endpoints, computed here
            # rather than copied by the model.
            proof = _covering_span(grounder.text, src_text, dst_text) if src and dst else None
            ev = grounder.ref(proof) if proof else None
            if src is None or dst is None or ev is None:
                stats['dropped_relations'] += 1
                continue
            rid = stable_id('llm_relation', sid, [relation_type, src, dst], revision='business')
            if rid in rel:
                old = rel[rid]
                rel[rid] = old.model_copy(update={'evidence': old.evidence + [e for e in [ev] if e not in old.evidence]})
            else:
                rel[rid] = BusinessRelation(relation_id=rid, relation_type=relation_type,
                                            source_entity_id=src, target_entity_id=dst, evidence=[ev],
                                            extraction_method=method)
        for obj in (response.get('rules') or [])[:40]:
            kind, anchor = (obj.get('kind'), obj.get('anchor')) if isinstance(obj, dict) else (None, None)
            ev = grounder.ref(anchor) if kind in RULE_KINDS else None
            if ev is None:
                stats['dropped_rules'] += 1
                continue
            rid = stable_id('llm_rule', sid, [uid, kind, norm_label(ev.quote)], revision='business')
            rules[rid] = BusinessRule(rule_id=rid, source_id=sid, kind=kind, statement=ev.quote, evidence=[ev])
    validate_business_graph(list(ent.values()), list(rel.values()))
    return {
        'entities': [e.model_dump(mode='json') for e in ent.values()],
        'relations': [r.model_dump(mode='json') for r in rel.values()],
        'rules': [r.model_dump(mode='json') for r in rules.values()],
        'errors': failures,
        'processed_unit_count': len(ok_units - failed_units),
        'chunk_count': len(jobs),
        'grounding': stats,
    }


ENRICHABLE_KINDS = {'Product', 'Organization', 'EvidenceType', 'ProductGroup', 'ProductSubgroup'}
# The deterministic scoring-sheet tree is arithmetic-checked; the LLM may only anchor to it.
ANCHOR_ONLY_KINDS = {'Criterion'}
_LEADING_CODE = re.compile(r'^\s*(?:phần\s+)?(?:[a-z]|\d+(?:[.,]\d+)*)\s*[.,:)\-]\s*', re.I)


_SHEET_PREFIX = re.compile(r'^\s*bộ\s+sản\s+phẩm\s*:\s*', re.I)
GROUP_FAMILY = {'CriterionSheet', 'ProductGroup', 'ProductSubgroup'}


def _resolution_key(label: str) -> str:
    return norm_label(_SHEET_PREFIX.sub('', _LEADING_CODE.sub('', str(label), count=1), count=1))


def _match(row: dict, candidates: list[dict]) -> dict | None:
    """Same label may recur on several sheets: require a shared evidence unit, then a shared page."""
    units = {e['evidence_unit_id'] for e in row['evidence']}
    pages = {e['pdf_page'] for e in row['evidence']}
    for test in (lambda c: units & {e['evidence_unit_id'] for e in c.get('evidence', [])},
                 lambda c: pages & {e['pdf_page'] for e in c.get('evidence', [])}):
        hits = [c for c in candidates if test(c)]
        if len(hits) == 1:
            return hits[0]
        if hits:
            return None
    return candidates[0] if len(candidates) == 1 and row['kind'] in ENRICHABLE_KINDS else None


def reconcile(proposed: dict, entities: list[dict], relations: list[dict]) -> dict:
    """Entity resolution against deterministic extraction (same source, kind, label without
    its leading code, and location).

    A matching LLM entity is folded into the existing one: its relations are re-pointed,
    duplicate relations dropped, and new descriptive features added only under keys the
    existing entity lacks. Scoring-sheet kinds are never modified, and an LLM Criterion
    without a deterministic match is dropped instead of forming a parallel tree."""
    index: dict[tuple, list[dict]] = {}
    for e in entities:
        index.setdefault((e['source_id'], e['kind'], _resolution_key(e['label'])), []).append(e)
    family = {}
    for e in entities:
        if e['kind'] in GROUP_FAMILY:
            family.setdefault((e['source_id'], _resolution_key(e['label'])), set()).add(e['kind'])
    options = {(e['source_id'], _resolution_key(e['label'])) for e in entities if e['kind'] == 'ScoreOption'}
    remap, enriched, kept, unanchored, kind_conflicts = {}, 0, [], 0, 0
    for row in proposed['entities']:
        key = (row['source_id'], _resolution_key(row['label']))
        target = _match(row, index.get((row['source_id'], row['kind'], key[1]), []))
        if row['kind'] == 'Condition' and key in options:
            kind_conflicts += 1  # an answer option restated as a condition
            continue
        if target is None and row['kind'] in GROUP_FAMILY and family.get(key, set()) - {row['kind']}:
            kind_conflicts += 1  # deterministic structure already typed this name differently
            continue
        if target is None:
            if row['kind'] in ANCHOR_ONLY_KINDS:
                unanchored += 1
            else:
                kept.append(row)
            continue
        remap[row['entity_id']] = target['entity_id']
        if row['kind'] in ENRICHABLE_KINDS:
            # The LLM mention becomes another grounded mention of the existing entity.
            evidence = target.setdefault('evidence', [])
            evidence.extend(e for e in row['evidence'] if e not in evidence)
            attrs = target.setdefault('attributes', {})
            added = [k for k in row.get('attributes', {}) if k not in attrs]
            for k in added:
                attrs[k] = row['attributes'][k]
            if added:
                enriched += len(added)
                previous = [k for k in str(attrs.get('llm_enriched_attributes') or '').split(',') if k]
                attrs['llm_enriched_attributes'] = ','.join(sorted(set(previous + added)))
    units_of = {e['entity_id']: {ev['evidence_unit_id'] for ev in e.get('evidence', [])}
                for e in list(entities) + kept}
    existing = {(r['relation_type'], r['source_entity_id'], r['target_entity_id']) for r in relations}
    out_rel, duplicates, ungrounded = [], 0, 0
    for row in proposed['relations']:
        if row['source_entity_id'] not in remap and row['source_entity_id'] not in units_of or \
                row['target_entity_id'] not in remap and row['target_entity_id'] not in units_of:
            ungrounded += 1  # endpoint dropped as unanchored
            continue
        row = dict(row, source_entity_id=remap.get(row['source_entity_id'], row['source_entity_id']),
                   target_entity_id=remap.get(row['target_entity_id'], row['target_entity_id']))
        if (row['relation_type'], row['source_entity_id'], row['target_entity_id']) in existing:
            duplicates += 1
            continue
        shared = units_of.get(row['source_entity_id'], set()) & units_of.get(row['target_entity_id'], set())
        if not shared & {ev['evidence_unit_id'] for ev in row['evidence']}:
            ungrounded += 1
            continue
        out_rel.append(row)
    # A Condition only means something under its criterion; drop ones left without a parent.
    linked = {r['target_entity_id'] for r in out_rel if r['relation_type'] == 'HAS_CONDITION'}
    orphans = [e for e in kept if e['kind'] == 'Condition' and e['entity_id'] not in linked]
    kept = [e for e in kept if e not in orphans]
    unanchored += len(orphans)
    return {**proposed, 'entities': kept, 'relations': out_rel,
            'reconciled': {'merged_entities': len(remap), 'enriched_attributes': enriched,
                           'duplicate_relations': duplicates, 'ungrounded_after_merge': ungrounded,
                           'unanchored_scoring_entities': unanchored, 'kind_conflicts': kind_conflicts}}
