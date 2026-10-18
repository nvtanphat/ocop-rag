"""Regression: OCOP tabular scans, VL result contract, score QA, parser lineage."""
from __future__ import annotations
from types import SimpleNamespace
from PIL import Image,ImageDraw
from ai_core.processing.ocop.document_vl import parse_vl_results
from ai_core.processing.ocop.table_parser import raster_tables
from ai_core.processing.ocop.pdf_quality import score_page_quality
from ai_core.processing.ocop.artifact_cache import PARSER_VERSION


def _page():
    return SimpleNamespace(rect=SimpleNamespace(width=500,height=700))


def test_vl_parse_table_html_keeps_all_cells_and_source_bbox():
    img=Image.new('RGB',(1000,1400),'white')
    result={'res':{'parsing_res_list':[{'block_id':0,'block_label':'text','block_bbox':[100,100,950,180],
        'block_content':'Quyết định 26/2026','block_order':0},
        {'block_id':1,'block_label':'table','block_bbox':[100,200,950,1000],
         'block_content':'<table><tr><th>Tiêu chí</th><th>Điểm</th></tr><tr><td>VietGAP *****</td><td>3</td></tr></table>',
         'block_order':1}]}}
    ocr,tables=parse_vl_results([result],img,_page())
    assert ocr.engine=='paddle_vl' and len(tables)==1
    assert tables[0]['col_count']==2 and tables[0]['row_count']==2
    assert len(tables[0]['cells'])==4 and tables[0]['review_status']=='needs_review'
    assert tables[0]['bbox']==[50.,100.,475.,500.]
    assert '*****' in ocr.blocks[1]['text']
    assert ocr.blocks[1]['confidence'] is None
    assert ocr.blocks[1]['candidate_only'] and tables[0]['candidate_only']


def test_vl_bad_payload_fails_instead_of_fabricating():
    from pytest import raises
    with raises(ValueError,match='missing_parsing_res_list'):
        parse_vl_results([{'res':{'something_else':[]}}],Image.new('RGB',(100,100)),_page())


def test_vl_keeps_unlocated_text_and_table_candidates():
    from ai_core.processing.ocop.layout import layout_page
    img=Image.new('RGB',(1000,1400),'white')
    html='<table><tr><td rowspan="2">Visible text</td></tr></table>'
    result={'res':{'parsing_res_list':[
        {'block_id':7,'block_label':'text','block_content':'Unlocated legal text','block_order':0},
        {'block_id':7,'block_label':'table','block_content':html,'block_order':1},
        {'block_id':9,'block_label':'text','block_bbox':[float('nan'),0,50,50],
         'block_content':'Invalid box text','block_order':2},
    ]}}
    ocr,tables=parse_vl_results([result],img,_page())
    ordered,warnings=layout_page(ocr.blocks,500,700,preserve_order=True)
    assert [b['text'] for b in ordered]==['Unlocated legal text','Visible text |','Invalid box text']
    assert [b['block_id'] for b in ordered]==['vl:0','vl:1','vl:2']
    assert ordered[0]['bbox'] is None and ordered[2]['bbox'] is None
    assert 'blocks_without_valid_bbox' in warnings
    assert 'vl_block_bbox_missing' in ocr.warnings and 'vl_block_bbox_invalid' in ocr.warnings
    assert tables[0]['bbox'] is None and tables[0]['cells']==[]
    assert any(w.startswith('vl_table_html_unparsed:') for w in tables[0]['warnings'])


def test_vl_plaintext_does_not_decode_html_entities_twice():
    from ai_core.processing.ocop.document_vl import table_plaintext
    assert table_plaintext('<table><tr><td>&amp;lt;star&amp;gt;</td></tr></table>')=='&lt;star&gt; |'


def test_vl_runtime_signature_fingerprints_local_model_files(tmp_path,monkeypatch):
    from ai_core.processing.ocop.document_vl import runtime_signature
    vl=tmp_path/'vl'
    layout=tmp_path/'layout'
    vl.mkdir()
    layout.mkdir()
    vl_file=vl/'weights.bin'
    layout_file=layout/'model.json'
    vl_file.write_bytes(b'first vl weights')
    layout_file.write_bytes(b'layout config')
    monkeypatch.setenv('OCOP_PADDLE_VL_MODEL_DIR',str(vl))
    monkeypatch.setenv('OCOP_PADDLE_VL_LAYOUT_MODEL_DIR',str(layout))
    first=runtime_signature('v1.6')
    vl_file.write_bytes(b'updated vl weights')
    second=runtime_signature('v1.6')
    assert first['pipeline_version']=='v1.6' and first['backend']=='native'
    assert first['vl_model']['sha256']!=second['vl_model']['sha256']
    assert first['layout_model']['sha256']==second['layout_model']['sha256']


