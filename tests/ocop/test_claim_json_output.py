"""Claim-level JSON answers: publish what passes every gate, drop the rest, say what is missing."""
import json

from ai_core.orchestration.ocop.answer import assemble


def row(text, *, unit='u1', status='verified', page=2):
    return {'source_id': 'D', 'evidence_unit_id': unit, 'source_spans': [{'pdf_page': page}],
            'review_status': status, 'text': text}


def results(*rows):
    return [{'tool': 'search_regulations', 'output': {'results': list(rows)}}]


class Model:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def chat(self, *args, **kwargs):
        raise AssertionError('structured path expected')

    def chat_structured(self, system, user, *, schema, max_tokens=1024):
        self.calls.append(schema)
        return json.dumps(self.payload)


def test_only_supported_claims_are_published_and_gaps_are_named():
    model = Model({'claims': [
        {'text': 'Hạt sen được công nhận hạng ba sao', 'sources': ['S1']},
        {'text': 'Giá bán là 99 nghìn đồng', 'sources': ['S1']},
    ], 'missing': ['giá bán']})
    out = assemble('Hạt sen được công nhận hạng nào?', results(row('Hạt sen được công nhận hạng ba sao.')), llm=model)
    assert out['status'] == 'partial_claims_verified'
    assert 'ba sao [S1]' in out['answer'] and '99' not in out['answer'].split('[Đã loại')[0]
    assert 'Nguồn chưa trả lời: giá bán' in out['answer']
    assert out['generation_diagnostics']['rejected'][0]['claim'].startswith('Giá bán')
    assert model.calls and model.calls[0]['required'] == ['claims', 'missing']


def test_grounded_claim_from_unreviewed_source_is_shown_labelled_never_as_verified():
    model = Model({'claims': [{'text': 'Hạt sen được công nhận hạng ba sao', 'sources': ['S1']}], 'missing': []})
    out = assemble('Hạt sen hạng nào?', results(row('Hạt sen được công nhận hạng ba sao.', status='needs_review')), llm=model)
    assert out['status'] == 'generated_unverified_claims'
    assert out['answer'].startswith('[LƯU Ý: Nguồn OCR/trích xuất chưa được duyệt')


def test_unreviewed_source_claim_must_still_be_grounded_in_the_cited_excerpt():
    cases = {
        'Hạt sen được nộp 2 bộ hồ sơ': 'grounding_numbers_missing',                   # number not in the excerpt
        'Hạt sen không được công nhận': 'grounding_negation_mismatch',               # negation the excerpt lacks
        'Quy định về bao bì sản phẩm xuất khẩu': 'grounding_terms_missing',          # invented content
    }
    for claim, reason in cases.items():
        model = Model({'claims': [{'text': claim, 'sources': ['S1']}], 'missing': []})
        out = assemble('Hạt sen hạng nào?', results(row('Hạt sen được công nhận hạng ba sao.', status='needs_review')), llm=model)
        assert out['status'] == 'citation_verification_failed', claim
        assert reason in out['generation_diagnostics']['reasons'], (claim, out['generation_diagnostics']['reasons'])


def test_star_and_score_claims_from_unreviewed_sources_stay_blocked():
    model = Model({'claims': [{'text': 'Sản phẩm đạt 4 sao', 'sources': ['S1']}], 'missing': []})
    out = assemble('Sản phẩm đạt mấy sao?', results(row('Sản phẩm đạt 4 sao theo OCR.', status='needs_review')), llm=model)
    assert out['status'] == 'citation_verification_failed'
    assert 'unsupported_score_or_star_claims' in out['generation_diagnostics']['reasons']


def test_claim_without_valid_source_id_is_rejected():
    model = Model({'claims': [{'text': 'Hạt sen được công nhận hạng ba sao', 'sources': ['S9']}], 'missing': []})
    out = assemble('Hạt sen hạng nào?', results(row('Hạt sen được công nhận hạng ba sao.')), llm=model)
    assert out['status'] == 'citation_verification_failed'
    assert 'unknown_citation_markers' in out['generation_diagnostics']['reasons']


