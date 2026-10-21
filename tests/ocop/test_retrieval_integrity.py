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


def test_reranker_candidate_depth_not_limited_to_3x_target_count(tmp_path,monkeypatch):
    rows=[_row(f'item_{i:02}',f'ho so thang diem {i}') for i in range(20)]
    idx=_index(tmp_path/'idx',rows)
    seen=[]
    def oracle_rerank(query, candidates, model_id, revision=None, **kwargs):
        seen.extend(r['chunk_id'] for r in candidates)
        return sorted(candidates,key=lambda r:r['chunk_id']=='item_19',reverse=True)
    monkeypatch.setattr(module,'_rerank',oracle_rerank)
    module.search(idx,'ho so thang diem',top_k=1,rerank=True,rerank_candidates=20)
    assert len(seen)>=20, 'The reranker pool is the configured depth, not a fixed multiple of top_k'
    seen.clear()
    module.search(idx,'ho so thang diem',top_k=1,rerank=True)
    assert len(seen)==module.get_settings().retrieval.rerank_candidates


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


def test_reranker_truncates_oversized_pair_explicitly_and_flags_it(monkeypatch):
    class MockTokenizer:
        def __call__(self, q, doc, **kwargs):
            return {'input_ids': list(range(1500))}  # 1500 tokens > 1024 budget
    class MockModel:
        tokenizer = MockTokenizer()
        max_length = None
        def predict(self, pairs, **kwargs):
            return [0.9] * len(pairs)

    model = MockModel()
    module._load_reranker.cache_clear()
    monkeypatch.setattr(module, '_load_reranker', lambda *a, **kw: model)
    candidates = [{'chunk_id': 'c1', 'text': 'đoạn văn bản OCOP dài'}]
    out = module._rerank('câu hỏi', candidates, 'BAAI/bge-reranker-v2-m3', pair_token_budget=1024)
    assert out[0]['rerank_input_truncated'] is True and model.max_length == 1024
    assert out[0]['reranker_score'] == 0.9


def test_reranker_scores_are_cached_per_query_and_passage(monkeypatch):
    calls = []

    class MockModel:
        tokenizer = None
        max_length = None
        def predict(self, pairs, **kwargs):
            calls.append(len(pairs))
            return [0.5] * len(pairs)

    module._RERANK_CACHE.clear()
    monkeypatch.setattr(module, '_load_reranker', lambda *a, **kw: MockModel())
    for _ in range(2):
        module._rerank('cùng câu hỏi', [{'chunk_id': 'c9', 'text': 'cùng đoạn'}], 'm', 'r')
    assert calls == [1]


def test_dense_failure_of_any_kind_falls_back_to_sparse_with_reason(tmp_path, monkeypatch):
    idx = _index(tmp_path / 'idx', [_row('alpha', 'tiêu chí đánh giá OCOP')])
    manifest = json.loads((idx / 'manifest.json').read_text(encoding='utf-8'))
    manifest['dense'] = {'enabled': True, 'model_id': 'x', 'dimension': 3, 'collection': 'c', 'host': 'h', 'port': 1}
    (idx / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    class QdrantDown(Exception):
        pass

    def boom(*a, **kw):
        raise QdrantDown('connection refused')
    monkeypatch.setattr(module, '_dense_hits', boom)
    rows = module.search(idx, 'tiêu chí', mode='hybrid')
    assert rows and rows[0]['retrieval_mode'] == 'sparse'
    assert rows[0]['retrieval_fallback_reason'] == 'dense_unavailable:QdrantDown'


def test_resolve_local_model_path(tmp_path):
    from ai_core.retrieval.ocop.models_config import resolve_local_model_path
    dummy_dir = tmp_path / "models" / "my-fake-test-model"
    dummy_dir.mkdir(parents=True)
    res_path, is_local = resolve_local_model_path("org/my-fake-test-model", root=tmp_path)
    assert is_local is True
    assert res_path == str(dummy_dir)

    res_path_none, is_local_none = resolve_local_model_path("nonexistent/model", root=tmp_path)
    assert is_local_none is False
    assert res_path_none == "nonexistent/model"




def test_dense_query_is_counted_with_real_tokenizer_and_cut_explicitly():
    class Tok:
        def __call__(self, text, **kwargs):
            return {'input_ids': list(range(len(text.split())))}

    class Model:
        tokenizer = Tok()
        max_seq_length = 10

    query, meta = module._fit_query(Model(), ' '.join(f'w{i}' for i in range(40)))
    assert meta['query_truncated'] is True and meta['query_tokens'] <= 10
    query, meta = module._fit_query(Model(), 'ngắn gọn thôi')
    assert meta['query_truncated'] is False and query == 'ngắn gọn thôi'
