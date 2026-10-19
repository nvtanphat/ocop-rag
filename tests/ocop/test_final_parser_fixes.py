"""Synthetic source geometry and sentences; no real-PDF gold labels."""
from tests.ocop.test_legal_structure import unit, extract


def test_transition_heading_is_not_a_temporal_assertion():
    result=extract([unit('DOC.CURRENT',13,'Điều 12. Điều khoản chuyển tiếp\n'
        '1. Giấy chứng nhận có giá trị trong thời hạn 36 tháng.')])
    assert not any(r['statement'].strip()=='Điều 12. Điều khoản chuyển tiếp' for r in result['business_rules'])
    assert any(r['kind']=='temporal' and '36 tháng' in r['statement'] for r in result['business_rules'])


def test_nominal_dossier_list_is_not_an_action_step():
    result=extract([unit('DOC.CURRENT',5,'Điều 6. Hồ sơ\n'
        '1. Hồ sơ đề nghị đánh giá, do UBND cấp tỉnh chuẩn bị, bao gồm:\n'
        'a) Phiếu đăng ký.\n2. UBND cấp tỉnh chuẩn bị hồ sơ theo quy định.')])
    steps=[e for e in result['business_entities'] if e['kind']=='ProcedureStep']
    assert len(steps)==1 and steps[0]['label'].startswith('2. UBND')


def test_scoring_notes_are_not_options_including_continuation():
    from tests.ocop.test_criterion_sheets import fixture,table
    units=fixture()
    units[5]=table(3,[('Phần A: SẢN PHẨM',40),('1. TỔ CHỨC SẢN XUẤT',40),
        ('1.1. Tiêu chí',40),('Phương án thấp',20),
        ('Chú ý: Không đánh giá bước tiếp theo khi mất an toàn thực phẩm.','')])
    units[6]=table(4,[('Chi áp dụng khi có câu chuyện sản phẩm',''),('Phương án cao',40)])
    units[6]['structured']['table_continuity']=[{'from_pdf_page':3,'to_pdf_page':4,'from_table_id':'table:3','to_table_id':'table:4'}]
    result=extract(units)
    labels=[e['label'] for e in result['business_entities'] if e['kind']=='ScoreOption']
    assert set(labels)=={'Phương án thấp','Phương án cao'}


def test_conditional_inspection_and_output_are_not_required_inputs():
    result=extract([unit('DOC.CURRENT',9,'Điều 7. Trình tự\n'
        '1. Cơ quan tham mưu quản lý OCOP cấp tỉnh kiểm tra thực tế nếu hồ sơ minh chứng không rõ ràng.\n'
        '2. UBND cấp tỉnh xem xét kết quả; UBND cấp tỉnh có văn bản và gửi hồ sơ đến Bộ Y tế.\n'
        '3. UBND cấp xã đề nghị chủ thể chuẩn bị đầy đủ hồ sơ, tài liệu minh chứng và nộp đúng hạn.')])
    es={e['entity_id']:e for e in result['business_entities']}
    requirements=[r for r in result['business_relations'] if r['relation_type']=='REQUIRES_EVIDENCE']
    assert len(requirements)==1
    assert es[requirements[0]['target_entity_id']]['label']=='tài liệu minh chứng'
    assert any('input' in r['reason'] for r in result['business_omissions'])


def test_coordinated_authorities_have_separate_responsibilities():
    result=extract([unit('DOC.CURRENT',10,'Điều 8. Thu hồi\n'
        '1. Chủ tịch UBND cấp tỉnh và Bộ trưởng Bộ Nông nghiệp và Môi trường xem xét hồ sơ.\n'
        '2. Bộ Y tế, Bộ Công Thương và Bộ Nông nghiệp và Môi trường kiểm tra hồ sơ.')])
    es={e['entity_id']:e for e in result['business_entities']}
    groups={}
    for r in result['business_relations']:
        if r['relation_type']=='RESPONSIBLE_FOR':
            groups.setdefault(r['target_entity_id'],set()).add(es[r['source_entity_id']]['label'])
    assert sorted(map(len,groups.values()))==[2,3]


def test_annex_banner_stops_article_even_with_ocr_unaccented_luc():
    result=extract([unit('DOC.AMEND',2,'Điều 3. Thi hành\n1. Bộ Y tế tổ chức thực hiện.'),
        unit('DOC.AMEND',3,'Kèm theo Quyết định số 1489/QĐ-TTg\nPhụ luc\n'
             '1. Bãi bỏ nội dung cũ.','paragraph'),
        unit('DOC.AMEND',4,'2. Nội dung phụ lục tiếp theo.','paragraph')])
    articles=[e for e in result['business_entities'] if e['kind']=='Article']
    assert len(articles)==1
    assert {r['pdf_page'] for r in articles[0]['evidence']}=={2}
    assert len([e for e in result['business_entities'] if e['kind']=='Clause'])==1


def test_issuer_uses_left_column_lines_and_preserves_each_literal_ref():
    lines=[('Email CHÍNH PHỦ',[10,1,120,8]),('ỦY BAN NHÂN DÂN',[20,20,180,35]),
           ('CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM',[300,20,580,35]),
           ('THÀNH PHỐ VÍ DỤ',[20,37,180,52]),('Độc lập – Tự do',[320,37,500,52]),
           ('Số: /QĐ-UBND',[20,65,170,80]),('QUYẾT ĐỊNH',[210,100,390,115])]
    u=unit('DOC.RECOGNITION',1,'\n'.join(t for t,_ in lines),'paragraph')
    u['structured']['quote_lines']=[{'text':t,'bbox':b,'pdf_page':1} for t,b in lines]
    result=extract([u],{'DOC.RECOGNITION':'recognition_decision'})
    doc=next(e for e in result['business_entities'] if e['kind']=='SourceDocument')
    assert doc['attributes']['issuer_candidate']=='ỦY BAN NHÂN DÂN\nTHÀNH PHỐ VÍ DỤ'
    assert {'ỦY BAN NHÂN DÂN','THÀNH PHỐ VÍ DỤ'}<={r['quote'] for r in doc['evidence']}
