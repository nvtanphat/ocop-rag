"""Evidence and business-ontology quality audit; never promotes machine candidates.

The report measures structural integrity, not extraction accuracy. Accuracy
requires a human-annotated gold set on the original OCOP PDF pages.
"""
from __future__ import annotations
from collections import Counter
import re
from .shapes import audit_shapes


def audit_knowledge(units: list[dict], layers: dict[str,list[dict]]) -> dict:
    by_id={u['unit_id']:u for u in units}
    entities=layers.get('business_entities',[])
    relations=layers.get('business_relations',[])
    rules=layers.get('business_rules',[])
    by_entity={e['entity_id']:e for e in entities}
    issue_counts=Counter()
    samples=[]
    def issue(name: str, item: str):
        issue_counts[name]+=1
        if len(samples)<30:samples.append({'reason':name,'item':item})
    def references(item_id: str, refs: list[dict]):
        if not refs:
            issue('missing_evidence_ref',item_id)
        for ref in refs:
            unit=by_id.get(ref.get('evidence_unit_id'))
            if not unit or unit.get('source_id')!=ref.get('source_id'):
                issue('orphan_evidence_ref',item_id)
                continue
            if ref.get('pdf_page') not in [s['pdf_page'] for s in unit.get('spans',[])]:
                issue('wrong_pdf_page',item_id)
            if not str(ref.get('quote') or '').strip():
                issue('empty_source_quote',item_id)
    for item in entities:
        references(item['entity_id'],item.get('evidence',[]))
        if item.get('status')=='verified':issue('automatic_verified_entity',item['entity_id'])
    for item in relations:
        references(item['relation_id'],item.get('evidence',[]))
        if item.get('source_entity_id') not in by_entity or item.get('target_entity_id') not in by_entity:
            issue('orphan_relation_endpoint',item['relation_id'])
        if item.get('status')=='verified':issue('automatic_verified_relation',item['relation_id'])
    for item in rules:
        references(item['rule_id'],item.get('evidence',[]))
        if item.get('status')!='verified' and (item.get('consequence') or item.get('if_all')):
            issue('unverified_executable_rule',item['rule_id'])
    arithmetic, incomplete = audit_arithmetic(units,layers)
    return {
        'shapes':audit_shapes(units,layers),
        'arithmetic_mismatches':arithmetic,
        'arithmetic_incomplete':incomplete,
        'quality_type':'structural_only_not_ocop_accuracy',
        'entity_types':dict(sorted(Counter(e['kind'] for e in entities).items())),
        'relation_types':dict(sorted(Counter(r['relation_type'] for r in relations).items())),
        'rule_types':dict(sorted(Counter(r['kind'] for r in rules).items())),
        'issues':dict(sorted(issue_counts.items())),
        'samples':samples,
        'machine_verified_facts':0,
        'ocr_score_accuracy_measured':False,
        'manual_gold_required':True,
    }


def audit_arithmetic(units, layers):
    """Compare observed candidates only; never repair scores or assess a product."""
    entities={e['entity_id']:e for e in layers.get('business_entities',[])}
    children={};options={};parts={}
    for relation in layers.get('business_relations',[]):
        src,dst=relation['source_entity_id'],relation['target_entity_id']
        if relation['relation_type']=='HAS_SUBCRITERION':
            children.setdefault(src,set()).add(dst)
        elif relation['relation_type']=='HAS_OPTION':
            options.setdefault(src,set()).add(dst)
        elif relation['relation_type']=='HAS_CRITERION':
            parts.setdefault(src,set()).add(dst)
    references={}
    for unit in units:
        if unit.get('unit_kind')!='article' or not re.search(r'Phần\s+[ABC]\s*:',unit.get('text',''),re.I):
            continue
        values={}
        headings=list(re.finditer(r'Phần\s+([ABC])\s*:',unit['text'],re.I))
        for i,heading in enumerate(headings):
            fragment=unit['text'][heading.end():headings[i+1].start() if i+1<len(headings) else len(unit['text'])]
            points=re.search(r'\((\d+)\s*(?:điểm|điêm|diểm|diêm)\b',fragment,re.I)
            if points:
                values[heading[1].upper()]=int(points[1])
        total=re.search(r'tối\s+đa\s+(?:là\s+)?(\d+)\s+điểm',unit['text'],re.I)
        references[unit['source_id']]=(values,int(total[1]) if total else None,unit)
    mismatches=[];incomplete=[]

    def check(kind,parent,ids,observed,expected=None):
        values=[entities[e]['attributes'].get('max_points_candidate' if entities[e]['kind']=='Criterion' else 'points_candidate') for e in ids]
        report={'check':kind,'entity_id':parent['entity_id'],'label':parent['label'],
                'observed_candidate':observed,'children':sorted(ids),
                'child_candidates':[{'entity_id':eid,'label':entities[eid]['label'],
                    'points_candidate':entities[eid]['attributes'].get('max_points_candidate' if entities[eid]['kind']=='Criterion' else 'points_candidate'),
                    'evidence':entities[eid]['evidence']} for eid in sorted(ids)],
                'evidence':parent['evidence']+[r for eid in sorted(ids) for r in entities[eid]['evidence']],
                'status':'candidate','values_changed':False}
        if kind in {'part_reference','sheet_total'} and parent['source_id'] in references:
            reference=references[parent['source_id']][2]
            report.update(reference_evidence_unit_id=reference['unit_id'],reference_spans=reference['spans'],
                          reference_text=reference['text'])
        if not isinstance(observed,(int,float)) or any(not isinstance(v,(int,float)) for v in values):
            missing=[eid for eid in ids if not isinstance(entities[eid]['attributes'].get(
                'max_points_candidate' if entities[eid]['kind']=='Criterion' else 'points_candidate'),(int,float))]
            if observed is None:
                missing.append(parent['entity_id'])
            incomplete.append({**report,'reason':'missing_candidate_points','missing_entity_ids':sorted(missing)})
            return
        if expected is None:
            expected=max(values) if kind=='criterion_option_max' else sum(values)
        if observed!=expected:
            mismatches.append({**report,'expected_from_candidates':expected})

    for eid,parent in entities.items():
        if parent['kind']=='Criterion' and parent.get('attributes',{}).get('sheet_number_candidate') is not None:
            score=parent['attributes'].get('max_points_candidate')
            if children.get(eid):
                check('parent_children_sum',parent,children[eid],score)
            elif options.get(eid):
                check('criterion_option_max',parent,options[eid],score)
            else:
                incomplete.append({'check':'criterion_option_max','entity_id':eid,'label':parent['label'],
                    'reason':'no_observed_score_options_or_children','evidence':parent['evidence']})
            letter=parent['attributes'].get('part_letter')
            reference=references.get(parent['source_id'])
            if letter and reference and letter in reference[0]:
                check('part_reference',parent,[],score,reference[0][letter])
        if parent['kind']=='CriterionSheet':
            ids=parts.get(eid,set())
            letters={entities[p]['attributes'].get('part_letter') for p in ids}
            reference=references.get(parent['source_id'])
            if letters=={'A','B','C'} and reference and reference[1] is not None:
                # The total itself is explicit in the reference article, not
                # imputed as a new fact on the sheet.
                check('sheet_total',parent,ids,reference[1])
            else:
                incomplete.append({'check':'sheet_total','entity_id':eid,'reason':'missing_parts_or_reference',
                                   'parts_observed':sorted(v for v in letters if v),'evidence':parent['evidence']})
    return mismatches,incomplete
