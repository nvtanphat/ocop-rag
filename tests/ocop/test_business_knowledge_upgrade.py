"""Evidence-bound semantic extraction regressions, independent of OCR models."""
from __future__ import annotations
import fitz
from pathlib import Path
from ai_core.processing.ocop.table_parser import native_tables
from ai_core.processing.ocop.business_candidates import candidates
from ai_core.knowledge.ocop.extractor import extract_semantics


def _recognition_fixture():
    # One explicit 3-row rowspan, two products. No row-order guessing allowed.
    cells = [
        {'row':0,'col':0,'text':'STT','bbox':[0,0,10,10]},
        {'row':0,'col':1,'text':'Tổ chức','bbox':[10,0,110,10]},
        {'row':0,'col':2,'text':'Sản phẩm','bbox':[110,0,250,10]},
        {'row':1,'col':0,'text':'1','bbox':[0,10,10,20]},
        {'row':1,'col':1,'text':'HTX Sen Huế','rowspan':2,'bbox':[10,10,110,30],
         'merged_extent_unknown':False},
        {'row':1,'col':2,'text':'Hạt sen','bbox':[110,10,250,20]},
        {'row':2,'col':0,'text':'2','bbox':[0,20,10,30]},
        {'row':2,'col':2,'text':'Trà sen','bbox':[110,20,250,30]},
    ]
    return {'unit_id':'unit:table:0001','source_id':'VN.HAIPHONG.OCOP','unit_kind':'table',
            'text':'STT | Tổ chức | Sản phẩm\n1 | HTX Sen Huế | Hạt sen\n2 | Trà sen',
            'spans':[{'pdf_page':3,'table_id':'table:native:0','bbox':[0,0,250,30]}],
            'structured':{'table_id':'table:native:0','cells':cells}}


def test_merged_rowspan_is_provenance_bound_not_last_seen():
    from ai_core.processing.ocop.business_candidates import _row_text
    unit=_recognition_fixture()
    rows=_row_text(unit['structured']['cells'])
    assert rows[2]['resolved_columns']['1']['text']=='HTX Sen Huế'
    assert rows[2]['resolved_columns']['1']['row']==1
    assert rows[2]['resolved_columns']['1']['inherited']
    unit['structured']['cells'][4].pop('rowspan')
    rows=_row_text(unit['structured']['cells'])
    assert '1' not in rows[2]['resolved_columns']


def test_hai_phong_recognition_inherited_owner_with_proof():
    unit=_recognition_fixture()
    sid='VN.HAIPHONG.QD525.2026'
    unit['source_id']=sid
    kind={sid:'recognition_decision'}
    extract=candidates([unit],kind)
    result=extract_semantics([unit],kind,extract)
    products=[r['label'] for r in result['business_entities'] if r['kind']=='Product']
    assert products==['Hạt sen','Trà sen'] or sorted(products)==['Hạt sen','Trà sen']
    records=[r for r in result['business_entities'] if r['kind']=='RecognitionRecord']
    assert len(records)==2
    assert any(r['attributes']['owner_inherited_from_merge'] for r in records)
    owners=[r for r in result['business_entities'] if r['kind']=='Organization']
    assert len(owners)==1 and len(owners[0]['evidence'])>=2
    links=[r for r in result['business_relations'] if r['relation_type']=='DECLARED_BY']
    assert len(links)==2 and any(len(r['evidence'])==2 for r in links)


def test_scoring_candidates_are_never_verified():
    sid='VN.OCOP.QD26.2026'
    unit={'unit_id':'unit:score:0001','source_id':sid,'unit_kind':'criterion_table_candidate',
          'text':'1.1. Chất lượng sản phẩm | 3\nCó chứng nhận hợp lệ *** | 2',
          'spans':[{'pdf_page':20,'table_id':'table:1','bbox':[0,0,100,100]}],
          'structured':{'table_id':'table:1','cells':[
             {'row':0,'col':0,'text':'1.1. Chất lượng sản phẩm','bbox':[0,0,80,40]},
             {'row':0,'col':1,'text':'3','bbox':[80,0,100,40]},
             {'row':1,'col':0,'text':'Có chứng nhận hợp lệ ***','bbox':[0,40,80,80]},
             {'row':1,'col':1,'text':'2','bbox':[80,40,100,80]},
          ]}}
    c=candidates([unit],{sid:'ocop_framework'})
    s=extract_semantics([unit],{sid:'ocop_framework'},c)
    assert any(e['kind']=='Criterion' for e in s['business_entities'])
    assert any(e['kind']=='ScoreOption' and e['attributes']['points_candidate']==2 for e in s['business_entities'])
    assert any(r['relation_type']=='HAS_OPTION' for r in s['business_relations'])
    assert any(r['relation_type']=='HAS_CONDITION' for r in s['business_relations'])
    assert all(e['status']=='candidate' for e in s['business_entities'])
    assert all(r['status']=='candidate' for r in s['business_relations'])
    assert all(not r['if_all'] and not r['consequence'] for r in s['business_rules'])