def test_score_claim_needs_verified_text_support():
    model = Model({'claims': [{'text': 'Sản phẩm đạt 90 điểm', 'sources': ['S1']}], 'missing': []})
    out = assemble('Sản phẩm đạt bao nhiêu điểm?', results(row('Sản phẩm được đánh giá.')), llm=model)
    assert out['status'] == 'citation_verification_failed'


def test_generation_is_skipped_when_the_prompt_source_does_not_cover_the_question():
    model = Model({'claims': [], 'missing': []})
    out = assemble('Thời hạn nộp hồ sơ đánh giá lại bao lâu?', results(row('Danh sách thành viên hội đồng thẩm định.')), llm=model)
    assert out['status'] == 'insufficient_context_for_generation' and not model.calls


def _catalog(**kinds):
    from ai_core.orchestration.ocop.catalog import EntityCatalog
    return EntityCatalog({'entities': {k: [{'label': v, 'source_ids': []} for v in vs] for k, vs in kinds.items()}})


def test_generic_legal_rule_naming_star_levels_may_be_shown_when_unreviewed_and_grounded():
    text = 'UBND cấp tỉnh quyết định công nhận sản phẩm OCOP 3 sao, 4 sao.'
    model = Model({'claims': [{'text': 'UBND cấp tỉnh quyết định công nhận sản phẩm OCOP 3 sao, 4 sao', 'sources': ['S1']}], 'missing': []})
    out = assemble('Cơ quan nào công nhận?', results(row(text, status='needs_review')), llm=model, catalog=_catalog(product=['Mứt Dâu']))
    assert out['status'] == 'generated_unverified_claims'
    blocked = assemble('Cơ quan nào công nhận?', results(row(text, status='needs_review')), llm=model)   # no catalog: stay blocked
    assert blocked['status'] == 'citation_verification_failed'


def test_rating_of_a_catalogued_product_in_prose_stays_blocked_until_verified():
    text = 'Công nhận sản phẩm Mứt Dâu đạt 4 sao.'
    model = Model({'claims': [{'text': 'Sản phẩm Mứt Dâu đạt 4 sao', 'sources': ['S1']}], 'missing': []})
    out = assemble('Mứt Dâu mấy sao?', results(row(text, status='needs_review')), llm=model, catalog=_catalog(product=['Mứt Dâu']))
    assert out['status'] == 'citation_verification_failed'
    assert 'unsupported_score_or_star_claims' in out['generation_diagnostics']['reasons']


def test_review_status_disclaimers_are_not_claims():
    model = Model({'claims': [{'text': 'Hạt sen được công nhận hạng ba sao', 'sources': ['S1']},
                              {'text': 'Bản OCR của tài liệu chưa được xác minh', 'sources': ['S1']}], 'missing': ['Nội dung OCR chưa được xác minh']})
    out = assemble('Hạt sen hạng nào?', results(row('Hạt sen được công nhận hạng ba sao.', status='needs_review')), llm=model)
    assert out['status'] == 'generated_unverified_claims' and 'Đã loại' not in out['answer'] and 'Nguồn chưa trả lời' not in out['answer']


def test_grounding_compares_dates_by_value_not_format():
    from ai_core.orchestration.ocop.verification import grounded_in_excerpt
    source = 'Quyết định này có hiệu lực kể từ ngày 22/05/2026 và thay thế Quyết định số 1489/QĐ-TTg.'
    ok, _ = grounded_in_excerpt('Quyết định có hiệu lực từ ngày 22 tháng 5 năm 2026 và thay thế Quyết định số 1489/QĐ-TTg.',
                                source, min_term_coverage=0.8)
    assert ok
    bad, reason = grounded_in_excerpt('Quyết định có hiệu lực từ ngày 23 tháng 5 năm 2026.', source, min_term_coverage=0.8)
    assert not bad and reason == 'grounding_numbers_missing'


def test_numbers_in_the_cited_document_identity_are_grounded():
    unit = row('Quyết định này có hiệu lực thi hành từ ngày 22 tháng 5 năm 2026.', status='needs_review')
    unit['source_id'] = 'VN.OCOP.QD26.2026'
    model = Model({'claims': [{'text': 'Quyết định 26/2026 có hiệu lực từ ngày 22 tháng 5 năm 2026', 'sources': ['S1']}], 'missing': []})
    out = assemble('QĐ26/2026 có hiệu lực từ ngày nào?', results(unit), llm=model)
    assert out['status'] == 'generated_unverified_claims'


