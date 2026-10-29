"""Citation identity guard. It cannot prove semantic entailment from OCR content."""

from __future__ import annotations
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

MARKER = re.compile(r"\[S(\d+)\]")


@lru_cache(maxsize=1)
def _corpus_sources() -> frozenset[str]:
    """Source ids registered in the locked corpus."""
    path = Path(__file__).resolve().parents[3] / "configs" / "ocop_sources.json"
    try:
        return frozenset(s["source_id"] for s in json.loads(path.read_text(encoding="utf-8")).get("sources", []))
    except (OSError, ValueError, KeyError):
        return frozenset()


def approved(row: dict) -> bool:
    """A row is trusted as source text when it is verified itself or comes from a source of the locked corpus.

    The corpus is approved as a whole; its per-row machine status (needs_review) says nothing against it. Rows of
    any other source stay unapproved. Every deterministic check on the claim (numbers, negation, binding, subject)
    still applies to an approved row.
    """
    return row.get("review_status") == "verified" or row.get("source_id") in _corpus_sources()


def check_source_markers(answer: str, citations: list[dict]) -> dict:
    references = {int(x) for x in MARKER.findall(answer)}
    valid = set(range(1, len(citations) + 1))
    invalid = sorted(references - valid)
    missing = not references and bool(answer.strip()) and bool(citations)
    status = (
        "missing_citations" if missing else ("markers_valid" if not invalid else "unknown_citation_markers")
    )
    # Only the sources the answer actually cites decide whether it is labelled unreviewed. A source of the locked
    # corpus is approved as a whole; its per-row machine status (needs_review) never reaches the reader. Sources
    # outside the corpus keep the label. This is labelling only: score and star claims are gated on the row itself.
    used = [x for i, x in enumerate(citations, 1) if i in references] or citations
    unverified = any(not approved(x) for x in used)
    return {
        "status": status,
        "invalid_markers": invalid,
        "unverified_source": unverified,
        "marker_count": len(references),
        "citation_count": len(citations),
        "missing_citations": missing,
    }


# A range ("từ 90 đến 100 điểm", "70 đến dưới 90 điểm") is one assertion: both bounds must be the source's, not
# each bound found somewhere in the same passage.
SCORE_ASSERTION = re.compile(
    r"(?<!\w)\d+(?:[.,]\d+)?(?:\s*(?:đến|tới|-|–)\s*(?:dưới\s+)?\d+(?:[.,]\d+)?)?\s*(?:điểm|sao)\b", re.I
)


def _cited_rows(marker_ids: list[int], citations: list[dict], evidence_rows: list[dict]) -> list[dict]:
    rows = []
    for n in marker_ids:
        if not 0 < n <= len(citations):
            continue
        c = citations[n - 1]
        rows.extend(
            r
            for r in evidence_rows
            if r.get("source_id") == c.get("source_id")
            and (r.get("evidence_unit_id") or r.get("unit_id")) == c.get("evidence_unit_id")
            and (not c.get("chunk_id") or r.get("chunk_id") == c.get("chunk_id"))
        )
    return rows


def _stated_in(assertion: str, verified: str) -> bool:
    """A score/star assertion is in the verified text literally, or ("74,6 điểm") as the number of a score label ("Điểm đánh giá: 74,6")."""
    if assertion in verified:
        return True
    number = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*điểm", assertion)
    return bool(number) and bool(
        re.search(r"điểm[^\d;|]{0,40}(?<!\d)" + re.escape(number[1]) + r"(?![\d.,]*\d)", verified)
    )


def _row_text(rows: list[dict]) -> str:
    text = " ".join(
        str(row.get("text") or row.get("evidence_text") or row.get("row_text") or "")
        for row in rows
        if approved(row)
    )
    return re.sub(r"\s+", " ", text.casefold())


