"""Literal, source-scoped legal document candidates; no current-law resolution.

Only exact registered numbers resolve document identities across PDFs. Evidence
retains the citing PDF's source_id, page, original text and bounding box.
"""
from __future__ import annotations

import re
from datetime import date

from ocop_contracts.ids import stable_id
from .contracts import BusinessRule, EntityType, contains_document_number
from ai_core.processing.ocop.temporal_candidates import _local_context


NUMBER = re.compile(r'(?<![\w/])\d{1,4}/(?:\d{4}/)?(?:QĐ-TTg|QĐ-UBND|NĐ-CP|NQ-CP|QH\d+|TT-[A-ZĐ]+)(?![\w/-])', re.I)
DATE = re.compile(r'ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(20\d{2})', re.I)
EFFECTIVE = re.compile(r'(?:Quyết định|Nghị định)\s+này\s+có\s+hiệu\s+lực(?:\s+thi\s+hành)?\s+(?:kể\s+)?từ\s+' + DATE.pattern, re.I)
ISSUER = re.compile(r'^(?:THỦ TƯỚNG CHÍNH PHỦ|CHÍNH PHỦ|ỦY BAN NHÂN DÂN[^\n]*?|UỶ BAN NHÂN DÂN[^\n]*?)(?=\s+CỘNG\b|\s*$)', re.M)


def _date(match):
    try:
        return date(int(match[3]), int(match[2]), int(match[1])).isoformat()
    except (ValueError, TypeError):
        return None


def _issuer_lines(unit,header):
    """Observed left-column heading above Số:, excluding right-column motto."""
    before=re.split(r'\bSố\s*:',header,maxsplit=1,flags=re.I)[0]
    geometry=unit.get('structured',{}).get('quote_lines',[])
    lines=[g for g in geometry if g.get('text') in before and g.get('bbox')]
    anchors=[g for g in lines if ISSUER.fullmatch(g['text'].strip())]
    if not anchors:
        matches=list(ISSUER.finditer(before))
        return [matches[-1][0]] if matches else []
    first=anchors[-1];box=first['bbox'];selected=[first]
    for g in sorted(lines,key=lambda g:g['bbox'][1]):
        b=g['bbox'];last=selected[-1]['bbox']
        if (b[1]>=last[3]-2 and b[1]-last[3]<=2*(last[3]-last[1]) and
            abs((b[0]+b[2])-(box[0]+box[2]))<max(box[2]-box[0],b[2]-b[0]) and
            re.match(r'^(?:THÀNH\s+PHỐ|TỈNH|HUYỆN|QUẬN|THỊ\s+XÃ|PHƯỜNG|XÃ)\b',g['text'])):
            selected.append(g)
    return [g['text'] for g in selected]


