"""Synthetic star legends and table cells, without PDF/OCR gold fixtures."""
import json
from tests.ocop.test_legal_structure import extract, unit


def fixture(*, note=True, header=True, gap=False, next_sheet=False):
    units = [unit('DOC.CURRENT',1,
        'Điều 3. Phân hạng\n3. Các hạng:\n'
        'a) Hạng 5 sao: Tổng điểm trung bình đạt từ 90 đến 100 điểm.\n'
        'b) Hạng 4 sao: Tổng điểm trung bình đạt từ 70 đến dưới 90 điểm.\n'
        'c) Hạng 3 sao: Tổng điểm trung bình đạt từ 50 đến dưới 70 điểm.\n'
        'd) Hạng 2 sao: Tổng điểm trung bình đạt từ 30 đến dưới 50 điểm.\n'
        'đ) Hạng 1 sao: Tổng điểm trung bình đạt dưới 30 điểm.'),
        unit('DOC.CURRENT',2,'PHỤ LỤC II','annex')]
    if header:
        units.append(unit('DOC.CURRENT',2,'3. Bộ sản phẩm: Sản phẩm tổng hợp','paragraph'))
    u = unit('DOC.CURRENT',2,'1.1. Bao bì | 3\nĐóng gói sáng tạo, bao bì đẹp | 2','criterion_table_candidate')
    u['structured'] = {'table_id':'table:synthetic','cells':[
        {'row':0,'col':0,'text':'1.1. Bao bì','bbox':[0,0,100,20]},
        {'row':0,'col':1,'text':'3','bbox':[100,0,120,20]},
        {'row':1,'col':0,'text':'Đóng gói sáng tạo, bao bì đẹp','bbox':[0,20,100,40],
         'image_marker_candidates':[{'text':'***','bbox':[70,25,90,35]}]},
        {'row':1,'col':1,'text':'2','bbox':[100,20,120,40]}]}
    u['spans'][0].update(table_id='table:synthetic',bbox=[0,0,120,40])
    units.append(u)
    if note:
        text = ('4. Bộ sản phẩm: Phiếu khác\n' if next_sheet else '') + (
            'Ghi chú: Dấu sao là yêu cầu tối thiểu phải đạt theo các cấp độ sao '
            '(*** - 3 sao; **** - 4 sao; ***** - 5 sao).')
        units.append(unit('DOC.CURRENT',4 if gap else 3,text,'paragraph'))
    return units


def test_star_thresholds_are_observed_candidates_with_open_lower_bound():
    result = extract(fixture())
    stars = {e['attributes']['star_level']:e for e in result['business_entities'] if e['kind']=='StarLevel'}
    assert set(stars)=={1,2,3,4,5}
    assert [(stars[n]['attributes']['min_points'],stars[n]['attributes']['max_points'])
            for n in range(1,6)]==[(None,30),(30,50),(50,70),(70,90),(90,100)]
    assert stars[5]['attributes']['max_inclusive'] is True
    assert stars[4]['attributes']['max_inclusive'] is False
    assert all(e['status']=='candidate' for e in stars.values())


def test_image_marker_targets_option_with_its_own_sheet_legend(tmp_path):
    units = fixture()
    result = extract(units)
    es = {e['entity_id']:e for e in result['business_entities']}
    edges = [r for r in result['business_relations'] if r['relation_type']=='MINIMUM_FOR']
    assert len(edges)==1
    edge = edges[0]
    assert es[edge['source_entity_id']]['kind']=='ScoreOption'
    assert es[edge['target_entity_id']]['attributes']['star_level']==3
    assert edge['attributes']['interpretation_verified'] is False
    assert edge['attributes']['marker_observed_in']=='image_marker_candidate'
    assert {r['pdf_page'] for r in edge['evidence']}=={2,3}
    assert edge['evidence'][0]['cell_id']=='table:synthetic:r1:c0'
    assert '***' not in edge['evidence'][0]['quote']
    from ai_core.graph.ocop.builder import build_graph
    knowledge = tmp_path/'knowledge'
    knowledge.mkdir()
    (knowledge/'manifest.json').write_text(json.dumps({'complete':True,'corpus_version':'stars'}))
    for name, rows in {'evidence_units':units,**result}.items():
        (knowledge/f'{name}.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    assert build_graph(knowledge,tmp_path/'graph')['counts']['rejected']==0


def test_legend_from_another_sheet_or_across_missing_pages_does_not_apply():
    for kwargs in ({'note':False},{'header':False},{'gap':True},{'next_sheet':True}):
        result = extract(fixture(**kwargs))
        assert not any(r['relation_type']=='MINIMUM_FOR' for r in result['business_relations'])


def test_explicit_legend_mapping_is_used_instead_of_assuming_marker_length():
    units = fixture()
    units[-1]['text'] = units[-1]['text'].replace('*** - 3 sao','*** - 4 sao')
    result = extract(units)
    edge = next(r for r in result['business_relations'] if r['relation_type']=='MINIMUM_FOR')
    target = next(e for e in result['business_entities'] if e['entity_id']==edge['target_entity_id'])
    assert target['attributes']['star_level']==4


def test_cached_marker_disagreement_is_omitted_without_rewriting_ocr():
    units=fixture()
    cell=next(u for u in units if u['unit_kind']=='criterion_table_candidate')['structured']['cells'][2]
    cell['independent_marker_counts_candidate']=[4]
    result=extract(units)
    assert not any(r['relation_type']=='MINIMUM_FOR' for r in result['business_relations'])
    assert cell['image_marker_candidates'][0]['text']=='***'
    assert any(r['reason']=='option_star_geometry_disagreement' for r in result['business_omissions'])


def test_pixel_groups_recognize_internal_runs_without_guessing_repeated_letters():
    import cv2
    import numpy as np
    from ocop_ocr.legend_proposals import asterisk_groups
    image = np.full((30,400),255,dtype=np.uint8)
    cv2.putText(image,'(*** - 3; **** - 4; ***** - 5)',(8,20),cv2.FONT_HERSHEY_SIMPLEX,.45,0,1,cv2.LINE_AA)
    assert [text for text,_ in asterisk_groups(image)]==['***','****','*****']
    image[:]=255
    cv2.putText(image,'xxxxx aaaaa abcddd',(8,20),cv2.FONT_HERSHEY_SIMPLEX,.45,0,1,cv2.LINE_AA)
    assert asterisk_groups(image)==[]


def test_image_legend_candidates_keep_corrupted_ocr_quote_and_candidate_status():
    units = fixture()
    text = 'Ghi chú: Dấu sao là yêu cầu tối thiểu phải đạt theo các cấp độ sao (44%. 3 sao; 44%-4 sao; đặc đ% 5 sao)'
    units[-1]['text'] = text
    units[-1]['structured']['image_legend_candidates'] = [
        {'text':'***','star_level_candidate':3,'status':'candidate','interpretation_verified':False}]
    result = extract(units)
    edge = next(r for r in result['business_relations'] if r['relation_type']=='MINIMUM_FOR')
    assert edge['status']=='candidate'
    assert edge['attributes']['interpretation_verified'] is False
    assert edge['evidence'][1]['quote']==text
