"""Regressions for source-safe PDF anchors and cache integrity."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ai_core.processing.ocop.easy_viet_ocr import _pdf_bbox
from ai_core.processing.ocop.pdf_pipeline import _page_job, _validate_boxes


def fakepage():
    return SimpleNamespace(rect=SimpleNamespace(width=200, height=200))


@pytest.mark.parametrize("bbox", [(float("nan"), 0, 10, 10), (0, 0, float("inf"), 10), (20, 20, 10, 30)])
def test_pixel_anchor_rejects_invalid_geometry(bbox):
    with pytest.raises(ValueError, match="bbox"):
        _pdf_bbox(bbox, width_px=100, height_px=100, page=fakepage())


def test_pdf_block_anchor_rejects_nonfinite_geometry():
    with pytest.raises(ValueError, match="bbox"):
        _validate_boxes([{"bbox": [0, 0, float("nan"), 50]}], [], 200, 200)


def test_pixel_bbox_clamps_small_overflow_to_page():
    assert _pdf_bbox((-2, -1, 101, 102), width_px=100, height_px=100,
                     page=fakepage()) == [0.0, 0.0, 200.0, 200.0]


def test_cache_invalidates_provenance_mismatch(tmp_path, monkeypatch):
    from ai_core.processing.ocop.artifact_cache import write_json
    import ai_core.processing.ocop.pdf_pipeline as pipeline
    import fitz

    profile = {"pdf_page": 1, "width_pt": 200.0, "height_pt": 200.0, "page_class": "native_text"}
    location = tmp_path / "cache.json"
    write_json(location, {"source_id": "WRONG", "pdf_page": 1, "width_pt": 200.0, "height_pt": 200.0,
                          "extracted_text": "forged", "review_status": "machine_extracted",
                          "blocks": [], "tables": [], "ocr_engine": None})
    calls = []
    monkeypatch.setattr(pipeline, "extract_page", lambda *a, **k: calls.append(True) or {
        "source_id": "EXPECTED", "pdf_page": 1, "width_pt": 200.0, "height_pt": 200.0,
        "extracted_text": "real", "review_status": "machine_extracted", "blocks": [],
        "tables": [], "ocr_engine": None, "profile": profile})
    path = tmp_path / "demo.pdf"
    with fitz.open() as document:
        document.new_page(width=200, height=200)
        document.save(path)
    artifact = _page_job((str(path), "EXPECTED", profile, str(location), False, 120, False, False))
    assert calls and artifact["source_id"] == "EXPECTED" and artifact["extracted_text"] == "real"


@pytest.mark.parametrize("tamper", ["text", "geometry"])
def test_cache_invalidates_tampered_content_and_page_geometry(tmp_path, monkeypatch, tamper):
    import ai_core.processing.ocop.pdf_pipeline as pipeline
    import fitz

    profile = {"pdf_page": 1, "width_pt": 200.0, "height_pt": 200.0, "page_class": "native_text"}
    calls = []
    monkeypatch.setattr(pipeline, "extract_page", lambda *a, **k: calls.append(1) or {
        "source_id": "EXPECTED", "pdf_page": 1, "width_pt": 200.0, "height_pt": 200.0,
        "extracted_text": "source text", "review_status": "machine_extracted", "blocks": [],
        "tables": [], "ocr_engine": None, "profile": profile})
    path = tmp_path / "demo.pdf"
    with fitz.open() as document:
        document.new_page(width=200, height=200)
        document.save(path)
    cache = tmp_path / "cache.json"
    job = (str(path), "EXPECTED", profile, str(cache), False, 120, False, False)
    first = _page_job(job)
    _page_job(job)
    assert len(calls) == 1
    forged = json.loads(cache.read_text())
    if tamper == "text":
        forged["extracted_text"] = "tampered"
    else:
        forged["width_pt"] = 500.0
    cache.write_text(json.dumps(forged))
    repaired = _page_job(job)
    assert len(calls) == 2 and repaired["extracted_text"] == first["extracted_text"]


def test_corrupt_profile_cache_forces_reprofiling(tmp_path, monkeypatch):
    import fitz
    import ai_core.processing.ocop.pdf_pipeline as pipeline
    from ai_core.domain.ocop_models import SourceDocument
    from ai_core.processing.ocop.registry import snapshot

    root = tmp_path
    source = root / "data/raw/ocop/demo.pdf"
    source.parent.mkdir(parents=True)
    with fitz.open() as document:
        page = document.new_page(width=200, height=200)
        page.insert_text((20, 40), "Sample legal text " * 13)
        document.save(source)
    source_document = SourceDocument(source_id="VN.TEST.PROFILE", path="data/raw/ocop/demo.pdf",
                                     source_kind="ocop_framework")
    registry = root / "sources.json"
    registry.write_text(json.dumps({"schema_version": 1, "sources": [source_document.model_dump(mode="json")]}))
    lock = root / "lock.json"
    lock.write_text(json.dumps(snapshot(root, [source_document])))
    options = {"registry": registry, "lock": lock, "output": root / "out",
               "cache_dir": root / "cache", "ocr": False, "tables": False}
    calls = []
    real_profile = pipeline.profile_pdf

    def wrapped(*args, **kwargs):
        calls.append(1)
        return real_profile(*args, **kwargs)

    monkeypatch.setattr(pipeline, "profile_pdf", wrapped)
    pipeline.run_pipeline(root, **options)
    pipeline.run_pipeline(root, **options)
    assert len(calls) == 1
    cache_file = next((root / "cache/_profiles").glob("*.json"))
    cached = json.loads(cache_file.read_text())
    cached["pages"][0]["needs_ocr_review"] = False
    cached["pages"][0]["page_class"] = "native_text"
    cache_file.write_text(json.dumps(cached))
    pipeline.run_pipeline(root, **options)
    assert len(calls) == 2
