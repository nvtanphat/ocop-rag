"""Citation identity guard. It cannot prove semantic entailment from OCR content."""
from __future__ import annotations
import re

MARKER = re.compile(r"\[S(\d+)\]")

def check_source_markers(answer:str,citations:list[dict])->dict:
    references={int(x) for x in MARKER.findall(answer)}
    valid=set(range(1,len(citations)+1))
    invalid=sorted(references-valid)
    missing=not references and bool(answer.strip()) and bool(citations)
    status="missing_citations" if missing else ("markers_valid" if not invalid else "unknown_citation_markers")
    unverified=any(x.get("review_status")!="verified" for x in citations)
    return {"status":status,"invalid_markers":invalid,"unverified_source":unverified,
            "marker_count":len(references),"citation_count":len(citations),"missing_citations":missing}


SCORE_ASSERTION = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?\s*(?:điểm|sao)\b", re.I)

def _cited_rows(marker_ids:list[int],citations:list[dict],evidence_rows:list[dict])->list[dict]:
    rows=[]
    for n in marker_ids:
        if not 0<n<=len(citations):continue
        c=citations[n-1]
        rows.extend(r for r in evidence_rows if r.get('source_id')==c.get('source_id') and
                    (r.get('evidence_unit_id') or r.get('unit_id'))==c.get('evidence_unit_id') and
                    (not c.get('chunk_id') or r.get('chunk_id')==c.get('chunk_id')))
    return rows


def _row_text(rows:list[dict])->str:
    text=' '.join(str(row.get('text') or row.get('evidence_text') or row.get('row_text') or '')
                  for row in rows if row.get('review_status')=='verified')
    return re.sub(r"\s+"," ",text.casefold())


def check_sensitive_claims(answer:str,evidence_rows:list[dict],citations:list[dict]|None=None)->dict:
    """Fail-closed on numeric score/star claims without verified textual support.

    With ``citations`` each sentence is checked against the verified text of the sources *it cites*: "5 sao" in
    one sentence is not excused by a different verified source that happens to contain "5 sao". Without them the
    pooled verified text is used (legacy behaviour). Still a guard, not semantic entailment: a matching number
    alone cannot establish application to a particular sheet.
    """
    def found(text):
        return {re.sub(r"\s+"," ",m.group(0).casefold()).strip() for m in SCORE_ASSERTION.finditer(text)}
    if citations is None:
        assertions=found(answer)
        verified=_row_text(evidence_rows)
        return {'unsupported_score_or_star_claims':sorted(x for x in assertions if x not in verified),
                'sensitive_claim_count':len(assertions)}
    assertions,unsupported=set(),set()
    for sentence in _split_claims(answer):
        stated=found(sentence)
        if not stated:continue
        assertions|=stated
        verified=_row_text(_cited_rows([int(i) for i in MARKER.findall(sentence)],citations,evidence_rows))
        unsupported.update(x for x in stated if x not in verified)
    return {'unsupported_score_or_star_claims':sorted(unsupported),'sensitive_claim_count':len(assertions)}

# Claim-level verification. Supports an optional audited semantic entailment
# backend; lexical overlap alone is never called semantic proof.
import unicodedata

# Do not split decimal numbers such as 3.5 (which would create two claims).
# Trailing citation markers immediately following end-of-sentence punctuation (. or ! or ?)
# belong to the preceding claim.
SENTENCE_TERMINATOR = re.compile(r'((?:(?<=[!?])|(?<!\d)\.)(?:\s*\[S\d+\])*)(?:\s+|\n+|$)|(?:\s*\[S\d+\])*\n+')
CRITICAL = re.compile(r'\b(?:\d{1,3}\s*(?:điểm|sao)|\d{4}|bắt buộc|miễn|không\s+phải|hiệu lực|được công nhận|hạn cuối)\b',re.I)
WORD = re.compile(r'[\wÀ-ỹ]+',re.U)


def _normalize(s:str)->str:
    return ' '.join(WORD.findall(unicodedata.normalize('NFC',s).casefold()))


def _split_claims(answer:str)->list[str]:
    # Marker-bearing lines can contain several independent claims.
    # Attach markers standing immediately after sentence terminators ("A. [S1] B") to sentence A.
    parts = []
    last = 0
    for m in SENTENCE_TERMINATOR.finditer(answer):
        part = answer[last:m.end()].strip()
        if part:
            parts.append(part)
        last = m.end()
    if last < len(answer):
        tail = answer[last:].strip()
        if tail:
            parts.append(tail)
    return parts


