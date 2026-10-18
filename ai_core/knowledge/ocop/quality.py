"""Evidence and business-ontology quality audit; never promotes machine candidates.

The report measures structural integrity, not extraction accuracy. Accuracy
requires a human-annotated gold set on the original OCOP PDF pages.
"""
from __future__ import annotations
from collections import Counter


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
    return {
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
