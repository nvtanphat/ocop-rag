"""Conversation memory for follow-up turns: what is being talked about, and which evidence was shown.

Four different things are kept apart on purpose:
  * conversation state (this module): the last answered topic as a standalone question, the things recently discussed
    (``referents``), and references to the evidence units the previous answers cited;
  * workflow checkpoints (system/checkpoints.py): LangGraph execution state, never read here;
  * the knowledge base / graph: the only source of evidence text;
  * answers: never stored. A reference is re-read from the corpus at the next turn, so memory can point at evidence but
    can never become evidence.
Nothing from a private (dossier) turn is stored.
"""

from __future__ import annotations

import re
from typing import Any

from ai_core.orchestration.ocop.language import Language, fold, get_language

MAX_REFERENTS = 4
MAX_EVIDENCE = 12
MAX_TURNS = 3
# slot keys holding the things a question can be about, per referent kind
REFERENT_SLOTS = {
    "form": ("form_ids", "form_id"),
    "sheet": ("sheet_number",),
    "article": ("article_id",),
    "document": ("document_codes", "document_code"),
    "product": ("product_names", "product_name"),
}
COMPARE_CUE = re.compile(r"\bso sanh\b|\bso voi\b|\bkhac voi\b|\bcung voi\b")
# Shared with query decomposition; grammar comes from the same language config.
DEMONSTRATIVE = get_language().followup.demonstrative


def empty() -> dict:
    return {"referents": {}, "standalone": "", "evidence": [], "corpus_version": None}


def _short(value: Any, limit: int = 128) -> bool:
    return isinstance(value, str) and 0 < len(value) <= limit


def sanitize(raw: Any) -> dict:
    """Memory travels inside the session dict; only well-formed, small, public-shaped values survive."""
    out = empty()
    if not isinstance(raw, dict):
        return out
    referents = raw.get("referents")
    if isinstance(referents, dict):
        for kind in REFERENT_SLOTS:
            values = referents.get(kind)
            if isinstance(values, list):
                out["referents"][kind] = [v for v in values if _short(v)][:MAX_REFERENTS]
    if _short(raw.get("standalone"), 600):
        out["standalone"] = raw["standalone"]
    if _short(raw.get("corpus_version"), 64):
        out["corpus_version"] = raw["corpus_version"]
    for ref in raw.get("evidence") or []:
        if (
            isinstance(ref, dict)
            and _short(ref.get("source_id"))
            and (_short(ref.get("chunk_id")) or _short(ref.get("evidence_unit_id")))
        ):
            out["evidence"].append(
                {
                    k: ref[k]
                    for k in ("source_id", "evidence_unit_id", "chunk_id", "pdf_page", "turn")
                    if k in ref and (_short(ref[k]) or isinstance(ref[k], int))
                }
            )
    out["evidence"] = out["evidence"][:MAX_EVIDENCE]
    return out


def _values(slots: dict, kind: str) -> list[str]:
    for key in REFERENT_SLOTS[kind]:
        value = slots.get(key)
        if isinstance(value, list):
            return [str(v) for v in value]
        if value not in (None, ""):
            return [str(value)]
    return []


def update(
    prior: dict, *, slots: dict, standalone: str, citations: list[dict], corpus_version: str | None
) -> dict:
    """State after an answered turn: recency-ordered referents, the standalone question, citation references."""
    state = sanitize(prior)
    for kind in REFERENT_SLOTS:
        seen = [v for v in _values(slots, kind)]
        if seen:
            state["referents"][kind] = list(dict.fromkeys([*seen[::-1], *state["referents"].get(kind, [])]))[
                :MAX_REFERENTS
            ]
    if standalone:
        state["standalone"] = standalone[:600]
    turn = max([r.get("turn", 0) for r in state["evidence"]] + [0]) + 1
    fresh = [
        {
            "source_id": c["source_id"],
            "pdf_page": c.get("pdf_page"),
            "turn": turn,
            **{k: c[k] for k in ("evidence_unit_id", "chunk_id") if isinstance(c.get(k), str)},
        }
        for c in citations
        if isinstance(c, dict) and isinstance(c.get("source_id"), str)
    ]
    kept = [r for r in state["evidence"] if r.get("turn", 0) > turn - MAX_TURNS]
    state["evidence"] = sanitize({"evidence": fresh + kept})["evidence"]
    state["corpus_version"] = corpus_version
    return state