def verify_claims(answer:str,citations:list[dict],evidence_rows:list[dict],
                  semantic_verifier=None)->dict:
    """Return claim-level support labels: supported/unsupported/unknown.

    `supported` requires verified source, a matching source-backed numeric/date
    invariant when critical, and either exact entailment (claim text is within
    source) or explicit audited semantic verifier approval. No language model
    text from retrieval has authority to declare itself verified.
    """
    evidence={}
    for row in evidence_rows:
        spans=row.get('source_spans') or row.get('spans') or []
        for i,c in enumerate(citations,1):
            if (row.get('source_id')==c.get('source_id') and
                (row.get('evidence_unit_id') or row.get('unit_id'))==c.get('evidence_unit_id') and
                (not c.get('chunk_id') or row.get('chunk_id')==c.get('chunk_id')) and
                isinstance(spans,list) and any(isinstance(span,dict) and
                    span.get('pdf_page')==c.get('pdf_page') and
                    isinstance(span.get('pdf_page'),int) and span['pdf_page']>0
                    for span in spans)):
                evidence.setdefault(i,[]).append(row)
    claims=[]
    for claim in _split_claims(answer):
        markers=[int(i) for i in MARKER.findall(claim)]
        prose=MARKER.sub('',claim).strip(' .,:;\n-')
        if not prose:continue
        sensitive=bool(CRITICAL.search(prose))
        if not markers:
            claims.append({'claim':prose,'cited':[],'status':'unsupported',
                           'reason':'missing_claim_citation','critical':sensitive});continue
        rows=[r for n in markers for r in evidence.get(n,[])]
        if not rows:
            claims.append({'claim':prose,'cited':markers,'status':'unsupported',
                           'reason':'citation_does_not_map_to_evidence','critical':sensitive});continue
        checked=[]
        for row in rows:
            if row.get('review_status')!='verified':
                checked.append(('unknown','source_not_verified'));continue
            source=str(row.get('text') or row.get('evidence_text') or row.get('row_text') or '')
            if not source.strip():
                checked.append(('unknown','empty_source_text'));continue
            nums=set(re.findall(r'(?<!\w)\d+(?:[.,]\d+)?(?!\w)',prose))
            source_nums=set(re.findall(r'(?<!\w)\d+(?:[.,]\d+)?(?!\w)',source))
            if nums-source_nums:
                checked.append(('unsupported','source_missing_claim_numbers'));continue
            neg=lambda s: bool(re.search(r'\b(?:không|chưa|miễn)\b',s,re.I))
            if neg(prose)!=neg(source) and ('không' in prose.lower() or 'miễn' in prose.lower()):
                checked.append(('unknown','negation_scope_unresolved'));continue
            if _normalize(prose) and _normalize(prose) in _normalize(source):
                checked.append(('supported','exact_verbatim_support'));continue
            if semantic_verifier is not None:
                verdict=semantic_verifier(prose,source)
                if verdict not in ('entails','contradicts','unknown'):
                    raise ValueError('Semantic verifier must return entails/contradicts/unknown')
                checked.append(('supported' if verdict=='entails' else
                                'unsupported' if verdict=='contradicts' else 'unknown',
                                'audited_semantic_'+verdict));continue
            checked.append(('unknown','needs_semantic_entailment_check'))
        # All cited sources must agree with a factual claim. A valid citation
        # cannot launder a conflicting or irrelevant second citation.
        status=('supported' if checked and all(a=='supported' for a,b in checked) else
                'unsupported' if checked and all(a=='unsupported' for a,b in checked) else 'unknown')
        claims.append({'claim':prose,'cited':markers,'status':status,
                       'reason':','.join(dict.fromkeys(b for a,b in checked)), 'critical':sensitive})
    bad=[x for x in claims if x['status']=='unsupported']
    uncertain=[x for x in claims if x['status']=='unknown']
    return {'status':'verified' if claims and not bad and not uncertain else
                     'unsupported' if bad else 'not_verified',
            'claims':claims,'supported':sum(c['status']=='supported' for c in claims),
            'unsupported':len(bad),'unknown':len(uncertain),
            'unsupported_critical':any(c['critical'] for c in bad+uncertain)}