def test_grounding_accepts_restated_question_number_and_range_member_but_not_new_figures():
    from ai_core.orchestration.ocop.verification import grounded_in_excerpt
    source = 'Sản phẩm OCOP đạt từ 3 sao đến 5 sao trước ngày Quyết định có hiệu lực tiếp tục có giá trị đến hết thời hạn.'
    claim = 'Sản phẩm OCOP đạt 4 sao trước ngày Quyết định có hiệu lực tiếp tục có giá trị đến hết thời hạn.'
    assert grounded_in_excerpt(claim, source, min_term_coverage=0.8)[0]  # 4 lies in the stated 3..5
    assert grounded_in_excerpt(claim.replace('4 sao', '7 sao'), source, min_term_coverage=0.8)[1] == 'grounding_numbers_missing'
    assert grounded_in_excerpt(claim.replace('4 sao', '7 sao'), source, min_term_coverage=0.8, asked='đạt 7 sao')[0]
    assert grounded_in_excerpt(claim.replace('4 sao', '9 sao'), source, min_term_coverage=0.8, asked='đạt 7 sao')[1] == 'grounding_numbers_missing'


def test_every_sentence_of_a_multi_sentence_claim_is_marked():
    from ai_core.orchestration.ocop.answer import _sentences
    assert _sentences('Có. Sản phẩm tiếp tục có giá trị.') == ['Có.', 'Sản phẩm tiếp tục có giá trị.']


def test_grounding_allows_rejecting_the_alternative_the_user_offered():
    from ai_core.orchestration.ocop.verification import grounded_in_excerpt
    source = 'Điều 1. Sửa đổi, bổ sung một số nội dung Quyết định số 148/QĐ-TTg ngày 24 tháng 02 năm 2023 của Thủ tướng Chính phủ'
    claim = 'Quyết định sửa đổi, bổ sung Quyết định 148/QĐ-TTg, không phải Quyết định 26.'
    assert grounded_in_excerpt(claim, source, min_term_coverage=0.8, asked='Sửa đổi QĐ148 hay Quyết định 26?')[0]
    assert grounded_in_excerpt(claim, source, min_term_coverage=0.8, asked='QĐ1489 sửa đổi QĐ148 hay QĐ26?')[0]
    # an alternative the user never mentioned is a new negative assertion and stays blocked
    assert not grounded_in_excerpt(claim, source, min_term_coverage=0.8, asked='Sửa đổi QĐ148?')[0]


def test_empty_claims_without_missing_are_asked_once_more(tmp_path):
    from ai_core.orchestration.ocop.answer import assemble
    calls = []

    class Flaky:
        def chat_structured(self, system, user, **kw):
            calls.append(user)
            return '{"claims":[],"missing":[]}' if len(calls) == 1 else \
                '{"claims":[{"text":"Hạn nộp hồ sơ là trước ngày 15/10/2026.","sources":["S1"]}],"missing":[]}'

    row = {'source_id': 'VN.X.2026', 'evidence_unit_id': 'u1', 'review_status': 'needs_review', 'table_backed': False,
           'text': 'Gửi hồ sơ trước ngày 15/10/2026. Hạn nộp hồ sơ là trước ngày 15/10/2026.',
           'source_spans': [{'pdf_page': 3}], 'chunk_id': 'c1'}
    out = assemble('Hạn nộp hồ sơ là khi nào?', [{'tool': 'search_regulations', 'output': {'results': [row]}}], llm=Flaky())
    assert len(calls) == 2 and 'LƯU Ý' in calls[1]
    assert out['status'] != 'citation_verification_failed'


def _unreviewed(text, page=4):
    return {'source_id': 'VN.X.2026', 'evidence_unit_id': 'u1', 'review_status': 'needs_review', 'table_backed': False,
            'text': text, 'source_spans': [{'pdf_page': page}], 'chunk_id': 'c1', 'pdf_page': page}


class _Fixed:
    def __init__(self, payload):
        self.payload = payload

    def chat_structured(self, system, user, **kw):
        return self.payload