def _sensitive_records_agree(claim: str, assertion: str, rows: list[dict], together: frozenset[str] = frozenset()) -> bool:
    """Use the most subject-specific source records, preserving cells of the same table row.

    Records that match the subject equally well are ambiguous: every one of them must state the assertion. Parallel
    items (the tiers "Hạng 5 sao: 90 đến 100 điểm", "Hạng 4 sao: ...") all match a claim about one tier equally; there
    the claim is bound when a single record states all of the sentence's assertions together (``together``)."""
    from ai_core.orchestration.ocop.language import get_language

    groups = {}
    for index, row in enumerate(rows):
        if not approved(row):
            continue
        spans = row.get("source_spans") or row.get("spans") or []
        span = next((s for s in spans if isinstance(s, dict)), {}) if isinstance(spans, list) else {}
        node_ids = row.get("graph_node_ids")
        if span.get("table_id") and isinstance(span.get("row"), int):
            identity = (row.get("source_id"), span["table_id"], span["row"])
        elif isinstance(node_ids, list) and node_ids and all(isinstance(value, str) for value in node_ids):
            identity = (row.get("source_id"), tuple(sorted(node_ids)))
        else:
            identity = (index,)
        groups.setdefault(identity, []).append(str(row.get("text") or row.get("evidence_text") or row.get("row_text") or ""))
    records = [part for texts in groups.values() for part in _split_claims(" ".join(texts))]
    lang = get_language()
    terms = {word for word in lang.content_words(SCORE_ASSERTION.sub(" ", MARKER.sub("", claim)))
             if not word.isdigit()}
    scores = [len(terms & set(lang.content_words(record))) for record in records]
    best = max(scores, default=0)
    candidates = [record for record, score in zip(records, scores) if score == best]
    squashed = [re.sub(r"\s+", " ", record.casefold()) for record in candidates]
    if not candidates:
        return False
    if all(_stated_in(assertion, record) for record in squashed):
        return True
    return len(together) > 1 and any(all(_stated_in(a, record) for a in together) for record in squashed)


def check_sensitive_claims(
    answer: str, evidence_rows: list[dict], citations: list[dict] | None = None
) -> dict:
    """Fail-closed on numeric score/star claims without verified textual support.

    With ``citations`` each sentence is checked against the verified text of the sources *it cites*: "5 sao" in
    one sentence is not excused by a different verified source that happens to contain "5 sao". Without them the
    pooled verified text is used (legacy behaviour). Still a guard, not semantic entailment: a matching number
    alone cannot establish application to a particular sheet.
    """

    def found(text):
        return {re.sub(r"\s+", " ", m.group(0).casefold()).strip() for m in SCORE_ASSERTION.finditer(text)}

    if citations is None:
        assertions = found(answer)
        verified = _row_text(evidence_rows)
        return {
            "unsupported_score_or_star_claims": sorted(x for x in assertions if not _stated_in(x, verified)),
            "sensitive_claim_count": len(assertions),
        }
    assertions, unsupported, misbound = set(), set(), set()
    for sentence in _split_claims(answer):
        stated = found(sentence)
        if not stated:
            continue
        assertions |= stated
        cited = _cited_rows([int(i) for i in MARKER.findall(sentence)], citations, evidence_rows)
        verified = _row_text(cited)
        for assertion in stated:
            present = _stated_in(assertion, verified)
            aligned = present and _sensitive_records_agree(sentence, assertion, cited, frozenset(stated))
            if not aligned:
                unsupported.add(assertion)
            if present and not aligned:
                misbound.add(assertion)
    return {"unsupported_score_or_star_claims": sorted(unsupported),
            "misbound_score_or_star_claims": sorted(misbound), "sensitive_claim_count": len(assertions)}


# Claim-level verification. Supports an optional audited semantic entailment
# backend; lexical overlap alone is never called semantic proof.

# Do not split decimal numbers such as 3.5 (which would create two claims).
# Trailing citation markers immediately following end-of-sentence punctuation (. or ! or ?)
# belong to the preceding claim.
SENTENCE_TERMINATOR = re.compile(
    r"((?:(?<=[!?])|(?<!\d)\.)(?:\s*\[S\d+\])*)(?:\s+|\n+|$)|(?:\s*\[S\d+\])*\n+"
)
CRITICAL = re.compile(
    r"\b(?:\d{1,3}\s*(?:điểm|sao)|\d{4}|bắt buộc|miễn|không\s+phải|hiệu lực|được công nhận|hạn cuối)\b", re.I
)
WORD = re.compile(r"[\wÀ-ỹ]+", re.U)