def _noun_pattern(lang: Language, kind: str) -> str:
    if kind == "document":
        names = [n for names in lang.document_types.values() for n in names] + ["van ban"]
    else:
        names = lang.structure_nouns.get(kind, [])
    return "|".join(
        r"\s+".join(re.escape(w) for w in fold(n).split()) for n in sorted(names, key=len, reverse=True)
    )


def _reference_count(folded: str, noun: str, lang: Language) -> int | None:
    quantities = {fold(k): v for k, v in lang.followup.reference_quantities.items()}
    if not quantities or not lang.followup.demonstrative:
        return None
    alternatives = "|".join(
        r"\s+".join(re.escape(w) for w in phrase.split())
        for phrase in sorted(quantities, key=len, reverse=True)
    )
    match = re.search(rf"\b({alternatives})\s+(?:{noun})\s+{lang.followup.demonstrative}\b", folded)
    if match:
        return quantities[re.sub(r"\s+", " ", match.group(1))]
    if lang.followup.alternative_reference and re.search(
        rf"\b(?:{noun})\s+{lang.followup.demonstrative}\s+{lang.followup.alternative_reference}\b", folded
    ):
        return 2
    return None


def singular_reference(question: str, lang: Language | None = None) -> bool:
    """A named kind + optional modifiers + demonstrative refers to an active topic.

    This composes catalog-independent structure nouns with the same demonstrative
    grammar used for plural references, rather than enumerating complete phrases.
    """
    lang = lang or get_language()
    nouns = "|".join(_noun_pattern(lang, kind) for kind in REFERENT_SLOTS)
    return bool(
        lang.followup.demonstrative
        and re.search(rf"\b(?:{nouns})(?:\s+[a-z]+){{0,2}}\s+{lang.followup.demonstrative}\b", fold(question))
    )


def dangling_reference(question: str, memory: Any, updates: dict, lang: Language | None = None) -> str | None:
    """Kind of thing (form, sheet, article, document) that a plural reference points back to when the conversation holds
    fewer than two such things and the question names none itself ("Hai mẫu này khác nhau ở đâu?" in a new session)."""
    lang = lang or get_language()
    referents = sanitize(memory)["referents"]
    folded = fold(question)
    for kind in REFERENT_SLOTS:
        noun = _noun_pattern(lang, kind)
        count = _reference_count(folded, noun, lang) if noun else None
        if (
            noun
            and not _values(updates, kind)
            and count is not None
            and len(referents.get(kind, [])) < (count or 2)
        ):
            return kind
    return None


def plural_referents(question: str, memory: Any, updates: dict, lang: Language | None = None) -> dict:
    """Slots for "hai mẫu này" / "so sánh với mẫu số 01": the recently discussed things the question points at.

    Only things the conversation actually discussed are used; a plural reference to fewer than two of them is left unresolved.
    """
    lang = lang or get_language()
    referents = sanitize(memory)["referents"]
    folded = fold(question)
    for kind in REFERENT_SLOTS:
        pool = referents.get(kind, [])
        noun = _noun_pattern(lang, kind)
        if not noun:
            continue
        new = _values(updates, kind)
        # "Hai mẫu này khác nhau ở đâu?": a plural demonstrative over a kind with at least two discussed items
        count = _reference_count(folded, noun, lang)
        if not new and count is not None and len(pool) >= (count or 2):
            return _as_slots(kind, pool[: count or len(pool)][::-1])
        # "So sánh với mẫu số 01": the new item against the most recent different one
        if new and len(new) == 1 and COMPARE_CUE.search(folded):
            before = [v for v in pool if v != new[0]]
            if before:
                return _as_slots(kind, [before[0], new[0]])
    return {}


