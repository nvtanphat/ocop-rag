"""G1/G2 regression: verified graph provenance, materialization and publish boundaries.

Tests use synthetic in-memory/temporary fixtures. No external service required.
"""
from __future__ import annotations
import json
import sys
import types
from pathlib import Path
import pytest
from ai_core.graph.ocop.builder import build_graph
from ai_core.graph.ocop.integrity import validate_graph_snapshot
from ai_core.graph.ocop.retriever import traverse
from ai_core.graph.ocop.store import publish_neo4j
from ai_core.orchestration.ocop.tools import ToolRegistry


def dump(path, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')


def make_knowledge(tmp_path):
    k=tmp_path/'knowledge';k.mkdir()
    (k/'manifest.json').write_text(json.dumps({'complete':True,'corpus_version':'v6-fixture'}))
    dump(k/'evidence_units.jsonl',[{'unit_id':'u1','source_id':'D1','review_status':'verified',
            'unit_kind':'article','text':'Điều kiện OCOP từ hồ sơ A','spans':[{'pdf_page':3}]}])
    dump(k/'entities.jsonl',[{'entity_id':'doc1','entity_type':'source_document','source_id':'D1',
            'name':'Quy định A','review_status':'verified','evidence_unit_ids':['u1']}])
    dump(k/'relations.jsonl',[])
    return k


def entity(i,kind,*,status='verified', uid='u1'):
    return {'entity_id':i,'kind':kind,'label':i,'source_id':'D1','status':status,
            'evidence':[{'source_id':'D1','evidence_unit_id':uid,'pdf_page':3,'quote':'Điều kiện OCOP'}],
            'attributes':{}}


def rel(*,page=3,uid='u1',status='verified'):
    return {'relation_id':'r1','relation_type':'HAS_RECORD','source_entity_id':'decision',
            'target_entity_id':'record','status':status,
            'evidence':[{'source_id':'D1','evidence_unit_id':uid,'pdf_page':page,'quote':'Điều kiện OCOP'}]}


def test_graph_detects_evidence_text_change_without_id_change(tmp_path):
    k=make_knowledge(tmp_path);g=tmp_path/'graph'
    a=build_graph(k,g)
    rows=[json.loads(line) for line in (k/'evidence_units.jsonl').read_text(encoding='utf-8').splitlines()]
    rows[0]['text']='Điều kiện OCOP đã được hiệu chỉnh';dump(k/'evidence_units.jsonl',rows)
    b=build_graph(k,g)
    assert a['graph_version']!=b['graph_version']
    assert (g/'snapshots'/a['graph_version']/'manifest.json').exists()
    assert (g/'snapshots'/b['graph_version']/'manifest.json').exists()
    assert validate_graph_snapshot(g)['graph_version']==b['graph_version']
    assert validate_graph_snapshot(g/'snapshots'/a['graph_version'])['graph_version']==a['graph_version']


def test_graph_rejects_unsupported_verified_source_entity(tmp_path):
    k=make_knowledge(tmp_path)
    dump(k/'entities.jsonl',[{'entity_id':'fake','entity_type':'article','source_id':'D1',
                               'name':'Wrong evidence', 'review_status':'verified',
                               'evidence_unit_ids':['nonexistent']}])
    out=tmp_path/'out';manifest=build_graph(k,out)
    assert manifest['counts']['rejected']>=1
    assert not any(row['node_id']=='fake' for row in
                   map(json.loads,(out/'nodes.jsonl').read_text().splitlines()))


def test_verified_business_entity_rejected_if_evidence_not_verified(tmp_path):
    k=make_knowledge(tmp_path)
    dump(k/'evidence_units.jsonl',[{'unit_id':'u1','source_id':'D1','review_status':'needs_review',
                                    'unit_kind':'article','text':'OCR chưa xác minh','spans':[{'pdf_page':3}]}])
    dump(k/'business_entities.jsonl',[entity('product','Product')])
    out=tmp_path/'out'; build_graph(k,out)
    assert not any(x['node_id']=='product' for x in
                   map(json.loads,(out/'nodes.jsonl').read_text().splitlines()))


def test_business_relation_proof_page_must_match(tmp_path):
    k=make_knowledge(tmp_path)
    dump(k/'business_entities.jsonl',[entity('decision','RecognitionDecision'),
                                      entity('record','RecognitionRecord')])
    dump(k/'business_relations.jsonl',[rel(page=20)])
    out=tmp_path/'out';build_graph(k,out)
    assert not any(x['relation_type']=='HAS_RECORD' for x in
                   map(json.loads,(out/'edges.jsonl').read_text().splitlines()))


def test_valid_business_relation_is_preserved_and_provenance_verified(tmp_path):
    k=make_knowledge(tmp_path)
    dump(k/'business_entities.jsonl',[entity('decision','RecognitionDecision'),
                                      entity('record','RecognitionRecord')])
    dump(k/'business_relations.jsonl',[rel()])
    out=tmp_path/'out';build_graph(k,out)
    result=traverse(out,['decision'],hops=1,relations=['HAS_RECORD'],verified_only=True,direction='out')
    assert 'record' in {n['node_id'] for n in result['nodes']}
    assert result['edges'][0]['evidence_unit_id']=='u1'


def test_graph_refuses_tampering_after_build(tmp_path):
    k=make_knowledge(tmp_path);g=tmp_path/'graph';build_graph(k,g)
    with (g/'edges.jsonl').open('a') as stream:stream.write('\\n')
    with pytest.raises(ValueError,match='integrity mismatch'):
        traverse(g,['doc1'],hops=0)
    with pytest.raises(ValueError,match='integrity mismatch'):
        publish_neo4j(g,password='unused')  # must reject before importing/connecting


def test_graph_tool_declines_inconsistent_index_version(tmp_path):
    root=tmp_path/'root';k=make_knowledge(tmp_path)
    g=root/'data/processed/ocop/graph';build_graph(k,g)
    idx=root/'data/processed/ocop/index';idx.mkdir(parents=True)
    (idx/'manifest.json').write_text(json.dumps({'corpus_version':'different-index'}))
    resp=ToolRegistry(root).dispatch('search_graph',query='OCOP',slots={'graph_seed_ids':['doc1']})
    assert resp['status']=='graph_index_version_mismatch'
    assert resp['results']==[]


def test_graph_tool_fails_closed_on_tampering(tmp_path):
    root=tmp_path/'root';k=make_knowledge(tmp_path)
    g=root/'data/processed/ocop/graph';build_graph(k,g)
    (g/'nodes.jsonl').write_text('malicious/partial content')
    resp=ToolRegistry(root).dispatch('search_graph',query='OCOP',slots={'graph_seed_ids':['doc1']})
    assert resp['status']=='graph_integrity_failed' and resp['results']==[]


class FakeCursor:
    def consume(self): return None

class FakeTx:
    def __init__(self,fail_on_edge=False): self.calls=[];self.fail_on_edge=fail_on_edge
    def run(self,query,**params):
        if self.fail_on_edge and 'MERGE (a)-[r:' in query:
            raise RuntimeError('simulated remote writer failure')
        self.calls.append((query,params))
        return FakeCursor()

class FakeSession:
    def __init__(self,fail_on_edge=False):
        self.tx=FakeTx(fail_on_edge);self.setup=[];self.executed=0
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def run(self,query,**params):self.setup.append(query);return FakeCursor()
    def execute_write(self,callback):self.executed+=1;return callback(self.tx)

class FakeDriver:
    def __init__(self,session):self._session=session;self.closed=False
    def session(self,**kwargs):return self._session
    def close(self):self.closed=True


def fake_backend(monkeypatch,*,fail_on_edge=False):
    session=FakeSession(fail_on_edge);driver=FakeDriver(session)
    fake_module=types.SimpleNamespace(GraphDatabase=types.SimpleNamespace(driver=lambda *a,**kw:driver))
    monkeypatch.setitem(sys.modules,'neo4j',fake_module)
    return session,driver


def test_neo4j_publication_is_one_snapshot_transaction(monkeypatch,tmp_path):
    k=make_knowledge(tmp_path);g=tmp_path/'graph'
    dump(k/'business_entities.jsonl',[entity('decision','RecognitionDecision'),
                                       entity('record','RecognitionRecord')])
    dump(k/'business_relations.jsonl',[rel()]);manifest=build_graph(k,g)
    session,driver=fake_backend(monkeypatch)
    outcome=publish_neo4j(g,password='unused',verified_only=True,batch_size=1)
    assert outcome['graph_version']==manifest['graph_version']
    assert outcome['snapshot_id'].endswith(':verified')
    assert session.executed==1 and driver.closed
    txcalls=session.tx.calls
    assert any('MERGE (a)-[r:HAS_RECORD' in q for q,_ in txcalls)
    assert all('snapshot_id:$snapshot_id' in q for q,_ in txcalls[:-1])
    assert 'OcopGraphActive' in txcalls[-1][0]  # active pointer updated LAST
    assert all(v['snapshot_id']==outcome['snapshot_id'] for _,v in txcalls)


def test_neo4j_publication_failure_does_not_switch_active(monkeypatch,tmp_path):
    k=make_knowledge(tmp_path);g=tmp_path/'graph'
    dump(k/'business_entities.jsonl',[entity('decision','RecognitionDecision'),
                                       entity('record','RecognitionRecord')])
    dump(k/'business_relations.jsonl',[rel()]);build_graph(k,g)
    session,driver=fake_backend(monkeypatch,fail_on_edge=True)
    with pytest.raises(RuntimeError,match='simulated remote writer failure'):
        publish_neo4j(g,password='unused')
    assert session.executed==1 and driver.closed
    assert all('OcopGraphActive' not in q for q,_ in session.tx.calls)
