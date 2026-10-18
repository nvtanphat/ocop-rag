"""red/green regressions for source-safe PDF/OCR/table parsing."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from PIL import Image

from ai_core.processing.ocop.structure_engine import parse_html_cells
from ai_core.processing.ocop.ocr_extractor import _pdf_bbox, _paddle
from ai_core.processing.ocop.pdf_pipeline import _page_job, _validate_boxes


def fakepage():
    return SimpleNamespace(rect=SimpleNamespace(width=200, height=200))


def test_html_line_break_keeps_legal_terms_separated():
    cells, nrows, ncols = parse_html_cells('<table><tr><th>Tiêu chí<br>chất lượng</th><td>Điểm<p>3</p></td></tr></table>')
    assert nrows == 1 and ncols == 2
    assert 'Tiêu chí chất lượng' in cells[0]['text']
    assert 'Điểm 3' in cells[1]['text']


@pytest.mark.parametrize('markup',[
    '<table><tr><td rowspan="0">3 sao</td></tr></table>',
    '<table><tr><td colspan="many">3 sao</td></tr></table>',
    '<table><tr><td rowspan="9999">3 sao</td></tr></table>',
])
def test_invalid_html_spans_rejected_without_inferred_table(markup):
    with pytest.raises(ValueError,match='(?:span|table)'):
        parse_html_cells(markup)


def test_html_rowspan_cannot_cross_end_of_table():
    with pytest.raises(ValueError,match='span'):
        parse_html_cells('<table><tr><td rowspan="2">Tiêu chí</td></tr></table>')


def test_html_cells_marked_unverified():
    cells,_,_=parse_html_cells('<table><tr><td>3</td></tr></table>')
    assert cells[0]['review_status'] == 'needs_review'


def test_paddle_adapter_rejects_mismatched_polygons_texts_scores():
    class Model:
        def predict(self, pixels):
            return [{'res':{'rec_polys':[[[10,20],[50,20],[50,40],[10,40]]],
                            'rec_texts':['Mẫu 01', 'Mẫu 02'],'rec_scores':[.9,.95]}}]
    with pytest.raises(RuntimeError,match='mismatch'):
        _paddle(Image.new('RGB',(100,100)),fakepage(),Model())


def test_paddle_adapter_rejects_missing_rec_fields():
    class Model:
        def predict(self,pixels):
            return [{'res':{'rec_texts':['Mẫu 01']}}]
    with pytest.raises(RuntimeError,match='mismatch'):
        _paddle(Image.new('RGB',(100,100)),fakepage(),Model())


@pytest.mark.parametrize('bbox', [(float('nan'),0,10,10),(0,0,float('inf'),10),(20,20,10,30)])
def test_pixel_anchor_rejects_invalid_geometry(bbox):
    with pytest.raises(ValueError,match='bbox'):
        _pdf_bbox(bbox,width_px=100,height_px=100,width_pt=200,height_pt=200)


def test_pdf_block_anchor_rejects_nonfinite_geometry():
    with pytest.raises(ValueError,match='bbox'):
        _validate_boxes([{'bbox':[0,0,float('nan'),50]}],[],200,200)


def test_cache_invalidates_provenance_mismatch(tmp_path,monkeypatch):
    from ai_core.processing.ocop.artifact_cache import write_json
    import ai_core.processing.ocop.pdf_pipeline as pp
    profile={'pdf_page':1,'width_pt':200.0,'height_pt':200.0,'page_class':'native_text'}
    location=tmp_path/'cache.json'
    fake={'source_id':'WRONG','pdf_page':1,'width_pt':200.,'height_pt':200.,'extracted_text':'forged',
          'review_status':'machine_extracted','blocks':[],'tables':[], 'ocr_engine':None}
    write_json(location,fake)
    calls=[]
    monkeypatch.setattr(pp,'extract_page',lambda *a,**k: calls.append(True) or {
        'source_id':'EXPECTED','pdf_page':1,'width_pt':200.,'height_pt':200.,'extracted_text':'real',
        'review_status':'machine_extracted','blocks':[],'tables':[],'ocr_engine':None,'profile':profile})
    import fitz
    path=tmp_path/'demo.pdf'
    with fitz.open() as doc:
        doc.new_page(width=200,height=200);doc.save(path)
    job=(str(path),'EXPECTED',profile,str(location),False,120,'tesseract',False,False,'auto',False)
    art=_page_job(job)
    assert calls and art['source_id']=='EXPECTED' and art['extracted_text']=='real'


def test_cache_invalidates_tampered_content(tmp_path,monkeypatch):
    import ai_core.processing.ocop.pdf_pipeline as pp
    profile={'pdf_page':1,'width_pt':200.,'height_pt':200.,'page_class':'native_text'}
    calls=[]
    monkeypatch.setattr(pp,'extract_page',lambda *a,**k: calls.append(1) or {
        'source_id':'EXPECTED','pdf_page':1,'width_pt':200.,'height_pt':200.,
        'extracted_text':'PDF actual text','review_status':'machine_extracted',
        'blocks':[],'tables':[],'ocr_engine':None,'profile':profile})
    import fitz
    path=tmp_path/'demo.pdf'
    with fitz.open() as doc:
        doc.new_page(width=200,height=200);doc.save(path)
    cache=tmp_path/'cache.json'
    job=(str(path),'EXPECTED',profile,str(cache),False,120,'tesseract',False,False,'auto',False)
    first=_page_job(job)
    assert len(calls)==1
    second=_page_job(job)
    assert len(calls)==1 and second['extracted_text']==first['extracted_text']
    tampered=json.loads(cache.read_text());tampered['extracted_text']='tampered text'
    cache.write_text(json.dumps(tampered))
    third=_page_job(job)
    assert len(calls)==2 and third['extracted_text']=='PDF actual text'


def test_cache_invalidates_mismatched_page_geometry(tmp_path,monkeypatch):
    import ai_core.processing.ocop.pdf_pipeline as pp
    profile={'pdf_page':1,'width_pt':200.,'height_pt':200.,'page_class':'native_text'}
    calls=[]
    monkeypatch.setattr(pp,'extract_page',lambda *a,**k: calls.append(1) or {
        'source_id':'EXPECTED','pdf_page':1,'width_pt':200.,'height_pt':200.,
        'extracted_text':'real','review_status':'machine_extracted',
        'blocks':[],'tables':[],'ocr_engine':None,'profile':profile})
    import fitz
    path=tmp_path/'demo.pdf'
    with fitz.open() as doc:
        doc.new_page(width=200,height=200);doc.save(path)
    cache=tmp_path/'cache.json'
    job=(str(path),'EXPECTED',profile,str(cache),False,120,'tesseract',False,False,'auto',False)
    _page_job(job)
    forged=json.loads(cache.read_text());forged['width_pt']=500.0
    cache.write_text(json.dumps(forged))
    art=_page_job(job)
    assert len(calls)==2 and art['width_pt']==200.


def test_auto_ocr_recovers_from_incomplete_paddle_response(monkeypatch):
    from ai_core.processing.ocop.ocr_extractor import run_ocr, OCRResult
    import ai_core.processing.ocop.ocr_extractor as adapter
    class Model:
        def predict(self,pixels):
            return [{'res':{'rec_polys':[], 'rec_texts':['3 sao'], 'rec_scores':[.99]}}]
    monkeypatch.setattr(adapter,'_tesseract',lambda *a,**kw: OCRResult([{
        'block_id':'fallback','text':'3 sao','bbox':[0,0,20,20],
        'method':'tesseract','confidence':.6}], 'tesseract',[]))
    result=run_ocr(Image.new('RGB',(100,100)),fakepage(),engine='auto',paddle_model=Model())
    assert result.blocks[0]['text']=='3 sao' and result.warnings
    assert any('paddle_fallback:RuntimeError' in x for x in result.warnings)


def test_bbox_slight_overflow_clamped_instead_of_fabricated():
    assert _pdf_bbox((-2,-1,101,102),width_px=100,height_px=100,width_pt=200,height_pt=200)==[0.,0.,200.,200.]


def test_html_merge_coordinates_skip_occupied_columns():
    cells,rows,cols=parse_html_cells('<table><tr><th rowspan="2">Nhóm</th><th colspan="2">Điểm</th></tr><tr><td>3 sao</td><td>5 sao</td></tr></table>')
    assert (rows,cols)==(2,3)
    assert [(x['row'],x['col'],x['rowspan'],x['colspan']) for x in cells]==[(0,0,2,1),(0,1,1,2),(1,1,1,1),(1,2,1,1)]
    assert all(x['review_status']=='needs_review' for x in cells)


def test_corrupt_profile_cache_forces_reprofiling(tmp_path,monkeypatch):
    import ai_core.processing.ocop.pdf_pipeline as pp
    from ai_core.domain.ocop_models import SourceDocument
    from ai_core.processing.ocop.registry import snapshot
    import fitz
    root=tmp_path
    file=root/'data/raw/ocop/demo.pdf';file.parent.mkdir(parents=True)
    with fitz.open() as doc:
        pg=doc.new_page(width=200,height=200)
        pg.insert_text((20,40),'Sample legal text ' * 13)
        doc.save(file)
    src=SourceDocument(source_id='VN.TEST.PROFILE',path='data/raw/ocop/demo.pdf',source_kind='ocop_framework')
    reg=root/'sources.json';reg.write_text(json.dumps({'schema_version':1,'sources':[src.model_dump(mode='json')]}))
    lock=root/'lock.json';lock.write_text(json.dumps(snapshot(root,[src])))
    kw={'registry':reg,'lock':lock,'output':root/'out','cache_dir':root/'cache','ocr':False,'tables':False}
    count=[]
    real_profile=pp.profile_pdf
    def wrapped(*args,**kwargs):
        count.append(1);return real_profile(*args,**kwargs)
    monkeypatch.setattr(pp,'profile_pdf',wrapped)
    pp.run_pipeline(root,**kw)
    pp.run_pipeline(root,**kw)
    assert len(count)==1
    profile_cache=next((root/'cache/_profiles').glob('*.json'))
    cached=json.loads(profile_cache.read_text())
    cached['pages'][0]['needs_ocr_review']=False
    cached['pages'][0]['page_class']='native_text'
    profile_cache.write_text(json.dumps(cached))
    pp.run_pipeline(root,**kw)
    assert len(count)==2