def test_page_number_from_the_source_header_is_grounded():
    out = assemble('Mẫu số 02 nằm ở trang nào?', [{'tool': 'search_regulations', 'output': {'results': [
        _unreviewed('Báo cáo tự đánh giá về sản phẩm Mẫu số 02 Phụ lục III ban hành kèm theo Quyết định.')]}}],
        llm=_Fixed('{"claims":[{"text":"Mẫu số 02 Phụ lục III ban hành kèm theo Quyết định ở trang 4.","sources":["S1"]}],"missing":[]}'))
    assert out['status'] == 'generated_unverified_claims', out['generation_diagnostics']


def test_missing_only_answer_names_the_gap_instead_of_dumping_excerpts():
    out = assemble('Mẫu số 02 nằm ở trang nào?', [{'tool': 'search_regulations', 'output': {'results': [
        _unreviewed('Báo cáo tự đánh giá về sản phẩm Mẫu số 02 Phụ lục III.')]}}],
        llm=_Fixed('{"claims":[{"text":"Mẫu 02 nằm ở trang 99 của phụ lục.","sources":["S1"]}],"missing":["trang đặt mẫu số 02"]}'))
    assert out['status'] == 'insufficient_evidence'
    assert 'trang đặt mẫu số 02' in out['answer'] and '[S1]' not in out['answer'] and 'VN.X.2026' not in out['answer']


def test_rejected_alternative_may_be_labelled_as_a_table_column():
    from ai_core.orchestration.ocop.verification import grounded_in_excerpt
    source = 'Nguyễn Thị Hà là chủ thể của Hợp tác xã Thụy Hương'
    claim = 'Nguyễn Thị Hà là chủ thể, không phải cột “người đại diện”.'
    assert grounded_in_excerpt(claim, source, min_term_coverage=0.8, asked='Nguyễn Thị Hà là người đại diện hay chủ thể?')[0]
    assert not grounded_in_excerpt(claim, source, min_term_coverage=0.8, asked='Nguyễn Thị Hà là chủ thể?')[0]


def test_a_claim_joining_a_quote_with_a_statement_of_absence_keeps_its_grounded_half():
    from ai_core.orchestration.ocop.answer import _split_clauses
    claim = 'Tiêu chí 1.1 ghi yêu cầu: “100% sản phẩm được trồng trên địa bàn cấp tỉnh”; nguồn không hiển thị mục ghi chú riêng.'
    assert _split_clauses(claim) == ['Tiêu chí 1.1 ghi yêu cầu: “100% sản phẩm được trồng trên địa bàn cấp tỉnh”',
                                     'nguồn không hiển thị mục ghi chú riêng.']
    assert len(_split_clauses('Điều kiện “a; b” áp dụng cho mọi sản phẩm.')) == 1  # a semicolon inside a quotation stays
    assert len(_split_clauses('Quyết định sửa đổi QĐ148, không phải Quyết định 26.')) == 1  # rejecting the offered alternative
    out = assemble('Tiêu chí 1.1 có ghi chú trồng trong tỉnh không?', results(
        row('Tiêu chí 1.1 Nguồn gốc sản phẩm Yêu cầu: 100% sản phẩm được trồng trên địa bàn cấp tỉnh', status='needs_review')),
        llm=Model({'claims': [{'text': 'Tiêu chí 1.1 Nguồn gốc sản phẩm Yêu cầu: 100% sản phẩm được trồng trên địa bàn cấp tỉnh; '
                                       'nguồn không hiển thị mục ghi chú riêng về bao bì xuất khẩu.', 'sources': ['S1']}], 'missing': []}))
    assert out['status'] in ('generated_unverified_claims', 'partial_claims_verified') and 'Yêu cầu: 100%' in out['answer']
    assert out['status'] != 'citation_verification_failed'


