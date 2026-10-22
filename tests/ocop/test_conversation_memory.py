from types import SimpleNamespace

from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.sessions import SessionStore

PRIOR = {'last_query': 'QĐ26/2026 Điều 6 quy định hồ sơ lần đầu ra sao?', 'intent': 'EXACT_LOOKUP',
         'slots': {'document_code': '26/2026', 'article_id': '6', 'years': ['2026']}, 'capabilities': ['exact_article']}


def _response(intent, slots, *, clarify=False, missing=()):
    return SimpleNamespace(intent=SimpleNamespace(value=intent),
                           route=SimpleNamespace(slots=slots, capabilities=['x'], needs_clarification=clarify, missing_slots=list(missing)))


def test_a_new_target_replaces_the_old_target_and_keeps_the_document():
    route = route_query('Còn mẫu số 02?', session=PRIOR)
    assert route.slots['document_code'] == '26/2026' and route.slots['form_id'] == '2'
    assert 'article_id' not in route.slots


def test_a_closing_cue_without_scope_continues_the_conversation():
    prior = {'last_query': 'Hạn nộp hồ sơ OCOP phường Thành Sen năm 2026 là khi nào?', 'intent': 'PROCEDURE_FORM',
             'slots': {'region': 'Thành Sen', 'years': ['2026']}, 'capabilities': []}
    assert route_query('Nơi tiếp nhận hồ sơ thì sao?', session=prior).slots.get('region') == 'Thành Sen'
    # the same words with a scope of their own are a new question
    assert 'region' not in route_query('Nơi tiếp nhận hồ sơ ở Hải Phòng thì sao?', session=prior).slots.get('region', '')


def test_a_demonstrative_continues_the_topic():
    prior = {'last_query': 'QĐ525 có tên sản phẩm HANA không?', 'intent': 'RECOGNITION_LOOKUP',
             'slots': {'document_code': '525', 'product_name': 'HANA'}, 'capabilities': []}
    assert route_query('Chủ thể sản xuất sản phẩm đó là ai?', session=prior).slots.get('product_name') == 'HANA'


def test_a_clarification_turn_does_not_move_the_conversation_scope():
    store = SessionStore()
    store.save('s', 'QĐ26/2026 Điều 6 quy định hồ sơ lần đầu ra sao?', _response('EXACT_LOOKUP', PRIOR['slots']))
    store.save('s', 'Còn năm 2023?', _response('CLARIFY', {'document_code': '26/2026', 'years': ['2023']}, clarify=True,
                                                missing=['document_version_or_event_year']))
    kept = store.get('s')
    assert kept['slots']['years'] == ['2026'] and kept['last_query'].startswith('QĐ26/2026 Điều 6')
    assert kept['unresolved']['missing_slots'] == ['document_version_or_event_year']
    store.save('s', 'Còn Điều 7?', _response('EXACT_LOOKUP', {'document_code': '26/2026', 'article_id': '7'}))
    assert 'unresolved' not in store.get('s') and store.get('s')['slots']['article_id'] == '7'


def _memory(**overrides):
    from ai_core.orchestration.ocop import memory
    state = memory.update(None, slots={'document_code': '26/2026', 'form_id': '1'}, standalone='Mẫu số 01 dùng để làm gì?',
                          citations=[{'source_id': 'VN.OCOP.QD26.2026', 'pdf_page': 4, 'chunk_id': 'c1', 'evidence_unit_id': 'u1'}],
                          corpus_version='v1')
    state = memory.update(state, slots={'document_code': '26/2026', 'form_id': '2'}, standalone='Mẫu số 02 dùng để làm gì?',
                          citations=[{'source_id': 'VN.OCOP.QD26.2026', 'pdf_page': 4, 'chunk_id': 'c2'}], corpus_version='v1')
    return {**state, **overrides}


def test_plural_reference_resolves_to_the_two_discussed_items_in_order():
    from ai_core.orchestration.ocop import memory
    carried = memory.plural_referents('Hai mẫu này khác nhau ở đâu?', _memory(), {})
    assert carried == {'form_ids': ['1', '2'], 'form_id': '1'}
    # nothing discussed twice -> nothing to resolve, nothing invented
    assert memory.plural_referents('Hai mẫu này khác nhau ở đâu?', memory.update(None, slots={'form_id': '1'}, standalone='x',
                                                                                citations=[], corpus_version='v1'), {}) == {}
    assert memory.plural_referents('So sánh với mẫu số 01', _memory(), {'form_id': '1', 'form_ids': None} | {'form_id': '1'}) == {
        'form_ids': ['2', '1'], 'form_id': '2'}


def test_rewrite_swaps_the_new_thing_in_and_keeps_words_of_the_question():
    from ai_core.orchestration.ocop import memory
    state = memory.update(None, slots={'document_code': '26/2026', 'article_id': '6'}, standalone='QĐ26/2026 Điều 6 quy định hồ sơ lần đầu ra sao?',
                          citations=[], corpus_version='v1')
    assert memory.rewrite('Còn Điều 7?', state, {'document_code': '26/2026', 'article_id': '7'}, {'article_id': '7'}) == (
        'QĐ26/2026 Điều 7 quy định hồ sơ lần đầu ra sao?', 'substitute:article')
    assert memory.rewrite('Nó thì sao?', state, {'document_code': '26/2026', 'article_id': '6'}, {})[1] == 'previous_standalone'
    text, method = memory.rewrite('Cơ quan tiếp nhận hồ sơ thì sao?', state, {'document_code': '26/2026', 'article_id': '6'}, {})
    assert method == 'state_scope' and text.startswith('Cơ quan tiếp nhận hồ sơ') and 'Điều 6' in text and '26/2026' in text


