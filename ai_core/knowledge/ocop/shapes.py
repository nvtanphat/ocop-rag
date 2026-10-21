"""Declarative candidate shape audit. Reports only; never repairs candidates."""
from collections import Counter, defaultdict
from ai_core.domain.ocop_citations import quote_bbox
from .star_requirements import SHEET


NODE_SHAPES = {
    'ScoreOption': {'points_candidate': (int, float, type(None)), 'parent_identified': (bool,)},
    'Criterion': {'level': (int,), 'max_points_candidate': (int, float, type(None))},
    'CriterionSheet': {'sheet_number': (str, int, type(None))},
    'StarLevel': {'star_level': (int,), 'min_points': (int, float, type(None)),
                  'max_points': (int, float, type(None)), 'interpretation_verified': (bool,)},
    'ProcedureStep': {'statement_candidate': (str,), 'deadline': (int, type(None)),
                      'deadline_unit': (str, type(None))},
}
PARENT_SHAPES = {
    'ScoreOption': ({'HAS_OPTION'}, 1, 1),
    'Criterion': ({'HAS_CRITERION', 'HAS_SUBCRITERION'}, 1, 1),
    'ProcedureStep': ({'RESPONSIBLE_FOR'}, 1, None),
}
ATOMIC_TYPES = {'ProcedureStep','Authority','EvidenceType','ScoreOption','Criterion',
                'Point','StarLevel','Product','Organization','RecognitionRecord'}
CONTAINER_TYPES = {'SourceDocument','Article','Clause','RecognitionDecision',
                   'LocalGuidance','CriterionSheet'}


def audit_shapes(units, layers, *, max_page_area_ratio=0.35, bbox_tolerance=2.0):
    by_unit={u['unit_id']:u for u in units}
    entities=layers.get('business_entities',[])
    relations=layers.get('business_relations',[])
    violations=[]
    parents=defaultdict(set); children=defaultdict(set); triples=Counter()
    for r in relations:
        key=(r['relation_type'],r['source_entity_id'],r['target_entity_id'])
        triples[key]+=1
        parents[(r['target_entity_id'],r['relation_type'])].add(r['source_entity_id'])
        children[(r['source_entity_id'],r['relation_type'])].add(r['target_entity_id'])
    def report(code,e,**details):
        severity=details.pop('severity','violation')
        violations.append({'constraint':code,'severity':severity,'entity_id':e.get('entity_id'),
            'node_type':e.get('kind'),'source_id':e.get('source_id'),
            'label':e.get('label'),'evidence':e.get('evidence',[]),**details})
    # Knowledge may contain repeated relation evidence rows. Agent projection
    # must merge these; report raw duplicates separately, not as graph failures.
    raw_duplicates=[{'relation_type':k[0],'source':k[1],'target':k[2],'count':v}
                    for k,v in triples.items() if v>1]
    page_boxes={}
    framework=set()
    for u in units:
        if u.get('structured',{}).get('source_kind')=='ocop_framework':
            framework.add(u['source_id'])
        if u.get('unit_kind')=='page':
            for span in u.get('spans',[]):
                page_boxes[(u['source_id'],span['pdf_page'])]=span['bbox']
    for e in entities:
        kind=e['kind']; attrs=e.get('attributes',{})
        for field,types in NODE_SHAPES.get(kind,{}).items():
            value=attrs.get(field)
            if field not in attrs or type(value) not in types:
                report('required_property_type',e,field=field,observed=value)
        if kind in PARENT_SHAPES:
            rels,minimum,maximum=PARENT_SHAPES[kind]
            found=set().union(*(parents[(e['entity_id'],r)] for r in rels))
            omission=attrs.get('authority_omission_reason') if kind=='ProcedureStep' else None
            if (len(found)<minimum and not omission) or (maximum is not None and len(found)>maximum):
                report('parent_cardinality',e,relations=sorted(rels),observed=len(found),
                       minimum=minimum,maximum=maximum)
        if kind=='CriterionSheet':
            # Index-only sheets have no actual scoring header/table yet.
            actual=any(e['source_id']==u['source_id'] and
                any(m[1]==str(attrs.get('sheet_number')) for m in SHEET.finditer(u.get('text','')))
                for u in units)
            actual=actual or bool(children[(e['entity_id'],'HAS_CRITERION')])
            if not actual:
                report('sheet_source_not_observed',e,severity='pending_source',classification_hint='source_pages_not_observed')
            elif not children[(e['entity_id'],'HAS_CRITERION')]:
                report('sheet_requires_criterion',e)
        if kind in {'CriterionRowCandidate','Condition'}:
            continue  # debug-only projection
        for ref in e.get('evidence',[]):
            box=ref.get('bbox');page=page_boxes.get((ref['source_id'],ref['pdf_page']))
            if box and page:
                if (box[0]>box[2] or box[1]>box[3] or
                    box[0]<page[0]-bbox_tolerance or box[1]<page[1]-bbox_tolerance or
                    box[2]>page[2]+bbox_tolerance or box[3]>page[3]+bbox_tolerance):
                    report('citation_outside_page',e,citation=ref,page_bbox=page)
                area=max(0,box[2]-box[0])*max(0,box[3]-box[1])
                full=max(1,(page[2]-page[0])*(page[3]-page[1]))
                if kind in ATOMIC_TYPES and area/full>max_page_area_ratio:
                    report('citation_page_area',e,ratio=round(area/full,5),citation=ref)
            unit=by_unit.get(ref.get('evidence_unit_id'))
            if unit and box and not ref.get('cell_id') and ref.get('row') is None:
                expected=quote_bbox(unit,ref['pdf_page'],ref.get('quote',''))
                if expected and any((box[0]<expected[0]-bbox_tolerance,box[1]<expected[1]-bbox_tolerance,
                                     box[2]>expected[2]+bbox_tolerance,box[3]>expected[3]+bbox_tolerance)):
                    report('citation_exceeds_quote_block',e,citation=ref,expected_bbox=expected)
                elif kind in CONTAINER_TYPES and expected and any(
                        abs(a-b)>bbox_tolerance for a,b in zip(box,expected)):
                    report('citation_quote_geometry_mismatch',e,citation=ref,expected_bbox=expected)
    for sid in sorted(framework):
        for kind,expected in [('CriterionSheet',26),('StarLevel',5)]:
            count=sum(e['source_id']==sid and e['kind']==kind for e in entities)
            if count!=expected:
                report('framework_count',{'source_id':sid,'kind':kind},expected=expected,observed=count)
    return {'policy':{'max_page_area_ratio':max_page_area_ratio,'bbox_tolerance':bbox_tolerance},
            'violations':violations,'counts':dict(Counter(v['constraint'] for v in violations)),
            'severity_counts':dict(Counter(v['severity'] for v in violations)),
            'raw_relation_duplicate_groups':raw_duplicates,
            'classification':'manual_review_required','repairs_applied':False}

