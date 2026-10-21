"""Entire review lifecycle on a synthetic PDF. Never approves real corpus data."""
import json
from pathlib import Path
import pytest
from ai_core.graph.ocop.builder import build_graph
from ai_core.graph.ocop.review import (load_queue,record_decision,rebuild_reviewed_graph,
                                      ledger_path,render_crop,statistics)
from ai_core.graph.ocop.retriever import traverse


@pytest.fixture
def corpus(tmp_path):
    import fitz
    from ai_core.processing.ocop.registry import SourceDocument,snapshot,sha256_file
    pdf=tmp_path/'data/raw/ocop/synthetic.pdf';pdf.parent.mkdir(parents=True)
    doc=fitz.open();page=doc.new_page();page.insert_text((20,30),'Synthetic product and owner');doc.save(pdf);doc.close()
    source=SourceDocument(source_id='SYNTHETIC',path='data/raw/ocop/synthetic.pdf',source_kind='recognition_decision')
    config=tmp_path/'configs';config.mkdir()
    (config/'ocop_sources.json').write_text(json.dumps({'schema_version':1,'sources':[source.model_dump(mode='json')]}))
    (config/'ocop_sources.lock.json').write_text(json.dumps(snapshot(tmp_path,[source])))
    base=tmp_path/'data/processed/ocop';k=base/'knowledge';k.mkdir(parents=True)
    ref={'source_id':'SYNTHETIC','evidence_unit_id':'unit:synthetic','pdf_page':1,
         'bbox':[10,10,210,50],'quote':'Synthetic product and owner','source_sha256':sha256_file(pdf)}
    unit={'unit_id':'unit:synthetic','source_id':'SYNTHETIC','unit_kind':'paragraph',
          'review_status':'needs_review','text':ref['quote'],'spans':[{'pdf_page':1,'bbox':ref['bbox'],
              'source_sha256':ref['source_sha256']}],'structured':{}}
    entity=lambda eid,kind,label:{'entity_id':eid,'kind':kind,'label':label,'source_id':'SYNTHETIC',
        'status':'candidate','attributes':{'points_candidate':None} if kind=='Product' else {},'evidence':[ref]}
    layers={'evidence_units':[unit],'entities':[],'relations':[],
        'business_entities':[entity('product:synthetic','Product','Synthetic product'),
                             entity('owner:synthetic','Organization','Synthetic owner')],
        'business_relations':[{'relation_id':'relation:synthetic','source_entity_id':'product:synthetic',
          'target_entity_id':'owner:synthetic','relation_type':'OWNED_BY','status':'candidate','evidence':[ref]}]}
    (k/'manifest.json').write_text(json.dumps({'complete':True,'corpus_version':'synthetic-review'}))
    for name,rows in layers.items():
        (k/(name+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
    build_graph(k,base/'graph')
    index=base/'index';index.mkdir()
    (index/'manifest.json').write_text(json.dumps({'corpus_version':'synthetic-review',
        'source_knowledge_version':'synthetic-review'}))
    (index/'evidence_units.jsonl').write_text(json.dumps(unit)+'\n')
    return tmp_path


def decide(root,target,decision='approve',correction=None):
    item=next(i for i in load_queue(root) if i['target_id']==target)
    record_decision(root,target,item['content_hash'],decision,'Synthetic human tester',correction=correction)
    rebuild_reviewed_graph(root)


def test_failed_dangling_edge_remains_reviewable_without_promotion(corpus):
    base=corpus/'data/processed/ocop'; path=base/'knowledge/business_relations.jsonl'
    relation=json.loads(path.read_text(encoding='utf-8'))
    relation['target_entity_id']='missing:owner'
    path.write_text(json.dumps(relation)+'\n',encoding='utf-8')
    build_graph(base/'knowledge',base/'graph')
    items=load_queue(corpus)
    decide(corpus,next(i['target_id'] for i in items if i['type']=='EvidenceUnit'))
    decide(corpus,'product:synthetic')
    edge=next(i for i in load_queue(corpus) if i['type']=='OWNED_BY')
    decide(corpus,edge['target_id'])
    current=next(i for i in load_queue(corpus) if i['target_id']==edge['target_id'])
    assert current['check']=='failed' and current['check_reason']=='missing_endpoint'
    assert not traverse(base/'graph',['product:synthetic'],relations=['OWNED_BY'])['edges']


def test_approve_is_scoped_and_verified_edge_requires_both_endpoints(corpus):
    items=load_queue(corpus);proof=next(i for i in items if i['type']=='EvidenceUnit')
    edge=next(i for i in items if i['type']=='OWNED_BY')
    decide(corpus,'product:synthetic')
    assert next(i for i in load_queue(corpus) if i['target_id']=='product:synthetic')['state']=='waiting_for_evidence_review'
    decide(corpus,proof['target_id']);decide(corpus,edge['target_id'])
    assert next(i for i in load_queue(corpus) if i['target_id']==edge['target_id'])['review_status']!='verified'
    decide(corpus,'owner:synthetic')
    graph=traverse(corpus/'data/processed/ocop/graph',['product:synthetic'],verified_only=True,hops=1,relations=['OWNED_BY'])
    assert len(graph['nodes'])==2 and len(graph['edges'])==1
    from ai_core.orchestration.ocop.tools import ToolRegistry
    result=ToolRegistry(corpus).dispatch('search_graph',query='Synthetic product',
        slots={'graph_seed_ids':['product:synthetic']},context={})
    # Explicit ledger decisions, with evidence and endpoints approved, are usable.
    assert result['include_failed'] is False
    assert any(n['node_id']=='owner:synthetic' and n['check']=='human_verified' for n in result['nodes'])
    assert any(e['relation_type']=='OWNED_BY' and e['check']=='human_verified' for e in result['edges'])


def test_correct_preserves_ocr_and_reject_overrides_append_only(corpus):
    proof=next(i for i in load_queue(corpus) if i['type']=='EvidenceUnit')
    decide(corpus,proof['target_id'])
    decide(corpus,'product:synthetic','correct',{'properties':{'points_candidate':3}})
    nodes=[json.loads(s) for s in (corpus/'data/processed/ocop/graph/nodes.jsonl').read_text(encoding='utf-8').splitlines()]
    node=next(n for n in nodes if n['node_id']=='product:synthetic')
    assert node['properties']['points_candidate']==3
    assert node['machine_candidate']['properties']['points_candidate'] is None
    assert node['human_review']['asserted_correction']['properties']['points_candidate']==3
    first=ledger_path(corpus).read_bytes()
    decide(corpus,'product:synthetic','reject')
    assert ledger_path(corpus).read_bytes().startswith(first)
    assert not traverse(corpus/'data/processed/ocop/graph',['product:synthetic'],verified_only=True)['nodes']


def test_stale_hash_blocks_write_and_extraction_change_requires_rereview(corpus):
    item=next(i for i in load_queue(corpus) if i['target_id']=='product:synthetic')
    with pytest.raises(ValueError,match='stale'):
        record_decision(corpus,item['target_id'],'0'*64,'approve','tester')
    decide(corpus,item['target_id'])
    path=corpus/'data/processed/ocop/knowledge/business_entities.jsonl'
    rows=[json.loads(s) for s in path.read_text().splitlines()];rows[0]['label']='Changed extraction'
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    rebuild_reviewed_graph(corpus)
    changed=next(i for i in load_queue(corpus) if i['target_id']==item['target_id'])
    assert changed['state']=='stale_content_needs_review' and changed['review_status']!='verified'


def test_crop_source_sha_and_api_decision_cycle(corpus,monkeypatch):
    from backend.api import ocop_routes
    from backend.api.ocop_main import app
    from fastapi.testclient import TestClient
    monkeypatch.setattr(ocop_routes,'ROOT',corpus)
    monkeypatch.delenv('OCOP_REVIEW_TOKEN',raising=False)
    client=TestClient(app)
    assert client.get('/api/ocop/review/stats').json()['total']==statistics(load_queue(corpus))['total']
    assert client.get('/api/ocop/review/queue?priority=P3').status_code==200
    item=client.get('/api/ocop/review/items/product:synthetic').json()
    image=client.get(item['citations'][0]['crop_url'])
    assert image.status_code==200 and image.content.startswith(b'\x89PNG')
    response=client.post('/api/ocop/review/decisions',json={'target_id':item['target_id'],
        'content_hash':item['content_hash'],'decision':'approve','reviewer':'Synthetic human tester'})
    assert response.status_code==200 and response.json()['review']['verified_nodes']==0
    broken=dict(item);broken['citations']=[dict(item['citations'][0],source_sha256='a'*64)]
    with pytest.raises(ValueError,match='SHA'): render_crop(corpus,broken,0)


def test_queue_priorities_and_explicit_dependencies(corpus):
    from ai_core.graph.ocop.review import priority
    for typ,props in [('ScoreOption',{}),('MINIMUM_FOR',{}),('StarLevel',{}),
                      ('RuleCandidate',{'modality':'temporal'}),('AMENDS',{})]:
        assert priority({'type':typ,'properties':props})[0]=='P1'
    assert priority({'type':'RESPONSIBLE_FOR','properties':{}})[0]=='P2'
    items=load_queue(corpus)
    item=next(i for i in items if i['type']=='OWNED_BY')
    assert {d['type'] for d in item['dependencies']}=={'EvidenceUnit','Product','Organization'}
    assert all(c.get('quote') and c.get('source_sha256') and c.get('crop_path') for c in item['citations'])


def test_review_refuses_old_graph_schema_and_mixed_knowledge(corpus):
    path=corpus/'data/processed/ocop/graph/manifest.json'
    manifest=json.loads(path.read_text());manifest['schema_revision']='old-parser'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='schema changed'):load_queue(corpus)
    rebuild_reviewed_graph(corpus)
    path=corpus/'data/processed/ocop/knowledge/manifest.json'
    manifest=json.loads(path.read_text());manifest['corpus_version']='different'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='versions differ'):load_queue(corpus)


