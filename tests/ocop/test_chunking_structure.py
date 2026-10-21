"""Adversarial, offline tests for context-preserving OCOP legal/table chunking."""
from __future__ import annotations
import json
import pytest
from ai_core.processing.ocop.knowledge_extract import page_units
from ai_core.retrieval.ocop.index_pipeline import split_units, build_chunks, build_index
from ai_core.retrieval.ocop.search import search


def make_unit(text, *, kind='article', structured=None, cells=None, page=7):
    structure=structured or {}
    if cells is not None:
        structure={**structure,'table_id':'test:table:1','cells':cells}
    return {'unit_id':'test-unit','source_id':'VN.TEST.QD26.2026','unit_kind':kind,'text':text,
            'spans':[{'pdf_page':page,'table_id':'test:table:1' if cells is not None else None}],
            'structured':structure,'hierarchy_path':['VN.TEST.QD26.2026',str(page),kind,'0'],
            'review_status':'needs_review'}


def test_heading_survives_each_legal_child():
    text='Điều 5. Tiêu chí OCOP\n' + ' '.join('Quy định về hồ sơ, yêu cầu chất lượng sản phẩm.' for _ in range(72))
    unit=make_unit(text,structured={'heading':'Điều 5. Tiêu chí OCOP'})
    parts=split_units(unit,max_words=45,overlap=3)
    assert len(parts)>5
    assert all('Điều 5. Tiêu chí OCOP' in p for p in parts)
    assert 'yêu cầu chất lượng sản phẩm.' in parts[-1]


def test_table_every_chunk_repeats_original_column_headers():
    content='Tên tiêu chí | Điểm tối đa\n'+'\n'.join(f'Tiêu chí {i} | {i%5}' for i in range(31))
    unit=make_unit(content,kind='criterion_table_candidate')
    parts=split_units(unit,max_words=40,overlap=4)
    assert len(parts)>1
    assert all('Tên tiêu chí | Điểm tối đa' in part for part in parts)
    assert all(sum(f'Tiêu chí {i} | {i%5}' in p for p in parts)==1 for i in range(31))


def test_oversized_table_row_keeps_score_together_and_marks_status():
    long_description=' '.join('mô-tả-chi-tiết' for _ in range(130))
    text='Tên tiêu chí | Điểm tối đa\n'+f'{long_description} | 5'
    unit=make_unit(text,kind='table')
    chunks=build_chunks([unit],'test',max_words=35,overlap=5)
    assert len(chunks)==1
    assert f'{long_description} | 5' in chunks[0]['text_for_bm25']
    assert chunks[0]['over_budget'] is True


def test_real_table_cells_keep_column_binding_and_cell_provenance():
    table={'table_id':'table:0','bbox':[0,20,300,240],'cells':[
        {'row':0,'col':0,'text':'Tên tiêu chí','is_header':True,'bbox':[0,20,200,50]},
        {'row':0,'col':1,'text':'Điểm tối đa','is_header':True,'bbox':[200,20,300,50]},
        {'row':1,'col':0,'text':'Nguồn gốc địa phương','bbox':[0,50,200,90]},
        {'row':1,'col':1,'text':'5','bbox':[200,50,300,90]},
    ]}
    pg={'source_id':'VN.TEST.QD26.2026','pdf_page':7,'extracted_text':'','tables':[table],
        'review_status':'needs_review'}
    unit=next(u for u in page_units(pg,source_kind='ocop_framework') if u['unit_kind']=='criterion_table_candidate')
    chunks=build_chunks([unit],'v5',max_words=35)
    assert chunks
    row_chunk=next(c for c in chunks if 'Nguồn gốc địa phương' in c['raw_text'])
    assert 'Điểm tối đa: 5' in row_chunk['text_for_bm25']
    assert row_chunk['row_ids']==[1]
    assert any(s.get('cell_id') and 'r1:c1' in s['cell_id'] and s['bbox']==[200.,50.,300.,90.] for s in row_chunk['spans'])
    assert all(s['pdf_page']==7 for s in row_chunk['spans'])


def test_source_context_is_grounded_not_fabricated():
    unit=make_unit('Điều 3. Điều kiện thành lập hồ sơ OCOP',structured={'heading':'Điều 3. Điều kiện thành lập hồ sơ OCOP'})
    meta={'VN.TEST.QD26.2026':{'document_number':'26/2026/QĐ-TTg','jurisdiction':'Việt Nam','metadata_review':'pending'}}
    chunk=build_chunks([unit],'version',source_metadata=meta)[0]
    assert '26/2026/QĐ-TTg' in chunk['text_for_embedding']
    assert 'Việt Nam' in chunk['text_for_embedding']
    assert chunk['context']['metadata_review']=='pending'
    assert chunk['raw_text'] in unit['text']
    assert chunk['evidence_unit_id']==unit['unit_id']


