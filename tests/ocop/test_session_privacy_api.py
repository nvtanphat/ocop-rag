"""Shared session store, masking of persisted text, structured 503s (API-01, GEN-01, SES-01)."""
import json
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from ai_core.orchestration.ocop.privacy import PrivacyConfig, redact
from ai_core.orchestration.ocop.sessions import SessionStore
from ai_core.orchestration.ocop.workflow import OcopAgent


def _response(slots=None):
    return SimpleNamespace(route=SimpleNamespace(slots=slots or {'document_code': '26/2026'}, capabilities=['exact_article']),
                           intent=SimpleNamespace(value='EXACT_LOOKUP'))


def test_privacy_file_validates_and_masks_identifiers():
    data = yaml.safe_load(open('configs/ocop_privacy.yaml', encoding='utf-8'))
    PrivacyConfig.model_validate(data)
    text = redact('tenant_id=ACME dossier_id: D-9 mail a.b@example.com gọi 0912 345 678 mã SECRET-001 key sk-abcdefghijklmnop1234')
    for secret in ('ACME', 'D-9', 'a.b@example.com', '345 678', 'SECRET-001', 'sk-abcdefghijklmnop1234'):
        assert secret not in text


def test_unknown_privacy_key_is_rejected():
    with pytest.raises(ValueError):
        PrivacyConfig.model_validate({'schema_version': 1, 'redactions': [], 'extra': 1})


def test_session_store_masks_last_query_and_expires():
    now = [0.0]
    store = SessionStore(ttl=10, limit=2, clock=lambda: now[0])
    store.save('s1', 'Điều 6 tenant_id=ACME?', _response())
    assert 'ACME' not in store.get('s1')['last_query'] and store.get('s1')['slots'] == {'document_code': '26/2026'}
    now[0] = 11
    assert store.get('s1') == {}
    for i in range(3):
        store.save(f'k{i}', 'q', _response())
    assert store.get('k0') == {} and store.get('k2')


def test_checkpoint_input_masks_the_question():
    state = OcopAgent._checkpoint_public_input({'query': 'Điều 6 principal_id=P-77 là gì?', 'session': {
        'session_id': 's', 'last_query': 'tenant_id=T-1 Điều 5'}, 'context': {}, 'auth': None})
    assert 'P-77' not in state['query'] and 'T-1' not in state['session']['last_query']


def _debug_client(tmp_path):
    from backend.api.ocop_debug import create_debug_app
    return TestClient(create_debug_app(tmp_path, allow_partial_debug=True))


def test_debug_api_keeps_the_session_between_turns(tmp_path, monkeypatch):
    seen = []

    class Agent:
        def __init__(self, *a, **k):
            pass

        def ask(self, query, *, session=None):
            seen.append(dict(session or {}))
            return SimpleNamespace(route=SimpleNamespace(slots={'document_code': '26/2026'}, capabilities=[]),
                                   intent=SimpleNamespace(value='EXACT_LOOKUP'),
                                   model_dump=lambda mode='json': {'answer': 'ok'})
    monkeypatch.setattr('backend.api.ocop_debug.OcopAgent', Agent)
    client = _debug_client(tmp_path)
    for _ in range(2):
        assert client.post('/api/ocop/query', json={'query': 'Điều 6?', 'session_id': 's1'}).status_code == 200
    assert seen[0] == {} and seen[1]['slots'] == {'document_code': '26/2026'}


def test_missing_llm_key_is_a_structured_503_not_a_500(tmp_path, monkeypatch):
    def broken():
        raise RuntimeError('OpenAI-compatible API key is not set sk-should-never-be-echoed')
    monkeypatch.setattr('backend.api.ocop_debug.make_answer_client', broken)
    response = _debug_client(tmp_path).post('/api/ocop/query', json={'query': 'Điều 6?', 'use_llm': True})
    assert response.status_code == 503
    detail = response.json()['detail']
    assert detail['code'] == 'llm_unavailable' and detail['layer'] == 'configuration'
    assert 'sk-should-never' not in json.dumps(detail)