def test_batch_crops_check_sources_once_and_deduplicate(corpus,monkeypatch):
    from ai_core.graph.ocop.review import render_queue_crops
    from ai_core.processing.ocop import pdf_loader
    real=pdf_loader.checked_sources;calls=[]
    def checked(*args):calls.append(1);return real(*args)
    monkeypatch.setattr(pdf_loader,'checked_sources',checked)
    assert render_queue_crops(corpus,load_queue(corpus))==1
    assert len(calls)==1


def test_cli_queue_stats_and_synthetic_decision(corpus,monkeypatch,capsys):
    from tools.cli import main
    def run(*args):
        monkeypatch.setattr('sys.argv',['cli.py','review',*args,'--root',str(corpus)])
        main();return json.loads(capsys.readouterr().out)
    assert run('stats')['total']>0
    exported=run('queue','--render')
    assert exported['unique_crops']==1 and Path(exported['output']).is_file()
    item=next(i for i in load_queue(corpus) if i['target_id']=='product:synthetic')
    result=run('decide','--target-id',item['target_id'],'--content-hash',item['content_hash'],
               '--decision','approve','--reviewer','Synthetic CLI tester')
    assert result['decision']['decision']=='approve' and ledger_path(corpus).is_file()


def test_inspection_regions_raise_priority_without_asserting_values(corpus):
    item=next(i for i in load_queue(corpus) if i['target_id']=='product:synthetic')
    ref=item['citations'][0]
    path=corpus/'data/review/ocop_review_attention_regions.jsonl';path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({k:ref[k] for k in ['source_id','pdf_page','bbox','source_sha256']})+'\n')
    flagged=next(i for i in load_queue(corpus) if i['target_id']==item['target_id'])
    assert flagged['priority']=='P2' and flagged['properties']==item['properties']
    assert flagged['review_status']!='verified' and not ledger_path(corpus).exists()


def test_reextraction_changed_target_id_flags_rereview_without_reusing_approval(corpus):
    decide(corpus,'product:synthetic')
    base=corpus/'data/processed/ocop/knowledge'
    path=base/'business_entities.jsonl'
    rows=[json.loads(s) for s in path.read_text().splitlines()]
    rows[0]['entity_id']='product:reextracted'
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    path=base/'business_relations.jsonl'
    row=json.loads(path.read_text());row['source_entity_id']='product:reextracted'
    path.write_text(json.dumps(row)+'\n')
    rebuild_reviewed_graph(corpus)
    item=next(i for i in load_queue(corpus) if i['target_id']=='product:reextracted')
    assert item['state']=='stale_content_needs_review' and item['review_status']!='verified'
    assert item['latest_decision']['target_id']=='product:synthetic'
