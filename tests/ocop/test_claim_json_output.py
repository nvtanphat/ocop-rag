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