def extract_documents(units, source_kinds, registry, index, entities, relations, rules,
                      omitted, add, link, ref):
    # Ambiguous registry numbers must not resolve to an arbitrary jurisdiction.
    numbers = {}
    for sid, source in registry.items():
        number = source.get('document_number')
        if number:
            numbers.setdefault(number.casefold(), []).append(sid)

    def document(sid, ev, target=None):
        target = target or sid
        number = registry[target].get('document_number')
        entity_id = add(EntityType.SOURCE_DOCUMENT, (number or target) if target != sid else sid, {'source_id':target}, ev,
                   key=f'document:{target}', attributes={
                       'registry_source_id':target,
                       'reference_only':target != sid,
                       'document_number_candidate':number if target != sid else None,
                       'issuer_candidate':None, 'signed_at_candidate':None,
                       'effective_from':None})
        if target == sid:
            entities[entity_id].attributes['reference_only'] = False
        return entity_id

    for unit in units:
        sid = unit['source_id']
        if sid not in registry or unit.get('unit_kind') not in ('article','paragraph','section'):
            continue
        spans = unit.get('spans') or []
        if not spans:
            continue
        text = unit.get('text') or ''
        record = {'source_id':sid, 'evidence_unit_id':unit['unit_id'],
                  'pdf_page':spans[0]['pdf_page']}
        if not text.strip():
            continue
        ev = ref(record, index, text=text)
        own = document(sid, ev)
        attrs = entities[own].attributes
        # Only the first page's header, before the title/bases/articles, is
        # eligible for signing metadata. Body citation dates are ineligible.
        if int(spans[0]['pdf_page']) == 1:
            header = re.split(r'QUYẾT\s+ĐỊNH|Căn\s+cứ|Điều\s+\d', text, maxsplit=1)[0]
            number = re.search(r'\bSố\s*:\s*(' + NUMBER.pattern + r')', header, re.I)
            # Signature watermark text can itself contain an isolated
            # "CHÍNH PHỦ". The issuing header is the last matching heading
            # before the document's own Số: line, not the first page mention.
            issuers = _issuer_lines(unit,header)
            signed = DATE.search(header)
            for field, value in (
                ('document_number_candidate', number[1] if number else None),
                ('issuer_candidate', '\n'.join(issuers) if issuers else None),
                ('signed_at_candidate', _date(signed) if signed else None),
            ):
                if value is not None:
                    if attrs[field] is None or attrs[field] == value:
                        attrs[field] = value
                    else:
                        attrs[field] = None
                        omitted[f'document_conflicting_{field}'] += 1
            if attrs['document_number_candidate'] is not None:
                entities[own].label = attrs['document_number_candidate']
            for literal in issuers:
                issuer_ref=ref(record,index,text=literal)
                if issuer_ref not in entities[own].evidence:
                    entities[own].evidence.append(issuer_ref)

        match = EFFECTIVE.search(text)
        if match:
            attrs['effective_from'] = _date(match)

        # Transition articles retain all clauses verbatim, including wrapped
        # continuations. They do not gain executable conditions or dates.
        if re.search(r'\bchuyển\s+tiếp\b', text, re.I):
            rid = stable_id('biz_rule', sid, [unit['unit_id'],'transition'], revision='business')
            rules[rid] = BusinessRule(rule_id=rid, source_id=sid, kind='temporal',
                                      statement=text, evidence=[ev])

        references = []
        for match in NUMBER.finditer(text):
            targets = numbers.get(match[0].casefold(), [])
            if len(targets) != 1:
                omitted['legal_reference_not_uniquely_registered'] += 1
                continue
            if targets[0] != sid and targets[0] not in references:
                references.append(targets[0])

        # Only operative amendment text, never a citation in an expiry clause
        # or the description of a different amending instrument.
        amendment = source_kinds.get(sid) in {'ocop_amendment','labeling_amendment'} and bool(
            re.match(r'\s*Điều\s+1[.:]?\s*Sửa\s+đổi', text, re.I))
        suspension = bool(re.match(
            r'\s*Điều\s+\d+[.:]\s*Tạm\s+(?:ngưng|đình\s+chỉ)\s+hiệu\s+lực',text,re.I))
        expiry = re.search(r'hết\s+hiệu\s+lực\s+sau\s+(\d+)\s+ngày', text, re.I)
        expiry_context = _local_context(text,expiry.start(),expiry.end()) if expiry else ''
        based = source_kinds.get(sid) == 'recognition_decision' and bool(re.search(r'Căn\s+cứ', text, re.I))
        for target in references:
            target_id = document(sid, ev, target)
            if amendment:
                # Article 1's opening identifies the amended decision; later
                # nested quoted references must not become extra targets.
                opening = re.split(r'\n\s*1[.)]\s', text, maxsplit=1)[0]
                if contains_document_number(opening,registry[target]['document_number']):
                    link('AMENDS', own, target_id, ev)
            if suspension:
                opening = re.split(r'\n\s*1[.)]\s',text,maxsplit=1)[0]
                if contains_document_number(opening,registry[target]['document_number']):
                    link('SUSPENDS',own,target_id,ev,attributes={
                        'temporal_effect':'suspension','interpretation_verified':False})
            if expiry:
                # Require the relative anchor, not a bare mention of expiry.
                if (contains_document_number(expiry_context,registry[target]['document_number']) and
                    re.search(r'kể\s+từ\s+ngày\s+Quyết\s+định\s+này\s+có\s+hiệu\s+lực', expiry_context, re.I)):
                    link('REPLACES', own, target_id, ev, attributes={
                        'effective_from':None, 'expires_after_days':int(expiry[1]),
                        'temporal_effect':'expiry', 'interpretation_verified':False})
            if based:
                # Restrict each reference to its actual Căn cứ paragraph.
                bases = re.findall(r'Căn\s+cứ[^;]+;', text, re.I)
                if any(contains_document_number(b,registry[target]['document_number']) for b in bases):
                    decision = add(EntityType.RECOGNITION_DECISION, sid, record, ev,
                                   key=sid, attributes={'decision_source_id':sid})
                    link('BASED_ON', decision, target_id, ev)

    from .article_tree import extract_article_tree
    extract_article_tree(units, registry, index, entities, omitted, add, link, ref, document)

    # Carry the explicit current-document anchor and its citation to expiry
    # edges, even if the effective-date clause lives in another evidence unit.
    for sid in {u['source_id'] for u in units}:
        docs = [e for e in entities.values() if e.kind == EntityType.SOURCE_DOCUMENT
                and e.source_id == sid and not e.attributes.get('reference_only')]
        if not docs:
            continue
        doc = docs[0]
        for relation in relations.values():
            if relation.relation_type != 'REPLACES' or relation.source_entity_id != doc.entity_id:
                continue
            relation.attributes['effective_from'] = doc.attributes.get('effective_from')
            # The anchor's provenance is included in both endpoints, so every
            # materialized evidence edge remains grounded at both endpoints.
            for anchor in doc.evidence:
                unit = index[anchor.evidence_unit_id]
                if EFFECTIVE.search(unit.get('text') or ''):
                    target = entities[relation.target_entity_id]
                    if anchor not in target.evidence:
                        target.evidence.append(anchor)
                    if anchor not in relation.evidence:
                        relation.evidence.append(anchor)
        for field in ('document_number_candidate','issuer_candidate','signed_at_candidate','effective_from'):
            if doc.attributes.get(field) is None:
                omitted[f'document_missing_{field}'] += 1
