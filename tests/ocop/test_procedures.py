"""Synthetic procedural evidence; no real-PDF unit fixtures."""
import json
from tests.ocop.test_legal_structure import unit,extract
from tests.ocop.test_criterion_sheets import table


def test_missing_punctuation_stops_at_actor_and_contact_heading():
    text=('6. Đề nghị các chủ thể đăng ký\n'
          'UBND phường Thành Sen đề nghị các chủ thể chuẩn bị hồ sơ, tài liệu minh chứng\n'
          'và gửi về phường đúng thời hạn\n'
          'UBND phường Thành Sen sẽ hướng dẫn các chủ thể hoàn thiện hồ sơ\n'
          'và nâng cao chất lượng sản phẩm\n'
          'THÔNG TIN LIÊN HỆ, HƯỚNG DẪN\n'
          'Điện thoại: 0123456789')
    result=extract([unit('DOC.LOCAL',4,text,'paragraph')],{'DOC.LOCAL':'local_guidance'},
                   registry={'DOC.LOCAL':{'document_number':None}})
    steps=[e for e in result['business_entities'] if e['kind']=='ProcedureStep']
    assert len(steps)==2
    assert all('THÔNG TIN' not in e['evidence'][0]['quote'] and
               not e['evidence'][0]['quote'].startswith('6.') for e in steps)
    assert all(e['evidence'][0]['quote'] in text for e in steps)
    docs=[e for e in result['business_entities'] if e['kind']=='EvidenceType']
    assert docs and all('sẽ hướng dẫn' not in r['quote'] for e in docs for r in e['evidence'])


def test_authority_aliases_merge_evidence_within_document_only():
    result=extract([
        unit('DOC.CURRENT',5,'Điều 7. Trình tự\n1. UBND cấp xã kiểm tra hồ sơ.\n'
             '2. ỦY BAN NHÂN DÂN CẤP XÃ tiếp nhận hồ sơ.'),
        unit('DOC.AMEND',2,'Điều 1. Trình tự\n1. UBND cấp xã tiếp nhận hồ sơ.')])
    authorities=[e for e in result['business_entities'] if e['kind']=='Authority']
    assert len(authorities)==2
    assert len({e['entity_id'] for e in authorities})==2
    assert len({e['attributes']['canonical_id'] for e in authorities})==1
    current=next(e for e in authorities if e['source_id']=='DOC.CURRENT')
    assert current['label']=='UBND cấp xã' and len(current['evidence'])==2
    assert all(e['source_id']==current['source_id'] for e in current['evidence'])


def test_accentless_alias_keeps_literal_ocr_quote_and_distinguishes_chair():
    result=extract([unit('DOC.CURRENT',5,'Điều 7. Trình tự\n'
        '1. UBND cap xa kiểm tra hồ sơ.\n2. Chủ tịch UBND cấp xã tổ chức đánh giá hồ sơ.')])
    authorities=[e for e in result['business_entities'] if e['kind']=='Authority']
    assert {e['label'] for e in authorities}=={'UBND cấp xã','Chủ tịch UBND cấp xã'}
    assert any(r['quote']=='UBND cap xa' for e in authorities for r in e['evidence'])


def test_document_noun_is_bounded_noise_and_scoring_options_are_excluded():
    result=extract([unit('DOC.CURRENT',4,'Điều 6. Hồ sơ\n'
        '1. UBND cấp xã chuẩn bị hồ sơ gồm tài liệu minh chứng và gửi về cấp tỉnh.\n'
        '2. UBND cấp xã kiểm tra văn bản ghi nhận quyền sử dụng)ea trong hồ sơ.'),
        table(18,[('1.1. Chất lượng',3),('Có hợp đồng liên kết trên 75% sản lượng',2)])])
    docs=[e for e in result['business_entities'] if e['kind']=='EvidenceType']
    assert [e['label'] for e in docs]==['tài liệu minh chứng']


def test_certificate_validity_becomes_temporal_candidate_not_action():
    result=extract([unit('DOC.LOCAL',4,'Giấy chứng nhận có giá trị trong thời hạn 36 tháng kể từ ngày ban hành.',
        'paragraph')],{'DOC.LOCAL':'local_guidance'},registry={'DOC.LOCAL':{'document_number':None}})
    assert not any(e['kind']=='ProcedureStep' for e in result['business_entities'])
    assert any(r['kind']=='temporal' and '36 tháng' in r['evidence'][0]['quote'] and
               r['status']=='candidate' for r in result['business_rules'])


def test_reporting_to_authority_is_a_verb_not_an_evidence_type():
    result=extract([unit('DOC.CURRENT',7,'Điều 7. Trình tự\n'
        '1. UBND cấp xã kiểm tra hồ sơ, tổng hợp, báo cáo Bộ Y tế.')])
    assert not any(e['kind']=='EvidenceType' for e in result['business_entities'])