def test_a_requested_criterion_code_keeps_its_row_when_question_terms_would_pick_other_prose():
    from ai_core.orchestration.ocop.answer import _most_relevant
    prose = [((f'S{i}', 6, f'u{i}', f'c{i}'), {'raw_text': 'đánh giá lại hồ sơ yêu cầu đánh giá tiêu chí', 'text': 'đánh giá lại hồ sơ yêu cầu'},
              {}, False) for i in range(8)]
    row = ((('S9', 28, 'u9', 'c9')), {'raw_text': '1.6. Bảo vệ môi trường | 3', 'text': '1.6. Bảo vệ môi trường | 3',
                                      'context': {'criterion_codes': ['1.6']}}, {}, True)
    kept = _most_relevant(prose + [row], ['danh', 'gia', 'tieu', 'yeu', 'cau'], 3, None, ['1.6'])
    assert row in kept
    assert row not in _most_relevant(prose + [row], ['danh', 'gia', 'tieu', 'yeu', 'cau'], 3, None, [])  # without the facet it lost


def test_a_model_that_finds_nothing_and_names_no_gap_gets_a_plain_answer_not_a_raw_dump():
    out = assemble('Điều khoản về hồ sơ?', results(row('Điều 1. Công nhận kết quả đánh giá.', status='needs_review')),
                   llm=Model({'claims': [], 'missing': []}))
    assert out['status'] == 'insufficient_evidence' and out['citations']
    assert 'Điều 1. Công nhận' not in out['answer']  # no excerpt is presented as if it answered


def test_model_failure_names_its_type_and_http_status_but_not_the_provider_message():
    class Down:
        def chat_structured(self, *a, **k):
            raise RuntimeError('Configured OpenAI-compatible model unavailable (HTTP 524: account 123 quota)')
    out = assemble('Hạt sen hạng nào?', results(row('Hạt sen được công nhận hạng ba sao.', status='needs_review')), llm=Down())
    diag = out['generation_diagnostics']
    assert diag['reasons'] == ['model_unavailable'] and diag['http_status'] == '524' and diag['error_type'] == 'RuntimeError'
    assert 'quota' not in json.dumps(diag)


def test_the_best_block_of_each_searched_part_keeps_its_place_even_without_a_shared_question_word():
    from ai_core.orchestration.ocop.answer import _most_relevant
    prose = [((f'S{i}', 6, f'u{i}', f'c{i}'), {'raw_text': 'công nhận sản phẩm đơn vị sản xuất hồ sơ', 'text': 'công nhận sản phẩm'}, {}, False)
             for i in range(8)]
    heading = (('S9', 1, 'u9', 'c9'), {'raw_text': 'ỦY BAN NHÂN DÂN THÀNH PHỐ HẢI PHÒNG', 'text': 'ỦY BAN NHÂN DÂN', 'query_part': 'văn bản đó do cơ quan nào ban hành'},
               {}, False)
    terms = ['cong', 'san', 'pham', 'don', 'vi', 'co', 'quan', 'hanh']
    assert heading in _most_relevant(prose + [heading], terms, 3)
    plain = (heading[0], {k: v for k, v in heading[1].items() if k != 'query_part'}, {}, False)
    assert plain not in _most_relevant(prose + [plain], terms, 3)


def test_claim_may_name_the_parent_heading_shown_above_the_excerpt():
    parent = row('1.1. Nguồn gốc sản phẩm: Yêu cầu: 100% sản phẩm được trồng trên địa bàn cấp tỉnh', status='needs_review')
    parent['context'] = {'parent_chain': ['Bộ sản phẩm: gạo, ngũ cốc, hạt sơ chế khác', '1.1. Nguồn gốc sản phẩm']}
    claim = 'Tiêu chí 1.1 của bộ sản phẩm gạo, ngũ cốc, hạt sơ chế khác có dòng Yêu cầu: 100% sản phẩm được trồng trên địa bàn cấp tỉnh.'
    out = assemble('Tiêu chí 1.1 có yêu cầu trồng trong tỉnh không?', results(parent),
                   llm=Model({'claims': [{'text': claim, 'sources': ['S1']}], 'missing': []}))
    assert out['status'] == 'generated_unverified_claims', out['generation_diagnostics']
    # a word that is neither in the excerpt nor in its headings is still ungrounded
    invented = claim.replace('gạo, ngũ cốc, hạt sơ chế khác', 'cà phê, ca cao, hồ tiêu')
    bad = assemble('Tiêu chí 1.1 có yêu cầu trồng trong tỉnh không?', results(parent),
                   llm=Model({'claims': [{'text': invented, 'sources': ['S1']}], 'missing': []}))
    assert bad['status'] == 'citation_verification_failed'


