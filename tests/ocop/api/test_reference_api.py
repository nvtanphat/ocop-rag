"""Verified public reference views reject stale, private and ungrounded records."""

import hashlib
import json

import fitz
import pytest
from fastapi.testclient import TestClient

from backend.api import ocop_routes
from backend.api.ocop_main import app


@pytest.fixture
def reference_api(tmp_path, monkeypatch):
    pdf = tmp_path / "data/raw/ocop/reference.pdf"
    pdf.parent.mkdir(parents=True)
    with fitz.open() as document:
        document.new_page(width=300, height=400).insert_text((40, 60), "Verified reference")
        document.save(pdf)
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    config = tmp_path / "configs"
    config.mkdir()
    (config / "ocop_sources.json").write_text(
        json.dumps({"sources": [{"source_id": "REFERENCE", "path": "data/raw/ocop/reference.pdf"}]})
    )
    (config / "ocop_sources.lock.json").write_text(
        json.dumps({"sources": [{"source_id": "REFERENCE", "sha256": sha}]})
    )
    data = tmp_path / "data/processed/ocop"
    (data / "index").mkdir(parents=True)
    (data / "knowledge").mkdir()
    (data / "index/manifest.json").write_text('{"corpus_version":"active"}')
    span = {"pdf_page": 1, "bbox": [30, 40, 150, 70], "source_sha256": sha}
    (data / "knowledge/evidence_units.jsonl").write_text(
        json.dumps(
            {
                "unit_id": "unit",
                "source_id": "REFERENCE",
                "spans": [span],
                "review_status": "verified",
                "text": "Verified reference",
            }
        )
        + "\n"
    )
    record = {
        "id": "rule",
        "label": "Verified reference",
        "review_status": "verified",
        "visibility": "public",
        "corpus_version": "active",
        "citations": [{"source_id": "REFERENCE", "evidence_unit_id": "unit", **span}],
    }
    monkeypatch.setattr(ocop_routes, "ROOT", tmp_path)
    monkeypatch.setattr(ocop_routes, "DATA", data)
    monkeypatch.setattr(ocop_routes.OcopSystemPipeline, "status", lambda *a, **k: {"state": "ready"})
    return TestClient(app), data, record


@pytest.mark.parametrize("kind", ["criteria", "products"])
def test_empty_verified_view_is_explicit(reference_api, kind):
    client, _, _ = reference_api
    response = client.get(f"/api/ocop/{kind}")
    assert response.status_code == 200
    assert response.json() == {"corpus_version": "active", "status": "no_verified_data", "items": []}


@pytest.mark.parametrize("kind", ["criteria", "products"])
def test_verified_view_keeps_complete_provenance_and_exports_only_public_fields(reference_api, kind):
    client, data, record = reference_api
    record["internal_notes"] = "never publish"
    (data / f"knowledge/verified_{kind}.jsonl").write_text(json.dumps(record) + "\n")
    result = client.get(f"/api/ocop/{kind}").json()
    assert result["status"] == "verified"
    item = result["items"][0]
    assert set(item) == {"id", "label", "citations"}
    assert "internal_notes" not in item
    assert item["citations"][0].items() >= record["citations"][0].items()


@pytest.mark.parametrize(
    "change",
    [
        {"corpus_version": "stale"},
        {"review_status": "needs_review"},
        {"visibility": "private"},
        {"tenant_id": "secret"},
        {"dossier_id": "secret"},
        {"citations": []},
        {"citations": [{"source_id": "UNKNOWN"}]},
    ],
)
def test_invalid_or_private_reference_is_never_published(reference_api, change):
    client, data, record = reference_api
    (data / "knowledge/verified_criteria.jsonl").write_text(json.dumps({**record, **change}) + "\n")
    assert client.get("/api/ocop/criteria").json()["items"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", "PRIVATE"),
        ("source_sha256", "a" * 64),
        ("pdf_page", 2),
        ("bbox", [30, 40, 160, 70]),
        ("evidence_unit_id", "missing"),
    ],
)
def test_citation_must_match_locked_pdf_and_evidence(reference_api, field, value):
    client, data, record = reference_api
    record["citations"][0][field] = value
    (data / "knowledge/verified_criteria.jsonl").write_text(json.dumps(record) + "\n")
    assert client.get("/api/ocop/criteria").json()["items"] == []


def test_incoherent_corpus_cannot_publish_verified_reference(reference_api, monkeypatch):
    client, data, record = reference_api
    (data / "knowledge/verified_criteria.jsonl").write_text(json.dumps(record) + "\n")
    monkeypatch.setattr(ocop_routes.OcopSystemPipeline, "status", lambda *a, **k: {"state": "not_ready"})
    assert client.get("/api/ocop/criteria").json()["items"] == []


def test_verified_label_cannot_invent_a_star_value(reference_api):
    client, data, record = reference_api
    record["label"] = "Sản phẩm đạt 5 sao"
    (data / "knowledge/verified_products.jsonl").write_text(json.dumps(record) + "\n")
    assert client.get("/api/ocop/products").json()["items"] == []


def test_unverified_source_cannot_publish_a_verified_reference(reference_api):
    client, data, record = reference_api
    units_file = data / "knowledge/evidence_units.jsonl"
    unit = json.loads(units_file.read_text())
    unit["review_status"] = "needs_review"
    units_file.write_text(json.dumps(unit) + "\n")
    (data / "knowledge/verified_criteria.jsonl").write_text(json.dumps(record) + "\n")
    assert client.get("/api/ocop/criteria").json()["items"] == []
