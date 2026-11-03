"""Structured OCOP query analysis: language signals + catalog entities -> Route.

An intent is a business question, not a retrieval technology. Analysis runs in fixed stages:
slot extraction (document, article, form, sheet, page, criterion, dates, entities from the catalog),
facet detection (vocabulary from configs/ocop_language.yaml), policy (private / follow-up /
clarify / out-of-scope) and tool selection. The shared LLM may only suggest an intent from the
enum when nothing deterministic matched; it can never supply tools or authorization.
"""

from __future__ import annotations

from ai_core.orchestration.ocop.document_scope import DocumentResolver, document_pattern

import re
import json
import unicodedata
from collections.abc import Callable
from datetime import date

from ai_core.orchestration.ocop.capabilities import (
    CAPABILITY_TO_TOOLS,
    MAX_TOOL_CALLS,
    TOOL_REGISTRY,
    Capability,
)
from ai_core.orchestration.ocop.catalog import EntityCatalog, Match
from ai_core.orchestration.ocop.contracts import Intent, Route
from ai_core.orchestration.ocop import memory
from ai_core.orchestration.ocop.language import Language, fold, get_language, has_diacritics
from ai_core.orchestration.ocop.privacy import get_privacy
from ai_core.orchestration.ocop.retrieval_strategy import choose_retrieval_path
from ai_core.retrieval.ocop.settings import get_settings
from ai_core.retrieval.ocop.decompose import sub_queries

TOOLS = frozenset(TOOL_REGISTRY)

