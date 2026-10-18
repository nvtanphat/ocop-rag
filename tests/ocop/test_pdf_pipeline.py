"""PDF: PDF native/scanned text, image coordinates, cache, grid, locked source."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_core.processing.ocop.artifact_cache import build_cache_key,write_json,load_json
from ai_core.processing.ocop.native_extractor import extract_native
from ai_core.processing.ocop.table_parser import native_tables,raster_tables
from ai_core.processing.ocop.ocr_extractor import _pdf_bbox, OCRResult
from ai_core.processing.ocop.pdf_pipeline import extract_page,run_pipeline
from ai_core.processing.ocop.profiler import profile_pdf
from ai_core.processing.ocop.registry import snapshot
from ai_core.domain.ocop_models import SourceDocument,ReviewStatus


@pytest.fixture
def document(tmp_path):
    fitz=pytest.importorskip('fitz')
    p=tmp_path/'sample.pdf'
    with fitz.open() as d:
        pg=d.new_page(width=450,height=550)
        pg.insert_text((40,60),'Dieu 1. Noi dung hop le\n',fontsize=12)
        for i in range(8):
            pg.insert_text((40,110+i*28),f'Khoan {i+1}. Quy dinh kiem tra an toan thuc pham',fontsize=10)
        d.save(p)
    return p


def test_native_bbox_and_page_validation(document):
    import fitz
    with fitz.open(document) as pdf:
        b=extract_native(pdf[0])
        assert len(b)>=8
        assert b[0]['bbox'][0]>=0
        assert b[0]['method']=='native'
        profile=profile_pdf(document,'TEST')[0]
        a=extract_page(pdf[0],profile,source_id='TEST',enable_ocr=False)
        assert a['pdf_page']==1
        assert a['blocks']
        assert a['extraction_method']=='native'
        assert a['review_status'] in {'machine_extracted','needs_review'}


def test_tesseract_to_pdf_point_bbox():
    bb=_pdf_bbox((200,100,500,350),width_px=1000,height_px=1000,width_pt=500,height_pt=700)
    assert bb==[100.,70.,250.,245.]
    assert all(n>=0 for n in bb)


def test_cache_deterministic_and_versioned(tmp_path):
    a=build_cache_key('a'*64,1,dpi=260,ocr_engine='tesseract',extract_ocr=True,detect_tables=True,model_version='x')
    b=build_cache_key('a'*64,1,dpi=260,ocr_engine='tesseract',extract_ocr=True,detect_tables=True,model_version='x')
    c=build_cache_key('a'*64,1,dpi=260,ocr_engine='paddle',extract_ocr=True,detect_tables=True,model_version='x')
    assert a==b and a!=c
    f=tmp_path/'sub'/'a.json'
    write_json(f,{'value':'cây rau'})
    assert load_json(f)['value']=='cây rau'


def test_grid_candidates_keep_coordinates_and_review(tmp_path):
    from PIL import Image,ImageDraw
    import fitz
    image=Image.new('RGB',(500,500),'white')
    d=ImageDraw.Draw(image)
    for x in [70,200,440]: d.line([(x,80),(x,330)],fill='black',width=3)
    for y in [80,140,205,265,330]: d.line([(70,y),(440,y)],fill='black',width=3)
    with fitz.open() as pdf:
        page=pdf.new_page(width=250,height=250)
        blocks=[{'bbox':[40,48,90,60],'text':'***', 'order':0}]
        results=raster_tables(image,page,blocks)
        assert results and results[0]['review_status']=='needs_review'
        assert results[0]['row_count']==4 and results[0]['col_count']==2
        assert any(c['text']=='***' for c in results[0]['cells'])
        assert all(0<=c['bbox'][0]<c['bbox'][2]<=page.rect.width for c in results[0]['cells'])


def test_page_error_is_quarantined_and_resumable(tmp_path,document,monkeypatch):
    root=tmp_path
    (root/'data/raw/ocop').mkdir(parents=True)
    target=root/'data/raw/ocop/demo.pdf'
    target.write_bytes(document.read_bytes())
    src=SourceDocument(source_id='VN.DEMO',path='data/raw/ocop/demo.pdf',source_kind='ocop_framework')
    registry=root/'r.json';registry.write_text(json.dumps({'schema_version':1,'sources':[src.model_dump(mode='json')]}))
    lock=root/'lock.json';lock.write_text(json.dumps(snapshot(root,[src])))
    out=root/'out'; cache=root/'cache'
    result=run_pipeline(root,registry=registry,lock=lock,output=out,cache_dir=cache,ocr=False,tables=False)
    assert result['complete'] and result['counts']['pages']==1
    result2=run_pipeline(root,registry=registry,lock=lock,output=out,cache_dir=cache,ocr=False,tables=False)
    assert result['counts']==result2['counts']
    target.write_bytes(b'not pdf')
    with pytest.raises(RuntimeError,match='differs'):
        run_pipeline(root,registry=registry,lock=lock,output=out,cache_dir=cache)


def test_signed_scan_is_not_treated_as_native_legal_content(monkeypatch,tmp_path):
    from PIL import Image
    import fitz
    img=Image.new('RGB',(500,700),'white')
    buf=__import__('io').BytesIO();img.save(buf,format='PNG')
    f=tmp_path/'scan.pdf'
    with fitz.open() as d:
        p=d.new_page(width=500,height=700)
        p.insert_image(p.rect,stream=buf.getvalue())
        p.insert_text((25,25),'Nguoi ky cong thong tin dien tu chinh phu')
        d.save(f)
    pr=profile_pdf(f,'TEST')[0]
    assert pr['page_class']=='ocr_candidate'
    monkeypatch.setattr('ai_core.processing.ocop.pdf_pipeline.run_ocr',lambda *a,**k: OCRResult([{
        'block_id':'ocr:test', 'text':'BANG TIEU CHI *** 15 diem',
        'bbox':[10,10,300,100],'method':'mock','confidence':0.7,'order':0}], 'mock',[]))
    with fitz.open(f) as d:
        art=extract_page(d[0],pr,source_id='TEST',enable_tables=False,ocr_engine='tesseract')
    assert 'Nguoi ky' not in art['extracted_text']
    assert '***' in art['extracted_text']
    assert art['review_status']=='needs_review'


def test_cross_page_is_not_silently_merged():
    from ai_core.processing.ocop.layout import layout_page
    x=[{'bbox':[20,20,60,38],'text':'DIEM 5','order':0}]
    ordered,warnings=layout_page(x,100,100)
    assert ordered[0]['text']=='DIEM 5' and ordered[0]['reading_order']==0


def test_paddle_mock_adapter_on_offline_pixels():
    from PIL import Image
    from types import SimpleNamespace
    from ai_core.processing.ocop.ocr_extractor import _paddle
    class Mock:
        def predict(self,pixels):
            return [{'res':{'rec_polys':[[[10,20],[50,20],[50,40],[10,40]]],
                            'rec_texts':['Mẫu 01'], 'rec_scores':[0.94]}}]
    r=_paddle(Image.new('RGB',(100,100)),SimpleNamespace(rect=SimpleNamespace(width=200,height=200)),Mock())
    assert r.engine=='paddle' and r.blocks[0]['bbox']==[20.,40.,100.,80.]


def test_ppstructure_mock_table_candidate():
    from PIL import Image
    from types import SimpleNamespace
    from ai_core.processing.ocop.structure_engine import ppstructure_tables
    class Mock:
        def predict(self,pixels):
            return [{'res':{'table_res_list':[{'table_region_bbox':[5,5,60,60], 'pred_html':'<table><tr><td>3</td></tr></table>'}]}}]
    t=ppstructure_tables(Image.new('RGB',(100,100)),SimpleNamespace(rect=SimpleNamespace(width=200,height=200)),Mock())
    assert t[0]['review_status']=='needs_review' and t[0]['bbox']==[10.,10.,120.,120.]


def test_ppstructure_merges_keep_explicit_rowspan_colspan():
    from ai_core.processing.ocop.structure_engine import parse_html_cells
    cells,rows,cols=parse_html_cells('<table><tr><th rowspan="2">A</th><td>1</td></tr><tr><td colspan="2">2</td></tr></table>')
    assert rows==2 and cols==3
    assert cells[0]['rowspan']==2
    assert cells[2]['col']==1 and cells[2]['colspan']==2
    assert all(cell['bbox'] is None for cell in cells)


def test_cross_page_candidate_never_materializes_merge():
    from ai_core.processing.ocop.table_continuity import possible_continuations
    pre={'source_id':'VN.TEST','pdf_page':1,'height_pt':100,
        'tables':[{'table_id':'a','bbox':[10,50,100,95],'col_count':3,'row_count':4}]}
    cur={'source_id':'VN.TEST','pdf_page':2,'height_pt':100,
        'tables':[{'table_id':'b','bbox':[10,5,100,80],'col_count':3,'row_count':4}]}
    c=possible_continuations(pre,cur)
    assert c and c[0]['status']=='needs_review'
    assert not possible_continuations(pre,{**cur,'pdf_page':3})


def test_native_bbox_overflow_clipped_with_original_retained():
    from ai_core.processing.ocop.pdf_pipeline import _validate_boxes
    b={'bbox':[5,10,101,35]}
    assert _validate_boxes([b],[],100,100)==1
    assert b['bbox']==[5,10,100,35]
    assert b['bbox_original']==[5,10,101,35]


def test_page_cache_hit_skips_expensive_extraction(tmp_path,document,monkeypatch):
    import ai_core.processing.ocop.pdf_pipeline as pdf_module
    root=tmp_path
    target=root/'data/raw/ocop/test.pdf'
    target.parent.mkdir(parents=True)
    target.write_bytes(document.read_bytes())
    src=SourceDocument(source_id='VN.TEST.CACHE',path='data/raw/ocop/test.pdf',source_kind='ocop_framework')
    registry=root/'sources.json'
    registry.write_text(json.dumps({'schema_version':1,'sources':[src.model_dump(mode='json')]}))
    lock=root/'source.lock.json'
    lock.write_text(json.dumps(snapshot(root,[src])))
    kw={'registry':registry,'lock':lock,'output':root/'out','cache_dir':root/'cache',
        'engine':'tesseract','ocr':False,'tables':False}
    first=pdf_module.run_pipeline(root,**kw)
    assert first['counts']['pages']==1
    monkeypatch.setattr(pdf_module,'extract_page',lambda *a,**k: (_ for _ in ()).throw(RuntimeError('cache not used')))
    second=pdf_module.run_pipeline(root,**kw)
    assert second['counts']==first['counts']
    assert second['complete']


def test_real_processed_corpus_complete_if_artifacts_available():
    import os
    root=Path(__file__).resolve().parents[2]
    external=os.environ.get('OCOP_PDF_ARTIFACT_DIR')
    manifest=(Path(external) if external else root/'data/processed/ocop/pages')/'manifest.json'
    if not manifest.exists():
        if external:
            pytest.fail('explicit PDF artifact directory has no manifest')
        pytest.skip('generated corpus is optional for source-only installs')
    data=json.loads(manifest.read_text())
    if not data.get('complete'):
        if external:
            pytest.fail('explicit PDF artifact corpus is incomplete')
        pytest.skip('partial dev-run manifest; no full release available')
    count=0
    from ai_core.processing.ocop.pdf_loader import checked_sources
    _,locked=checked_sources(root,root/'configs/ocop_sources.json',root/'configs/ocop_sources.lock.json')
    digests={s['source_id']:s['sha256'] for s in locked['sources']}
    assert data['input_snapshot_sha256']==locked['aggregate_sha256']
    for source in data['sources']:
        p=manifest.parent/source['artifact']
        records=[json.loads(x) for x in p.read_text(encoding='utf8').splitlines()]
        assert len(records)==source['page_count_expected']
        assert [r['pdf_page'] for r in records]==list(range(1,len(records)+1))
        assert all(r['source_id']==source['source_id'] and not r.get('quarantined') for r in records)
        assert source['source_sha256']==digests[source['source_id']]
        assert all(r['source_sha256']==digests[r['source_id']] for r in records)
        count+=len(records)
    assert count==data['counts']['pages']==583
    assert data['counts']['ocr_executed']==315
