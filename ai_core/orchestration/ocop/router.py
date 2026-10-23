"""Structured OCOP query analysis: language signals + catalog entities -> Route.

An intent is a business question, not a retrieval technology. Analysis runs in fixed stages:
slot extraction (document, article, form, sheet, page, criterion, dates, entities from the catalog),
facet detection (vocabulary from configs/ocop_language.yaml), policy (private / follow-up /
clarify / out-of-scope) and tool selection. The shared LLM may only suggest an intent from the
enum when nothing deterministic matched; it can never supply tools or authorization.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from datetime import date

from ai_core.orchestration.ocop.capabilities import CAPABILITY_TO_TOOLS, MAX_TOOL_CALLS, TOOL_REGISTRY, Capability
from ai_core.orchestration.ocop.catalog import EntityCatalog, Match
from ai_core.orchestration.ocop.contracts import Intent, Route
from ai_core.orchestration.ocop import memory
from ai_core.orchestration.ocop.language import Language, fold, get_language, has_diacritics
from ai_core.orchestration.ocop.privacy import get_privacy
from ai_core.orchestration.ocop.retrieval_strategy import choose_retrieval_path
from ai_core.retrieval.ocop.settings import get_settings

TOOLS = frozenset(TOOL_REGISTRY)

ROUTES = {
    Intent.OCOP_OVERVIEW: ('hybrid', ['search_regulations']),
    Intent.EXACT_LOOKUP: ('exact', ['lookup_legal_unit']),
    Intent.PRODUCT_CLASSIFICATION: ('structured', ['lookup_product_subgroup']),
    Intent.CRITERIA_LOOKUP: ('structured', ['lookup_criterion']),
    Intent.PROCEDURE_FORM: ('structured', ['lookup_form']),
    Intent.TEMPORAL_COMPARE: ('graph_hybrid', ['resolve_temporal_applicability', 'search_regulations']),
    Intent.RECOGNITION_LOOKUP: ('structured', ['lookup_recognition']),
    Intent.SECTOR_COMPLIANCE: ('hybrid', ['search_regulations']),
    Intent.DOSSIER_REVIEW: ('agentic', ['review_dossier']),
    Intent.SCORE_ESTIMATE: ('agentic', ['estimate_score']),
    Intent.MULTIHOP_REASONING: ('graph_hybrid', ['search_regulations', 'search_graph']),
    Intent.FOLLOWUP: ('hybrid', ['search_regulations']),
    Intent.CLARIFY: ('clarify', []),
    Intent.OUT_OF_SCOPE: ('clarify', []),
}
INTENT_CAPABILITY = {
    Intent.PRODUCT_CLASSIFICATION: Capability.CLASSIFY_PRODUCT, Intent.CRITERIA_LOOKUP: Capability.CRITERIA,
    Intent.RECOGNITION_LOOKUP: Capability.RECOGNITION, Intent.PROCEDURE_FORM: Capability.PROCEDURE_FORM,
    Intent.SECTOR_COMPLIANCE: Capability.SECTOR_COMPLIANCE, Intent.TEMPORAL_COMPARE: Capability.TEMPORAL,
    Intent.MULTIHOP_REASONING: Capability.RELATION_REASONING,
}
PRIVATE_CAPABILITIES = frozenset({Capability.REVIEW_DOSSIER, Capability.ESTIMATE_SCORE})
YEAR = re.compile(r'\b20\d{2}\b')
DATE_ISO = re.compile(r'\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b')
DATE_VI = re.compile(r'\b(0?[1-9]|[12]\d|3[01])[/.-](0?[1-9]|1[0-2])[/.-](20\d{2})\b')
BARE_CRITERION = re.compile(r'^\s*[A-Za-z]?\d{1,2}(?:\.\d{1,2}){1,3}\s*[?.!]*\s*$')
FOLLOWUP_SCOPE_KEYS = frozenset({
    'document_code', 'document_codes', 'article_id', 'form_id', 'form_ids', 'star_rating', 'as_of_date', 'years', 'region',
    'product_name', 'product_group', 'criterion_id', 'recognition_year', 'assessment_year', 'pdf_page',
    'sheet_number', 'organization_name',
})
# What the question is about, as opposed to where it applies (document, locality, year): a new target replaces the old one.
TARGET_KEYS = frozenset({'article_id', 'form_id', 'form_ids', 'sheet_number', 'criterion_id', 'pdf_page', 'product_name',
                         'organization_name'})
# Pattern for an identifier that looks like a private record handle (config-free: structural, not corpus data).
PRIVATE_HANDLE = get_privacy().regex('private_handle')


def _nfc(text: str) -> str:
    return unicodedata.normalize('NFC', text)


def _alt(words: list[str]) -> str:
    return '|'.join(r'\s+'.join(re.escape(w) for w in fold(x).split()) for x in sorted(words, key=len, reverse=True))


class _Patterns:
    """Regexes assembled from the vocabulary file (folded, whole word)."""

    def __init__(self, lang: Language):
        doc = _alt([w for words in lang.document_types.values() for w in words])
        n = lang.structure_nouns
        number = r'(\d{1,4}(?:[/.-]\d{2,4})?(?:[/.-][a-z]+\d*)*)'
        self.document = re.compile(r'(?<![a-z0-9])(?:' + doc + r')\s*(?:so\s*)?' + number)
        self.bare_number = re.compile(r'(?<![a-z0-9/])(\d{1,4}/(?:19|20)\d{2}(?:/[a-z]+\d*)?(?:-[a-z]+)*)(?![a-z0-9/])')
        self.type_words = {kind: re.compile(r'(?<![a-z0-9])(?:' + _alt(words) + r')(?![a-z0-9])')
                           for kind, words in lang.document_types.items()}
        self.article = re.compile(r'(?<![a-z0-9])(?:' + _alt(n['article']) + r')\s*(\d{1,3})(?!\d)')
        self.form = re.compile(r'(?<![a-z0-9])(?:' + _alt(n['form']) + r')\s*(?:so\s*)?0?([1-9]\d?)(?!\d)')
        self.form_list = re.compile(r'(?<![a-z0-9])(?:' + _alt(n['form']) + r')\s*(?:so\s*)?0?([1-9]\d?)\b'
                                    r'((?:\s*(?:,|va|&|/)\s*0?[1-9]\d?\b){1,6})')
        self.sheet = re.compile(r'(?<![a-z0-9])(?:' + _alt(n['sheet']) + r')\s*(?:so\s*)?(\d{1,3})(?!\d)')
        self.page = re.compile(r'(?<![a-z0-9])(?:' + _alt(n['page']) + r')\s*(\d{1,4})(?!\d)')
        self.criterion = re.compile(r'(?<![a-z0-9])(?:' + _alt(n['criterion']) + r')\s+(?:so\s+)?([a-z]?\d+(?:\.\d+){0,3})(?!\d)')
        self.star = re.compile(r'(?<![\d.])(' + '|'.join(str(x) for x in lang.star_levels) + r')\s*(?:' + _alt(lang.star_noun) + r')\b')
        markers = _alt(lang.locality_markers)
        self.locality_marker = re.compile(r'(?<![a-z0-9])(?:' + markers + r')\s+(?=\S)')
        self.word = re.compile(r'[\wÀ-ỹ]+')
        self.markers = frozenset(unicodedata.normalize('NFC', m).casefold() for m in lang.locality_markers)
        self.locality_blocker = re.compile(r'(?:' + _alt(lang.locality_marker_blockers) + r')\s*$')
        self.product_marker = re.compile(r'(?<![a-z0-9])(?:' + _alt(lang.product_markers) + r')\s+(.+)')
        self.terminator = re.compile(r'(?<![a-z0-9])(?:' + _alt(lang.entity_terminators) + r')(?![a-z0-9])|[?.!,;:]')
        self.non_entity = re.compile(r'^(?:' + _alt(lang.non_entity_phrases) + r')$')


_PATTERN_CACHE: dict[int, _Patterns] = {}


def _patterns(lang: Language) -> _Patterns:
    if id(lang) not in _PATTERN_CACHE:
        _PATTERN_CACHE[id(lang)] = _Patterns(lang)
    return _PATTERN_CACHE[id(lang)]


def _product_from_marker(query: str, folded: str, p: _Patterns) -> str | None:
    """Name following a product marker, ended by an interrogative/connective; spelling is preserved."""
    marker = p.product_marker.search(folded)
    if not marker:
        return None
    start = marker.start(1)
    tail = folded[start:]
    end = p.terminator.search(tail)
    raw = query[start:start + (end.start() if end else len(tail))].strip(' ,-')
    key = fold(raw)
    if not raw or p.non_entity.match(key) or re.match(r'^(?:20\d{2}|\d+)\b', key) or len(raw.split()) > 9:
        return None
    return raw


def _gazetteer(lang: Language, text: str) -> list[Match]:
    """Provincial names from the vocabulary file, matched under the same accent policy as the catalog."""
    return EntityCatalog({'entities': {'region': [{'label': name, 'source_ids': []} for name in lang.localities]}}).find(
        'region', text)


def _capitalised_run(p: _Patterns, text: str, start: int, limit: int = 4) -> str | None:
    words, pos = [], start
    for _ in range(limit):
        m = p.word.match(text, pos)
        if not m or not m.group(0)[0].isupper():
            break
        words.append(m.group(0))
        pos = m.end()
        gap = re.match(r'\s+', text[pos:])
        if not gap:
            break
        pos += gap.end()
    return ' '.join(words) or None


def _document_by_title_year(lang: Language, p: _Patterns, catalog: EntityCatalog, folded: str, *, years_found: list[str]):
    """"Luật ... 2023" -> the one catalogued law of 2023 (type word + year, both from the vocabulary/registry)."""
    if len(set(years_found)) != 1:
        return None
    for kind, rx in p.type_words.items():
        if rx.search(folded):
            code = catalog.document_by_type_year(kind, years_found[0])
            if code:
                return code
    return None


def extract_slots(query: str, *, catalog: EntityCatalog | None = None, language: Language | None = None) -> dict:
    """Explicit slots only; never assume a date, product group or document."""
    lang = language or get_language()
    p = _patterns(lang)
    text = _nfc(query)
    folded = fold(text)
    slots: dict = {}
    if (m := p.document.search(folded)) and not re.fullmatch(r'(?:19|20)\d{2}', m.group(1)):
        slots['document_code'] = text[m.start(1):m.end(1)]
    elif m := p.bare_number.search(folded):
        slots['document_code'] = text[m.start():m.end()]
    elif catalog is not None and (code := _document_by_title_year(lang, p, catalog, folded, years_found=YEAR.findall(text))):
        slots['document_code'] = code
    # Several documents named in one question (a comparison): every one is searched, none is dropped.
    codes = list(dict.fromkeys(text[m.start(1):m.end(1)] for m in p.document.finditer(folded)
                               if not re.fullmatch(r'(?:19|20)\d{2}', m.group(1))))
    if len(codes) > 1:
        slots['document_codes'] = codes
    if m := p.article.search(folded):
        slots['article_id'] = m.group(1)
    form_ids = [x.lstrip('0') for x in dict.fromkeys(m.group(1) for m in p.form.finditer(folded))]
    for m in p.form_list.finditer(folded):
        form_ids.extend(str(int(n)) for n in [m.group(1), *re.findall(r'(?:,|va|&|/)\s*0?([1-9]\d?)\b', m.group(2))])
    form_ids = list(dict.fromkeys(form_ids))
    if len(form_ids) > 1:
        slots['form_ids'] = form_ids
    if form_ids:
        slots['form_id'] = form_ids[0]
    if m := p.star.search(folded):
        slots['star_rating'] = int(m.group(1))
    last_date = None
    for m in DATE_ISO.finditer(text):
        try:
            last_date = (m.start(), date(*map(int, m.groups())).isoformat())
        except ValueError:
            pass
    for m in DATE_VI.finditer(text):
        try:
            day, month, year = map(int, m.groups())
            candidate = (m.start(), date(year, month, day).isoformat())
            if last_date is None or candidate[0] > last_date[0]:
                last_date = candidate
        except ValueError:
            pass
    if last_date:
        slots['as_of_date'] = last_date[1]
    years = list(dict.fromkeys(YEAR.findall(text)))
    if years:
        slots['years'] = years
    if (m := p.page.search(folded)) and int(m.group(1)) > 0:
        slots['pdf_page'] = int(m.group(1))
    if (m := p.sheet.search(folded)) and int(m.group(1)) > 0:
        slots['sheet_number'] = int(m.group(1))
    if m := p.criterion.search(folded):
        if not re.fullmatch(r'20\d{2}', m.group(1)):
            slots['criterion_id'] = m.group(1)
    catalog = catalog or EntityCatalog()
    # Locality: catalog entry, else a marker + capitalised words the user literally wrote.
    regions = catalog.find('region', text) or _gazetteer(lang, text)
    if regions:
        slots['region'] = regions[0].label
    else:
        accented = has_diacritics(text)
        for m in p.locality_marker.finditer(folded):
            marker = re.sub(r'\s+', ' ', text[m.start():m.end()].strip().casefold())
            if accented and marker not in p.markers:
                continue  # accented query: "quan" in "liên quan" is not the marker "quận"
            name = _capitalised_run(p, text, m.end())
            if name and not p.locality_blocker.search(folded[:m.start()]):
                slots['region'] = name
                break
    products = catalog.find('product', text) or catalog.find('product_group', text)
    if products:
        slots['product_name'] = max(products, key=lambda x: x.end - x.start).label
    elif name := _product_from_marker(text, folded, p):
        slots['product_name'] = name
    if orgs := catalog.find('organization', text):
        slots['organization_name'] = max(orgs, key=lambda x: x.end - x.start).label
    only_year_in_code = len(years) == 1 and not slots.get('document_code')
    event = re.search(r'(?:' + _alt(lang.cues['event_year_scope']) + r').{0,90}?\bnam\s+(20\d{2})\b', folded)
    assessment = re.search(r'(?:' + _alt(lang.cues['assessment_year_scope']) + r').{0,90}?\bnam\s+(20\d{2})\b', folded)
    if event:
        slots['recognition_year'] = int(event.group(1))
    if assessment:
        slots['assessment_year'] = int(assessment.group(1))
    if only_year_in_code:
        if lang.hit(text, 'assessment_year_marker'):
            slots['assessment_year'] = int(years[0])
        if lang.hit(text, 'recognition_year_marker'):
            slots['recognition_year'] = int(years[0])
    return slots


def _merge_followup(prior: dict, updates: dict) -> dict:
    """Carry only ordinary question-extracted scope; never ids, auth or verified flags."""
    raw = prior.get('slots') or {}
    if not isinstance(raw, dict):
        raw = {}
    slots = {key: value for key, value in raw.items() if key in FOLLOWUP_SCOPE_KEYS and (
        isinstance(value, str) and len(value) <= 128 or
        type(value) is int and 0 <= value <= 2100 or
        key in ('years', 'form_ids') and isinstance(value, list) and len(value) <= 8 and
        all(isinstance(x, str) and len(x) <= 12 for x in value))}
    new_doc = updates.get('document_code')
    if new_doc and fold(str(new_doc)) != fold(str(slots.get('document_code') or '')):
        slots = {key: value for key, value in slots.items() if key not in TARGET_KEYS}  # another document: its Điều/Mẫu/Phiếu are not the old one's
    if set(updates) & TARGET_KEYS:  # a new thing asked about replaces the old one ("Còn mẫu số 02?" is no longer Điều 6)
        slots = {key: value for key, value in slots.items() if key not in TARGET_KEYS}
    slots.update(updates)
    if 'years' in updates:
        if 'as_of_date' not in updates:
            slots.pop('as_of_date', None)
        for key in ('assessment_year', 'recognition_year'):
            if key not in updates:
                slots.pop(key, None)
    return slots


class Facets:
    """Question facets derived from vocabulary cues and slots (one place, no scattered keyword lists)."""

    def __init__(self, lang: Language, text: str, slots: dict):
        folded = fold(text)
        h = lambda name: lang.hit(text, name)  # noqa: E731
        self.authority = h('authority')
        self.multihop = h('multihop')
        self.compliance = h('compliance')
        self.classification = h('classification')
        self.procedure = h('procedure')
        self.scoring_method = h('scoring_method')
        years = slots.get('years') or []
        legal = h('temporal_legal_scope')
        compare_scope = h('temporal_compare_scope') or h('temporal_compare_old_new')
        self.temporal = bool((len(years) >= 2 and legal) or h('temporal_strong') or (
            h('temporal_compare') and (len(years) >= 2 or (years and compare_scope) or h('temporal_compare_old_new'))))
        stars = bool(slots.get('star_rating'))
        self.normative_star = stars and h('normative_star') and not h('recognition_listing_negative')
        self.rating_assertion = stars and h('rating_assertion')
        self.recognition = not self.authority and h('recognition')
        self.criteria = h('criteria') or self.normative_star or bool(slots.get('criterion_id') or slots.get('sheet_number'))
        self.evidence_requirements = h('evidence_requirements')
        self.relation = bool(slots.get('document_code') and h('relation')) or h('relation_open')
        negated = bool(re.search(r'(?<![a-z0-9])(?:' + _alt(lang.cues['scoring_negation']) + r')\s+(?:can\s+)?(?:tinh|cham|uoc tinh)\s+diem\b', folded))
        verbs = h('private_scoring_verbs')
        self.private_scoring = (not self.scoring_method and not negated and (
            h('private_scoring') or bool(re.fullmatch(r'(?:hay\s+)?(?:tinh|cham|uoc tinh)\s+diem(?:\s+ocop)?[?.!]*', folded)) or
            (bool(re.search(r'\btinh diem\b.{0,30}(?<![a-z0-9])(?:' + _alt(lang.cues['scoring_hypothetical']) + r')\b', folded))) or
            (verbs and h('private_scoring_object'))))
        self.private_dossier = h('private_dossier') and not h('private_dossier_negative')
        self.private_scope = h('private_scope') or bool(h('private_open') and PRIVATE_HANDLE.search(folded.upper()))
        self.recognition_listing = h('recognition_listing')


def _capabilities(facets: Facets, slots: dict) -> tuple[list[Capability], list[str]]:
    found: list[Capability] = []
    reasons: list[str] = []

    def add(cap: Capability, reason: str):
        if cap not in found:
            found.append(cap)
            reasons.append(reason)
    if slots.get('document_code') and (slots.get('article_id') or slots.get('pdf_page')):
        add(Capability.EXACT_ARTICLE, 'document_and_locator')
    if facets.authority:
        add(Capability.EXACT_ARTICLE, 'authority_signal')
    if facets.classification:
        add(Capability.CLASSIFY_PRODUCT, 'product_classification_signal')
    if facets.criteria or facets.scoring_method:
        add(Capability.CRITERIA, 'criterion_signal')
    if facets.evidence_requirements:
        add(Capability.EVIDENCE_REQUIREMENTS, 'evidence_requirements_signal')
    if slots.get('form_id') or facets.procedure:
        add(Capability.PROCEDURE_FORM, 'procedure_form_signal')
    if facets.temporal:
        add(Capability.TEMPORAL, 'legal_temporal_signal')
    if facets.recognition or facets.rating_assertion or (slots.get('product_name') and slots.get('_producer')):
        add(Capability.RECOGNITION, 'recognition_signal')
    if facets.compliance:
        add(Capability.SECTOR_COMPLIANCE, 'compliance_signal')
    if facets.private_dossier:
        add(Capability.REVIEW_DOSSIER, 'private_dossier_action')
    if facets.private_scoring:
        add(Capability.ESTIMATE_SCORE, 'private_scoring_action')
    if facets.relation or (Capability.EVIDENCE_REQUIREMENTS in found and Capability.CRITERIA in found):
        add(Capability.RELATION_REASONING, 'relational_signal')
    if not found:
        add(Capability.OVERVIEW, 'general_ocop_question')
    return found, reasons


def _select_tools(caps: list[Capability], slots: dict, facets: Facets) -> tuple[list[str], list[str]]:
    """Primary tools answer the question; secondary tools only enrich it and never block the answer."""
    explicit = set(caps)
    if explicit & PRIVATE_CAPABILITIES:
        return list(dict.fromkeys(t for c in caps if c in PRIVATE_CAPABILITIES for t in CAPABILITY_TO_TOOLS[c])), []
    primary: list[str] = []
    secondary: list[str] = []
    located = Capability.EXACT_ARTICLE in explicit
    criterion_scope = any(slots.get(k) for k in ('criterion_id', 'product_name', 'product_group', 'document_code', 'sheet_number'))
    for cap in caps:
        tools = list(CAPABILITY_TO_TOOLS[cap])
        target = primary
        if located and cap != Capability.EXACT_ARTICLE:
            # A located article is answered from that article; other capabilities are optional extras
            # and only when the question carries what they need (a form number; a criterion/product scope).
            if cap == Capability.PROCEDURE_FORM and slots.get('form_id'):
                target = secondary
            elif cap == Capability.CRITERIA and (slots.get('criterion_id') or slots.get('sheet_number')):
                target = secondary
            elif cap in (Capability.TEMPORAL, Capability.RELATION_REASONING, Capability.RECOGNITION):
                target = primary
            else:
                continue
        if cap == Capability.PROCEDURE_FORM and not slots.get('form_id'):
            tools = ['search_regulations']
        if cap == Capability.CRITERIA and not criterion_scope and not explicit & {
                Capability.CLASSIFY_PRODUCT, Capability.EVIDENCE_REQUIREMENTS}:
            tools = ['search_regulations']
        target.extend(tools)
    if len(caps) > 1 and 'search_regulations' not in primary + secondary and explicit & {
            Capability.TEMPORAL, Capability.SECTOR_COMPLIANCE, Capability.RELATION_REASONING}:
        primary.append('search_regulations')
    if Capability.RECOGNITION in explicit and 'search_regulations' not in primary:
        secondary.append('search_regulations')   # the decision's own articles explain a list of recognised products
    if explicit == {Capability.EXACT_ARTICLE} and not facets.authority:
        primary = ['lookup_legal_unit']
    if facets.authority:
        primary = list(dict.fromkeys(['lookup_legal_unit', 'search_regulations', *primary]))
    if Capability.TEMPORAL in explicit and Capability.RECOGNITION in explicit:
        primary = ['lookup_recognition'] + [t for t in primary if t != 'lookup_recognition']
    primary = list(dict.fromkeys(t for t in primary if t in TOOLS))
    secondary = [t for t in dict.fromkeys(secondary) if t in TOOLS and t not in primary]
    return primary, secondary


def _route_business(query: str, *, session: dict | None = None, llm_route: Callable[[str], dict] | None = None,
                indexed_content_bigram_coverage: Callable[[str], float | None] | None = None,
                catalog: EntityCatalog | None = None, language: Language | None = None) -> Route:
    lang = language or get_language()
    catalog = catalog or EntityCatalog()
    q = _nfc(query).strip()
    if not q:
        return Route(intent=Intent.CLARIFY, strategy='clarify', needs_clarification=True,
                     missing_slots=['question'], reason_codes=['empty_query'])
    folded = fold(q)
    prior = session or {}
    has_prior = bool(prior.get('last_query'))
    updates = extract_slots(q, catalog=catalog, language=lang)
    # "Hai mẫu này khác nhau ở đâu?": things the conversation discussed, named by a plural reference or a comparison.
    carried = memory.plural_referents(q, prior.get('memory'), updates, lang) if has_prior else {}
    if not carried and (dangling := memory.dangling_reference(q, prior.get('memory'), updates, lang)):
        # "these two forms" with nothing earlier to point at: ask which, never guess from whatever the search returns
        return Route(intent=Intent.CLARIFY, strategy='clarify', needs_clarification=True,
                     missing_slots=['referent_' + dangling], reason_codes=['plural_reference_unresolved'])
    own_scope = bool(set(updates) & {'document_code', 'article_id', 'form_id', 'sheet_number', 'pdf_page',
                                     'criterion_id', 'product_name', 'organization_name', 'region'})
    structural_scope = bool(set(updates) & {'document_code', 'article_id', 'form_id', 'sheet_number', 'pdf_page', 'criterion_id'})
    content = lang.content_words(q)
    opener = bool(re.match(r'^(?:' + _alt(lang.followup.openers) + r'|20\d{2}\b|nam\s+20\d{2}\b)', folded))
    pronoun = bool(lang.words('pronouns', lang.followup.pronouns).search(folded))
    pronoun = pronoun or memory.singular_reference(q, lang)
    tail = bool(lang.words('tail_cues', lang.followup.tail_cues).search(folded)) if lang.followup.tail_cues else False
    # A reference ("sản phẩm đó", "... thì sao?") with no scope of its own continues the conversation, whatever its length.
    # A reference or closing cue continues the conversation unless the question says WHERE it applies (document, locality) itself:
    # naming only a new target ("Mẫu số 02 thì sao?") still inherits the document.
    own_where = bool(set(updates) & {'document_code', 'document_codes', 'region'})
    followup = has_prior and (opener or bool(carried) or (not own_where and (pronoun or tail)))
    updates = {**updates, **carried}
    slots = _merge_followup(prior, updates) if followup else updates
    old_code = (prior.get('slots') or {}).get('document_code') if followup else None
    old_year = YEAR.findall(str(old_code or ''))
    changed_year = updates.get('years', [])
    if old_year and changed_year and changed_year[-1] != old_year[-1] and not updates.get('document_code'):
        return Route(intent=Intent.CLARIFY, strategy='clarify', slots=slots, needs_clarification=True,
                     missing_slots=['document_version_or_event_year'],
                     reason_codes=['historical_year_conflicts_with_pinned_document'])
    facets = Facets(lang, q, slots)
    producer = lang.hit(q, 'producer')
    if producer:
        slots_for_caps = {**slots, '_producer': True}
    else:
        slots_for_caps = slots

    # Private requests never reach public search; AuthContext is checked in the workflow.
    if facets.private_scope and not facets.private_dossier and not facets.private_scoring:
        return Route(intent=Intent.DOSSIER_REVIEW, strategy='agentic', slots={}, required_tools=['review_dossier'],
                     capabilities=[Capability.REVIEW_DOSSIER.value], reason_codes=['private_scope_request'])

    in_domain = (lang.hit(q, 'in_domain') or structural_scope or facets.temporal or facets.classification or
                 facets.compliance or facets.authority or facets.criteria or facets.recognition or facets.scoring_method or
                 facets.private_dossier or facets.private_scoring or any(catalog.mentions(q).values()) or
                 bool(slots.get('star_rating') or slots.get('years') and followup))
    explicit_oos = lang.hit(q, 'explicit_out_of_scope')
    bare_code = bool(BARE_CRITERION.match(q)) and not followup
    reopened = False
    if not in_domain and not followup and not explicit_oos and indexed_content_bigram_coverage is not None:
        try:
            coverage = indexed_content_bigram_coverage(q)
        except (OSError, RuntimeError, ValueError, TypeError, KeyError):
            coverage = None
        if isinstance(coverage, (int, float)) and not isinstance(coverage, bool) and \
                get_settings().agent.scope_min_bigram_coverage <= coverage <= 1.0:
            in_domain = reopened = True
    if explicit_oos:
        return Route(intent=Intent.OUT_OF_SCOPE, strategy='clarify', slots=slots, reason_codes=['explicit_out_of_scope'])
    if bare_code or (not in_domain and not followup and len(content) <= 3) or (
            pronoun and not has_prior and not own_scope and len(content) <= 2):
        missing = ['document_or_sheet_for_code'] if bare_code else ['topic']
        return Route(intent=Intent.CLARIFY, strategy='clarify', slots=slots, needs_clarification=True,
                     missing_slots=missing, reason_codes=['fragment_needs_scope'])
    if not in_domain and not followup:
        return Route(intent=Intent.OUT_OF_SCOPE, strategy='clarify', slots=slots, reason_codes=['no_domain_signal'])

    caps, cap_reasons = _capabilities(Facets(lang, q, slots_for_caps) if producer else facets, slots_for_caps)
    scores: dict[Intent, int] = {}
    if facets.private_scoring and not facets.scoring_method:
        scores[Intent.SCORE_ESTIMATE] = 90
    if facets.scoring_method:
        scores[Intent.CRITERIA_LOOKUP] = 70
    if facets.private_dossier:
        scores[Intent.DOSSIER_REVIEW] = 85
    if facets.multihop and (facets.criteria or facets.procedure or facets.compliance or facets.recognition):
        scores[Intent.MULTIHOP_REASONING] = 80
    if facets.temporal:
        scores[Intent.TEMPORAL_COMPARE] = 75
    if facets.authority:
        scores[Intent.EXACT_LOOKUP] = 88
    elif updates.get('article_id') and updates.get('document_code'):
        scores[Intent.EXACT_LOOKUP] = 70
    if facets.classification:
        scores[Intent.PRODUCT_CLASSIFICATION] = 65
    if facets.compliance:
        scores[Intent.SECTOR_COMPLIANCE] = 60
    if facets.recognition and not facets.normative_star:
        scores[Intent.RECOGNITION_LOOKUP] = 55
    if (slots.get('product_name') or slots.get('organization_name')) and producer:
        scores[Intent.RECOGNITION_LOOKUP] = max(75, scores.get(Intent.RECOGNITION_LOOKUP, 0))
    if facets.rating_assertion and slots.get('star_rating') and not facets.scoring_method:
        scores[Intent.RECOGNITION_LOOKUP] = max(78, scores.get(Intent.RECOGNITION_LOOKUP, 0))
    if facets.normative_star:
        scores[Intent.CRITERIA_LOOKUP] = max(85, scores.get(Intent.CRITERIA_LOOKUP, 0))
    if facets.procedure:
        scores[Intent.PROCEDURE_FORM] = 50
    if facets.criteria:
        scores.setdefault(Intent.CRITERIA_LOOKUP, 45)
    if lang.hit(q, 'procedure_own'):
        scores[Intent.PROCEDURE_FORM] = 72
    if facets.multihop:
        scores.setdefault(Intent.MULTIHOP_REASONING, 35)
    if facets.recognition and facets.recognition_listing:
        scores[Intent.RECOGNITION_LOOKUP] = 80
    if followup and not scores:
        try:
            parent = Intent(prior.get('intent'))
        except (ValueError, TypeError):
            parent = Intent.OCOP_OVERVIEW
        scores[Intent.OCOP_OVERVIEW if parent == Intent.FOLLOWUP else parent] = 30
    if scores:
        intent = max(scores, key=scores.get)
    else:
        intent = Intent.OCOP_OVERVIEW
        if llm_route is not None:
            try:
                result = llm_route(q)
                candidate = Intent(result['intent'])
                if candidate != Intent.CONVERSATION and (candidate not in (Intent.DOSSIER_REVIEW, Intent.SCORE_ESTIMATE) or prior.get('dossier_id')):
                    intent = candidate
                safe = {'product_name', 'product_group', 'region', 'as_of_date', 'document_code', 'form_id', 'criterion_id'}
                slots.update({k: v for k, v in (result.get('slots') or {}).items()
                              if k in safe and isinstance(v, (str, int)) and len(str(v)) <= 128})
            except (ValueError, KeyError, TypeError, AttributeError):
                pass
    effective = intent
    if followup and Intent.SCORE_ESTIMATE not in scores and Intent.DOSSIER_REVIEW not in scores:
        if not scores or max(scores.values()) < 75:
            intent = Intent.FOLLOWUP
            try:
                effective = Intent(prior.get('intent'))
            except (ValueError, TypeError):
                effective = Intent.OCOP_OVERVIEW
            if effective in (Intent.FOLLOWUP, Intent.CLARIFY, Intent.OUT_OF_SCOPE):
                effective = Intent.OCOP_OVERVIEW
    strategy, _ = ROUTES[effective]

    if facets.normative_star:
        caps = [c for c in caps if c != Capability.RECOGNITION]
        if Capability.CRITERIA not in caps:
            caps.insert(0, Capability.CRITERIA)
        cap_reasons.append('normative_star_requires_criteria_not_recognition_records')
    document_changed = bool(updates.get('document_code') and
                            updates['document_code'] != (prior.get('slots') or {}).get('document_code'))
    if followup and caps == [Capability.OVERVIEW] and not document_changed:
        previous = [Capability(x) for x in prior.get('capabilities') or [] if x in Capability._value2member_map_]
        if previous:
            caps = previous
        else:
            try:
                old = Intent(prior.get('intent'))
            except (TypeError, ValueError):
                old = Intent.OCOP_OVERVIEW
            caps = [INTENT_CAPABILITY[old]] if old in INTENT_CAPABILITY else caps
    if intent == Intent.OUT_OF_SCOPE:
        caps = []
    elif caps == [Capability.OVERVIEW] and effective in INTENT_CAPABILITY:
        caps = [INTENT_CAPABILITY[effective]]
    if set(caps) & PRIVATE_CAPABILITIES:
        caps = [c for c in caps if c in PRIVATE_CAPABILITIES]
    required, secondary = _select_tools(caps, slots, facets)
    if not required and effective in ROUTES:
        required = list(ROUTES[effective][1])
    if (slots.get('years') and not slots.get('document_code') and
            effective in (Intent.PROCEDURE_FORM, Intent.CRITERIA_LOOKUP, Intent.SECTOR_COMPLIANCE, Intent.OCOP_OVERVIEW)
            and 'search_regulations' in required and not set(caps) & PRIVATE_CAPABILITIES
            and not (slots.get('region') and lang.hit(q, 'deadline'))):
        required = list(dict.fromkeys(['resolve_temporal_applicability', *required]))
    if slots.get('pdf_page') and slots.get('document_code') and not set(caps) & PRIVATE_CAPABILITIES:
        required, secondary = ['lookup_legal_unit'], []
    missing = []
    if effective in (Intent.DOSSIER_REVIEW, Intent.SCORE_ESTIMATE):
        missing = [key for key in ('tenant_id', 'dossier_id') if not prior.get(key)]
    if missing:
        return Route(intent=Intent.CLARIFY, strategy='clarify', slots=slots, needs_clarification=True,
                     missing_slots=missing, reason_codes=['required_dossier_context_missing'])
    if len(required) + len(secondary) > MAX_TOOL_CALLS:
        secondary = secondary[:max(0, MAX_TOOL_CALLS - len(required))]
    if len(required) > MAX_TOOL_CALLS:
        return Route(intent=Intent.CLARIFY, strategy='clarify', slots=slots, needs_clarification=True,
                     missing_slots=['split_question'], reason_codes=['tool_budget_exceeded'] + cap_reasons)
    others = [x for x in scores if x != effective and scores[x] >= 40]
    return Route(intent=intent, strategy=strategy, retrieval_path=choose_retrieval_path(required + secondary),
                 slots=slots, required_tools=required, secondary_tools=secondary, secondary_intents=others[:3],
                 capabilities=[c.value for c in caps],
                 reason_codes=(['followup_slot_override' if followup else 'deterministic_multi_signal'] + cap_reasons +
                               (['indexed_content_bigram_scope_recovery'] if reopened else [])),
                 confidence=None)


def route_query(query: str, *, session: dict | None = None, llm_route: Callable[[str], dict] | None = None,
                indexed_content_bigram_coverage: Callable[[str], float | None] | None = None,
                catalog: EntityCatalog | None = None, language: Language | None = None,
                dialogue_client=None) -> Route:
    """Dialogue acts compose with, rather than compete against, business intents."""
    from ai_core.orchestration.ocop import dialogue
    prior = session or {}
    decision, task = dialogue.understand(_nfc(query), language=language)
    options = dict(session=prior, llm_route=llm_route, catalog=catalog, language=language,
                   indexed_content_bigram_coverage=indexed_content_bigram_coverage)
    # A complete grammar match consumes all words. Mixed messages keep the task
    # remainder and must take business routing, including private/auth policy.
    if decision.action == 'respond':
        return Route(intent=Intent.CONVERSATION, strategy='conversation', dialogue=decision,
                     reason_codes=['dialogue_full_utterance'])
    if decision.action in dialogue.REPAIR:
        return _repair_route(decision, prior, options)
    pending = prior.get('unresolved') or {}
    if (pending.get('question') and extract_slots(task, catalog=catalog, language=language)
            and set(pending.get('missing_slots') or []) & {'topic', 'document_or_sheet_for_code', 'document_or_sheet'}):
        # Resume only topic clarification. Authentication/version conflicts are
        # never satisfied by a conversational slot answer.
        pending_query = str(pending['question'])
        if BARE_CRITERION.fullmatch(pending_query):
            pending_query = (language or get_language()).structure_nouns['criterion'][0]+' '+pending_query
        resumed = _route_business(pending_query + ' ' + task, **options)
        resumed.reason_codes.append('clarification_resumed')
        resumed.dialogue = decision.model_copy(update={'action': 'resume'})
        return resumed
    business_query = task or query
    if 'correction' in decision.acts and prior.get('last_query'):
        business_query = (language or get_language()).followup.openers[0]+' '+business_query
    choice = _route_business(business_query, **options)
    if (dialogue_client is not None and not decision.acts and
            choice.intent in (Intent.CLARIFY, Intent.OUT_OF_SCOPE) and
            not choice.slots and choice.reason_codes in (['fragment_needs_scope'], ['no_domain_signal'])):
        assisted = dialogue.assisted(dialogue_client, query, has_topic=bool(prior.get('last_query')))
        if assisted:
            if assisted.action in dialogue.REPAIR:
                return _repair_route(assisted, prior, options)
            return Route(intent=Intent.CONVERSATION, strategy='conversation', dialogue=assisted,
                         reason_codes=['dialogue_structured_abstention_fallback'])
    choice.dialogue = decision
    return choice


def _repair_route(decision, prior: dict, options: dict) -> Route:
    if decision.action == 'correction' or not prior.get('last_query'):
        return Route(intent=Intent.CLARIFY, strategy='clarify', needs_clarification=True,
                     missing_slots=['correction_detail' if prior.get('last_query') else 'topic'],
                     reason_codes=['dialogue_repair_needs_detail'], dialogue=decision)
    # Re-read the active question against current corpus. Never treat a previous
    # answer, or social prose, as evidence. Existing verification still applies.
    choice = _route_business(str(prior['last_query']), **options)
    choice.slots = dict(prior.get('slots') or choice.slots)
    choice.reason_codes.append('dialogue_revalidate_topic')
    choice.dialogue = decision
    return choice
