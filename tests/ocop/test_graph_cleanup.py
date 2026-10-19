"""Synthetic projection tests; raw debug knowledge must remain untouched."""
import json
from ai_core.graph.ocop.builder import build_graph


def put(path, rows):
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')


def test_one_edge_merges_pages_and_debug_layers_stay_outside_graph(tmp_path):
    k=tmp_path/'knowledge'; k.mkdir()
    (k/'manifest.json').write_text(json.dumps({'complete':True,'corpus_version':'test',
        'document_registry':{'S':{'document_number':'26/2026/QD'}}}))
    units=[{'unit_id':f'u{p}','source_id':'S','text':'literal', 'unit_kind':'paragraph',
        'review_status':'candidate','spans':[{'pdf_page':p,'bbox':[0,0,10,10],
        'source_sha256':'a'*64}]} for p in (1,2)]
    put(k/'evidence_units.jsonl',units)
    refs=[{'source_id':'S','evidence_unit_id':u['unit_id'],'pdf_page':p,
        'bbox':[0,0,10,10],'quote':'literal','source_sha256':'a'*64}
        for p,u in enumerate(units,1)]
    def entity(eid,kind,attrs=None):
        return {'entity_id':eid,'kind':kind,'source_id':'S','label':eid,
                'status':'candidate','attributes':attrs or {},'evidence':refs}
    put(k/'business_entities.jsonl',[entity('parent','Criterion'),entity('option','ScoreOption'),
        entity('shadow','CriterionRowCandidate'),entity('mark','Condition',{'marker_observed':'***'}),
        entity('decision','RecognitionDecision')])
    def relation(kind,start,end,ref):
        return {'relation_type':kind,'source_entity_id':start,'target_entity_id':end,
                'status':'candidate','evidence':[ref]}
    put(k/'business_relations.jsonl',[
        relation('HAS_OPTION','parent','option',r) for r in refs]+[
        relation('HAS_CONDITION','parent','mark',refs[0])])
    put(k/'business_rules.jsonl',[{'rule_id':'scoring','kind':'scoring','source_id':'S',
        'statement':'literal','status':'candidate','evidence':refs}])
    original=(k/'business_entities.jsonl').read_bytes()
    manifest=build_graph(k,tmp_path/'graph')
    assert manifest['counts']['rejected']==0
    nodes=[json.loads(l) for l in (tmp_path/'graph/nodes.jsonl').read_text().splitlines()]
    edges=[json.loads(l) for l in (tmp_path/'graph/edges.jsonl').read_text().splitlines()]
    assert not {'Condition','CriterionRowCandidate','RuleCandidate'} & {n['node_type'] for n in nodes}
    edge=next(e for e in edges if e['relation_type']=='HAS_OPTION')
    assert {c['pdf_page'] for c in edge['citations']}=={1,2}
    triples=[(e['relation_type'],e['source_entity_id'],e['target_entity_id']) for e in edges]
    assert len(triples)==len(set(triples))
    assert next(n for n in nodes if n['node_id']=='decision')['label']=='26/2026/QD'
    assert (k/'business_entities.jsonl').read_bytes()==original