def _normalize(s: str) -> str:
    return " ".join(WORD.findall(unicodedata.normalize("NFC", s).casefold()))


def negation_conflict(claim: str, source: str) -> bool:
    """Detect a changed polarity on the matching clause, not an unrelated negative elsewhere."""
    from ai_core.orchestration.ocop.language import fold, get_language

    lang = get_language()
    negative = lang.words("claim_negation", lang.cues["claim_negation"])

    def signature(text):
        text = fold(text)
        polarity = bool(negative.search(text))
        words = " ".join(lang.content_words(negative.sub(" ", text)))
        return polarity, words

    polarity, words = signature(claim)
    if not words:
        return False
    matches = [other for part in re.split(r"[;!?\n]|(?<!\d)\.(?!\d)", source)
               for other, body in [signature(part)] if " " + words + " " in " " + body + " "]
    return bool(matches) and polarity not in matches


def numeric_binding_conflict(claim: str, source: str) -> bool:
    """A present number cannot be moved to another identically worded quantity label."""
    from ai_core.orchestration.ocop.language import fold, get_language

    lang = get_language()
    units = {fold(word) for word in lang.cues["claim_quantity_units"]}
    boundaries = lang.stop | {fold(word) for word in lang.cues["claim_quantity_boundaries"]}

    def bindings(text):
        result = []
        ranges = {m.start(2): {str(n) for n in range(int(m[1]), int(m[2]) + 1)}
                  for m in _RANGE.finditer(text) if 0 < int(m[2]) - int(m[1]) <= 20}
        for match in re.finditer(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)", text):
            value = match[0].replace(",", ".").lstrip("0") or "0"
            prefix = re.search(r"([^\W\d_]+)[ \t]*$", text[:match.start()])
            if prefix and fold(prefix[1]) in units:
                result.append((value, ("prefix", fold(prefix[1]))))
            tail = re.match(r"[ \t]+([^\W\d_]+(?:[ \t]+[^\W\d_]+){0,7})", text[match.end():])
            if not tail:
                continue
            words = re.findall(r"[a-z]+", fold(tail[1]))
            if not words or words[0] not in units:
                continue
            label = [words[0]]
            for word in words[1:3]:
                if word in boundaries:
                    break
                label.append(word)
            values = ranges.get(match.start(), {value})
            result.extend((value, tuple(label)) for value in values)
        return result

    available = {}
    for value, label in bindings(source):
        available.setdefault(label, set()).add(value)
    return any(label in available and value not in available[label] for value, label in bindings(claim))


def _split_claims(answer: str) -> list[str]:
    # Marker-bearing lines can contain several independent claims.
    # Attach markers standing immediately after sentence terminators ("A. [S1] B") to sentence A.
    parts = []
    last = 0
    for m in SENTENCE_TERMINATOR.finditer(answer):
        part = answer[last : m.end()].strip()
        if part:
            parts.append(part)
        last = m.end()
    if last < len(answer):
        tail = answer[last:].strip()
        if tail:
            parts.append(tail)
    return parts