def _as_slots(kind: str, values: list[str]) -> dict:
    key = REFERENT_SLOTS[kind][0]
    if len(REFERENT_SLOTS[kind]) == 2:  # kinds that hold several values at once (list slot + first value)
        out = {key: values}
        out[REFERENT_SLOTS[kind][1]] = values[0]
        return out
    return {REFERENT_SLOTS[kind][0]: values[-1]}


def _surface(lang: Language, kind: str, value: str) -> str:
    if kind == "form":
        return (
            f"{lang.structure_nouns['form'][0].capitalize()} {int(value):02d}" if value.isdigit() else value
        )
    if kind == "article":
        return f"{lang.structure_nouns['article'][0].capitalize()} {value}"
    if kind == "sheet":
        return f"{lang.structure_nouns['sheet'][0].capitalize()} {value}"
    if kind == "document":
        return f"{next(iter(lang.document_types.values()))[0].capitalize()} {value}"
    return value


_SUBSTITUTIONS = {  # kind -> regexp finding the reference to replace inside the previous standalone question
    "form": re.compile(r"(?i)\bmẫu(?:\s+số)?\s+\d+"),
    "article": re.compile(r"(?i)\bđiều\s+\d+"),
    "sheet": re.compile(r"(?i)\bphiếu(?:\s+số)?\s+\d+"),
    "document": re.compile(
        r"(?i)\b(?:QĐ|Quyết\s+định|Nghị\s+định|NĐ|Thông\s+tư|TT)\s*(?:số\s+)?\d{1,4}(?:/\d{4})?(?:/[\wĐ-]+)?"
    ),
}
_OPENER = re.compile(r"(?i)^\s*(?:thế\s+còn|vậy\s+còn|còn|thế\s+thì|vậy\s+thì|thế|vậy|nếu\s+vậy)\s+")


