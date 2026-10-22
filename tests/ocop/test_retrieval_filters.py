"""retrieval integrity, provenance and multi-stage evaluation: synthetic fixtures.

No weights or external Qdrant service are needed for these contract tests.
"""
import json
from types import SimpleNamespace

import pytest

from ai_core.retrieval.ocop.index_pipeline import create_bm25
from ai_core.retrieval.ocop.search import search
from ai_core.evaluation.ocop.harness import evaluate_retrieval


def row(i, text, source='A', status='verified', version='v7'):
    return {'chunk_id':i,'evidence_unit_id':i,'source_id':source,
            'spans':[{'pdf_page':1}],'review_status':status,
            'corpus_version':version,'text_for_bm25':text,'raw_text':text}


def index(root, rows):
    root.mkdir(parents=True,exist_ok=True)
    (root/'chunks.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    info=create_bm25(rows,root/'bm25.json.gz')
    (root/'manifest.json').write_text(json.dumps({'corpus_version':'v7',
        'counts':{'chunks':len(rows)},'bm25':info,'dense':{'enabled':False}}))
    return root


def rewrite_rows(root, rows):
    (root/'chunks.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')


def test_fails_closed_if_chunk_content_changes_but_ids_same(tmp_path):
    idx=index(tmp_path/'i',[row('a','tiêu chí'),row('b','đánh giá')])
    rewrite_rows(idx,[row('a','sai tiêu chí'),row('b','đánh giá')])
    with pytest.raises(RuntimeError,match='mismatch'):
        search(idx,'tiêu chí')


def test_fails_closed_if_review_status_mutated(tmp_path):
    idx=index(tmp_path/'i',[row('a','tiêu chí')])
    rewrite_rows(idx,[row('a','tiêu chí',status='needs_review')])
    with pytest.raises(RuntimeError,match='mismatch'):
        search(idx,'tiêu chí',include_needs_review=False)


def test_fails_closed_on_duplicate_chunk_id(tmp_path):
    idx=index(tmp_path/'i',[row('a','first'),row('b','second')])
    rewrite_rows(idx,[row('a','first'),row('a','second')])
    with pytest.raises(RuntimeError,match='duplicate'):
        search(idx,'first')


def test_fails_closed_on_chunk_version_drift(tmp_path):
    idx=index(tmp_path/'i',[row('a','first',version='old')])
    with pytest.raises(RuntimeError,match='version'):
        search(idx,'first')


def test_fails_closed_if_manifest_hash_tampered(tmp_path):
    idx=index(tmp_path/'i',[row('a','first')]); m=json.loads((idx/'manifest.json').read_text())
    m['bm25']['records_hash']='00'*32
    (idx/'manifest.json').write_text(json.dumps(m))
    with pytest.raises(RuntimeError,match='manifest records hash'):
        search(idx,'first')


def test_accented_unaccented_and_d_stroke_both_retrieve(tmp_path):
    idx=index(tmp_path/'i',[row('a','Điều kiện và tiêu chí OCOP')])
    assert search(idx,'dieu kien tieu chi',mode='sparse')[0]['chunk_id']=='a'
    assert search(idx,'Điều kiện tiêu chí',mode='sparse')[0]['chunk_id']=='a'


def test_exact_accented_hits_rank_above_only_folded_matches(tmp_path):
    idx=index(tmp_path/'i',[row('a','ma'),row('b','má')])
    assert search(idx,'má',mode='sparse')[0]['chunk_id']=='b'


def test_scope_applies_before_sparse_top_k(tmp_path):
    rows=[row(f'no{i}','thang diem',status='needs_review') for i in range(80)]
    rows.append(row('yes','thang diem',source='X',status='verified'))
    idx=index(tmp_path/'i',rows)
    hits=search(idx,'thang diem',top_k=1,source_id='X',include_needs_review=False)
    assert [h['chunk_id'] for h in hits]==['yes']


def test_candidate_pool_parameter_validated(tmp_path):
    idx=index(tmp_path/'i',[row('a','tiêu chí')])
    with pytest.raises(ValueError,match='rerank_candidates'):search(idx,'tiêu chí',rerank_candidates=0)
    with pytest.raises(ValueError,match='rerank_candidates'):search(idx,'tiêu chí',rerank_candidates=201)


def test_bm25_records_hash_reproducible(tmp_path):
    rows=[row('a','tiêu chí'),row('b','điều kiện')]
    info=create_bm25(rows,tmp_path/'i.gz'); first=(tmp_path/'i.gz').read_bytes()
    assert create_bm25(rows,tmp_path/'i.gz')==info
    assert first==(tmp_path/'i.gz').read_bytes()


def test_harness_rerank_comparison_and_latency_metrics(tmp_path):
    idx=tmp_path/'data/processed/ocop/index';idx.mkdir(parents=True)
    (idx/'manifest.json').write_text(json.dumps({'corpus_version':'v7','dense':{'enabled':False}}))
    data=tmp_path/'gold.jsonl'
    data.write_text(json.dumps({'case_id':'1','query':'tieu chi','source_id':'A',
                                'label_status':'pdf_page_confirmed','pdf_page':1})+'\n')
    seen=[]
    def runner(_idx,query,**kwargs):
        seen.append(kwargs)
        return [{'source_id':'A','pdf_page':1}]
    report=evaluate_retrieval(tmp_path,data,modes=('sparse','sparse_rerank','hybrid_rerank'),runner=runner)
    assert [r.get('rerank',False) for r in seen]==[False,True]
    assert report['results']['sparse_rerank']['recall_at_10']==1.0
    assert report['results']['sparse_rerank']['p95_latency_ms']>=0
    assert report['results']['sparse_rerank']['error_count']==0
    assert report['results']['hybrid_rerank']['status']=='not_run_missing_dense_index'


def test_graph_and_retrieval_share_knowledge_version_not_derived_index_hash(tmp_path):
    from ai_core.graph.ocop.builder import build_graph
    from ai_core.orchestration.ocop.tools import ToolRegistry
    root=tmp_path/'project'
    know=tmp_path/'knowledge';know.mkdir()
    (know/'manifest.json').write_text(json.dumps({'complete':True,'corpus_version':'knowledge-A'}))
    unit={'unit_id':'unit1','source_id':'DOC','review_status':'verified','unit_kind':'article',
          'text':'Thông tin OCOP nguồn hợp lệ','spans':[{'pdf_page':1,'bbox':[0,0,100,20],
                                                        'block_id':'native:0:0','source_sha256':'a'*64}]}
    (know/'evidence_units.jsonl').write_text(json.dumps(unit)+'\n')
    (know/'entities.jsonl').write_text(json.dumps({'entity_id':'doc1','entity_type':'source_document',
         'source_id':'DOC','name':'Đăng ký','review_status':'verified','evidence_unit_ids':['unit1']})+'\n')
    (know/'relations.jsonl').write_text('')
    graph=root/'data/processed/ocop/graph';build_graph(know,graph)
    idx=root/'data/processed/ocop/index';index(idx,[row('cid','Thông tin OCOP',source='DOC')])
    manifest=json.loads((idx/'manifest.json').read_text())
    manifest['corpus_version']='derived-index-fingerprint'
    manifest['source_knowledge_version']='knowledge-A'
    (idx/'manifest.json').write_text(json.dumps(manifest))
    result=ToolRegistry(root).dispatch('search_graph',query='OCOP',slots={'graph_seed_ids':['doc1']})
    assert result.get('status')!='graph_index_version_mismatch'
    manifest['source_knowledge_version']='wrong-knowledge'
    (idx/'manifest.json').write_text(json.dumps(manifest))
    result=ToolRegistry(root).dispatch('search_graph',query='OCOP',slots={'graph_seed_ids':['doc1']})
    assert result['status']=='graph_index_version_mismatch'


def test_qdrant_dense_build_creates_keyword_payload_indexes_first(monkeypatch):
    import sys
    import numpy as np
    from ai_core.retrieval.ocop import index_pipeline as ip
    events=[]
    class FakeQdrant:
        def __init__(self, **kwargs): pass
        def get_collections(self):return SimpleNamespace(collections=[])
        def create_collection(self,**kwargs):events.append(('create_collection',kwargs))
        def create_payload_index(self,**kwargs):events.append(('create_payload_index',kwargs))
        def upsert(self,**kwargs):events.append(('upsert',kwargs))
        def count(self,**kwargs):return SimpleNamespace(count=1)
    class FakeModel:
        max_seq_length=512
        def tokenizer(self,text,**kwargs):return {'input_ids':[1,2,3]}
    class VectorParams:
        def __init__(self,**kwargs):pass
    class PointStruct:
        def __init__(self,**kwargs): self.kwargs=kwargs
    models=SimpleNamespace(VectorParams=VectorParams,Distance=SimpleNamespace(COSINE='Cosine'),
                 PayloadSchemaType=SimpleNamespace(KEYWORD='keyword'),PointStruct=PointStruct)
    monkeypatch.setitem(sys.modules,'qdrant_client',SimpleNamespace(QdrantClient=FakeQdrant,models=models))
    monkeypatch.setattr(ip,'_load_embedding',lambda *_:FakeModel())
    monkeypatch.setattr(ip,'_encode',lambda model,texts,is_query:np.ones((len(texts),3)))
    data=[{**row('a','Điều kiện OCOP'),'text_for_embedding':'Điều kiện OCOP','over_budget':False}]
    result=ip.build_dense(data,collection='test_dense',model_id='fake')
    assert result['points']==1
    assert [item[1]['field_name'] for item in events if item[0]=='create_payload_index']==[
        'source_id','review_status','corpus_version','evidence_unit_id']
    assert [name for name,_ in events].index('create_payload_index') < [name for name,_ in events].index('upsert')


def test_qdrant_scoped_search_filters_all_constraints(monkeypatch):
    import sys
    import numpy as np
    from ai_core.retrieval.ocop import search as module
    collected=[]
    class Filter:
        def __init__(self,must):self.must=must
    class FieldCondition:
        def __init__(self,key,match):self.key,self.match=key,match
    class MatchValue:
        def __init__(self,value):self.value=value
    class QdrantClient:
        def __init__(self,**kwargs):pass
        def query_points(self,**kwargs):
            collected.append(kwargs)
            return SimpleNamespace(points=[SimpleNamespace(payload={'chunk_id':'yes'},score=0.95)])
    models=SimpleNamespace(Filter=Filter,FieldCondition=FieldCondition,MatchValue=MatchValue)
    monkeypatch.setitem(sys.modules,'qdrant_client',SimpleNamespace(QdrantClient=QdrantClient,models=models))
    monkeypatch.setattr(module,'_load_embedding',lambda *_:object())
    monkeypatch.setattr(module,'_encode',lambda *_:np.array([[0.1,0.2,0.3]]))
    manifest={'corpus_version':'v7','dense':{'enabled':True,'dimension':3,'model_id':'mock',
             'collection':'mock','host':'localhost','port':6333}}
    result,meta=module._dense_hits('OCOP',manifest,5,source_id='DOC',include_needs_review=False)
    assert result==[('yes',0.95)] and meta['query_truncated'] is False
    constraints={x.key:x.match.value for x in collected[0]['query_filter'].must}
    assert constraints=={'source_id':'DOC','review_status':'verified','corpus_version':'v7'}