ROUTES = {
    Intent.OCOP_OVERVIEW: ("hybrid", ["search_regulations"]),
    Intent.EXACT_LOOKUP: ("exact", ["lookup_legal_unit"]),
    Intent.PRODUCT_CLASSIFICATION: ("structured", ["lookup_product_subgroup"]),
    Intent.CRITERIA_LOOKUP: ("structured", ["lookup_criterion"]),
    Intent.PROCEDURE_FORM: ("structured", ["lookup_form"]),
    Intent.TEMPORAL_COMPARE: ("graph_hybrid", ["resolve_temporal_applicability", "search_regulations"]),
    Intent.RECOGNITION_LOOKUP: ("structured", ["lookup_recognition"]),
    Intent.SECTOR_COMPLIANCE: ("hybrid", ["search_regulations"]),
    Intent.MULTIHOP_REASONING: ("graph_hybrid", ["search_regulations", "search_graph"]),
    Intent.FOLLOWUP: ("hybrid", ["search_regulations"]),
    Intent.CLARIFY: ("clarify", []),
    Intent.OUT_OF_SCOPE: ("clarify", []),
}
INTENT_CAPABILITY = {
    Intent.EXACT_LOOKUP: Capability.EXACT_ARTICLE,
    Intent.PRODUCT_CLASSIFICATION: Capability.CLASSIFY_PRODUCT,
    Intent.CRITERIA_LOOKUP: Capability.CRITERIA,
    Intent.RECOGNITION_LOOKUP: Capability.RECOGNITION,
    Intent.PROCEDURE_FORM: Capability.PROCEDURE_FORM,
    Intent.SECTOR_COMPLIANCE: Capability.SECTOR_COMPLIANCE,
    Intent.TEMPORAL_COMPARE: Capability.TEMPORAL,
    Intent.MULTIHOP_REASONING: Capability.RELATION_REASONING,
}
CAPABILITY_INTENT = {cap: intent for intent, cap in INTENT_CAPABILITY.items()}
CAPABILITY_INTENT[Capability.EVIDENCE_REQUIREMENTS] = Intent.CRITERIA_LOOKUP
INTENT_PRIORITY = {
    Intent.EXACT_LOOKUP: 70,
    Intent.PRODUCT_CLASSIFICATION: 65,
    Intent.CRITERIA_LOOKUP: 45,
    Intent.PROCEDURE_FORM: 50,
    Intent.TEMPORAL_COMPARE: 75,
    Intent.RECOGNITION_LOOKUP: 55,
    Intent.SECTOR_COMPLIANCE: 60,
    Intent.MULTIHOP_REASONING: 35,
}
PRIVATE_CAPABILITIES: frozenset[Capability] = frozenset()
YEAR = re.compile(r"\b20\d{2}\b")
DATE_ISO = re.compile(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b")
DATE_VI = re.compile(r"\b(0?[1-9]|[12]\d|3[01])[/.-](0?[1-9]|1[0-2])[/.-](20\d{2})\b")
BARE_CRITERION = re.compile(r"^\s*[A-Za-z]?\d{1,2}(?:\.\d{1,2}){1,3}\s*[?.!]*\s*$")
FOLLOWUP_SCOPE_KEYS = frozenset(
    {
        "document_code",
        "document_codes",
        "article_id",
        "form_id",
        "form_ids",
        "star_rating",
        "as_of_date",
        "years",
        "region",
        "product_name",
        "product_names",
        "product_group",
        "criterion_id",
        "recognition_year",
        "assessment_year",
        "pdf_page",
        "sheet_number",
        "organization_name",
    }
)
# What the question is about, as opposed to where it applies (document, locality, year): a new target replaces the old one.
TARGET_KEYS = frozenset(
    {
        "article_id",
        "form_id",
        "form_ids",
        "sheet_number",
        "criterion_id",
        "pdf_page",
        "product_name",
        "product_names",
        "organization_name",
    }
)
# Pattern for an identifier that looks like a private record handle (config-free: structural, not corpus data).
PRIVATE_HANDLE = get_privacy().regex("private_handle")


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _alt(words: list[str]) -> str:
    return "|".join(
        r"\s+".join(re.escape(w) for w in fold(x).split()) for x in sorted(words, key=len, reverse=True)
    )


class _Patterns:
    """Regexes assembled from the vocabulary file (folded, whole word)."""

    def __init__(self, lang: Language):
        n = lang.structure_nouns
        self.document = document_pattern(lang)
        self.bare_number = re.compile(
            r"(?<![a-z0-9/])(\d{1,4}/(?:19|20)\d{2}(?:/[a-z]+\d*)?(?:-[a-z]+)*)(?![a-z0-9/])"
        )
        self.type_words = {
            kind: re.compile(r"(?<![a-z0-9])(?:" + _alt(words) + r")(?![a-z0-9])")
            for kind, words in lang.document_types.items()
        }
        self.article = re.compile(r"(?<![a-z0-9])(?:" + _alt(n["article"]) + r")\s*(\d{1,3})(?!\d)")
        self.form = re.compile(r"(?<![a-z0-9])(?:" + _alt(n["form"]) + r")\s*(?:so\s*)?0?([1-9]\d?)(?!\d)")
        self.form_list = re.compile(
            r"(?<![a-z0-9])(?:" + _alt(n["form"]) + r")\s*(?:so\s*)?0?([1-9]\d?)\b"
            r"((?:\s*(?:,|va|&|/)\s*0?[1-9]\d?\b){1,6})"
        )
        self.sheet = re.compile(r"(?<![a-z0-9])(?:" + _alt(n["sheet"]) + r")\s*(?:so\s*)?(\d{1,3})(?!\d)")
        self.page = re.compile(r"(?<![a-z0-9])(?:" + _alt(n["page"]) + r")\s*(\d{1,4})(?!\d)")
        self.criterion = re.compile(
            r"(?<![a-z0-9])(?:" + _alt(n["criterion"]) + r")\s+(?:so\s+)?([a-z]?\d+(?:\.\d+){0,3})(?!\d)"
        )
        self.star = re.compile(
            r"(?<![\d.])("
            + "|".join(str(x) for x in lang.star_levels)
            + r")\s*(?:"
            + _alt(lang.star_noun)
            + r")\b"
        )
        markers = _alt(lang.locality_markers)
        self.locality_marker = re.compile(r"(?<![a-z0-9])(?:" + markers + r")\s+(?=\S)")
        self.word = re.compile(r"[\wÀ-ỹ]+")
        self.markers = frozenset(unicodedata.normalize("NFC", m).casefold() for m in lang.locality_markers)
        self.locality_blocker = re.compile(r"(?:" + _alt(lang.locality_marker_blockers) + r")\s*$")
        self.product_marker = re.compile(r"(?<![a-z0-9])(?:" + _alt(lang.product_markers) + r")\s+(.+)")
        self.terminator = re.compile(
            r"(?<![a-z0-9])(?:" + _alt(lang.entity_terminators) + r")(?![a-z0-9])|[?.!,;:]"
        )
        self.non_entity = re.compile(r"^(?:" + _alt(lang.non_entity_phrases) + r")$")
        heads = lang.cues.get("single_syllable_entity_heads") or []
        self.entity_head = re.compile(r"(?<![a-z0-9])(?:" + _alt(heads) + r")\s*$") if heads else None
        self.chapter = re.compile(r"(?<![a-z0-9])(?:" + _alt(n.get("chapter", [])) + r")\s+[ivxlcdm0-9]+\b") if n.get("chapter") else None
        statute_types = [w for kind in ("law", "decree", "circular") for w in lang.document_types.get(kind, [])]
        # A named statute ("Luật An toàn thực phẩm"): the type word followed by a title, not by a number.
        self.statute_title = re.compile(r"(?<![a-z0-9])(?:" + _alt(statute_types) + r")\s+(?!(?:so\s*)?\d)[a-z]")


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
    raw = query[start : start + (end.start() if end else len(tail))].strip(" ,-")
    key = fold(raw)
    if not raw or p.non_entity.match(key) or re.match(r"^(?:20\d{2}|\d+)\b", key) or len(raw.split()) > 9:
        return None
    if not get_language().content_words(raw, accent_aware=True):
        return None  # only function words ("sản phẩm phải được ...") name nothing
    return raw


def _gazetteer(lang: Language, text: str) -> list[Match]:
    """Provincial names from the vocabulary file, matched under the same accent policy as the catalog."""
    return EntityCatalog(
        {"entities": {"region": [{"label": name, "source_ids": []} for name in lang.localities]}}
    ).find("region", text)


def _capitalised_run(p: _Patterns, text: str, start: int, limit: int = 4) -> str | None:
    words, pos = [], start
    for _ in range(limit):
        m = p.word.match(text, pos)
        if not m or not m.group(0)[0].isupper():
            break
        words.append(m.group(0))
        pos = m.end()
        gap = re.match(r"\s+", text[pos:])
        if not gap:
            break
        pos += gap.end()
    return " ".join(words) or None


def _document_by_title_year(
    lang: Language, p: _Patterns, catalog: EntityCatalog, folded: str, *, years_found: list[str]
):
    """ "Luật ... 2023" -> the one catalogued law of 2023 (type word + year, both from the vocabulary/registry)."""
    if len(set(years_found)) != 1:
        return None
    for kind, rx in p.type_words.items():
        if rx.search(folded):
            code = catalog.document_by_type_year(kind, years_found[0])
            if code:
                return code
    return None


def _years_naming_a_document(lang: Language, text: str, folded: str) -> list[str]:
    """Years that can name a document: a year the question scopes to an event or an assessment ("công nhận năm
    2025") dates that event, not a decision of that year."""
    scoped = {
        m.group(1)
        for key in ("event_year_scope", "assessment_year_scope")
        for m in re.finditer(r"(?:" + _alt(lang.cues[key]) + r").{0,90}?\bnam\s+(20\d{2})\b", folded)
    }
    return [year for year in YEAR.findall(text) if year not in scoped - _version_years(lang, folded)]


def _version_years(lang: Language, folded: str) -> set[str]:
    """Years written right after a name of the rules' version: "theo quy trình năm 2023", "bộ quy định 2026", and
    "quy trình đánh giá năm 2023" (the process of assessing, not the year something was assessed)."""
    return {
        m.group(1)
        for m in re.finditer(
            r"(?<![a-z])(?:"
            + _alt(lang.cues["version_reference"])
            + r")(?:\s+ocop)?(?:\s+(?:"
            + _alt(lang.cues["assessment_year_scope"])
            + r"))?\s+(?:nam\s+)?(20\d{2})\b",
            folded,
        )
    }


def extract_slots(
    query: str, *, catalog: EntityCatalog | None = None, language: Language | None = None
) -> dict:
    """Explicit slots only; never assume a date, product group or document."""
    lang = language or get_language()
    p = _patterns(lang)
    text = _nfc(query)
    folded = fold(text)
    slots: dict = {}
    documents = DocumentResolver(language=lang)
    if (m := p.document.search(folded)) and not re.fullmatch(r"(?:19|20)\d{2}", m.group(1)):
        slots["document_code"] = documents.qualify(text[m.start(1) : m.end(1)], text[m.start() : m.start(1)])
    elif m := p.bare_number.search(folded):
        slots["document_code"] = text[m.start() : m.end()]
    elif catalog is not None and (
        code := _document_by_title_year(lang, p, catalog, folded, years_found=_years_naming_a_document(lang, text, folded))
    ):
        slots["document_code"] = code
    # Several documents named in one question (a comparison): every one is searched, none is dropped.
    codes = list(
        dict.fromkeys(
            documents.qualify(text[m.start(1) : m.end(1)], text[m.start() : m.start(1)])
            for m in p.document.finditer(folded)
            if not re.fullmatch(r"(?:19|20)\d{2}", m.group(1))
        )
    )
    if len(codes) > 1:
        slots["document_codes"] = codes
    if m := p.article.search(folded):
        slots["article_id"] = m.group(1)
    form_ids = [x.lstrip("0") for x in dict.fromkeys(m.group(1) for m in p.form.finditer(folded))]
    for m in p.form_list.finditer(folded):
        form_ids.extend(
            str(int(n)) for n in [m.group(1), *re.findall(r"(?:,|va|&|/)\s*0?([1-9]\d?)\b", m.group(2))]
        )
    form_ids = list(dict.fromkeys(form_ids))
    if len(form_ids) > 1:
        slots["form_ids"] = form_ids
    if form_ids:
        slots["form_id"] = form_ids[0]
    if m := p.star.search(folded):
        slots["star_rating"] = int(m.group(1))
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
        slots["as_of_date"] = last_date[1]
    years = list(dict.fromkeys(YEAR.findall(text)))
    if years:
        slots["years"] = years
    if (m := p.page.search(folded)) and int(m.group(1)) > 0:
        slots["pdf_page"] = int(m.group(1))
    if (m := p.sheet.search(folded)) and int(m.group(1)) > 0:
        slots["sheet_number"] = int(m.group(1))
    if m := p.criterion.search(folded):
        statute_section = m.group(0).startswith("muc") and (
            (p.chapter and p.chapter.search(folded)) or p.statute_title.search(folded) or p.type_words["law"].search(folded)
        )
        if not re.fullmatch(r"20\d{2}", m.group(1)) and not statute_section:
            slots["criterion_id"] = m.group(1)
    catalog = catalog or EntityCatalog()
    # Locality: catalog entry, else a marker + capitalised words the user literally wrote.
    regions = catalog.find("region", text) or _gazetteer(lang, text)
    if regions:
        slots["region"] = regions[0].label
    else:
        accented = has_diacritics(text)
        for m in p.locality_marker.finditer(folded):
            marker = re.sub(r"\s+", " ", text[m.start() : m.end()].strip().casefold())
            if accented and marker not in p.markers:
                continue  # accented query: "quan" in "liên quan" is not the marker "quận"
            name = _capitalised_run(p, text, m.end())
            if name and not p.locality_blocker.search(folded[: m.start()]):
                slots["region"] = name
                break
    # A catalog name inside a legal/structural locator is the locator, not the entity: "Điều 7" is an
    # article even though "điều" (cashew) is also a product group. fold() keeps NFC character offsets.
    locators = [m.span() for pattern in (p.article, p.sheet, p.form, p.page, p.criterion) for m in pattern.finditer(folded)]

    # A name inside a statute's title is part of the title: "Luật An toàn thực phẩm" is not the product "thực phẩm".
    for m in p.statute_title.finditer(folded):
        end = p.terminator.search(folded, m.end())
        locators.append((m.start(), end.start() if end else len(folded)))

    def standalone(x) -> bool:
        if len(x.label.split()) > 1 or p.entity_head is None:
            return True
        tail = folded[x.end :].lstrip()
        return bool(p.entity_head.search(folded[: x.start]) or not tail or p.terminator.match(tail))

    def outside_locators(matches):
        return [
            x
            for x in matches
            if standalone(x) and not any(x.start < end and start < x.end for start, end in locators)
        ]

    products = outside_locators(catalog.find("product", text))
    linked = outside_locators(catalog.link("product", text, is_content=lambda w: bool(lang.content_words(w))))
    products += [m for m in linked if not any(m.start < x.end and x.start < m.end for x in products)]
    products = sorted(products, key=lambda m: m.start)
    if products:
        names = list(dict.fromkeys(m.label for m in products))
        slots["product_name"] = names[0]
        if len(names) > 1:
            slots["product_names"] = names
    elif groups := outside_locators(catalog.find("product_group", text)):
        slots["product_name"] = max(groups, key=lambda x: x.end - x.start).label
    elif name := _product_from_marker(text, folded, p):
        slots["product_name"] = name
    orgs = outside_locators(catalog.find("organization", text)) or outside_locators(
        catalog.link("organization", text, is_content=lambda w: bool(lang.content_words(w)))
    )
    if orgs:
        slots["organization_name"] = max(orgs, key=lambda x: x.end - x.start).label
    only_year_in_code = len(years) == 1 and not slots.get("document_code")
    event = re.search(r"(?:" + _alt(lang.cues["event_year_scope"]) + r").{0,90}?\bnam\s+(20\d{2})\b", folded)
    assessment = re.search(
        r"(?:" + _alt(lang.cues["assessment_year_scope"]) + r").{0,90}?\bnam\s+(20\d{2})\b", folded
    )
    versions = _version_years(lang, folded)
    if event and event.group(1) not in versions:
        slots["recognition_year"] = int(event.group(1))
    if assessment and assessment.group(1) not in versions:
        slots["assessment_year"] = int(assessment.group(1))
    if only_year_in_code and years[0] not in versions:
        if lang.hit(text, "assessment_year_marker"):
            slots["assessment_year"] = int(years[0])
        if lang.hit(text, "recognition_year_marker"):
            slots["recognition_year"] = int(years[0])
    return slots


def _scope_years_to_rule_versions(route: Route, query: str, language: Language | None = None) -> Route:
    """A year with no document named mostly names the version of the OCOP rules ("quy trình năm 2023", "bộ quy định
    2026"): the routed question is scoped to that year's rule document.

    It runs on the final route, after scope and follow-up decisions, so a derived document never makes a question
    in-domain nor reads as a document the user pinned. The year is an event year instead when the question dates a
    recognition or an assessment, or asks about a locality, whose documents are local decisions.
    """
    slots = route.slots
    lang = language or get_language()
    text = _nfc(query)
    if (
        route.needs_clarification
        or route.intent in (Intent.CLARIFY, Intent.OUT_OF_SCOPE, Intent.CONVERSATION)
        or not slots.get("years")
        or slots.get("document_code")
        or slots.get("region")
        or slots.get("recognition_year")
        or slots.get("assessment_year")
        or lang.hit(text, "recognition")
    ):
        return route
    folded = fold(text)
    kinds = [kind for kind, rx in _patterns(lang).type_words.items() if rx.search(folded)]
    years = [y for y in _years_naming_a_document(lang, text, folded) if y in slots["years"]] or slots["years"]
    resolver = DocumentResolver(language=lang)
    codes = [resolver.ocop_rules_of_year(year, kinds) for year in years]
    if not codes or not all(codes):
        return route
    codes = list(dict.fromkeys(codes))
    slots["document_code"] = codes[0]
    slots["document_from_year"] = True
    if len(codes) > 1:
        slots["document_codes"] = codes
    return route


def _merge_followup(prior: dict, updates: dict) -> dict:
    """Carry only ordinary question-extracted scope; never ids, auth or verified flags."""
    raw = prior.get("slots") if isinstance(prior.get("slots"), dict) else {}
    slots = {
        key: value
        for key, value in raw.items()
        if key in FOLLOWUP_SCOPE_KEYS
        and (
            isinstance(value, str)
            and len(value) <= 128
            or type(value) is int
            and 0 <= value <= 2100
            or key in ("years", "form_ids", "product_names")
            and isinstance(value, list)
            and len(value) <= 8
            and all(isinstance(x, str) and len(x) <= (128 if key == "product_names" else 12) for x in value)
        )
    }
    if raw.get("document_from_year"):
        # The document was read off the previous turn's year, not named: the new turn's year decides it again.
        slots = {key: value for key, value in slots.items() if key not in ("document_code", "document_codes")}
    new_doc = updates.get("document_code")
    if new_doc and fold(str(new_doc)) != fold(str(slots.get("document_code") or "")):
        slots = {
            key: value for key, value in slots.items() if key not in TARGET_KEYS
        }  # another document: its Điều/Mẫu/Phiếu are not the old one's
    new_region = updates.get("region")
    if new_region and not new_doc and fold(str(new_region)) != fold(str(slots.get("region") or "")):
        # A decision belongs to one locality: asking the same thing "for Hải Phòng" does not stay on Huế's decision.
        slots = {
            key: value
            for key, value in slots.items()
            if key not in {"document_code", "article_id", "form_id", "sheet_number", "pdf_page"}
        }
    if (
        set(updates) & TARGET_KEYS
    ):  # a new thing asked about replaces the old one ("Còn mẫu số 02?" is no longer Điều 6)
        slots = {key: value for key, value in slots.items() if key not in TARGET_KEYS}
    slots.update(updates)
    if "years" in updates:
        if "as_of_date" not in updates:
            slots.pop("as_of_date", None)
        for key in ("assessment_year", "recognition_year"):
            if key not in updates:
                slots.pop(key, None)
    return slots


class Facets:
    """Question facets derived from vocabulary cues and slots (one place, no scattered keyword lists)."""

    def __init__(self, lang: Language, text: str, slots: dict):
        folded = fold(text)
        h = lambda name: lang.hit(text, name)  # noqa: E731
        self.authority = h("authority")
        self.multihop = h("multihop")
        parts = sub_queries(text)
        self.multihop = self.multihop or bool(parts and all(lang.hit(part, "question_words") for part in parts))
        self.compliance = h("compliance")
        self.classification = h("classification")
        self.procedure = h("procedure")
        self.scoring_method = h("scoring_method")
        years = slots.get("years") or []
        legal = h("temporal_legal_scope")
        compare_scope = h("temporal_compare_scope") or h("temporal_compare_old_new")
        self.temporal = bool(
            (len(years) >= 2 and legal)
            or h("temporal_strong")
            or (h("temporal_validity") and not h("temporal_fact"))
            or (
                h("temporal_compare")
                and (len(years) >= 2 or (years and compare_scope) or h("temporal_compare_old_new"))
            )
        )
        stars = bool(slots.get("star_rating"))
        # "sản phẩm bên mình đã được 3 sao": the asker states their own unnamed product's level; no record names it.
        own = h("own_subject") and not (slots.get("product_name") or slots.get("organization_name"))
        self.normative_star = stars and h("normative_star") and not h("recognition_listing_negative")
        self.rating_assertion = stars and h("rating_assertion") and not own
        # A star level together with a named place, producer or product asks about recorded recognitions even when
        # the question never says "công nhận"; a rule about reaching that level (normative) or a deadline does not.
        star_record = (
            stars
            and bool(slots.get("region") or slots.get("organization_name") or slots.get("product_name"))
            and not self.normative_star
            and not self.procedure
            and not h("deadline")
        )
        self.recognition = not self.authority and not own and (h("recognition") or star_record)
        self.criteria = (
            h("criteria")
            or self.normative_star
            or bool(slots.get("criterion_id") or slots.get("sheet_number"))
        )
        self.evidence_requirements = h("evidence_requirements")
        self.relation = bool(slots.get("document_code") and h("relation")) or h("relation_open")
        negated = bool(
            re.search(
                r"(?<![a-z0-9])(?:"
                + _alt(lang.cues["scoring_negation"])
                + r")\s+(?:can\s+)?(?:tinh|cham|uoc tinh)\s+diem\b",
                folded,
            )
        )
        verbs = h("private_scoring_verbs")
        self.private_scoring = (
            not self.scoring_method
            and not negated
            and (
                h("private_scoring")
                or bool(re.fullmatch(r"(?:hay\s+)?(?:tinh|cham|uoc tinh)\s+diem(?:\s+ocop)?[?.!]*", folded))
                or (
                    bool(
                        re.search(
                            r"\btinh diem\b.{0,30}(?<![a-z0-9])(?:"
                            + _alt(lang.cues["scoring_hypothetical"])
                            + r")\b",
                            folded,
                        )
                    )
                )
                or (verbs and h("private_scoring_object"))
            )
        )
        self.private_dossier = h("private_dossier") and not h("private_dossier_negative")
        self.private_scope = h("private_scope") or bool(
            h("private_open") and PRIVATE_HANDLE.search(folded.upper())
        )
        self.recognition_listing = h("recognition_listing")
        # A legal change is a temporal task even when the question says neither "hiệu lực" nor "so sánh".
        legal_change = bool(
            slots.get("document_code")
            and h("document_change")
            and (h("relation") or len(slots.get("document_codes") or []) > 1 or h("amend_object"))
            and not self.procedure
        )
        self.relation = self.relation or legal_change
        self.temporal = self.temporal or legal_change


def _capabilities(facets: Facets, slots: dict) -> tuple[list[Capability], list[str]]:
    found: list[Capability] = []
    reasons: list[str] = []

    def add(cap: Capability, reason: str):
        if cap not in found:
            found.append(cap)
            reasons.append(reason)

    if slots.get("document_code") and (slots.get("article_id") or slots.get("pdf_page")):
        add(Capability.EXACT_ARTICLE, "document_and_locator")
    if facets.authority:
        add(Capability.EXACT_ARTICLE, "authority_signal")
    if facets.classification:
        add(Capability.CLASSIFY_PRODUCT, "product_classification_signal")
    if facets.criteria or facets.scoring_method:
        add(Capability.CRITERIA, "criterion_signal")
    if facets.evidence_requirements:
        add(Capability.EVIDENCE_REQUIREMENTS, "evidence_requirements_signal")
    if slots.get("form_id") or facets.procedure:
        add(Capability.PROCEDURE_FORM, "procedure_form_signal")
    if facets.temporal:
        add(Capability.TEMPORAL, "legal_temporal_signal")
    if (
        facets.recognition
        or facets.rating_assertion
        or (slots.get("product_name") and slots.get("_producer"))
    ):
        add(Capability.RECOGNITION, "recognition_signal")
    if facets.compliance:
        add(Capability.SECTOR_COMPLIANCE, "compliance_signal")
    if facets.relation or (Capability.EVIDENCE_REQUIREMENTS in found and Capability.CRITERIA in found):
        add(Capability.RELATION_REASONING, "relational_signal")
    if not found:
        add(Capability.OVERVIEW, "general_ocop_question")
    return found, reasons


def _select_tools(caps: list[Capability], slots: dict, facets: Facets) -> tuple[list[str], list[str]]:
    """Primary tools answer the question; secondary tools only enrich it and never block the answer."""
    explicit = set(caps)
    if explicit & PRIVATE_CAPABILITIES:
        return list(
            dict.fromkeys(t for c in caps if c in PRIVATE_CAPABILITIES for t in CAPABILITY_TO_TOOLS[c])
        ), []
    primary: list[str] = []
    secondary: list[str] = []
    located = Capability.EXACT_ARTICLE in explicit
    # A pinned document names where to read, not which criterion: with a star level asked and no criterion, sheet or
    # product ("theo QĐ 148, hạng 4 sao bao nhiêu điểm") the answer is the document's rating-class text, not sheet rows.
    criterion_scope = any(
        slots.get(k) for k in ("criterion_id", "product_name", "product_group", "sheet_number")
    ) or bool(slots.get("document_code") and not slots.get("star_rating"))
    for cap in caps:
        tools = list(CAPABILITY_TO_TOOLS[cap])
        target = primary
        if located and cap != Capability.EXACT_ARTICLE:
            # A located article is answered from that article; other capabilities are optional extras
            # and only when the question carries what they need (a form number; a criterion/product scope).
            if cap == Capability.PROCEDURE_FORM and slots.get("form_id"):
                target = secondary
            elif cap == Capability.CRITERIA and (slots.get("criterion_id") or slots.get("sheet_number")):
                target = secondary
            elif cap in (Capability.TEMPORAL, Capability.RELATION_REASONING, Capability.RECOGNITION):
                target = primary
            else:
                continue
        if cap == Capability.PROCEDURE_FORM and not slots.get("form_id"):
            tools = ["search_regulations"]
        if (
            cap == Capability.CRITERIA
            and not criterion_scope
            and not explicit & {Capability.CLASSIFY_PRODUCT, Capability.EVIDENCE_REQUIREMENTS}
        ):
            tools = ["search_regulations"]
        target.extend(tools)
    if (
        len(caps) > 1
        and "search_regulations" not in primary + secondary
        and explicit & {Capability.TEMPORAL, Capability.SECTOR_COMPLIANCE, Capability.RELATION_REASONING}
    ):
        primary.append("search_regulations")
    if Capability.RECOGNITION in explicit and "search_regulations" not in primary:
        secondary.append(
            "search_regulations"
        )  # the decision's own articles explain a list of recognised products
    if (
        explicit & {Capability.CRITERIA, Capability.OVERVIEW}
        and not located
        and "lookup_product_subgroup" not in primary
        and len(primary) + len(secondary) < MAX_TOOL_CALLS
    ):
        # Criteria are kept per product set: a product named in passing ("mình làm nước mắm") is linked to its set,
        # which answers nothing when no set is named.
        secondary.append("lookup_product_subgroup")
    if (
        get_settings().agent.graph_secondary
        and not located
        and (len(caps) > 1 or explicit & {Capability.RECOGNITION, Capability.TEMPORAL, Capability.SECTOR_COMPLIANCE})
        and "search_graph" not in primary + secondary
        and len(primary) + len(secondary) < MAX_TOOL_CALLS
    ):
        # What one passage points at lies in another document or unit (the framework that classifies a recognised
        # product, the provision an amendment changes, the body that grants a star level): the graph hops from the
        # evidence found by the other tools, as an enrichment that never blocks the answer.
        secondary.append("search_graph")
    if explicit == {Capability.EXACT_ARTICLE} and not facets.authority:
        primary = ["lookup_legal_unit"]
    if facets.authority:
        primary = list(dict.fromkeys(["lookup_legal_unit", "search_regulations", *primary]))
    if Capability.TEMPORAL in explicit and Capability.RECOGNITION in explicit:
        primary = ["lookup_recognition"] + [t for t in primary if t != "lookup_recognition"]
    primary = list(dict.fromkeys(t for t in primary if t in TOOLS))
    secondary = [t for t in dict.fromkeys(secondary) if t in TOOLS and t not in primary]
    return primary, secondary


def _semantic_label(semantic_route, q: str, has_prior: bool) -> Intent | None:
    """The intent whose example utterances ``q`` clearly resembles, or None when the proposal is not clear enough."""
    if semantic_route is None:
        return None
    try:
        proposal = semantic_route(q)
        agent = get_settings().agent
        if proposal is None or proposal.score < agent.semantic_min_score or proposal.margin < agent.semantic_min_margin:
            return None
        label = Intent(proposal.intent)
    except Exception:  # noqa: BLE001 - a failing proposer must leave the deterministic route untouched
        return None
    return None if label == Intent.FOLLOWUP and not has_prior else label


def _model_labels(llm_scope: Callable[[str], dict], q: str, prior: dict) -> tuple[Intent | None, list[Intent]]:
    """Only enum labels cross the model boundary; slots and tools stay server-owned."""
    previous = "PREVIOUS: " + str(prior["last_query"]) + "\n" if prior.get("last_query") else ""
    scoped = {key: value for key, value in (prior.get("slots") or {}).items() if key in FOLLOWUP_SCOPE_KEYS}
    if scoped:
        previous += "SCOPE: " + json.dumps(scoped, ensure_ascii=False) + "\n"
    text = previous + "CURRENT: " + q
    try:
        result = llm_scope(text) or {}
        label = Intent(result.get("intent"))
    except (ValueError, TypeError, AttributeError, RuntimeError, OSError):
        return None, []
    if label == Intent.CONVERSATION or (label == Intent.FOLLOWUP and not prior.get("last_query")):
        return None, []
    extras = result.get("secondary_intents") or []
    secondary = []
    if isinstance(extras, list) and label not in (Intent.OUT_OF_SCOPE, Intent.CLARIFY):
        for name in extras[:3]:
            if isinstance(name, str) and name in Intent._value2member_map_:
                intent = Intent(name)
                if intent != label and intent in INTENT_CAPABILITY and intent not in secondary:
                    secondary.append(intent)
    return label, secondary


def _route_business(
    query: str,
    *,
    session: dict | None = None,
    llm_route: Callable[[str], dict] | None = None,
    llm_scope: Callable[[str], dict] | None = None,
    semantic_route: Callable[[str], object] | None = None,
    indexed_content_bigram_coverage: Callable[[str], float | None] | None = None,
    catalog: EntityCatalog | None = None,
    language: Language | None = None,
) -> Route:
    lang = language or get_language()
    catalog = catalog or EntityCatalog()
    q = _nfc(query).strip()
    if not q:
        return Route(
            intent=Intent.CLARIFY,
            strategy="clarify",
            needs_clarification=True,
            missing_slots=["question"],
            reason_codes=["empty_query"],
        )
    folded = fold(q)
    prior = session or {}
    has_prior = bool(prior.get("last_query"))
    updates = extract_slots(q, catalog=catalog, language=lang)
    # "Hai mẫu này khác nhau ở đâu?": things the conversation discussed, named by a plural reference or a comparison.
    carried = {
        **memory.singular_referents(q, prior.get("memory"), updates, prior.get("slots") or {}, lang),
        **memory.plural_referents(q, prior.get("memory"), updates, lang),
    } if has_prior else {}
    if (
        dangling := memory.dangling_reference(
            q, prior.get("memory"), {**updates, **carried}, lang, prior_slots=prior.get("slots")
        )
    ):
        # "these two forms" with nothing earlier to point at: ask which, never guess from whatever the search returns
        return Route(
            intent=Intent.CLARIFY,
            strategy="clarify",
            needs_clarification=True,
            missing_slots=["referent_" + dangling],
            reason_codes=["reference_unresolved"],
        )
    own_scope = bool(
        set(updates)
        & {
            "document_code",
            "article_id",
            "form_id",
            "sheet_number",
            "pdf_page",
            "criterion_id",
            "product_name",
            "organization_name",
            "region",
        }
    )
    structural_scope = bool(
        set(updates) & {"document_code", "article_id", "form_id", "sheet_number", "pdf_page", "criterion_id"}
    )
    content = lang.content_words(q)
    opener = bool(re.match(r"^(?:" + _alt(lang.followup.openers) + r"|20\d{2}\b|nam\s+20\d{2}\b)", folded))
    pronoun = bool(lang.words("pronouns", lang.followup.pronouns).search(folded))
    pronoun = pronoun or memory.singular_reference(q, lang)
    tail = bool(lang.followup.tail_cues and lang.words("tail_cues", lang.followup.tail_cues).search(folded))
    # A reference ("sản phẩm đó", "... thì sao?") with no scope of its own continues the conversation, whatever its length.
    # A reference or closing cue continues the conversation unless the question says WHERE it applies (document, locality) itself:
    # naming only a new target ("Mẫu số 02 thì sao?") still inherits the document.
    own_where = bool(set(updates) & {"document_code", "document_codes", "region"})
    followup = has_prior and (opener or bool(carried) or (not own_where and (pronoun or tail)))
    updates = {**updates, **carried}
    slots = _merge_followup(prior, updates) if followup else updates
    old_code = (prior.get("slots") or {}).get("document_code") if followup else None
    old_year = YEAR.findall(str(old_code or ""))
    changed_year = updates.get("years", [])
    if old_year and changed_year and changed_year[-1] != old_year[-1] and not updates.get("document_code"):
        return Route(
            intent=Intent.CLARIFY,
            strategy="clarify",
            slots=slots,
            needs_clarification=True,
            missing_slots=["document_version_or_event_year"],
            reason_codes=["historical_year_conflicts_with_pinned_document"],
        )
    facets = Facets(lang, q, slots)
    producer = lang.hit(q, "producer")
    slots_for_caps = {**slots, "_producer": True} if producer else slots

    if facets.private_scope or facets.private_dossier or facets.private_scoring:
        return Route(
            intent=Intent.OUT_OF_SCOPE,
            strategy="clarify",
            slots=slots,
            reason_codes=["private_dossier_unsupported"],
        )

    in_domain = (
        lang.hit(q, "in_domain")
        or structural_scope
        or facets.temporal
        or facets.classification
        or facets.compliance
        or facets.authority
        or facets.criteria
        or facets.recognition
        or facets.scoring_method
        or any(matches for kind, matches in catalog.mentions(q).items() if kind != "region")
        or bool(slots.get("star_rating") or slots.get("years") and followup)
    )
    explicit_oos = lang.hit(q, "explicit_out_of_scope")
    # Where the rules have nothing to say they ask the next tiers instead of guessing, and the rules stay the cheap path
    # for everything they are sure of. Second tier: the closest example utterances, when clearly ahead. Third tier: the
    # model, picking one label of a closed list. A label only steers this route and is checked against the enum; it never
    # names a tool. The answer is kept so that a question is asked at most once.
    opinion: list[tuple[Intent | None, str]] = []
    model_secondary: list[Intent] = []

    def second_opinion() -> tuple[Intent | None, str]:
        if not opinion:
            label, source = _semantic_label(semantic_route, q, has_prior), "semantic"
            if label is None and llm_scope is not None:
                label, extra = _model_labels(llm_scope, q, prior)
                model_secondary.extend(extra)
                source = "model"
            opinion.append((label, source))
        return opinion[0]

    semantic = None
    # A bare fragment with no conversation to lean on says too little to classify: asking for scope is the rules' job.
    askable = has_prior or len(content) > 3
    # A question that names its own scope (a product, a place) but carries no domain cue is asked too: otherwise neither
    # tier ever sees it and it is out of scope by default. Only "follow-up" does not apply to it, since it scopes itself.
    if not in_domain and not followup and not explicit_oos and askable and (semantic_route or llm_scope):
        verdict, source = second_opinion()
        if verdict == Intent.FOLLOWUP:
            if not own_scope:
                followup = True
                slots = _merge_followup(prior, updates)
        elif verdict == Intent.OUT_OF_SCOPE:
            return Route(
                intent=Intent.OUT_OF_SCOPE, strategy="clarify", slots=slots, reason_codes=[source + "_out_of_scope"]
            )
        elif verdict is not None:
            in_domain = True
            semantic = verdict
    bare_code = bool(BARE_CRITERION.match(q)) and not followup
    if bare_code:
        slots["criterion_id"] = q.rstrip("?.! ").strip()
    # "Điều 5 quy định gì?": an article number with nothing else says nothing about which of several documents is meant.
    structure_words = {w for names in lang.structure_nouns.values() for n in names for w in lang.content_words(n)}
    bare_locator = (
        bool(updates.get("article_id"))
        and not updates.get("document_code")
        and not followup
        and not set(content) - structure_words
        and len(catalog.labels("document")) > 1
    )
    reopened = False
    off_corpus = False
    if not in_domain and not followup and not explicit_oos and indexed_content_bigram_coverage is not None:
        try:
            coverage = indexed_content_bigram_coverage(q)
        except (OSError, RuntimeError, ValueError, TypeError, KeyError):
            coverage = None
        if isinstance(coverage, (int, float)) and not isinstance(coverage, bool):
            if get_settings().agent.scope_min_bigram_coverage <= coverage <= 1.0:
                in_domain = reopened = True
            else:
                # Long enough to measure and not found in the corpus: a complete off-topic question, not a fragment of one.
                off_corpus = True
    if explicit_oos:
        return Route(
            intent=Intent.OUT_OF_SCOPE,
            strategy="clarify",
            slots=slots,
            reason_codes=["explicit_out_of_scope"],
        )
    if (
        bare_code
        or bare_locator
        or (not in_domain and not followup and not off_corpus and len(content) <= 3)
        or (pronoun and not has_prior and not own_scope and len(content) <= 2)
    ):
        missing = ["document_or_sheet_for_code"] if bare_code else ["document_for_locator"] if bare_locator else ["topic"]
        return Route(
            intent=Intent.CLARIFY,
            strategy="clarify",
            slots=slots,
            needs_clarification=True,
            missing_slots=missing,
            reason_codes=["fragment_needs_scope"],
        )
    if not in_domain and not followup:
        return Route(
            intent=Intent.OUT_OF_SCOPE, strategy="clarify", slots=slots, reason_codes=["no_domain_signal"]
        )

    caps, cap_reasons = _capabilities(Facets(lang, q, slots_for_caps) if producer else facets, slots_for_caps)
    # Intent and the plan start from the same capability analysis, including page locators and relations.
    scores: dict[Intent, int] = {
        CAPABILITY_INTENT[cap]: INTENT_PRIORITY[CAPABILITY_INTENT[cap]]
        for cap in caps
        if cap in CAPABILITY_INTENT
    }
    if facets.scoring_method:
        scores[Intent.CRITERIA_LOOKUP] = 70
    if facets.multihop and (facets.criteria or facets.procedure or facets.compliance or facets.recognition or facets.temporal):
        scores[Intent.MULTIHOP_REASONING] = 80
    if facets.authority:
        scores[Intent.EXACT_LOOKUP] = 88
    if (slots.get("product_name") or slots.get("organization_name")) and producer:
        scores[Intent.RECOGNITION_LOOKUP] = max(75, scores.get(Intent.RECOGNITION_LOOKUP, 0))
    if (
        (slots.get("product_name") or slots.get("organization_name"))
        and lang.hit(q, "recognition_attribute")
        and not (facets.criteria or facets.scoring_method or facets.normative_star)
    ):
        scores[Intent.RECOGNITION_LOOKUP] = max(75, scores.get(Intent.RECOGNITION_LOOKUP, 0))
    if facets.rating_assertion and slots.get("star_rating") and not facets.scoring_method:
        scores[Intent.RECOGNITION_LOOKUP] = max(78, scores.get(Intent.RECOGNITION_LOOKUP, 0))
    if facets.normative_star:
        scores[Intent.CRITERIA_LOOKUP] = max(85, scores.get(Intent.CRITERIA_LOOKUP, 0))
    if lang.hit(q, "procedure_own"):
        scores[Intent.PROCEDURE_FORM] = 72
    if facets.multihop:
        scores.setdefault(Intent.MULTIHOP_REASONING, 35)
    if facets.recognition and facets.recognition_listing:
        scores[Intent.RECOGNITION_LOOKUP] = 80
    # Entity linking (the question names a catalogued product or producer) with no stronger signal: the question is about that
    # entity's record, which lives in the verified recognition store, not in free text.
    if (slots.get("product_name") or slots.get("organization_name")) and (
        catalog.find("product", q)
        or catalog.find("organization", q)
        or catalog.link("product", q)
        or catalog.link("organization", q)
    ):
        scores.setdefault(Intent.RECOGNITION_LOOKUP, 40)
    if followup and not scores:
        try:
            parent = Intent(prior.get("intent"))
        except (ValueError, TypeError):
            parent = Intent.OCOP_OVERVIEW
        scores[Intent.OCOP_OVERVIEW if parent == Intent.FOLLOWUP else parent] = 30
    if scores:
        intent = max(scores, key=scores.get)
        if scores[intent] < get_settings().agent.rule_confident_score and not followup and (semantic_route or llm_scope):
            # A weak rule (a general cue, an entity mention) is a guess; clearly closer example utterances overrule it.
            label, source = second_opinion()
            # A vote for the catch-all overview, or for asking the user, is no evidence against a specific intent the
            # rules found: "Hải Phòng ... bao nhiêu sản phẩm 3 sao ... quyết định 525" names its scope in full.
            if label is not None and label not in (
                intent, Intent.FOLLOWUP, Intent.OUT_OF_SCOPE, Intent.OCOP_OVERVIEW, Intent.CLARIFY
            ):
                prior_cap = INTENT_CAPABILITY.get(intent)
                intent = label
                if label in INTENT_CAPABILITY:
                    caps = [INTENT_CAPABILITY[label]] + [
                        cap for cap in caps
                        if cap not in (prior_cap, Capability.OVERVIEW, INTENT_CAPABILITY[label])
                    ]
                cap_reasons.append(source + "_override")
    else:
        intent = Intent.OCOP_OVERVIEW
        label, source = (semantic, "semantic") if semantic else second_opinion() if (semantic_route or llm_scope) else (None, "")
        if label == Intent.OUT_OF_SCOPE and not structural_scope:
            return Route(
                intent=Intent.OUT_OF_SCOPE, strategy="clarify", slots=slots, reason_codes=[source + "_out_of_scope"]
            )
        if label == Intent.FOLLOWUP and has_prior and not followup:
            followup = True
            slots = _merge_followup(prior, updates)
            cap_reasons.append(source + "_followup")
        # A question that names its document ("quyết định 797") has a topic: a vote to ask for one is not taken.
        elif label is not None and label not in (Intent.FOLLOWUP, Intent.OUT_OF_SCOPE) and not (
            label == Intent.CLARIFY and structural_scope
        ):
            intent = label
            cap_reasons.append(source + "_intent")
        if llm_route is not None:
            try:
                result = llm_route(q)
                candidate = Intent(result["intent"])
                if candidate != Intent.CONVERSATION:
                    intent = candidate
                # A label proposal cannot invent a source or replace an explicitly pinned document.
            except (ValueError, KeyError, TypeError, AttributeError):
                pass
    if intent == Intent.CLARIFY:
        return Route(
            intent=intent, strategy="clarify", slots=slots, needs_clarification=True,
            missing_slots=["topic"], reason_codes=["model_needs_scope"],
        )
    effective = intent
    if followup:
        if not scores or max(scores.values()) < 75:
            intent = Intent.FOLLOWUP
            try:
                effective = Intent(prior.get("intent"))
            except (ValueError, TypeError):
                effective = Intent.OCOP_OVERVIEW
            if effective in (Intent.FOLLOWUP, Intent.CLARIFY, Intent.OUT_OF_SCOPE):
                effective = Intent.OCOP_OVERVIEW
    strategy, _ = ROUTES[effective]

    if facets.normative_star:
        caps = [c for c in caps if c != Capability.RECOGNITION]
        if Capability.CRITERIA not in caps:
            caps.insert(0, Capability.CRITERIA)
        cap_reasons.append("normative_star_requires_criteria_not_recognition_records")
    document_changed = bool(
        updates.get("document_code")
        and updates["document_code"] != (prior.get("slots") or {}).get("document_code")
    )
    if followup and caps == [Capability.OVERVIEW] and not document_changed:
        previous = [
            Capability(x) for x in prior.get("capabilities") or [] if x in Capability._value2member_map_
        ]
        if previous:
            caps = previous
        else:
            try:
                old = Intent(prior.get("intent"))
            except (TypeError, ValueError):
                old = Intent.OCOP_OVERVIEW
            caps = [INTENT_CAPABILITY[old]] if old in INTENT_CAPABILITY else caps
    if intent == Intent.OUT_OF_SCOPE:
        caps = []
    elif caps == [Capability.OVERVIEW] and effective in INTENT_CAPABILITY:
        caps = [INTENT_CAPABILITY[effective]]
    for extra in model_secondary:
        cap = INTENT_CAPABILITY[extra]
        if cap not in caps and intent != Intent.OUT_OF_SCOPE:
            caps.append(cap)
    if set(caps) & PRIVATE_CAPABILITIES:
        caps = [c for c in caps if c in PRIVATE_CAPABILITIES]
    required, secondary = _select_tools(caps, slots, facets)
    if not required and effective in ROUTES:
        required = list(ROUTES[effective][1])
    if (
        slots.get("years")
        and not slots.get("document_code")
        and effective
        in (Intent.PROCEDURE_FORM, Intent.CRITERIA_LOOKUP, Intent.SECTOR_COMPLIANCE, Intent.OCOP_OVERVIEW)
        and "search_regulations" in required
        and not set(caps) & PRIVATE_CAPABILITIES
        and not (slots.get("region") and lang.hit(q, "deadline"))
    ):
        required = list(dict.fromkeys(["resolve_temporal_applicability", *required]))
    if slots.get("pdf_page") and slots.get("document_code") and not set(caps) & PRIVATE_CAPABILITIES:
        required, secondary = ["lookup_legal_unit"], []
    if len(required) + len(secondary) > MAX_TOOL_CALLS:
        secondary = secondary[: max(0, MAX_TOOL_CALLS - len(required))]
    if len(required) > MAX_TOOL_CALLS:
        return Route(
            intent=Intent.CLARIFY,
            strategy="clarify",
            slots=slots,
            needs_clarification=True,
            missing_slots=["split_question"],
            reason_codes=["tool_budget_exceeded"] + cap_reasons,
        )
    others = list(dict.fromkeys([*model_secondary, *(x for x in scores if x != effective and scores[x] >= 40)]))
    return Route(
        intent=intent,
        strategy=strategy,
        retrieval_path=choose_retrieval_path(required + secondary),
        slots=slots,
        required_tools=required,
        secondary_tools=secondary,
        secondary_intents=others[:3],
        capabilities=[c.value for c in caps],
        reason_codes=(
            ["followup_slot_override" if followup else "deterministic_multi_signal"]
            + cap_reasons
            + (["indexed_content_bigram_scope_recovery"] if reopened else [])
        ),
        confidence=None,
    )


def route_query(
    query: str,
    *,
    session: dict | None = None,
    llm_route: Callable[[str], dict] | None = None,
    llm_scope: Callable[[str], dict] | None = None,
    semantic_route: Callable[[str], object] | None = None,
    indexed_content_bigram_coverage: Callable[[str], float | None] | None = None,
    catalog: EntityCatalog | None = None,
    language: Language | None = None,
    dialogue_client=None,
) -> Route:
    """Dialogue acts compose with, rather than compete against, business intents."""
    from ai_core.orchestration.ocop import dialogue

    prior = session or {}
    decision, task = dialogue.understand(_nfc(query), language=language)
    options = dict(
        session=prior,
        llm_route=llm_route,
        llm_scope=llm_scope,
        semantic_route=semantic_route,
        catalog=catalog,
        language=language,
        indexed_content_bigram_coverage=indexed_content_bigram_coverage,
    )
    # A complete grammar match consumes all words. Mixed messages keep the task
    # remainder and must take business routing, including private/auth policy.
    if decision.action == "respond":
        return Route(
            intent=Intent.CONVERSATION,
            strategy="conversation",
            dialogue=decision,
            reason_codes=["dialogue_full_utterance"],
        )
    if decision.action in dialogue.REPAIR:
        return _repair_route(decision, prior, options)
    pending = prior.get("unresolved") or {}
    if (
        pending.get("question")
        and extract_slots(task, catalog=catalog, language=language)
        and set(pending.get("missing_slots") or [])
        & {"topic", "document_or_sheet_for_code", "document_or_sheet"}
    ):
        # Resume only topic clarification. Authentication/version conflicts are
        # never satisfied by a conversational slot answer.
        pending_query = str(pending["question"])
        if BARE_CRITERION.fullmatch(pending_query):
            pending_query = (language or get_language()).structure_nouns["criterion"][0] + " " + pending_query
        resumed = _route_business(pending_query + " " + task, **options)
        resumed.reason_codes.append("clarification_resumed")
        resumed.dialogue = decision.model_copy(update={"action": "resume"})
        return _scope_years_to_rule_versions(resumed, pending_query + " " + task, language)
    business_query = task or query
    if "correction" in decision.acts and prior.get("last_query"):
        business_query = (language or get_language()).followup.openers[0] + " " + business_query
    choice = _route_business(business_query, **options)
    if (
        dialogue_client is not None
        and not decision.acts
        and choice.intent in (Intent.CLARIFY, Intent.OUT_OF_SCOPE)
        and not choice.slots
        and choice.reason_codes in (["fragment_needs_scope"], ["no_domain_signal"])
    ):
        assisted = dialogue.assisted(dialogue_client, query, has_topic=bool(prior.get("last_query")))
        if assisted:
            if assisted.action in dialogue.REPAIR:
                return _repair_route(assisted, prior, options)
            return Route(
                intent=Intent.CONVERSATION,
                strategy="conversation",
                dialogue=assisted,
                reason_codes=["dialogue_structured_abstention_fallback"],
            )
    choice.dialogue = decision
    return _scope_years_to_rule_versions(choice, business_query, language)


def _repair_route(decision, prior: dict, options: dict) -> Route:
    if decision.action == "correction" or not prior.get("last_query"):
        return Route(
            intent=Intent.CLARIFY,
            strategy="clarify",
            needs_clarification=True,
            missing_slots=["correction_detail" if prior.get("last_query") else "topic"],
            reason_codes=["dialogue_repair_needs_detail"],
            dialogue=decision,
        )
    # Re-read the active question against current corpus. Never treat a previous
    # answer, or social prose, as evidence. Existing verification still applies.
    choice = _route_business(str(prior["last_query"]), **options)
    choice.slots = dict(prior.get("slots") or choice.slots)
    choice.reason_codes.append("dialogue_revalidate_topic")
    choice.dialogue = decision
    return choice