def test_remembered_evidence_is_dropped_when_the_corpus_or_the_document_scope_changed():
    from ai_core.orchestration.ocop import memory
    state = _memory()
    kept, dropped = memory.reusable_evidence(state, corpus_version='v1', source_ids={'VN.OCOP.QD26.2026'})
    assert len(kept) == 2 and not dropped
    kept, dropped = memory.reusable_evidence(state, corpus_version='v1', source_ids={'VN.OTHER'})
    assert not kept and {d['reason'] for d in dropped} == {'scope_changed'}
    kept, dropped = memory.reusable_evidence(state, corpus_version='v2', source_ids=None)
    assert not kept and {d['reason'] for d in dropped} == {'corpus_version_changed'}


def test_a_private_turn_leaves_nothing_in_memory_and_malformed_memory_is_discarded():
    from ai_core.orchestration.ocop import memory
    private = memory.update(None, slots={'document_code': '1'}, standalone='hồ sơ của tôi', private=True,
                            citations=[{'source_id': 'dossier', 'chunk_id': 'x'}], corpus_version='v1')
    assert private == memory.empty()
    assert memory.sanitize({'referents': {'form': 'not-a-list'}, 'evidence': [{'source_id': 3}, 'x'], 'standalone': 5}) == memory.empty()


def test_a_form_gap_is_reported_while_the_rest_of_the_evidence_is_answered():
    from ai_core.orchestration.ocop.answer import assemble  # noqa: F401 (the gate lives in the workflow; see below)
    from ai_core.orchestration.ocop.workflow import OcopAgent
    agent = OcopAgent.__new__(OcopAgent)
    row = {'source_id': 'VN.X', 'evidence_unit_id': 'u1', 'review_status': 'needs_review', 'text': 'Mẫu số 01 là phiếu đăng ký.',
           'source_spans': [{'pdf_page': 4}], 'chunk_id': 'c1'}
    state = {'route': {'intent': 'PROCEDURE_FORM', 'strategy': 'x', 'slots': {}, 'required_tools': ['lookup_form']},
             'query': 'Mẫu số 01 dùng để làm gì?',
             'results': [{'tool': 'lookup_form', 'output': {'results': [], 'status': 'incomplete_form_ids', 'missing_form_ids': ['1']}},
                         {'tool': 'search_regulations', 'output': {'results': [row], 'status': 'ok'}}]}
    agent.llm = None
    agent._catalog = lambda: None
    out = agent.answer(state)['answer']
    assert out['status'] != 'insufficient_form_scope' and out['citations']
    assert 'không mô tả nội dung của biểu mẫu' in out['answer']
    only_gap = agent.answer({**state, 'results': state['results'][:1]})['answer']
    assert only_gap['status'] == 'insufficient_form_scope'


def test_a_new_target_the_earlier_question_never_mentioned_is_asked_afresh_inside_the_scope():
    from ai_core.orchestration.ocop import memory
    state = memory.update(None, slots={'document_code': '26/2026'}, standalone='Quyết định 26/2026 quy định gì về hồ sơ?',
                          citations=[], corpus_version='v1')
    text, method = memory.rewrite('Còn Điều 7?', state, {'document_code': '26/2026', 'article_id': '7'}, {'article_id': '7'})
    assert method == 'generic_target' and text == 'Điều 7 của Quyết định 26/2026 nói gì?'  # not "...về hồ sơ?"


def test_naming_only_a_new_target_with_a_closing_cue_inherits_the_document():
    prior = {'last_query': 'Quyết định 26/2026 quy định gì về hồ sơ?', 'intent': 'OCOP_OVERVIEW',
             'slots': {'document_code': '26/2026', 'years': ['2026']}, 'capabilities': []}
    route = route_query('Mẫu số 02 thì sao?', session=prior)
    assert route.slots['document_code'] == '26/2026' and route.slots['form_id'] == '2'
    # a document of its own makes it a new question about that document
    assert route_query('Mẫu số 02 của QĐ148/2023 thì sao?', session=prior).slots['document_code'] == '148/2023'


def test_debug_app_survives_a_request_and_keeps_serving_after_a_failed_one(tmp_path):
    from fastapi.testclient import TestClient

    from backend.api.ocop_debug import create_debug_app
    with TestClient(create_debug_app(tmp_path, allow_partial_debug=True), raise_server_exceptions=False) as client:
        assert client.post('/api/ocop/query', json={'query': ''}).status_code == 422
        assert client.post('/api/ocop/query', json={'query': 'x', 'retrieval_mode': 'bogus'}).status_code == 422
        broken = client.post('/api/ocop/query', json={'query': 'OCOP là gì?', 'use_llm': False})
        assert broken.status_code in (200, 503)  # an empty corpus root is reported, never an unhandled 500
        assert client.post('/api/ocop/query', json={'query': ''}).status_code == 422  # and the app is still up


def test_switching_document_replaces_the_number_in_the_previous_question():
    from ai_core.orchestration.ocop import memory
    state = memory.update(None, slots={'document_code': '26/2026', 'form_id': '2'},
                          standalone='Mẫu số 02 của Quyết định 26/2026 nói gì?', citations=[], corpus_version='v1')
    text, method = memory.rewrite('Còn QĐ148/2023?', state, {'document_code': '148/2023', 'form_id': '2'}, {'document_code': '148/2023'})
    assert method == 'substitute:document' and text == 'Mẫu số 02 của Quyết định 148/2023 nói gì?'