def verify_claims(
    answer: str, citations: list[dict], evidence_rows: list[dict], semantic_verifier=None
) -> dict:
    """Return claim-level support labels: supported/unsupported/unknown.

    `supported` requires verified source, a matching source-backed numeric/date
    invariant when critical, and either exact entailment (claim text is within
    source) or explicit audited semantic verifier approval. No language model
    text from retrieval has authority to declare itself verified.
    """
    evidence = {}
    for row in evidence_rows:
        spans = row.get("source_spans") or row.get("spans") or []
        for i, c in enumerate(citations, 1):
            if (
                row.get("source_id") == c.get("source_id")
                and (row.get("evidence_unit_id") or row.get("unit_id")) == c.get("evidence_unit_id")
                and (not c.get("chunk_id") or row.get("chunk_id") == c.get("chunk_id"))
                and isinstance(spans, list)
                and any(
                    isinstance(span, dict)
                    and span.get("pdf_page") == c.get("pdf_page")
                    and isinstance(span.get("pdf_page"), int)
                    and span["pdf_page"] > 0
                    for span in spans
                )
            ):
                evidence.setdefault(i, []).append(row)
    claims = []
    for claim in _split_claims(answer):
        markers = [int(i) for i in MARKER.findall(claim)]
        prose = MARKER.sub("", claim).strip(" .,:;\n-")
        if not prose:
            continue
        sensitive = bool(CRITICAL.search(prose))
        if not markers:
            claims.append(
                {
                    "claim": prose,
                    "cited": [],
                    "status": "unsupported",
                    "reason": "missing_claim_citation",
                    "critical": sensitive,
                }
            )
            continue
        rows = [r for n in markers for r in evidence.get(n, [])]
        if not rows:
            claims.append(
                {
                    "claim": prose,
                    "cited": markers,
                    "status": "unsupported",
                    "reason": "citation_does_not_map_to_evidence",
                    "critical": sensitive,
                }
            )
            continue
        checked = []
        for row in rows:
            if not approved(row):
                checked.append(("unknown", "source_not_verified"))
                continue
            source = str(row.get("text") or row.get("evidence_text") or row.get("row_text") or "")
            if not source.strip():
                checked.append(("unknown", "empty_source_text"))
                continue
            nums = set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)", prose))
            source_nums = set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)", source))
            # The excerpt header the model was shown names the document ("QD525.2026"), so its numbers are grounded too.
            source_nums |= set(re.findall(r"\d+", str(row.get("source_id") or "")))
            if nums - source_nums:
                checked.append(("unsupported", "source_missing_claim_numbers"))
                continue

            if negation_conflict(prose, source):
                checked.append(("unknown", "negation_scope_unresolved"))
                continue
            if numeric_binding_conflict(prose, source):
                checked.append(("unsupported", "source_numeric_binding_mismatch"))
                continue
            if _normalize(prose) and _normalize(prose) in _normalize(source):
                checked.append(("supported", "exact_verbatim_support"))
                continue
            if semantic_verifier is not None:
                verdict = semantic_verifier(prose, source)
                if verdict not in ("entails", "contradicts", "unknown"):
                    raise ValueError("Semantic verifier must return entails/contradicts/unknown")
                checked.append(
                    (
                        "supported"
                        if verdict == "entails"
                        else "unsupported"
                        if verdict == "contradicts"
                        else "unknown",
                        "audited_semantic_" + verdict,
                    )
                )
                continue
            checked.append(("unknown", "needs_semantic_entailment_check"))
        # All cited sources must agree with a factual claim. A valid citation
        # cannot launder a conflicting or irrelevant second citation.
        status = (
            "supported"
            if checked and all(a == "supported" for a, b in checked)
            else "unsupported"
            if checked and all(a == "unsupported" for a, b in checked)
            else "unknown"
        )
        claims.append(
            {
                "claim": prose,
                "cited": markers,
                "status": status,
                "reason": ",".join(dict.fromkeys(b for a, b in checked)),
                "critical": sensitive,
            }
        )
    bad = [x for x in claims if x["status"] == "unsupported"]
    uncertain = [x for x in claims if x["status"] == "unknown"]
    return {
        "status": "verified"
        if claims and not bad and not uncertain
        else "unsupported"
        if bad
        else "not_verified",
        "claims": claims,
        "supported": sum(c["status"] == "supported" for c in claims),
        "unsupported": len(bad),
        "unknown": len(uncertain),
        "unsupported_critical": any(c["critical"] for c in bad + uncertain),
    }


def _numbers(text: str) -> set[str]:
    """Digit runs compared by value, so ``05``/``5`` and ``22/5/2026``/``22 tháng 5 năm 2026`` agree."""
    return {run.lstrip("0") or "0" for run in re.findall(r"\d+", text)}


_RANGE = re.compile(r"(?:từ|tu)\s+(\d+)\s*(?:[a-zà-ỹ]+\s+){0,2}?(?:đến|den|tới|toi|-)\s*(\d+)", re.I)


