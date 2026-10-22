"""Evidence image endpoint: highlighted regions from the SHA-locked PDF, strict validation."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

fitz = pytest.importorskip('fitz')


@pytest.fixture
def client(tmp_path, monkeypatch):
    from backend.api import ocop_routes
    from backend.api.ocop_main import app
    pdf = tmp_path / 'data/raw/ocop/a.pdf'
    pdf.parent.mkdir(parents=True)
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), 'Evidence text')
        doc.save(pdf)
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    (tmp_path / 'configs').mkdir()
    (tmp_path / 'configs/ocop_sources.json').write_text(json.dumps({'sources': [{'source_id': 'S', 'path': 'data/raw/ocop/a.pdf'}]}))
    (tmp_path / 'configs/ocop_sources.lock.json').write_text(json.dumps({'sources': [{'source_id': 'S', 'sha256': digest}]}))
    monkeypatch.setattr(ocop_routes, 'ROOT', tmp_path)
    return TestClient(app), digest


def test_renders_png_with_highlight_and_crop(client):
    c, digest = client
    full = c.get('/api/ocop/sources/S/pages/1/evidence.png', params={'box': '30,40,150,70', 'sha': digest})
    assert full.status_code == 200 and full.content.startswith(b'\x89PNG')
    cropped = c.get('/api/ocop/sources/S/pages/1/evidence.png', params={'box': '30,40,150,70', 'crop': 'true'})
    assert cropped.status_code == 200 and len(cropped.content) != len(full.content)


@pytest.mark.parametrize('params', [{'box': '30,40,20,70'}, {'box': 'a,b,c,d'}, {'box': '0,0,999,999'},
                                    {'dpi': '9999'}, {'sha': 'a' * 64}])
def test_bad_box_dpi_or_sha_is_refused(client, params):
    c, _ = client
    assert c.get('/api/ocop/sources/S/pages/1/evidence.png', params=params).status_code == 422


def test_unknown_source_and_page_are_refused(client):
    c, _ = client
    assert c.get('/api/ocop/sources/NOPE/pages/1/evidence.png').status_code == 404
    assert c.get('/api/ocop/sources/S/pages/9/evidence.png').status_code == 422