def test_a_claim_naming_the_sheet_it_was_asked_about_is_not_dropped_for_the_word_phieu():
    from ai_core.orchestration.ocop.verification import grounded_in_excerpt
    source = '1.1. Nguồn gốc sản phẩm | 3\nYêu cầu: 100% sản phẩm được trồng trên địa bàn cấp tỉnh\nVN.OCOP.QD26.2026'
    claim = 'Ở tiêu chí 1.1 của Phiếu 3 QĐ26/2026, nội dung “100% sản phẩm được trồng trên địa bàn cấp tỉnh” nằm ở dòng “Yêu cầu”.'
    assert grounded_in_excerpt(claim, source, min_term_coverage=0.8, asked='Theo phiếu 3 QĐ26/2026, tiêu chí 1.1 có ghi chú trồng trong tỉnh không?')[0]
    # content that is not in the source still fails, whatever structure nouns surround it
    assert not grounded_in_excerpt('Phiếu 3 có yêu cầu 100% sản phẩm xuất khẩu sang thị trường châu Âu.', source, min_term_coverage=0.8)[0]


def test_consecutive_run_check_finds_a_run_at_a_later_occurrence_of_a_repeated_word():
    from ai_core.orchestration.ocop.verification import grounded_in_excerpt
    source = 'Nguồn gốc sản phẩm Yêu cầu 100% sản phẩm trồng địa bàn tỉnh Hà Tĩnh đạt'
    claim = 'sản phẩm trồng địa bàn tỉnh Hà Tĩnh'  # the run "sản phẩm trồng địa bàn tỉnh" sits at the second "sản phẩm"
    assert grounded_in_excerpt(claim, source, min_term_coverage=0.8)[0]


def test_a_gap_sharing_a_sentence_with_the_review_remark_is_kept():
    from ai_core.orchestration.ocop.answer import _parse_claims
    claims, missing = _parse_claims(json.dumps({'claims': [], 'missing': [
        'SOURCE không nêu điều khoản về hồ sơ trong Quyết định 525; nội dung OCR chưa được xác minh.',
        'Các đoạn OCR chưa được xác minh.', 'Không có mẫu số 02.']}))
    assert missing == ['SOURCE không nêu điều khoản về hồ sơ trong Quyết định 525', 'Không có mẫu số 02']


def test_all_claims_rejected_but_a_gap_named_gives_the_gap_not_a_raw_dump():
    out = assemble('Điều khoản về hồ sơ?', results(row('Điều 1. Công nhận kết quả đánh giá.', status='needs_review')),
                   llm=Model({'claims': [{'text': 'Quyết định ghi nhận đề nghị của Hội đồng thẩm định tại Tờ trình riêng.', 'sources': ['S1']}],
                              'missing': ['SOURCE không nêu điều khoản về hồ sơ; nội dung OCR chưa được xác minh.']}))
    assert out['status'] == 'insufficient_evidence' and 'không nêu điều khoản về hồ sơ' in out['answer']
    assert 'Điều 1. Công nhận' not in out['answer']


def test_a_claim_may_say_a_graph_relation_in_vietnamese_but_only_its_own():
    from ai_core.orchestration.ocop.answer import _relation_gloss
    from ai_core.orchestration.ocop.verification import grounded_in_excerpt
    edge = '26/2026/QĐ-TTg [REPLACES] 148/QĐ-TTg'
    shown = edge + '\n' + _relation_gloss(edge)
    assert 'thay thế' in _relation_gloss(edge) and 'sửa đổi' not in _relation_gloss(edge)
    assert grounded_in_excerpt('Quyết định 26/2026/QĐ-TTg thay thế Quyết định 148/QĐ-TTg.', shown, min_term_coverage=0.8)[0]
    assert not grounded_in_excerpt('Quyết định 26/2026/QĐ-TTg sửa đổi Quyết định 148/QĐ-TTg.', shown, min_term_coverage=0.8)[0]
    assert _relation_gloss('một dòng không có nhãn quan hệ') == ''
