"""High-fidelity *candidate* OCOP business extraction from existing PageArtifacts.

Uses structural hints for recognition rows and form fields. Legal/scoring logic
remains inert until a separately audited, approved rule is supplied. Nothing in
this module performs entity resolution across legal jurisdictions or OCR guesses.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ai_core.domain.ocop_ids import stable_id
from .contracts import (
    BusinessEntity, BusinessRelation, BusinessRule, EvidenceRef, EntityType,
    Status, validate_business_graph,
)


KEYWORDS = (
    ("exemption", re.compile(r"(?:được\s+miễn|không\s+phải|không\s+thuộc\s+diện)", re.I)),
    ("prohibition", re.compile(r"(?:nghiêm\s+cấm|không\s+được)", re.I)),
    ("obligation", re.compile(r"(?:\bphải\b|bắt\s+buộc|có\s+trách\s+nhiệm)", re.I)),
    ("temporal", re.compile(r"(?:có\s+hiệu\s+lực|kể\s+từ\s+ngày|chuyển\s+tiếp|tạm\s+ngưng\s+hiệu\s+lực)", re.I)),
)


def _ref(candidate: dict, evidence_index: dict[str, dict], text: str | None = None) -> EvidenceRef:
    src, uid = candidate['source_id'], candidate['evidence_unit_id']
    unit = evidence_index.get(uid)
    if unit is None or unit['source_id'] != src:
        raise ValueError('missing or mismatched source evidence')
    spans = unit.get('spans') or []
    page = int(candidate.get('pdf_page') or spans[0]['pdf_page'])
    if page not in [int(s['pdf_page']) for s in spans]:
        raise ValueError('candidate page not present in source spans')
    original = unit.get('text') or ''
    if not original.strip():
        raise ValueError('empty evidence body')
    quote = (text or candidate.get('row_text') or candidate.get('label_candidate') or '').strip()
    row_no = candidate.get('row')
    bbox = None
    if row_no is not None:
        cells = [c for c in unit.get('structured', {}).get('cells', [])
                 if int(c.get('row', -1)) == int(row_no)]
        if not cells:
            raise ValueError('table row missing from evidence source')
        if quote:
            # A row extracted from structured table cells may differ in layout
            # newlines from the flat table text. Reconstruct from ORIGINAL cells.
            reconstructed = ' | '.join(str(c.get('text') or '').strip()
                       for c in sorted(cells,key=lambda x:int(x.get('col',0)))
                       if str(c.get('text') or '').strip())
            if quote != reconstructed and quote not in original and not reconstructed.startswith(quote):
                raise ValueError('candidate row text not traceable to table cells')
            quote = reconstructed[:1200]
        rectangles = [c.get('bbox') for c in cells if c.get('bbox')]
        if rectangles:
            bbox = (min(v[0] for v in rectangles), min(v[1] for v in rectangles),
                    max(v[2] for v in rectangles), max(v[3] for v in rectangles))
    else:
        if quote and quote not in original:
            raise ValueError('quote not literally present in evidence source')
        if not quote:
            quote = original[:min(200,len(original))].strip()
    span = next(s for s in spans if int(s['pdf_page']) == page)
    return EvidenceRef(source_id=src,evidence_unit_id=uid,pdf_page=page,
          table_id=candidate.get('table_id') or span.get('table_id'),
          row=row_no,bbox=bbox or span.get('bbox'),quote=quote)


def _cell_ref(candidate: dict, evidence_index: dict[str, dict], col: int) -> EvidenceRef | None:
    """Return the literal source cell for points/mandatory marks, if present.

    Do not replace an OCR cell with alternative crop text or a guessed value.
    A missing cell yields None and remains unresolved.
    """
    unit=evidence_index.get(candidate.get('evidence_unit_id'))
    if not unit or unit.get('source_id')!=candidate.get('source_id'):
        return None
    row=int(candidate.get('row',-1))
    cells=[c for c in unit.get('structured',{}).get('cells',[])
           if int(c.get('row',-2))==row and int(c.get('col',-2))==col]
    if len(cells)!=1 or not str(cells[0].get('text') or '').strip():
        return None
    cell=cells[0]
    raw=str(cell['text']).strip()
    span=unit.get('spans') or []
    if not span:
        return None
    page=int(candidate.get('pdf_page') or span[0]['pdf_page'])
    if page not in [int(s['pdf_page']) for s in span]:
        return None
    table_id=candidate.get('table_id') or unit.get('structured',{}).get('table_id')
    return EvidenceRef(source_id=candidate['source_id'],
        evidence_unit_id=candidate['evidence_unit_id'],pdf_page=page,
        table_id=table_id, row=row,
        cell_id=f'{table_id}:r{row}:c{col}' if table_id else None,
        bbox=cell.get('bbox'),quote=raw)


def _short_label(value: str) -> str:
    return re.sub(r'\s+', ' ', value).strip()[:350]


def extract_semantics(units: list[dict], source_kinds: dict[str, str],
                      candidate_sets: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Create typed graph facts from only source-observable information.

    The outputs are read-only candidates. No candidate is automatically verified,
    and a missing score/owner/date is represented as unknown, NEVER imputed.
    """
    evidence_by_id = {u['unit_id']: u for u in units}
    entities: dict[str, BusinessEntity] = {}
    relations: dict[str, BusinessRelation] = {}
    rules: dict[str, BusinessRule] = {}
    omitted = Counter()

    def add(kind: EntityType, label: str, record: dict, evidence: EvidenceRef,
            *, key: str, attributes: dict | None = None) -> str:
        src = record['source_id']
        entity_id = stable_id('biz_entity', src, [kind.value, key], revision='biz-v1')
        new = BusinessEntity(entity_id=entity_id, kind=kind, label=label,
            source_id=src, evidence=[evidence], attributes=attributes or {})
        if entity_id in entities:
            existing = entities[entity_id]
            if existing.kind != kind or existing.source_id != src:
                raise ValueError('entity identity collision')
            if (evidence.source_id, evidence.evidence_unit_id, evidence.pdf_page) not in {
                (e.source_id, e.evidence_unit_id, e.pdf_page) for e in existing.evidence
            }:
                existing.evidence.append(evidence)
        else:
            entities[entity_id] = new
        return entity_id

    def link(relation: str, src: str, dst: str, ev: EvidenceRef, *, extra_evidence: list[EvidenceRef] | None = None) -> None:
        rid = stable_id('biz_relation', ev.source_id,
                        [relation, src, dst, ev.evidence_unit_id, ev.row], revision='biz-v1')
        relations[rid] = BusinessRelation(relation_id=rid, relation_type=relation,
                   source_entity_id=src, target_entity_id=dst, evidence=[ev, *(extra_evidence or [])])

    # Table row candidates MUST NOT be promoted to Criterion/ScoreOption.
    # A row may be a heading, subtotal, merged cell or score option.
    for row in candidate_sets.get('criterion_candidates', []):
        try:
            ev = _ref(row, evidence_by_id)
            add(EntityType.CRITERION_ROW, _short_label(row.get('label_candidate','')) or 'Dòng bảng',
                row, ev, key=row['candidate_id'], attributes={
                    'score_candidate': row.get('score_candidate'),
                    'table_id': row.get('table_id'), 'row': row.get('row')})
        except (KeyError, ValueError):
            omitted['criterion_row_missing_evidence'] += 1

    # Structure-aware scoring candidate graph, not a point-awarding engine.
    # Only a NUMBERED row may introduce a parent criterion. The following rows
    # are linked as options only within the SAME original table. All statuses
    # remain candidate and score values are observational, not approved rules.
    from collections import defaultdict
    score_tables = defaultdict(list)
    for row in candidate_sets.get('criterion_candidates', []):
        score_tables[(row.get('source_id'),row.get('evidence_unit_id'),row.get('table_id'))].append(row)
    heading_re = re.compile(r'^\s*(?:\d+(?:\.\d+){1,3}[.)]?|[A-C][.])\s+\S', re.I)
    markers_re = re.compile(r'(?<!\*)\*{3,5}(?!\*)')
    for _,rows in sorted(score_tables.items(),key=lambda item:str(item[0])):
        parent_id = None
        for row in sorted(rows,key=lambda rec:int(rec.get('row',0))):
            raw = str(row.get('label_candidate') or '')
            parts=[part.strip() for part in raw.split('|')]
            label=parts[0] if parts else ''
            try:
                ev = _ref(row,evidence_by_id)
            except (KeyError,ValueError):
                omitted['score_row_missing_evidence']+=1
                continue
            score=row.get('score_candidate')
            if score is not None and (not isinstance(score,int) or not 0<=score<=100):
                score=None
            if heading_re.match(label):
                parent_id=add(EntityType.CRITERION, _short_label(label),row,ev,
                    key=f'numbered:{row["candidate_id"]}',attributes={
                        'max_points_candidate':score,
                        'table_id':row.get('table_id'),
                        'row':row.get('row')})
            elif score is not None and len(label.strip()) >= 5:
                option_id=add(EntityType.SCORE_OPTION, _short_label(label),row,ev,
                    key=f'score-option:{row["candidate_id"]}',attributes={
                        'points_candidate':score, 'parent_identified':bool(parent_id),
                        'table_id':row.get('table_id'), 'row':row.get('row')})
                score_cols=[int(c.get('col',-1)) for c in evidence_by_id[row['evidence_unit_id']]
                    .get('structured',{}).get('cells',[]) if int(c.get('row',-1))==int(row.get('row',-2))]
                score_ev=_cell_ref(row,evidence_by_id,max(score_cols)) if score_cols else None
                if score_ev and score_ev.quote.replace(' ','')==str(score):
                    entities[option_id].evidence.append(score_ev)
                if parent_id:
                    link('HAS_OPTION',parent_id,option_id,ev,
                         extra_evidence=[score_ev] if score_ev and score_ev.quote.replace(' ','')==str(score) else None)
                rule_id=stable_id('biz_scoring_rule',row['source_id'],
                    [row['candidate_id']],revision='biz-v2')
                rules[rule_id]=BusinessRule(rule_id=rule_id,source_id=row['source_id'],
                    kind='scoring',statement=raw,evidence=[ev,score_ev] if score_ev and score_ev.quote.replace(' ','')==str(score) else [ev])
            for mark in sorted(set(markers_re.findall(label))):
                if not parent_id:
                    continue
                condition_id=add(EntityType.CONDITION, f'Dấu {mark} (cần xác minh)',row,ev,
                    key=f'mandatory-marker:{row["candidate_id"]}:{mark}',attributes={
                        'marker_observed':mark, 'interpretation_verified':False})
                link('HAS_CONDITION',parent_id,condition_id,ev)

    for row in candidate_sets.get('form_candidates', []):
        try:
            ev = _ref(row, evidence_by_id)
            form_id = add(EntityType.FORM_TEMPLATE,
                 _short_label(row.get('title','')) or 'Biểu mẫu', row, ev,
                 key=row['candidate_id'], attributes={'form_number':row.get('form_number')})
            for i, label in enumerate(row.get('fields_candidate', [])):
                label = _short_label(label)
                if len(label) < 3:
                    continue
                field_ev = _ref(row, evidence_by_id, text=label)
                field_id = add(EntityType.FORM_FIELD, label, row, field_ev,
                               key=f'{row["candidate_id"]}:field:{i}',
                               attributes={'required':None, 'field_position':i})
                link('HAS_FIELD', form_id, field_id, field_ev)
        except (KeyError, ValueError):
            omitted['form_missing_evidence'] += 1

    # Recognition tables may have true merged owner cells. When the upstream
    # table engine provides native rowspan geometry, carry that source cell to
    # subsequent product rows. NEVER fill by mere previous-row adjacency.
    for row in candidate_sets.get('recognition_candidates', []):
        src = row.get('source_id', '')
        cols = row.get('resolved_columns') or {}
        parts = [p.strip() for p in str(row.get('row_text') or '').split('|')]
        def value(col: int) -> str:
            col_record = cols.get(str(col)) or {}
            return str(col_record.get('text') or '').strip()
        sequence = value(0) if cols else (parts[0] if parts else '')
        if not re.fullmatch(r'\d+', sequence):
            omitted['recognition_header_or_incomplete_row'] += 1
            continue
        if src.startswith('VN.HUE.'):
            product, producer = ((value(1),value(2)) if cols and value(1) and value(2)
                                 else (parts[1],parts[2]) if len(parts)>=5 else ('',''))
            owner_column = 2
        elif src.startswith('VN.HAIPHONG.'):
            producer, product = ((value(1),value(2)) if cols
                                 else (parts[1],parts[2]) if len(parts)>=7 else ('',''))
            owner_column = 1
        else:
            omitted['recognition_unknown_layout'] += 1
            continue
        if len(_short_label(product)) < 3 or len(_short_label(producer)) < 3:
            omitted['recognition_missing_owner_or_product'] += 1
            continue
        owner_cell = cols.get(str(owner_column), {})
        inherited = bool(owner_cell.get('inherited'))
        owner_ref = None
        if inherited:
            origin_row = owner_cell.get('row')
            if origin_row is None or int(origin_row) >= int(row.get('row',0)):
                omitted['recognition_unsafe_merged_owner'] += 1
                continue
            try:
                owner_ref = _ref({**row,'row':origin_row}, evidence_by_id)
            except (KeyError,ValueError):
                omitted['recognition_unsafe_merged_owner'] += 1
                continue
        try:
            ev = _ref(row, evidence_by_id)
            decision = add(EntityType.RECOGNITION_DECISION, src, row, ev,
                           key=src, attributes={'decision_source_id':src})
            rec = add(EntityType.RECOGNITION_RECORD,
                      _short_label(row['row_text']), row, ev, key=row['candidate_id'],
                      attributes={'star_rating_candidate':row.get('star_candidate'),
                                  'row_number':sequence,'owner_inherited_from_merge':inherited})
            product_id = add(EntityType.PRODUCT, _short_label(product), row, ev,
                             key=f'{row["candidate_id"]}:product')
            owner_id = add(EntityType.ORGANIZATION, _short_label(producer), row, ev,
                           key=f'organization:{_short_label(producer).casefold()}')
            if owner_ref:
                entities[owner_id].evidence.append(owner_ref)
            link('HAS_RECORD',decision,rec,ev)
            link('RECOGNIZES',rec,product_id,ev)
            link('DECLARED_BY',rec,owner_id,ev,extra_evidence=[owner_ref] if owner_ref else None)
        except (KeyError, ValueError):
            omitted['recognition_missing_evidence'] += 1

    # Deontic extraction is ONLY a textual claim candidate. We deliberately do
    # not compile OCR prose into executable IF/THEN or effective-date rules.
    permitted = {'food_safety_law','food_safety_decree','food_safety_resolution',
                 'labeling_decree','labeling_amendment','cooperative_law',
                 'ocop_framework','ocop_historical','ocop_amendment'}
    for u in units:
        if source_kinds.get(u['source_id']) not in permitted or u['unit_kind'] not in ('article','paragraph','section'):
            continue
        for line_no,line in enumerate((u.get('text') or '').splitlines()):
            line=line.strip()
            if len(line) < 25:
                continue
            for kind,pattern in KEYWORDS:
                if not pattern.search(line):
                    continue
                # keep contextual paragraph, but no hidden text content synthesis
                try:
                    ev = _ref({'source_id':u['source_id'],
                               'evidence_unit_id':u['unit_id'],
                               'pdf_page':u['spans'][0]['pdf_page']}, evidence_by_id, text=line)
                    rid=stable_id('biz_rule', u['source_id'], [u['unit_id'],line_no,kind],revision='biz-v1')
                    rules[rid]=BusinessRule(rule_id=rid,source_id=u['source_id'],
                              kind=kind,statement=line,evidence=[ev])
                except (KeyError, ValueError):
                    omitted['rule_missing_evidence'] += 1
                break  # one dominant modality per line; ambiguous remains candidate

    typed_entities=sorted(entities.values(),key=lambda x:x.entity_id)
    typed_relations=sorted(relations.values(),key=lambda x:x.relation_id)
    validate_business_graph(typed_entities,typed_relations)
    return {
       'business_entities':[e.model_dump(mode='json') for e in typed_entities],
       'business_relations':[r.model_dump(mode='json') for r in typed_relations],
       'business_rules':[r.model_dump(mode='json') for r in sorted(rules.values(),key=lambda x:x.rule_id)],
       'business_omissions':[{'reason':key,'count':val} for key,val in sorted(omitted.items())],
    }