def test_document_subordinate_ministry_does_not_supply_actor_to_dossier_list():
    result=extract([unit('DOC.CURRENT',4,'Điều 6. Hồ sơ\n1. Hồ sơ bao gồm:\n'
        'a) Bản tự công bố sản phẩm theo mẫu.\n'
        'b) Phiếu kiểm nghiệm gồm chỉ tiêu an toàn do Bộ Y tế ban hành.')])
    assert not any(e['kind']=='ProcedureStep' for e in result['business_entities'])


def test_wrapped_chair_title_stays_with_authority_and_description_is_separate():
    result=extract([unit('DOC.CURRENT',6,'Điều 7. Trình tự\n'
        '1. Khi cần thiết, Chủ tịch\nUBND cấp xã tổ chức họp đánh giá hồ sơ\n'
        'Thành phần gồm các đơn vị liên quan.')])
    steps=[e for e in result['business_entities'] if e['kind']=='ProcedureStep']
    assert len(steps)==1 and steps[0]['attributes']['authority_candidate']=='Chủ tịch UBND cấp xã'
    assert 'Thành phần' not in steps[0]['evidence'][0]['quote']


def test_from_and_up_to_are_not_actors_and_issued_documents_are_outputs():
    result=extract([unit('DOC.CURRENT',7,'Điều 7. Trình tự\n'
        '1. Việc tiếp nhận hồ sơ từ UBND cấp xã, kiểm tra hồ sơ do cơ quan tham mưu quản lý OCOP cấp tỉnh chủ trì.\n'
        '2. UBND cấp xã gửi hồ sơ lên Bộ Y tế đề nghị đánh giá sản phẩm.\n'
        '3. UBND cấp xã ban hành các văn bản hướng dẫn hồ sơ.')])
    es={e['entity_id']:e for e in result['business_entities']}
    assert all(es[r['source_entity_id']]['label']!='Bộ Y tế' for r in result['business_relations'] if r['relation_type']=='RESPONSIBLE_FOR')
    assert not any(e['kind']=='EvidenceType' for e in es.values())


def test_an_earlier_action_does_not_make_actor_a_list_declaration():
    result=extract([unit('DOC.CURRENT',7,'Điều 7. Trình tự\n'
        '1. UBND cấp tỉnh tiếp nhận hồ sơ.\n'
        '- Tổ chức họp đánh giá hồ sơ.\n'
        '- Chuẩn bị hồ sơ điện tử.')])
    steps=[e for e in result['business_entities'] if e['kind']=='ProcedureStep']
    assert len(steps)==1 and steps[0]['attributes']['statement_candidate'].startswith('1.')


def test_revised_legislation_and_issued_reports_are_not_required_papers():
    result=extract([unit('DOC.CURRENT',7,'Điều 7. Trình tự\n'
        '1. Bộ Y tế rà soát, sửa đổi, bổ sung các văn bản hướng dẫn.\n'
        '2. UBND cấp xã ban hành báo cáo đánh giá hồ sơ theo Mẫu số 03 và văn bản đề nghị.')])
    assert not any(r['relation_type']=='REQUIRES_EVIDENCE' for r in result['business_relations'])