def test_token_budget_handles_long_vietnamese_string_without_dropping_data():
    unit=make_unit('Điều 2. Danh mục\n'+'điều_kiện_sản_phẩm_ocab '*160,structured={'heading':'Điều 2. Danh mục'})
    chunks=build_chunks([unit],'v5',max_words=200,token_budget=160)
    assert len(chunks)>1
    assert all(c['estimated_tokens']<=160 or c['over_budget'] for c in chunks)
    assert all('Điều 2. Danh mục' in c['text_for_bm25'] for c in chunks)
    assert 'điều_kiện_sản_phẩm_ocab' in chunks[-1]['raw_text']


def test_chunk_ids_and_source_offsets_stable_across_builds():
    unit=make_unit('Điều 6. Chất lượng\n' + '\n'.join(f'Mục {i}. Quy định hợp lệ.' for i in range(50)))
    first=build_chunks([unit],'v5',max_words=35,overlap=3)
    second=build_chunks([unit],'v5',max_words=35,overlap=3)
    assert first==second
    assert [c['chunk_id'] for c in first]==[c['chunk_id'] for c in second]
    assert all(c['char_start'] is not None and c['char_end'] is not None for c in first)
    assert all(unit['text'][c['char_start']:c['char_end']]==c['raw_text'] for c in first)


def test_search_expands_parent_context_with_source_guard(tmp_path):
    kb=tmp_path/'kb';kb.mkdir()
    unit=make_unit('Điều 7. Hồ sơ OCOP\n'+' '.join('Thành phần hồ sơ đầy đủ.' for _ in range(45)))
    (kb/'evidence_units.jsonl').write_text(json.dumps(unit,ensure_ascii=False)+'\n',encoding='utf-8')
    (kb/'manifest.json').write_text(json.dumps({'complete':True,'corpus_version':'knowledge-fixture','counts':{'pages':1}}),encoding='utf-8')
    idx=tmp_path/'index';build_index(knowledge=kb,index_dir=idx,max_words=40)
    rows=search(idx,'Thành phần hồ sơ',top_k=1,expand_parent=True,parent_max_chars=500)
    assert rows and len(rows[0]['parent_context'])<=500
    assert rows[0]['parent_evidence_unit_id']==unit['unit_id']
    assert rows[0]['source_id']==unit['source_id']
    assert rows[0]['parent_source_spans'][0]['pdf_page']==7
    assert search(idx,'Thành phần hồ sơ',source_id='another',expand_parent=True)==[]


def test_invalid_token_budget_rejected():
    with pytest.raises(ValueError):
        build_chunks([make_unit('Điều 1. Kiểm tra')],'v5',token_budget=10)


def test_leading_whitespace_does_not_shift_provenance_offsets():
    unit=make_unit('  \nĐiều 8. Nội dung\n'+' Trách nhiệm chủ thể. '*50,
                   structured={'heading':'Điều 8. Nội dung'})
    chunks=build_chunks([unit],'v5',max_words=34)
    assert all(unit['text'][c['char_start']:c['char_end']]==c['raw_text'] for c in chunks)


def test_no_header_table_does_not_drop_first_data_row():
    unit=make_unit('Hợp tác xã A | 3\nHợp tác xã B | 4',kind='table')
    chunks=build_chunks([unit],'v5',max_words=35)
    assert any(0 in c['row_ids'] and 'Hợp tác xã A | 3' in c['raw_text'] for c in chunks)
    assert not any(c['context'].get('table_header_inferred') for c in chunks)


def test_single_very_long_table_cell_never_silently_disappears():
    raw='chuoi_khong_co_khoang_trang' * 1200
    unit=make_unit('Tên tiêu chí | Điểm\n'+raw+' | 2',kind='table')
    chunks=build_chunks([unit],'v5',max_words=60,token_budget=160)
    assert any(raw in c['raw_text'] and c['over_budget'] for c in chunks)


def test_actual_local_token_counter_controls_chunk_budget():
    unit=make_unit('Điều 1. Ghi chú\n' + ' '.join('Một số tiêu chí OCOP.' for _ in range(45)))
    # Deliberately strict fake tokenizer approximates 1 token per character.
    chunks=build_chunks([unit],'v5',max_words=200,token_budget=200,counter=len)
    assert len(chunks)>2
    assert all(c['estimated_tokens']==len(c['text_for_embedding']) for c in chunks)
    assert all(c['token_count_method']=='model_tokenizer' for c in chunks)
    assert all(not c['over_budget'] for c in chunks)


def test_source_metadata_change_invalidates_index_version(tmp_path,monkeypatch):
    import ai_core.retrieval.ocop.index_pipeline as ip
    kb=tmp_path/'kb';kb.mkdir()
    unit=make_unit('Điều 1. Chất lượng')
    (kb/'evidence_units.jsonl').write_text(json.dumps(unit,ensure_ascii=False)+'\n',encoding='utf-8')
    (kb/'manifest.json').write_text(json.dumps({'complete':True,'corpus_version':'fixed','counts':{'pages':1}}),encoding='utf-8')
    monkeypatch.setattr(ip,'_source_metadata',lambda root=ip.ROOT:{unit['source_id']:{'document_number':'26/2026/QĐ-TTg'}})
    first=build_index(knowledge=kb,index_dir=tmp_path/'index')['corpus_version']
    monkeypatch.setattr(ip,'_source_metadata',lambda root=ip.ROOT:{unit['source_id']:{'document_number':'26/2027/QĐ-TTg'}})
    second=build_index(knowledge=kb,index_dir=tmp_path/'index')['corpus_version']
    assert first!=second