def _range_numbers(text: str) -> set[str]:
    """Integers lying inside a stated "từ A đến B" range (short ranges only): "từ 3 sao đến 5 sao" covers 4."""
    covered: set[str] = set()
    for m in _RANGE.finditer(text):
        low, high = int(m.group(1)), int(m.group(2))
        if low < high and high - low <= 20:
            covered.update(str(n) for n in range(low, high + 1))
    return covered


_REJECTED_ALTERNATIVE = re.compile(r"[,;]?\s*(?:chứ\s+)?không\s+phải(?:\s+là)?\s+([^.,;]+)", re.I)


def _spelled_out(text: str) -> str:
    """ "QĐ26" -> "quyết định 26": a document-type abbreviation glued to its number is expanded to the type's full name."""
    from ai_core.orchestration.ocop.language import fold, get_language

    folded = fold(text)
    for names in get_language().document_types.values():
        for short in names[1:]:
            folded = re.sub(
                r"(?<![a-z0-9])" + re.escape(fold(short)) + r"(?=\s*\d)", fold(names[0]) + " ", folded
            )
    return folded


def _without_rejected_alternative(prose: str, asked: str) -> str:
    """Drop ", không phải X" when X is something the user offered ("A hay X?"): it answers the question's
    alternative instead of asserting a new fact, and the positive part that remains is still checked."""
    from ai_core.orchestration.ocop.language import fold, get_language

    if not asked:
        return prose
    lang = get_language()
    words = set(lang.content_words(_spelled_out(asked)))

    def keep(match: re.Match) -> str:
        labels = {fold(w) for w in lang.table_words}
        named = [w for w in lang.content_words(_spelled_out(match.group(1))) if w not in labels]
        return "" if named and set(named) <= words else match.group(0)

    return _REJECTED_ALTERNATIVE.sub(keep, prose)


def grounded_in_excerpt(
    prose: str, source: str, *, min_term_coverage: float, critical: bool = False, asked: str = ""
) -> tuple[bool, str]:
    """Deterministic grounding of a claim in the excerpt the model was shown (not a proof of legal truth).

    Used for a claim that is not a verbatim copy of its source (an unreviewed source, or a paraphrase of a verified one,
    or one that combines several cited rows): such a claim may be shown, labelled as unreviewed when its source is, when
    (1) every number in it occurs in the excerpt or inside a range the excerpt states,
    (2) negation/exemption wording agrees with the excerpt,
    (3) enough of its content words occur in the excerpt (stricter for critical claims) and (4) its words are not
    merely scattered: a run of consecutive content words from the claim occurs in the excerpt.
    """
    from ai_core.orchestration.ocop.language import get_language

    prose = _without_rejected_alternative(prose, asked)
    # A user's number is not authority for a factual assertion. Values must occur in the source or its stated range.
    if _numbers(prose) - _numbers(source) - _range_numbers(source):
        return False, "grounding_numbers_missing"
    if negation_conflict(prose, source):
        return False, "grounding_negation_mismatch"
    if numeric_binding_conflict(prose, source):
        return False, "grounding_numeric_binding_mismatch"
    lang = get_language()
    from ai_core.orchestration.ocop.language import fold

    filler = {fold(w) for w in lang.claim_filler}
    claim_terms = [t for t in lang.content_words(prose) if t not in filler]
    if not claim_terms:
        return False, "grounding_no_content"
    source_terms = lang.content_words(source)
    present = set(source_terms)
    coverage = sum(t in present for t in claim_terms) / len(claim_terms)
    if coverage < (0.9 if critical else min_term_coverage):
        return False, "grounding_terms_missing"
    # longest run of consecutive claim words that is also consecutive in the source (not tied to a word's first occurrence)
    best, widths = 0, [0] * (len(source_terms) + 1)
    for term in claim_terms:
        widths = [0] + [widths[j] + 1 if source_terms[j] == term else 0 for j in range(len(source_terms))]
        best = max(best, *widths)
    if best < min(3, len(claim_terms)):
        return False, "grounding_terms_scattered"
    return True, "grounded_in_unreviewed_excerpt"