def test_authority_deadline_unit_and_consecutive_page_inheritance(tmp_path):
    units=[unit('DOC.CURRENT',5,'Điều 7. Trình tự\n2. Tiếp nhận và đánh giá hồ sơ.\nTrong thời hạn 15 ngày làm việc kể từ ngày tiếp nhận hồ sơ, UBND cấp xã:'),
           unit('DOC.CURRENT',6,'a) Kiểm tra thành phần hồ sơ và đánh giá nội dung.\n'
                'b) Ban hành báo cáo, văn bản đề nghị UBND cấp tỉnh đánh giá; gửi hồ sơ đến UBND cấp tỉnh.','paragraph')]
    result=extract(units)
    es={e['entity_id']:e for e in result['business_entities']}
    edges=[r for r in result['business_relations'] if r['relation_type']=='RESPONSIBLE_FOR']
    assert edges
    assert all(es[r['source_entity_id']]['label']=='UBND cấp xã' for r in edges)
    continued=next(es[r['target_entity_id']] for r in edges if r['evidence'][0]['pdf_page']==6)
    assert continued['attributes']['deadline']==15
    assert continued['attributes']['deadline_unit']=='ngày làm việc'
    assert {e['pdf_page'] for e in continued['evidence']}=={5,6}
    from ai_core.graph.ocop.builder import build_graph
    knowledge=tmp_path/'knowledge';knowledge.mkdir()
    (knowledge/'manifest.json').write_text(json.dumps({'complete':True,'corpus_version':'procedures'}))
    for name,rows in {'evidence_units':units,**result}.items():
        (knowledge/f'{name}.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    assert build_graph(knowledge,tmp_path/'graph')['counts']['rejected']==0


def test_recipient_is_not_asserted_as_subject_and_calendar_year_is_not_imputed():
    result=extract([unit('DOC.CURRENT',5,
        'Điều 7. Trình tự\n1. Chủ thể nộp hồ sơ cho UBND cấp xã trước ngày 30 tháng 4.')])
    steps=[e for e in result['business_entities'] if e['kind']=='ProcedureStep']
    assert not steps  # a recipient alone cannot establish the procedure actor
    from ai_core.knowledge.ocop.procedures import _deadline
    assert _deadline('trước ngày 30 tháng 4')['deadline_date_candidate'] is None
    assert not any(r['relation_type']=='RESPONSIBLE_FOR' for r in result['business_relations'])


def test_headings_bases_validity_and_signature_text_are_not_action_steps():
    units=[unit('DOC.CURRENT',4,
        'Điều 6. Hồ sơ\n1. Trình tự thu hồi giấy chứng nhận\n'
        '2. Căn cứ Quyết định số 148/QĐ-TTg.\n'
        '3. Giấy chứng nhận có giá trị 36 tháng.\n'
        '4. Email chinhphu.vn UBND cấp xã hướng dẫn hồ sơ.\n'
        '5. UBND cấp xã kiểm tra hồ sơ trong 15 ngày làm việc.')]
    result=extract(units)
    steps=[e for e in result['business_entities'] if e['kind']=='ProcedureStep']
    assert len(steps)==1
    assert steps[0]['attributes']['action_candidate']=='kiểm tra'
    assert steps[0]['attributes']['object_candidate'].startswith('hồ sơ')
    assert steps[0]['attributes']['deadline']==15


def test_regular_days_and_multiple_deadlines_stay_distinct():
    result=extract([unit('DOC.CURRENT',10,
        'Điều 8. Thu hồi\n1. UBND cấp tỉnh quyết định thu hồi trong 15 ngày.\n'
        '2. Hồ sơ nộp không sớm hơn 180 ngày và không muộn hơn 120 ngày.')])
    steps=[e for e in result['business_entities'] if e['kind']=='ProcedureStep']
    assert any(e['attributes']['deadline']==15 and e['attributes']['deadline_unit']=='ngày' for e in steps)
    assert not any('180' in e['attributes']['statement_candidate'] for e in steps)
    from ai_core.knowledge.ocop.procedures import _deadline
    window=_deadline('không sớm hơn 180 ngày và không muộn hơn 120 ngày')
    assert window['deadline'] is None
    assert '120' in window['deadline_mentions_candidate']


def test_explicit_evidence_type_attaches_to_criterion_and_procedure():
    criterion=table(2,[('1.1. Chất lượng',3),('Yêu cầu: Có phiếu kiểm nghiệm hợp lệ','')])
    units=[criterion,unit('DOC.CURRENT',4,
        'Điều 6. Hồ sơ\n1. UBND cấp xã chuẩn bị hồ sơ gồm phiếu đăng ký theo Mẫu số 01 Phụ lục III.')]
    result=extract(units)
    es={e['entity_id']:e for e in result['business_entities']}
    sources={es[r['source_entity_id']]['kind'] for r in result['business_relations'] if r['relation_type']=='REQUIRES_EVIDENCE'}
    assert sources=={'Criterion','ProcedureStep'}
    assert all(es[r['target_entity_id']]['kind']=='EvidenceType' for r in result['business_relations'] if r['relation_type']=='REQUIRES_EVIDENCE')


def test_local_scope_and_referenced_forms_remain_candidates_with_unknown_fields():
    u=unit('DOC.LOCAL',1,
        'UBND phường Thành Sen hướng dẫn nộp hồ sơ trước ngày 15/10/2026.\n'
        'Hồ sơ gồm Phiếu theo Mẫu số 01, Phụ lục III và báo cáo theo Mẫu số 02, Phụ lục III.','paragraph')
    result=extract([u],{'DOC.LOCAL':'local_guidance'},registry={'DOC.LOCAL':{'document_number':None}})
    assert any(r['relation_type']=='APPLIES_IN' for r in result['business_relations'])
    forms=[e for e in result['business_entities'] if e['kind']=='FormTemplate']
    assert {e['attributes']['form_number'] for e in forms}=={'01','02'}
    assert all(e['attributes']['annex_number_candidate']=='III' and e['attributes']['fields_candidate'] is None for e in forms)
    assert any(e['kind']=='ProcedureStep' and e['attributes']['deadline_date_candidate']=='2026-10-15' for e in result['business_entities'])
    assert any(e['kind']=='ProcedureStep' and e['attributes']['deadline_inclusive_candidate'] is False for e in result['business_entities'])
    assert all(e['status']=='candidate' for e in result['business_entities'])


def test_collective_ministry_header_is_not_replaced_by_report_recipient():
    result=extract([unit('DOC.CURRENT',2,
        'Điều 3. Trách nhiệm\n1. Các Bộ: Y tế, Công Thương, Nông nghiệp và Môi trường\n'
        'a) Chủ động rà soát văn bản và gửi về Bộ Y tế để tổng hợp.\n'
        '2. Bộ Công Thương: Kiểm tra, giám sát kinh doanh trên nền tảng thương mại điện tử.')],
        {'DOC.CURRENT':'food_safety_resolution'})
    es={e['entity_id']:e for e in result['business_entities']}
    review={es[r['source_entity_id']]['label'] for r in result['business_relations']
            if r['relation_type']=='RESPONSIBLE_FOR' and 'rà soát' in es[r['target_entity_id']]['attributes']['statement_candidate']}
    assert review=={'Bộ Y tế','Bộ Công Thương','Bộ Nông nghiệp và Môi trường'}
    assert any(r['relation_type']=='RESPONSIBLE_FOR' and es[r['source_entity_id']]['label']=='Bộ Công Thương'
               and 'thương mại điện tử' in es[r['target_entity_id']]['attributes']['statement_candidate']
               for r in result['business_relations'])


def test_certificate_output_and_negative_option_are_not_evidence_requirements():
    units=[unit('DOC.CURRENT',3,
        'Điều 4. Công nhận\n1. Bộ Nông nghiệp và Môi trường quyết định công nhận, cấp giấy chứng nhận OCOP 5 sao.'),
        table(18,[('1.1. Chất lượng',3),('□ Không được cấp giấy chứng nhận chất lượng',0)])]
    result=extract(units)
    assert not any(r['relation_type']=='REQUIRES_EVIDENCE' for r in result['business_relations'])


def test_named_advisory_role_is_actor_and_submitted_to_chair_is_not():
    result=extract([unit('DOC.CURRENT',6,
        'Điều 7. Trình tự\n3. Cơ quan tham mưu quản lý OCOP cấp tỉnh tổng hợp hồ sơ, '
        'trình Chủ tịch UBND cấp tỉnh quyết định công nhận.')])
    es={e['entity_id']:e for e in result['business_entities']}
    actors={es[r['source_entity_id']]['label'] for r in result['business_relations'] if r['relation_type']=='RESPONSIBLE_FOR'}
    assert actors=={'Cơ quan tham mưu quản lý OCOP cấp tỉnh'}


def test_mid_line_actor_after_sentence_end_starts_a_new_step():
    from ai_core.knowledge.ocop.extractor import _rule_sentences
    from ai_core.knowledge.ocop.procedures import _procedure_sentences
    text = ("a) Chủ thể OCOP chuẩn bị hồ sơ đăng ký tham gia đánh giá, nâng hạng theo\n"
            "quy định tại điểm b khoản 1 Điều 6 Quyết định này UBND cấp xã chuẩn bị hồ sơ\n"
            "theo quy định tại khoản 2 Điều 6 Quyết định này. UBND cấp tỉnh chuẩn bị hồ sơ")
    steps = _procedure_sentences(text, _rule_sentences)
    assert [s.split()[0:3] for s in steps] == [["a)", "Chủ", "thể"], ["UBND", "cấp", "xã"], ["UBND", "cấp", "tỉnh"]]
    assert all(step in text for step in steps)          # literal slices, nothing inserted


def test_delegation_inside_a_sentence_is_not_split():
    from ai_core.knowledge.ocop.extractor import _rule_sentences
    from ai_core.knowledge.ocop.procedures import _procedure_sentences
    text = "Chủ tịch UBND cấp tỉnh giao UBND cấp xã tổ chức họp đánh giá sản phẩm."
    assert _procedure_sentences(text, _rule_sentences) == [text]


def test_ocr_tone_variant_of_de_nghi_still_marks_a_recipient():
    from ai_core.knowledge.ocop.procedures import _subjects
    text = ("Hội đồng cấp trung ương tổ chức họp, báo cáo kết quả đánh giá và để nghị "
            "Bộ trưởng Bộ Nông nghiệp và Môi trường công nhận sản phẩm.")
    assert [m[0] for m in _subjects(text)] == ["Hội đồng cấp trung ương"]