def rewrite(
    question: str,
    memory: Any,
    slots: dict,
    updates: dict,
    *,
    carried: dict | None = None,
    lang: Language | None = None,
    previous_slots: dict | None = None,
) -> tuple[str, str]:
    """A follow-up as a standalone question: ``(text, method)``.

    1. an explicit new thing replaces the same kind of thing in the previous standalone question
       ("Còn Điều 7?" after "QĐ26/2026 Điều 6 quy định gì?" -> "QĐ26/2026 Điều 7 quy định gì?");
    2. otherwise the question keeps its own words and states the scope it relies on;
    3. a bare reference ("Nó thì sao?") is the previous standalone question.
    """
    lang = lang or get_language()
    state = sanitize(memory)
    base = state["standalone"]
    if not base:
        return question, "no_memory"
    stripped = _OPENER.sub("", question).strip()
    resolved = {**updates, **(carried or {})}
    # Another document than the one under discussion: what was asked about (Điều/Mẫu/Phiếu of the old one) does not travel.
    switched = [
        d for d in _values(updates, "document") if d not in state["referents"].get("document", [])[:1]
    ] and state["referents"].get("document")
    carries_target = any(_SUBSTITUTIONS[kind].search(base) for kind in ("article", "form", "sheet"))
    if (
        switched
        and carries_target
        and not any(_values(resolved, kind) for kind in ("article", "form", "sheet"))
    ):
        shown = " và ".join(_surface(lang, "document", v) for v in _values(updates, "document"))
        return lang.followup.generic_question.format(target=shown, scope=""), "document_switch"
    nouns = {
        w
        for kind in ("form", "sheet", "article")
        for n in lang.structure_nouns.get(kind, [])
        for w in lang.content_words(n)
    }
    # The name of the product/organisation swapped in is the thing replaced, not a word of the question.
    named = {
        w
        for key in ("product_name", "organization_name")
        for w in lang.content_words(str(updates.get(key) or ""))
    }
    own_words = [
        w
        for w in lang.content_words(stripped)
        if w not in nouns and w not in named and not re.fullmatch(r"[a-z]{0,3}\d+|hai|ba|nay|do|ay", w)
    ]  # codes (qd148) are scope, not words
    if not own_words:
        # nothing but a reference: the previous standalone question, with whatever explicit thing the user swapped in
        text, replaced = base, []
        for kind, pattern in _SUBSTITUTIONS.items():
            new = _values(resolved, kind)
            if new and pattern.search(text):
                text = pattern.sub(" và ".join(_surface(lang, kind, v) for v in new), text, count=1)
                replaced.append(kind)
        # another product/organisation than the one the previous question named ("Còn ST25?" after a question on HANA)
        for key in ("product_name", "organization_name"):
            old, new = (previous_slots or {}).get(key), updates.get(key)
            if old and new and old != new and old.casefold() in text.casefold():
                text = re.sub(re.escape(old), lambda _: str(new), text, count=1, flags=re.I)
                replaced.append("product" if key == "product_name" else "organization")
        # a new article/form/sheet the earlier question never referred to: ask about it afresh inside the carried scope
        fresh = [
            (kind, _values(resolved, kind))
            for kind in ("article", "form", "sheet")
            if _values(resolved, kind) and kind not in replaced
        ]
        if fresh:
            target = " và ".join(_surface(lang, kind, v) for kind, vals in fresh for v in vals)
            scope = [_surface(lang, kind, v) for kind in ("document",) for v in _values(slots, kind)]
            if slots.get("region"):
                scope.append(str(slots["region"]))
            if slots.get("product_name"):
                scope.append(f"sản phẩm {slots['product_name']}")
            of = f" {lang.followup.scope_of} " + ", ".join(dict.fromkeys(scope)) if scope else ""
            return lang.followup.generic_question.format(target=target, scope=of), "generic_target"
        return text, ("substitute:" + ",".join(replaced)) if replaced else "previous_standalone"
    # the question has words of its own: keep them and state the scope it relies on (including what it points back to)
    explicit = {
        k
        for k in updates
        if k
        in {key for keys in REFERENT_SLOTS.values() for key in keys}
        | {"region", "product_name", "organization_name"}
    }
    scope = []
    for kind in ("document", "article", "form", "sheet"):
        if set(REFERENT_SLOTS[kind]) & explicit:
            continue
        scope += [_surface(lang, kind, v) for v in _values(slots, kind)]
    products = _values(slots, "product")
    if products and not set(REFERENT_SLOTS["product"]) & explicit:
        scope.append("sản phẩm " + " và ".join(products))
    if slots.get("organization_name") and "organization_name" not in explicit:
        scope.append(f"chủ thể {slots['organization_name']}")
    if slots.get("region") and "region" not in explicit:
        scope.append(str(slots["region"]))
    scope = list(dict.fromkeys(scope))
    return (stripped.rstrip("?. ") + " (" + ", ".join(scope) + ")?" if scope else stripped), "state_scope"


def reusable_evidence(
    memory: Any, *, corpus_version: str | None, source_ids: set[str] | None
) -> tuple[list[dict], list[dict]]:
    """Which remembered evidence references may be re-read for this turn, and why the others may not.

    A reference is dropped when the corpus changed since it was cited, or when the new question is scoped to documents
    that do not include its source.
    """
    state = sanitize(memory)
    kept, dropped = [], []
    for ref in state["evidence"]:
        if corpus_version and state["corpus_version"] and state["corpus_version"] != corpus_version:
            dropped.append({**ref, "reason": "corpus_version_changed"})
        elif source_ids is not None and ref["source_id"] not in source_ids:
            dropped.append({**ref, "reason": "scope_changed"})
        else:
            kept.append(ref)
    return kept, dropped