def test_vl_requires_preprovisioned_model_directories(monkeypatch):
    from pytest import raises
    from ai_core.processing.ocop.document_vl import runtime_signature
    monkeypatch.delenv('OCOP_PADDLE_VL_MODEL_DIR',raising=False)
    monkeypatch.delenv('OCOP_PADDLE_VL_LAYOUT_MODEL_DIR',raising=False)
    with raises(RuntimeError,match='paddleocr_vl_local_model_required'):
        runtime_signature('v1.6')


def test_vl_run_uses_low_variance_local_inference_settings():
    from ai_core.processing.ocop.document_vl import run_vl
    class Model:
        def predict(self,image,**kwargs):
            self.image=image
            self.kwargs=kwargs
            return [{'res':{'parsing_res_list':[{'block_bbox':[0,0,20,20],
                'block_label':'text','block_content':'Local OCR'}]}}]
    model=Model()
    ocr,tables=run_vl(Image.new('RGB',(100,100)),_page(),model=model)
    assert ocr.blocks[0]['text']=='Local OCR' and tables==[]
    assert model.kwargs=={'temperature':0.0,'top_p':1.0,
                          'use_doc_orientation_classify':False,
                          'use_doc_unwarping':False,'use_layout_detection':True}


def test_scan_table_with_weak_vertical_support_detected():
    img=Image.new('RGB',(900,1000),'white')
    dr=ImageDraw.Draw(img)
    # Merged cells leave vertical columns discontinuous, as in OCOP QD26.
    for y in range(270,811,30):
        dr.line((100,y,800,y),fill='black',width=2)
    for x in (100,710,800):
        for y in range(270,811,80):
            dr.line((x,y,x,min(810,y+39)),fill='black',width=2)
    t=raster_tables(img,_page(),[])
    assert t and t[0]['col_count'] == 2 and t[0]['row_count']>=12
    assert all(c['review_status']=='needs_review' for c in t[0]['cells'])


def test_quality_reports_blank_scoring_cells_not_verified():
    q=score_page_quality({'page_class':'ocr_candidate'},[],[{'bbox':[0,0,500,300],
      'row_count':2,'col_count':2,'cells':[{'row':0,'col':0,'text':'Yêu cầu ****','bbox':None},
       {'row':0,'col':1,'text':'','bbox':None}, {'row':1,'col':0,'text':'Chất lượng','bbox':None},
       {'row':1,'col':1,'text':'3','bbox':None}]}])
    assert q['table_cells']==4 and q['table_cells_with_bbox']==0
    assert q['potential_score_cells_blank']==1 and q['strict_numeric_score_candidates']==1
    assert q['requires_manual_score_validation'] and q['quality_is_not_legal_verification']


def test_versioned_parsing_cache_is_upgraded():
    assert PARSER_VERSION.startswith('ocop-pdf-v4.')


def test_score_refinement_keeps_original_ocr_and_marks_unverified():
    from ai_core.processing.ocop.score_cell_ocr import recover_scoring_cells
    tbl={'bbox':[0,0,500,300],'col_count':2,'cells':[{'row':0,'col':0,'bbox':[0,0,390,40],
        'text':'Tiêu chí ****'},{'row':0,'col':1,'bbox':[390,0,500,40],'text':'|'}]}
    result=recover_scoring_cells(Image.new('RGB',(1000,1400),'white'),_page(),[tbl],
        ocr_reader=lambda crop:[('3',.97)])
    assert tbl['cells'][1]['text']=='|'
    assert result['score_candidates_added']==1
    assert tbl['cells'][1]['score_ocr_candidates'][0]['review_status']=='needs_review'


def test_score_refinement_rejects_garbage():
    from ai_core.processing.ocop.score_cell_ocr import recover_scoring_cells
    tbl={'bbox':[0,0,500,300],'col_count':2,'cells':[{'row':0,'col':1,'bbox':[390,0,500,40],'text':''}]}
    assert recover_scoring_cells(Image.new('RGB',(1000,1400),'white'),_page(),[tbl],
         ocr_reader=lambda crop:[('500',.99)])['score_candidates_added']==0


