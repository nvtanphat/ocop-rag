"""Independent RED regression suite: retrieval audit, no production changes.
Run from project root: pytest -q /path/to/test_ocop_retrieval_v5_independent.py
Five failed tests represent desired safeguards/features; one control should pass.
"""
from __future__ import annotations
import json
import sys
from types import SimpleNamespace
import numpy as np
import pytest
from ai_core.retrieval.ocop import search as module
from ai_core.retrieval.ocop.index_pipeline import create_bm25


def _row(cid, text, *, review='verified', parent=None, source='VN.TEST'):
    return dict(chunk_id=cid,evidence_unit_id=parent or cid,source_id=source,
        spans=[{'pdf_page':1}], review_status=review, corpus_version='fixture',
        text_for_bm25=text, raw_text=text)


def _index(root, rows, *, dense=False):
    root.mkdir(parents=True, exist_ok=True)
    with (root/'chunks.jsonl').open('w',encoding='utf-8') as f:
        for row in rows: f.write(json.dumps(row,ensure_ascii=False)+'\n')
    create_bm25(rows, root/'bm25.json.gz')
    (root/'manifest.json').write_text(json.dumps({'corpus_version':'fixture',
        'dense':{'enabled':dense,'model_id':'fake','dimension':3,'host':'127.0.0.1',
                 'port':6333,'collection':'fake'}}),encoding='utf-8')
    return root


def test_control_fresh_sparse_index_returns_matching_source(tmp_path):
    idx=_index(tmp_path/'idx', [_row('alpha','thang diem nhat'), _row('beta','giay chung nhan')])
    rows=module.search(idx,'thang',top_k=1)
    assert rows and rows[0]['chunk_id']=='alpha'


def test_reject_stale_posting_chunk_mismatch_instead_of_wrong_source(tmp_path):
    idx=_index(tmp_path/'idx', [_row('alpha','foo_unique'),_row('beta','bar_unique')])
    # Deployment race / partial rebuild: chunk rows reorder, BM25 postings unchanged.
    with (idx/'chunks.jsonl').open('w',encoding='utf-8') as f:
        for row in [_row('beta','bar_unique'),_row('alpha','foo_unique')]:
            f.write(json.dumps(row)+'\n')
    with pytest.raises((RuntimeError,ValueError), match='[Cc]orpus|[Ii]ndex|[Mm]ismatch'):
        module.search(idx,'foo_unique',top_k=1)


def test_verified_only_dense_pushes_review_filter_into_vector_backend(tmp_path,monkeypatch):
    rows=[_row(f'bad_{i}', 'quy dinh',review='needs_review') for i in range(45)]
    rows.append(_row('verified_46','quy dinh',review='verified'))
    idx=_index(tmp_path/'idx',rows,dense=True)
    class FakePoints:
        def __init__(self,pts):self.points=pts
    class FakeQdrant:
        def __init__(self,**kwargs):pass
        def query_points(self,**kwargs):
            flt=kwargs.get('query_filter')
            # Emulate Qdrant where review_status filter would apply BEFORE top-K.
            wants_verified = ('verified' in str(flt)) if flt is not None else False
            pool=[rows[-1]] if wants_verified else rows
            return FakePoints([SimpleNamespace(payload={'chunk_id':r['chunk_id']},score=1.0)
                               for r in pool[:kwargs['limit']]])
    class Filter:
        def __init__(self, must): self.must=must
        def __repr__(self): return repr(self.must)
    class FieldCondition:
        def __init__(self,key,match):self.key,self.match=key,match
        def __repr__(self):return f'{self.key}:{self.match}'
    class MatchValue:
        def __init__(self,value):self.value=value
        def __repr__(self):return repr(self.value)
    fake_models=SimpleNamespace(Filter=Filter,FieldCondition=FieldCondition,MatchValue=MatchValue)
    monkeypatch.setitem(sys.modules,'qdrant_client',SimpleNamespace(QdrantClient=FakeQdrant,models=fake_models))
    monkeypatch.setattr(module,'_load_embedding',lambda *_:object())
    monkeypatch.setattr(module,'_encode',lambda *_:np.array([[1.0,0.0,0.0]]))
    found=module.search(idx,'quy dinh',mode='dense',top_k=1,include_needs_review=False)
    assert found and found[0]['chunk_id']=='verified_46'


def test_vietnamese_unaccented_query_recovers_accented_document(tmp_path):
    idx=_index(tmp_path/'idx', [_row('criterion','tiêu chí đánh giá sản phẩm OCOP'),
                                  _row('other','quyết định công nhận sản phẩm')])
    assert any(r['chunk_id']=='criterion' for r in module.search(idx,'tieu chi',mode='sparse'))


def test_reranker_candidate_depth_not_limited_to_3x_final_k(tmp_path,monkeypatch):
    rows=[_row(f'item_{i:02}',f'ho so thang diem {i}') for i in range(20)]
    idx=_index(tmp_path/'idx',rows)
    seen=[]
    def oracle_rerank(query, candidates, model_id, revision=None):
        seen.extend(r['chunk_id'] for r in candidates)
        return sorted(candidates,key=lambda r:r['chunk_id']=='item_19',reverse=True)
    monkeypatch.setattr(module,'_rerank',oracle_rerank)
    module.search(idx,'ho so thang diem',top_k=1,rerank=True)
    assert len(seen)>=20, 'A fixed 3x pool makes reranker miss relevant candidates'


def test_unpinned_reranker_does_not_enable_remote_code(tmp_path,monkeypatch):
    options={}
    def fake_crossencoder(model,**kwargs):
        options.update(kwargs)
        return object()
    monkeypatch.setitem(sys.modules,'sentence_transformers',SimpleNamespace(CrossEncoder=fake_crossencoder))
    module._load_reranker.cache_clear()
    module._load_reranker('example/some-reranker',None)
    assert options.get('trust_remote_code') is False


def test_reranker_reports_explicit_rerank_unavailable_when_model_load_fails(tmp_path, monkeypatch):
    idx = _index(tmp_path / 'idx', [_row('alpha', 'tiêu chí đánh giá OCOP')])
    module._load_reranker.cache_clear()
    def fail_load(*args, **kwargs):
        raise ValueError("Model unavailable offline")
    monkeypatch.setattr(module, '_load_reranker', fail_load)
    
    hits = module.search(idx, 'tiêu chí', rerank=True)
    assert len(hits) == 1
    assert hits[0].get('rerank_unavailable') is True
    assert 'rerank_unavailable' in hits[0]['ranking_reason']
    assert 'Model unavailable offline' in hits[0]['ranking_reason']


def test_reranker_forbids_silent_truncation_when_pair_budget_exceeded(monkeypatch):
    class MockTokenizer:
        def __call__(self, q, doc, **kwargs):
            return {'input_ids': list(range(1500))}  # 1500 tokens > 1024 budget
    class MockModel:
        tokenizer = MockTokenizer()
        def predict(self, pairs, **kwargs):
            return [0.9] * len(pairs)
            
    module._load_reranker.cache_clear()
    monkeypatch.setattr(module, '_load_reranker', lambda *a, **kw: MockModel())
    
    candidates = [{'chunk_id': 'c1', 'text': 'đoạn văn bản OCOP dài'}]
    with pytest.raises(RuntimeError, match='pair_token_budget'):
        module._rerank('câu hỏi', candidates, 'BAAI/bge-reranker-v2-m3', pair_token_budget=1024)