def test_native_table_row_coordinates_not_column_major():
    # Native text table with contrasting column coordinates.
    with fitz.open() as pdf:
        page=pdf.new_page(width=400,height=300)
        for y,row in enumerate([('STT','Sản phẩm'),('1','Hạt sen'),('2','Cà phê')]):
            for x,txt in enumerate(row):
                page.insert_text((30+x*130,50+y*40),txt)
        # Instead of depending on auto detector, simulate its table contract.
        class Row:
            def __init__(self, cells):self.cells=cells
        class Table:
            row_count=2;col_count=2;bbox=(20,40,300,120)
            rows=[Row([(20,40,100,70),(100,40,300,70)]),
                  Row([(20,70,100,120),(100,70,300,120)])]
            cells=[(20,40,100,70),(20,70,100,120),(100,40,300,70),(100,70,300,120)]
            def extract(self):return [['STT','Sản phẩm'],['1','Hạt sen']]
        class Finder: tables=[Table()]
        class Page:
            def find_tables(self,**kwargs):
                assert kwargs=={"strategy":"lines_strict"}
                return Finder()
        table=native_tables(Page())[0]
        assert table['cells'][1]['row']==0 and table['cells'][1]['col']==1
        assert table['cells'][1]['bbox']==[100.,40.,300.,70.]
        assert table['cells'][1]['text']=='Sản phẩm'


def test_semantic_quality_does_not_promote_machine_candidates():
    from ai_core.knowledge.ocop.quality import audit_knowledge
    sid='VN.OCOP.QD26.2026'
    unit={'unit_id':'unit:1','source_id':sid,'spans':[{'pdf_page':20}]}
    ent={'entity_id':'ent:1','source_id':sid,'kind':'Criterion',
         'status':'candidate','evidence':[{'evidence_unit_id':'unit:1','source_id':sid,'pdf_page':20,'quote':'a'}]}
    report=audit_knowledge([unit],{'business_entities':[ent],'business_relations':[],'business_rules':[]})
    assert report['issues']=={} and report['machine_verified_facts']==0
    assert report['manual_gold_required']


def test_native_real_hai_phong_coordinates_and_rowspan():
    file=Path(__file__).resolve().parents[2]/'data/raw/ocop/recognition_decisions/qd-cong-nhan-san-pham-ocop-2025-1-..signed639060091328998926.pdf'
    if not file.is_file():
        return
    with fitz.open(file) as pdf:
        table=native_tables(pdf[2])[0]
    owner=next(c for c in table['cells'] if c['row']==1 and c['col']==1)
    product=next(c for c in table['cells'] if c['row']==1 and c['col']==2)
    assert owner['bbox'][0] < product['bbox'][0]
    assert owner['rowspan']==4
    assert owner['text'].startswith('Công ty Trách')


def test_score_option_has_cell_level_pdf_provenance():
    sid='VN.OCOP.QD26.2026'
    unit={'unit_id':'unit:score:source','source_id':sid,'unit_kind':'criterion_table_candidate',
          'text':'1.1. Chất lượng | 3\nCó tài liệu chứng minh | 2',
          'spans':[{'pdf_page':18,'table_id':'t:1','bbox':[0,0,100,80]}],
          'structured':{'table_id':'t:1','cells':[
            {'row':0,'col':0,'text':'1.1. Chất lượng','bbox':[0,0,70,40]},
            {'row':0,'col':1,'text':'3','bbox':[70,0,100,40]},
            {'row':1,'col':0,'text':'Có tài liệu chứng minh','bbox':[0,40,70,80]},
            {'row':1,'col':1,'text':'2','bbox':[70,40,100,80]},
          ]}}
    layer=extract_semantics([unit],{sid:'ocop_framework'},candidates([unit],{sid:'ocop_framework'}))
    option=next(e for e in layer['business_entities'] if e['kind']=='ScoreOption')
    assert len(option['evidence'])==2
    score_source=option['evidence'][1]
    assert score_source['quote']=='2'
    assert score_source['bbox']==[70.,40.,100.,80.]
    assert score_source['pdf_page']==18 and score_source['cell_id']=='t:1:r1:c1'
    assert option['status']=='candidate'