def test_auto_table_model_failure_falls_back_instead_of_quarantining(monkeypatch):
    """Regression: auto PP-Structure cannot break source-locked page coverage."""
    from unittest.mock import patch
    import fitz
    from ai_core.processing.ocop.pdf_pipeline import extract_page
    from ai_core.processing.ocop.ocr_extractor import OCRResult
    with fitz.open() as pdf:
        page=pdf.new_page(width=500,height=700)
        profile={'pdf_page':1,'page_class':'ocr_candidate','needs_ocr_review':True,
                 'largest_image_area_ratio':1.,'width_pt':500.,'height_pt':700.}
        fake=OCRResult([{'block_id':'a','text':'OCOP','bbox':[50,50,100,100],
                         'order':0,'method':'mock','confidence':.8}], 'mock',[])
        with patch('ai_core.processing.ocop.pdf_pipeline.run_ocr',return_value=fake),\
             patch('ai_core.processing.ocop.pdf_pipeline.raster_tables',return_value=[]),\
             patch('ai_core.processing.ocop.pdf_pipeline.ppstructure_tables',side_effect=RuntimeError('bad version')):
            art=extract_page(page,profile,source_id='S',ocr_engine='tesseract',table_engine='auto')
        assert art['extracted_text']=='OCOP'
        assert art['ocr_engine']=='mock'


def test_paddle_vl_table_is_shared_with_page_ocr(monkeypatch):
    import fitz
    from ai_core.processing.ocop.pdf_pipeline import extract_page
    from ai_core.processing.ocop.ocr_extractor import OCRResult
    source=OCRResult([{'block_id':'vl:0','text':'Tiêu chí 3','bbox':[10,10,80,40],
                       'method':'paddleocr_vl','order':0,'confidence':None}], 'paddle_vl',[])
    fake_table={'table_id':'table:paddle_vl:0','method':'paddleocr_vl','bbox':[10,60,200,300],
                'row_count':1,'col_count':2,'cells':[], 'review_status':'needs_review'}
    hits=[]
    def fake(*args,**kwargs):
        hits.append(1)
        return source,[fake_table]
    monkeypatch.setattr('ai_core.processing.ocop.pdf_pipeline.run_vl',fake)
    with fitz.open() as d:
        pg=d.new_page(width=500,height=700)
        profile={'pdf_page':1,'page_class':'ocr_candidate','needs_ocr_review':True,
                 'largest_image_area_ratio':1.,'width_pt':500.,'height_pt':700.}
        a=extract_page(pg,profile,source_id='VN.TEST',ocr_engine='paddle_vl',table_engine='paddle_vl')
    assert hits==[1] and a['extraction_method']=='paddle_vl'
    assert a['tables'][0]['method']=='paddleocr_vl'
    assert a['review_status']=='needs_review'


def test_paddle_vl_page_keeps_model_reading_order(monkeypatch):
    import fitz
    from ai_core.processing.ocop.pdf_pipeline import extract_page
    from ai_core.processing.ocop.ocr_extractor import OCRResult
    source=OCRResult([
        {'block_id':'vl:0','text':'first in reading order','bbox':[100,200,300,230],
         'method':'paddleocr_vl','order':0,'confidence':None},
        {'block_id':'vl:1','text':'second in reading order','bbox':[10,40,100,70],
         'method':'paddleocr_vl','order':1,'confidence':None},
    ],'paddle_vl',[])
    monkeypatch.setattr('ai_core.processing.ocop.pdf_pipeline.run_vl',lambda *a,**k:(source,[]))
    with fitz.open() as d:
        page=d.new_page(width=500,height=700)
        profile={'pdf_page':1,'page_class':'ocr_candidate','needs_ocr_review':True,
                 'largest_image_area_ratio':1.,'width_pt':500.,'height_pt':700.}
        art=extract_page(page,profile,source_id='VN.TEST',ocr_engine='paddle_vl',enable_tables=False)
    assert art['extracted_text']=='first in reading order\nsecond in reading order'


def test_table_audit_only_claims_metrics_for_labeled_pages():
    from tools.audit_pdf_quality import evaluate
    results=[{'source_id':'VN.TEST','pdf_page':1,'table_count':1,'tables':[{'col_count':2}]},
             {'source_id':'VN.TEST','pdf_page':2,'table_count':0,'tables':[]}]
    gold={('VN.TEST',1):{'has_table':True,'expected_columns':2},
          ('VN.TEST',2):{'has_table':False}}
    e=evaluate(results,gold)
    assert e['counts']['annotated_pages']==2
    assert e['table_presence_precision']==1.0 and e['column_exact_match_rate']==1.0
    assert evaluate(results,{})['table_presence_recall'] is None