def _numbers(text: str) -> set[str]:
    """Digit runs compared by value, so ``05``/``5`` and ``22/5/2026``/``22 tháng 5 năm 2026`` agree."""
    return {run.lstrip('0') or '0' for run in re.findall(r'\d+', text)}


_RANGE = re.compile(r'(?:từ|tu)\s+(\d+)\s*(?:[a-zà-ỹ]+\s+){0,2}?(?:đến|den|tới|toi|-)\s*(\d+)', re.I)


def _range_numbers(text: str) -> set[str]:
    """Integers lying inside a stated "từ A đến B" range (short ranges only): "từ 3 sao đến 5 sao" covers 4."""
    covered: set[str] = set()
    for m in _RANGE.finditer(text):
        low, high = int(m.group(1)), int(m.group(2))
        if low < high and high - low <= 20:
            covered.update(str(n) for n in range(low, high + 1))
    return covered


_REJECTED_ALTERNATIVE = re.compile(r'[,;]?\s*(?:chứ\s+)?không\s+phải(?:\s+là)?\s+([^.,;]+)', re.I)


def _spelled_out(text: str) -> str:
    """"QĐ26" -> "quyết định 26": a document-type abbreviation glued to its number is expanded to the type's full name."""
    from ai_core.orchestration.ocop.language import fold, get_language
    folded = fold(text)
    for names in get_language().document_types.values():
        for short in names[1:]:
            folded = re.sub(r'(?<![a-z0-9])' + re.escape(fold(short)) + r'(?=\s*\d)', fold(names[0]) + ' ', folded)
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
        return '' if named and set(named) <= words else match.group(0)
    return _REJECTED_ALTERNATIVE.sub(keep, prose)


def grounded_in_excerpt(prose: str, source: str, *, min_term_coverage: float, critical: bool = False,
                        asked: str = '') -> tuple[bool, str]:
    """Deterministic grounding of a claim in the excerpt the model was shown (not a proof of legal truth).

    Used only for sources that no human has reviewed: such a claim may be shown, labelled as unreviewed, when
    (1) every number in it occurs in the excerpt (or in the question, or inside a range the excerpt states),
    (2) negation/exemption wording agrees with the excerpt,
    (3) enough of its content words occur in the excerpt (stricter for critical claims) and (4) its words are not
    merely scattered: a run of consecutive content words from the claim occurs in the excerpt.
    """
    from ai_core.orchestration.ocop.language import get_language
    prose = _without_rejected_alternative(prose, asked)
    # A number the user wrote in the question is a premise being restated, not a figure the model introduced; a number
    # inside a range the source states is covered by it. Anything else must occur in the excerpt.
    if _numbers(prose) - _numbers(source) - _numbers(asked) - _range_numbers(source):
        return False, 'grounding_numbers_missing'
    negation = lambda s: bool(re.search(r'\b(?:không|chưa|miễn)\b', s, re.I))  # noqa: E731
    if negation(prose) != negation(source) and re.search(r'\b(?:không|miễn)\b', prose, re.I):
        return False, 'grounding_negation_mismatch'
    lang = get_language()
    from ai_core.orchestration.ocop.language import fold
    filler = {fold(w) for w in lang.claim_filler}
    claim_terms = [t for t in lang.content_words(prose) if t not in filler]
    if not claim_terms:
        return False, 'grounding_no_content'
    source_terms = lang.content_words(source)
    present = set(source_terms)
    coverage = sum(t in present for t in claim_terms) / len(claim_terms)
    if coverage < (0.9 if critical else min_term_coverage):
        return False, 'grounding_terms_missing'
    run, best, previous = 0, 0, -1
    positions = {}
    for i, t in enumerate(source_terms):
        positions.setdefault(t, []).append(i)
    for t in claim_terms:
        nxt = next((p for p in positions.get(t, []) if p == previous + 1), None)
        run = run + 1 if nxt is not None else 1 if t in positions else 0
        previous = nxt if nxt is not None else (positions[t][0] if t in positions else -1)
        best = max(best, run)
    if best < min(3, len(claim_terms)):
        return False, 'grounding_terms_scattered'
    return True, 'grounded_in_unreviewed_excerpt'
