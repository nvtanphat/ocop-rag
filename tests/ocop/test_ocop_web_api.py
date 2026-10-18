"""API contract tests for clean, source-only OCOP distribution."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.api.ocop_main import app
from backend.api import ocop_routes as routes
from ai_core.system.pipeline import OcopSystemPipeline

ROOT = Path(__file__).resolve().parents[2]
client = TestClient(app)


def test_overview_without_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "DATA", tmp_path)
    response = client.get('/api/ocop/overview')
    assert response.status_code == 200
    data = response.json()
    assert data['sources'] == 12
    assert data['pages'] == {}
    assert data['index'] == {}
    assert data['graph'] == {}


def test_sources_and_signed_pdf_remain_available_before_build():
    sources = client.get('/api/ocop/sources').json()
    assert len(sources) == 12
    first = sources[0]['source_id']
    response = client.get(f'/api/ocop/sources/{first}/pdf')
    assert response.status_code == 200
    assert response.content.startswith(b'%PDF')
    assert client.get('/api/ocop/sources/NOT-REGISTERED/pdf').status_code == 404


def test_extracted_views_empty_when_not_built(monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "DATA", tmp_path)
    routes._graph_data.cache_clear()
    criteria = client.get('/api/ocop/criteria?limit=2').json()
    assert criteria['kind'] == 'machine_candidates'
    assert criteria['items'] == []
    assert client.get('/api/ocop/forms').json()['items'] == []
    assert client.get('/api/ocop/recognitions?limit=2').json()['items'] == []
    graph = client.get('/api/ocop/graph').json()
    assert graph['nodes'] == [] and graph['edges'] == []


def test_api_fails_closed_without_built_corpus(monkeypatch, tmp_path):
    monkeypatch.setattr(routes, 'DATA', tmp_path)
    for mode in ('sparse', 'hybrid'):
        response = client.post('/api/ocop/query', json={
            'query': 'Mẫu số 01', 'retrieval_mode': mode, 'use_llm': False,
        })
        assert response.status_code == 503
    # Even a forged index manifest is insufficient without an approved build.
    index = tmp_path / 'index'
    index.mkdir()
    (index / 'manifest.json').write_text('{"dense":{"enabled":true}}', encoding='utf-8')
    monkeypatch.setattr(OcopSystemPipeline, 'status', lambda self, **k: {'state': 'not_ready'})
    assert client.post('/api/ocop/query', json={
        'query': 'Mẫu số 01', 'retrieval_mode': 'sparse', 'use_llm': False,
    }).status_code == 503


def test_api_query_after_coherent_build_uses_agent(monkeypatch, tmp_path):
    idx = tmp_path / 'index'
    idx.mkdir()
    (idx / 'manifest.json').write_text('{"dense":{"enabled":false},"corpus_version":"clean-v1"}', encoding='utf-8')
    monkeypatch.setattr(routes, 'DATA', tmp_path)
    # Agent behavior itself is checked in separate contract tests; only verify public wiring here.
    monkeypatch.setattr(OcopSystemPipeline, 'status', lambda self, **kwargs: {'state':'ready'})
    calls = []

    class FakeAgent:
        def ask(self, query, **kwargs):
            calls.append((query, kwargs))
            return SimpleNamespace(model_dump=lambda **opts: {'status': 'retrieval_only', 'citations': []})

    monkeypatch.setattr(routes, '_agent', lambda *args: FakeAgent())
    response = client.post('/api/ocop/query', json={
        'query':'Mẫu số 01', 'retrieval_mode':'sparse', 'use_llm':False,
    })
    assert response.status_code == 200
    assert calls[0][0] == 'Mẫu số 01'
    assert client.post('/api/ocop/query', json={
        'query':'Mẫu số 01', 'retrieval_mode':'hybrid', 'use_llm':False,
    }).status_code == 409


def test_user_cannot_pass_private_auth_context():
    response = client.post('/api/ocop/query', json={
        'query': 'Rà soát hồ sơ của tôi', 'tenant_id': 'some-tenant',
        'authenticated': True, 'use_llm': False,
    })
    assert response.status_code == 422
