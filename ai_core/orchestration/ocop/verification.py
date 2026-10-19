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

def check_sensitive_claims(answer:str,evidence_rows:list[dict])->dict:
    """Fail-closed on numeric score/star claims without verified textual support.

    This is a lightweight *guard*, not semantic entailment verification.
    A matching number alone cannot establish application to a particular sheet.
    """
    assertions={re.sub(r"\s+"," ",m.group(0).casefold()).strip() for m in SCORE_ASSERTION.finditer(answer)}
    verified=' '.join(str(row.get('text') or row.get('evidence_text') or row.get('row_text') or '')
                      for row in evidence_rows if row.get('review_status')=='verified')
    verified=re.sub(r"\s+"," ",verified.casefold())
    unsupported=sorted(x for x in assertions if x not in verified)
    return {'unsupported_score_or_star_claims':unsupported,'sensitive_claim_count':len(assertions)}

# Claim-level verification. Supports an optional audited semantic entailment
# backend; lexical overlap alone is never called semantic proof.
from dataclasses import dataclass,asdict
import unicodedata

# Do not split decimal numbers such as 3.5 (which would create two claims).
CLAIM_SPLIT = re.compile(r'(?<=[!?])\s+|(?<!\d)\.\s+|\n+')
CRITICAL = re.compile(r'\b(?:\d{1,3}\s*(?:điểm|sao)|\d{4}|bắt buộc|miễn|không\s+phải|hiệu lực|được công nhận|hạn cuối)\b',re.I)
WORD = re.compile(r'[\wÀ-ỹ]+',re.U)


def _normalize(s:str)->str:
    return ' '.join(WORD.findall(unicodedata.normalize('NFC',s).casefold()))


def _split_claims(answer:str)->list[str]:
    # Marker-bearing lines can contain several independent claims.
    return [x.strip() for x in CLAIM_SPLIT.split(answer) if x.strip()]


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