def test_inherited_legal_heading_is_from_same_page_only():
    # Very long section text becomes separate paragraph units via extractor.
    text='Mục 3. Hướng dẫn OCOP\n' + 'Thông tin hồ sơ.\n'*180
    pg={'source_id':'VN.TEST.QD26.2026','pdf_page':7,'extracted_text':text,'tables':[],
        'review_status':'needs_review'}
    units=page_units(pg)
    paragraphs=[u for u in units if u['unit_kind']=='paragraph']
    assert paragraphs and all(u['structured'].get('legal_heading')=='Mục 3. Hướng dẫn OCOP' for u in paragraphs)
    child=build_chunks(paragraphs,'v5',max_words=50)
    assert child and all('Mục 3. Hướng dẫn OCOP' in ch['text_for_embedding'] for ch in child)
    next_page=page_units({**pg,'pdf_page':8,'extracted_text':'Thông tin tiếp nối không có tiêu đề'})
    assert all(not u['structured'].get('legal_heading') for u in next_page)


def test_parent_expansion_rejects_unverified_units_when_verified_only(tmp_path):
    unit=make_unit('Điều 1. Văn bản chưa duyệt OCOP')
    kb=tmp_path/'kb';kb.mkdir()
    (kb/'evidence_units.jsonl').write_text(json.dumps(unit,ensure_ascii=False)+'\n',encoding='utf-8')
    (kb/'manifest.json').write_text(json.dumps({'complete':True,'corpus_version':'x','counts':{'pages':1}}),encoding='utf-8')
    idx=tmp_path/'idx';build_index(knowledge=kb,index_dir=idx)
    assert search(idx,'Văn bản OCOP',expand_parent=True,include_needs_review=False)==[]


def test_dense_refuses_oversize_row_before_qdrant_write(monkeypatch):
    import sys,types
    import ai_core.retrieval.ocop.index_pipeline as ip
    class StubModel:
        max_seq_length=2048
        def tokenizer(self,text,**kwargs):return {'input_ids':[1,2,3]}
    mod=types.ModuleType('qdrant_client')
    mod.QdrantClient=lambda *a,**kw: (_ for _ in ()).throw(AssertionError('Qdrant must not be contacted'))
    mod.models=object()
    monkeypatch.setitem(sys.modules,'qdrant_client',mod)
    monkeypatch.setattr(ip,'_load_embedding',lambda model,revision=None: StubModel())
    monkeypatch.setattr(ip,'_encode',lambda *args,**kwargs: types.SimpleNamespace(shape=(1,768)))
    with pytest.raises(RuntimeError,match='Over-budget atomic'):
        ip.build_dense([{'chunk_id':'bad','text_for_embedding':'long row','over_budget':True}],
                       collection='test',model_id='local')


def test_dense_rejects_actual_embedding_truncation(monkeypatch):
    import sys,types
    import ai_core.retrieval.ocop.index_pipeline as ip
    class StubModel:
        max_seq_length=80
        def tokenizer(self,text,**kwargs):return {'input_ids':list(range(90))}
    mod=types.ModuleType('qdrant_client')
    mod.QdrantClient=lambda *a,**kw: (_ for _ in ()).throw(AssertionError('Qdrant must not be contacted'))
    mod.models=object()
    monkeypatch.setitem(sys.modules,'qdrant_client',mod)
    monkeypatch.setattr(ip,'_load_embedding',lambda model,revision=None: StubModel())
    monkeypatch.setattr(ip,'_encode',lambda *args,**kwargs: types.SimpleNamespace(shape=(1,768)))
    with pytest.raises(RuntimeError,match='would truncate'):
        ip.build_dense([{'chunk_id':'bad','text_for_embedding':'long row','over_budget':False}],
                       collection='test',model_id='local')


def test_long_parent_expansion_never_mix_another_parent(tmp_path):
    kb=tmp_path/'kb';kb.mkdir()
    units=[make_unit('Điều 1. Danh mục\n'+' hồ sơ sản phẩm OCOP'*220),
           {**make_unit('Điều 2. Khác nguồn\n'+ 'bí mật mẫu kiểm thử'*50),
            'unit_id':'unit-2','source_id':'VN.OTHER.QD.2020'}]
    with (kb/'evidence_units.jsonl').open('w',encoding='utf-8') as fh:
        for u in units: fh.write(json.dumps(u,ensure_ascii=False)+'\n')
    (kb/'manifest.json').write_text(json.dumps({'complete':True,'corpus_version':'v2','counts':{'pages':2}}),encoding='utf-8')
    idx=tmp_path/'idx';build_index(knowledge=kb,index_dir=idx,token_budget=220)
    hits=search(idx,'sản phẩm OCOP',top_k=1,expand_parent=True,parent_max_chars=210)
    assert len(hits)==1
    assert len(hits[0]['parent_context'])<=210
    assert 'bí mật mẫu kiểm thử' not in hits[0]['parent_context']
