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
