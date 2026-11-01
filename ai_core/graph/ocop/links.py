"""Rule-derived links that cross the boundaries the extractor keeps apart.

The extractor keeps every relation inside one source and one evidence unit, so no path of the graph leads from a
recognition list to the framework that classifies its products, from an amending decision to the provision it
changes, or from a star level to the body that grants it. Multi-hop questions cross exactly those boundaries.
The links are derived here from the literal text of the evidence units and the checked nodes, each with the quote
that justifies it and a source citation for both ends:

* CITES: a unit names "Điều N" of its own document or of a numbered document in the corpus -> that article's unit.
* AMENDS_PROVISION: an amending unit changes "Điều N" / "Phụ lục X" / "Mẫu số N" -> that provision of the amended
  document (the documents already tied by a checked AMENDS / REPLACES / SUSPENDS edge).
* CLASSIFIED_UNDER: a recognised product -> the framework's criterion sheet whose product set lists it.
* HAS_STAR: a recognition record -> the star level it states, in the current framework.
* AUTHORITY_RULE: a star level -> the unit saying which authority recognises that level.

Links are observations from text, never legal conclusions: they carry ``legal_verified: False``.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import defaultdict
from types import SimpleNamespace
from typing import Iterable

from ocop_contracts.ids import stable_id
from ocop_contracts.ratings import level_class
from ai_core.domain.ocop_citations import quote_bbox
from ai_core.knowledge.ocop.authorities import find_authorities
from ai_core.knowledge.ocop.contracts import contains_document_number
from ai_core.orchestration.ocop.language import fold, get_language
from ai_core.retrieval.ocop.settings import get_settings

# The link rules participate in the materialized graph schema fingerprint.
LINK_RELATIONS = frozenset({"CITES", "AMENDS_PROVISION", "CLASSIFIED_UNDER", "HAS_STAR", "AUTHORITY_RULE"})
# A hub (document, decision) may be crossed only by the relations that are its own meaning.
DOCUMENT_RELATIONS = frozenset({"AMENDS", "REPLACES", "SUSPENDS", "BASED_ON"})
_USABLE = frozenset({"passed"})


def _rx(lang=None):
    """Patterns built from the vocabulary file (cached with it): provisions, amendments, headings and stars."""
    lang = lang or get_language()

    def build():
        alt = lang.alternation
        article = alt(lang.structure_nouns["article"])
        clause, point, annex, form = (alt("provision_" + name) for name in ("clause", "point", "annex", "form"))
        kinds = alt([word for words in lang.document_types.values() for word in words])
        of = alt("reference_connector")
        part = rf"(?:(?:{point}\s+[a-zđ]{{1,2}}\s*,?\s*)?(?:{clause}\s+\d+(?:\s*,\s*\d+)*\s*,?\s*)?)"
        flags = re.I | re.S
        return SimpleNamespace(
            own=re.compile(rf"(?:{of}\s+)?(?:{kinds}\s+)?{alt('own_document_marker')}\b", flags),
            named=re.compile(rf"(?:{of}\s+)?{kinds}\b(?P<rest>.{{0,100}})", flags),
            provision=re.compile(rf"{part}?{article}\s+(?P<n>\d+)\b(?=(?P<tail>[^\n]{{0,120}}))", re.I),
            amend=re.compile(
                rf"(?P<verb>{alt('amend_verb')})\s+(?:{alt('amend_object')}\s+(?:{of}\s+)?)?{part}?"
                rf"(?P<what>{article}\s+\d+|{annex}\s+[IVXL]+|{form}\s*\d+)",
                re.I,
            ),
            heading=re.compile(
                rf"^[\s#*]*(?:(?P<article>{article})\s+(?P<n>\d+)\b|(?P<annex>{annex})\s+(?P<roman>[IVXL]+)\b"
                rf"|(?P<form>{form})\s*0?(?P<f>\d+)\b)",
                re.I,
            ),
            star=re.compile(rf"(?<!\d)({level_class()})\s*{alt(lang.star_noun)}\b", re.I),
        )

    return lang.compiled("links", build)


_CLAUSES = re.compile(r"\n(?=\s*(?:[^\W\d_]\)|\d+\.)\s)")


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def _kind_key(text: str) -> str:
    return fold(text).split()[0]  # "điều" -> "dieu", "phụ lục" -> "phu", "mẫu"/"biểu" -> "mau"/"bieu"


def _heading_key(text: str) -> tuple[str, str] | None:
    """('dieu', '7'), ('phu', 'II'), ('mau', '1') for a unit whose text opens with that heading."""
    match = _rx().heading.match(_nfc(text))
    if not match:
        return None
    if match.group("article"):
        return _kind_key(match.group("article")), match.group("n")
    if match.group("annex"):
        return _kind_key(match.group("annex")), match.group("roman").upper()
    return _kind_key(match.group("form")), match.group("f")


def _what_key(what: str) -> tuple[str, str]:
    parts = _nfc(what).split()
    if parts[-1].isalpha():  # an annex is numbered with a roman numeral
        return _kind_key(what), parts[-1].upper()
    return _kind_key(what), parts[-1].lstrip("0") or "0"


def _without_parentheses(text: str) -> str:
    """"Ủy ban nhân dân (sau đây gọi tắt là UBND) cấp tỉnh" names the same body as "Ủy ban nhân dân cấp tỉnh"."""
    return " ".join(re.sub(r"\([^)]*\)", " ", text).split())


def _words(text: str, accented: bool) -> list[str]:
    lang = get_language()
    text = _nfc(text).casefold()
    keep = set(lang.content_words(text, accent_aware=True))
    if accented:
        return [w for w in re.findall(r"\w+", text) if fold(w) in keep and not w.isdigit()]
    return [w for w in re.findall(r"\w+", fold(text)) if w in keep and not w.isdigit()]


class SetLinker:
    """Which product set (criterion sheet) lists the asked product, by inverse set frequency of the words.

    People name a product ("nước mắm", "gạo ST25"); the framework names sets ("Bộ sản phẩm: Tương, nước mắm, gia vị
    dạng lỏng khác"). A set is named when it lists the asked words that the fewest sets list (a pair of adjacent
    words counts double). A syllable inside one of the corpus's compound words ("tiêu" of "tiêu chí") and a lone word
    common across the corpus ("thành" of "chia thành") are not product words.
    """

    def __init__(self, texts: Iterable[str]):
        self.exact: dict[str, int] = {}
        self.folded: dict[str, int] = {}
        self.units = 0
        for text in texts:
            self.units += 1
            text = _nfc(text).casefold()
            for counts, words in ((self.exact, re.findall(r"\w+", text)), (self.folded, re.findall(r"\w+", fold(text)))):
                for term in {*words, *(a + " " + b for a, b in zip(words, words[1:]))}:
                    counts[term] = counts.get(term, 0) + 1

    @classmethod
    def from_jsonl(cls, path) -> "SetLinker":
        def texts():
            if path.is_file():
                with path.open(encoding="utf-8") as handle:
                    for line in handle:
                        yield json.loads(line).get("text") or ""

        return cls(texts())

    def rank(self, asked_text: str, labels: dict[str, str]) -> list[str]:
        """Ids of the sets named by ``asked_text`` (empty when none is clearly named, at most three)."""
        if not labels:
            return []
        accented = fold(asked_text) != _nfc(asked_text).casefold()
        counts = self.exact if accented else self.folded

        def terms(text: str) -> set[str]:
            words = _words(text, accented)
            return set(words) | {a + " " + b for a, b in zip(words, words[1:])}

        # The words naming the kind of list ("Bộ sản phẩm") say nothing about which product a set holds.
        heading = set().union(*(terms(label.split(":", 1)[0]) for label in labels.values() if ":" in label))
        listed = {key: terms(label.split(":", 1)[-1]) - heading for key, label in labels.items()}
        asked = terms(asked_text) - heading
        agent = get_settings().agent
        minimum = agent.compound_pair_min_share * self.units
        sequence = re.findall(r"\w+", _nfc(asked_text).casefold())
        sequence = sequence if accented else [fold(w) for w in sequence]
        listed_terms = set().union(*listed.values())
        asked -= {
            word
            for a, b in zip(sequence, sequence[1:])
            if counts.get(a + " " + b, 0) >= minimum > 0 and a + " " + b not in listed_terms
            for word in (a, b)
        }
        common = agent.link_word_max_share * self.units
        asked = {w for w in asked if " " in w or not self.units or counts.get(w, 0) <= common}
        frequency: dict[str, int] = {}
        for words in listed.values():
            for word in words:
                frequency[word] = frequency.get(word, 0) + 1
        weight = lambda w: (2 if " " in w else 1) * math.log(1 + len(labels) / frequency[w])  # noqa: E731
        scores = {key: sum(weight(w) for w in asked & words) for key, words in listed.items()}
        best = max(scores.values())
        chosen = [key for key in labels if best > 0 and scores[key] == best]
        return chosen if 0 < len(chosen) <= 3 else []


def _usable(row: dict) -> bool:
    return row.get("check") in _USABLE


def _quote_citation(unit: dict, quote: str) -> dict | None:
    from ai_core.graph.ocop.builder import _specific_citation

    spans = unit.get("spans") or []
    if not spans or not quote or quote not in (unit.get("text") or ""):
        return None
    pages = {int(span["pdf_page"]) for span in spans}
    if len(pages) == 1:
        page = next(iter(pages))
    else:
        # Resolve every occurrence from line geometry. Never assign a quote
        # to the first page merely because that page starts the unit.
        text = unit["text"]
        lines = text.splitlines()
        geometry = unit.get("structured", {}).get("quote_lines", [])
        if len(geometry) != len(lines) or any(g.get("text") != line for g, line in zip(geometry, lines)):
            return None
        quote_pages = set()
        for match in re.finditer(re.escape(quote), text):
            first = text.count("\n", 0, match.start())
            last = text.count("\n", 0, max(match.start(), match.end() - 1))
            quote_pages.update(g.get("pdf_page") for g in geometry[first:last + 1])
        if len(quote_pages) != 1 or not quote_pages.issubset(pages):
            return None
        page = next(iter(quote_pages))
    ref = {
        "source_id": unit["source_id"],
        "evidence_unit_id": unit["unit_id"],
        "quote": quote,
        "pdf_page": page,
        "bbox": quote_bbox(unit, page, quote),
    }
    return _specific_citation(ref, unit)


def _unit_citation(unit: dict) -> dict | None:
    """The whole unit as one source reference (its text is the proof when the reference is read back)."""
    from ai_core.graph.ocop.builder import _span_citations

    spans = _span_citations(unit, unit["unit_id"], unit["source_id"])
    return spans[0] if spans else None


def derive_links(nodes: list[dict], edges: list[dict], units: dict[str, dict], registry: dict, version: str):
    """Link rows (check ``passed``) and a per-relation summary; every row names the quote that justifies it."""
    lang, rx = get_language(), _rx()
    unit_node: dict[str, str] = {}
    for node in nodes:
        if node["node_type"] == "EvidenceUnit" and _usable(node) and len(node.get("evidence_unit_ids", [])) == 1:
            unit_node.setdefault(node["evidence_unit_ids"][0], node["node_id"])
    real = {uid: u for uid, u in units.items() if u.get("unit_kind") != "page" and uid in unit_node}
    numbers = {sid: info.get("document_number") for sid, info in registry.items() if info.get("document_number")}
    heads: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for uid, unit in real.items():
        key = _heading_key(unit.get("text", ""))
        if key:
            heads[(unit["source_id"], *key)].append(uid)

    def target_units(source_id: str, key: tuple[str, str]) -> list[str]:
        found = heads.get((source_id, *key), [])
        articles = [uid for uid in found if real[uid].get("unit_kind") == "article"]
        chosen = articles or found
        return chosen if 0 < len(chosen) <= 2 else []

    # Documents an amending / replacing / suspending decision acts on, from the checked document-level edges.
    node_source = {n["node_id"]: n["source_id"] for n in nodes}
    acts_on: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge["relation_type"] in {"AMENDS", "REPLACES", "SUSPENDS"} and _usable(edge):
            a, b = node_source.get(edge["source_entity_id"]), node_source.get(edge["target_entity_id"])
            if a and b and a != b:
                acts_on[a].add(b)

    links: dict[str, dict] = {}

    def add(relation, src_node, dst_node, citing_uid, citations, method, props):
        if not citations or not all(citations):
            return
        citing = units[citing_uid]
        edge_id = stable_id("kg_edge", citing["source_id"], [src_node, relation, dst_node], revision=version)
        cited = [c["evidence_unit_id"] for c in citations]
        row = links.get(edge_id)
        if row is None:
            links[edge_id] = {
                "edge_id": edge_id,
                "relation_type": relation,
                "source_entity_id": src_node,
                "target_entity_id": dst_node,
                "evidence_unit_id": citing_uid,
                "evidence_unit_ids": sorted(set(cited)),
                "source_id": citing["source_id"],
                "review_status": "needs_review",
                "corpus_version": version,
                "citations": citations,
                "properties": props,
                "derived": True,
                "origin": "deterministic",
                "check": "passed",
                "validation": {"status": "source_grounded", "method": "link:" + method, "legal_verified": False},
            }
        else:
            row["citations"] = [*row["citations"], *(c for c in citations if c not in row["citations"])]
            row["evidence_unit_ids"] = sorted(set(row["evidence_unit_ids"]) | set(cited))

    # --- CITES and AMENDS_PROVISION: provisions named in the text -------------------------------------------------
    for uid, unit in real.items():
        sid, text = unit["source_id"], unit.get("text") or ""
        amending = acts_on.get(sid, set())
        consumed: list[tuple[int, int]] = []
        for match in rx.amend.finditer(text):
            consumed.append(match.span())
            key = _what_key(match.group("what"))
            for target_sid in amending:
                for target_uid in target_units(target_sid, key):
                    quote = match.group(0)
                    add(
                        "AMENDS_PROVISION",
                        unit_node[uid],
                        unit_node[target_uid],
                        uid,
                        [_quote_citation(unit, quote), _unit_citation(real[target_uid])],
                        "amended_provision",
                        {"action": fold(match.group("verb")).split()[0], "provision": match.group("what")},
                    )
        for match in rx.provision.finditer(text):
            if any(start <= match.start() < end for start, end in consumed):
                continue
            tail = match.group("tail")
            lead = len(tail) - len(tail.lstrip())
            tail = tail.lstrip()
            reach = 0  # how far past the article number the quoted words go
            if (own := rx.own.match(tail)) is not None:
                target_sid, reach = sid, own.end()
            elif (named := rx.named.match(tail)) is not None:
                rest = named.group("rest")[:80]
                target_sid = next((s for s, number in numbers.items() if contains_document_number(rest, number)), None)
                if target_sid is not None:
                    reach = named.start("rest") + rest.find(numbers[target_sid]) + len(numbers[target_sid])
            elif sid in acts_on:
                target_sid = None  # a bare "Điều N" of an amending decision names the amended document's article
            else:
                target_sid = sid
            if target_sid is None:
                continue
            quote = text[match.start() : match.end() + (lead + reach if reach else 0)].strip()
            for target_uid in target_units(target_sid, (_kind_key(lang.structure_nouns["article"][0]), match.group("n"))):
                if target_uid == uid:
                    continue
                add(
                    "CITES",
                    unit_node[uid],
                    unit_node[target_uid],
                    uid,
                    [_quote_citation(unit, quote), _unit_citation(real[target_uid])],
                    "provision_reference",
                    {"provision": "Điều " + match.group("n"), "same_document": target_sid == sid},
                )

    # --- CLASSIFIED_UNDER: recognised product -> criterion sheet of the current framework -------------------------
    kinds = {sid: info.get("source_kind") for sid, info in registry.items()}
    frameworks = [sid for sid, kind in kinds.items() if kind == "ocop_framework"]
    sheets = {
        n["node_id"]: n
        for n in nodes
        if n["node_type"] == "CriterionSheet" and _usable(n) and n["source_id"] in frameworks
    }
    linker = SetLinker(u.get("text", "") for u in units.values() if u.get("unit_kind") != "page")
    recognised = {e["target_entity_id"] for e in edges if e["relation_type"] == "RECOGNIZES" and _usable(e)}
    for product in nodes:
        # Only a product a recognition decision lists has a framework set to be classified under; the foods named in
        # food-safety regulations are not OCOP products.
        if product["node_id"] not in recognised or not _usable(product) or not product.get("evidence_unit_ids"):
            continue
        puid = product["evidence_unit_ids"][0]
        if puid not in unit_node:
            continue
        for framework in frameworks:
            labels = {k: n["label"] for k, n in sheets.items() if n["source_id"] == framework}
            for sheet_id in linker.rank(product["label"], labels):
                sheet = sheets[sheet_id]
                # The unit that opens the sheet (its heading with the product list), not just any unit of the sheet.
                heading = next(
                    (c for c in sheet.get("citations", []) if (c.get("quote") or "").startswith(sheet["label"][:20])),
                    next(iter(sheet.get("citations", [])), None),
                )
                suid = heading["evidence_unit_id"] if heading else None
                if suid not in real:
                    continue
                cite = next((c for c in product.get("citations", []) if c.get("quote")), None)
                add(
                    "CLASSIFIED_UNDER",
                    product["node_id"],
                    sheet_id,
                    puid,
                    [cite, _unit_citation(real[suid])],
                    "product_set_words",
                    {"product": product["label"], "sheet": sheet["label"]},
                )

    # --- HAS_STAR and AUTHORITY_RULE: star level -> recognising body ----------------------------------------------
    stars: dict[tuple[str, int], dict] = {}
    for node in nodes:
        level = (node.get("properties") or {}).get("star_level")
        if node["node_type"] == "StarLevel" and _usable(node) and level and node["source_id"] in frameworks:
            stars[(node["source_id"], int(level))] = node
    recognition_cue = get_language()
    for record in nodes:
        if record["node_type"] != "RecognitionRecord" or not _usable(record):
            continue
        cite = next((c for c in record.get("citations", []) if c.get("row") is not None and rx.star.search(c.get("quote", ""))), None)
        if cite is None or cite["evidence_unit_id"] not in unit_node:
            continue
        level = int(rx.star.search(cite["quote"]).group(1))
        for framework in frameworks:
            star = stars.get((framework, level))
            if star and star.get("citations"):
                add(
                    "HAS_STAR",
                    record["node_id"],
                    star["node_id"],
                    cite["evidence_unit_id"],
                    [cite, star["citations"][0]],
                    "record_star_literal",
                    {"star_level": level},
                )
    for (framework, level), star in stars.items():
        for uid, unit in real.items():
            if unit["source_id"] != framework:
                continue
            text = unit.get("text") or ""
            for clause in _CLAUSES.split(text):
                clause = clause.strip()
                if (
                    recognition_cue.hit(clause, "recognition")
                    and any(True for _ in find_authorities(_without_parentheses(clause)))
                    and level in {int(n) for n in rx.star.findall(clause)}
                ):
                    add(
                        "AUTHORITY_RULE",
                        star["node_id"],
                        unit_node[uid],
                        uid,
                        [_quote_citation(unit, clause.split("\n")[0].strip()), _unit_citation(unit)],
                        "authority_clause",
                        {"star_level": level},
                    )
    rows = sorted(links.values(), key=lambda row: row["edge_id"])
    summary: dict[str, int] = defaultdict(int)
    for row in rows:
        summary[row["relation_type"]] += 1
    return rows, dict(summary)
