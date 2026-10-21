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


def test_unverified_source_claims_are_never_published_as_supported():
    model = Model({'claims': [{'text': 'Hạt sen được công nhận hạng ba sao', 'sources': ['S1']}], 'missing': []})
    out = assemble('Hạt sen hạng nào?', results(row('Hạt sen được công nhận hạng ba sao.', status='needs_review')), llm=model)
    assert out['status'] == 'citation_verification_failed'
    assert 'source_not_verified' in out['generation_diagnostics']['reasons']


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
