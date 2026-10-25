"""PDF: PDF native/scanned text, image coordinates, cache, grid, locked source."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ocop_ocr.artifact_cache import build_cache_key, write_json, load_json
from ocop_ocr.native_extractor import extract_native
from ocop_ocr.table_parser import raster_tables
from ocop_ocr.easy_viet_ocr import _pdf_bbox
from ocop_ocr.ocr_types import OCRResult
from ocop_ocr.pdf_pipeline import extract_page, run_pipeline
from ocop_ocr.profiler import profile_pdf
from ocop_contracts.registry import snapshot
from ocop_contracts.models import SourceDocument


@pytest.fixture
def document(tmp_path):
    fitz = pytest.importorskip("fitz")
    p = tmp_path / "sample.pdf"
    with fitz.open() as d:
        pg = d.new_page(width=450, height=550)
        pg.insert_text((40, 60), "Dieu 1. Noi dung hop le\n", fontsize=12)
        for i in range(8):
            pg.insert_text(
                (40, 110 + i * 28), f"Khoan {i + 1}. Quy dinh kiem tra an toan thuc pham", fontsize=10
            )
        d.save(p)
    return p


def test_native_bbox_and_page_validation(document):
    import fitz

    with fitz.open(document) as pdf:
        b = extract_native(pdf[0])
        assert len(b) >= 8
        assert b[0]["bbox"][0] >= 0
        assert b[0]["method"] == "native"
        profile = profile_pdf(document, "TEST")[0]
        a = extract_page(pdf[0], profile, source_id="TEST", enable_ocr=False)
        assert a["pdf_page"] == 1
        assert a["blocks"]
        assert a["extraction_method"] == "native"
        assert a["review_status"] in {"machine_extracted", "needs_review"}


def test_ocr_pixel_bbox_to_pdf_points():
    bb = _pdf_bbox(
        (200, 100, 500, 350),
        width_px=1000,
        height_px=1000,
        page=type("Page", (), {"rect": type("Rect", (), {"width": 500, "height": 700})()})(),
    )
    assert bb == [100.0, 70.0, 250.0, 245.0]
    assert all(n >= 0 for n in bb)


def test_cache_deterministic_and_versioned(tmp_path):
    a = build_cache_key(
        "a" * 64,
        1,
        dpi=300,
        ocr_engine="easyocr_vietocr",
        extract_ocr=True,
        detect_tables=True,
        model_version="x",
    )
    b = build_cache_key(
        "a" * 64,
        1,
        dpi=300,
        ocr_engine="easyocr_vietocr",
        extract_ocr=True,
        detect_tables=True,
        model_version="x",
    )
    c = build_cache_key(
        "a" * 64,
        1,
        dpi=300,
        ocr_engine="native_only",
        extract_ocr=True,
        detect_tables=True,
        model_version="x",
    )
    assert a == b and a != c
    f = tmp_path / "sub" / "a.json"
    write_json(f, {"value": "cây rau"})
    assert load_json(f)["value"] == "cây rau"


def test_grid_candidates_keep_coordinates_and_review(tmp_path):
    from PIL import Image, ImageDraw
    import fitz

    image = Image.new("RGB", (500, 500), "white")
    d = ImageDraw.Draw(image)
    for x in [70, 200, 440]:
        d.line([(x, 80), (x, 330)], fill="black", width=3)
    for y in [80, 140, 205, 265, 330]:
        d.line([(70, y), (440, y)], fill="black", width=3)
    with fitz.open() as pdf:
        page = pdf.new_page(width=250, height=250)
        blocks = [{"bbox": [40, 48, 90, 60], "text": "***", "order": 0}]
        results = raster_tables(image, page, blocks)
        assert results and results[0]["review_status"] == "needs_review"
        assert results[0]["row_count"] == 4 and results[0]["col_count"] == 2
        assert any(c["text"] == "***" for c in results[0]["cells"])
        assert all(0 <= c["bbox"][0] < c["bbox"][2] <= page.rect.width for c in results[0]["cells"])


def test_grid_ignores_repeated_dashes_inside_score_column():
    from PIL import Image, ImageDraw
    import fitz
    from ocop_ocr.table_parser import raster_tables

    image = Image.new("RGB", (700, 700), "white")
    draw = ImageDraw.Draw(image)
    for x in (70, 300, 640):
        draw.line([(x, 60), (x, 540)], fill="black", width=3)
    for y in range(60, 541, 60):
        draw.line([(70, y), (640, y)], fill="black", width=3)
    # Repeated short scan marks can exceed cumulative x-projection support,
    # but no individual mark is long enough to be a real table border.
    for y in range(60, 480, 60):
        draw.line([(500, y + 15), (500, y + 39)], fill="black", width=2)

    with fitz.open() as pdf:
        page = pdf.new_page(width=700, height=700)
        results = raster_tables(image, page, [])

    assert results and results[0]["row_count"] == 8
    assert results[0]["col_count"] == 2
    assert results[0]["extraction_quality"]["fragmented_column_rules_rejected"] == 1


def test_page_error_is_quarantined_and_resumable(tmp_path, document, monkeypatch):
    root = tmp_path
    (root / "data/raw/ocop").mkdir(parents=True)
    target = root / "data/raw/ocop/demo.pdf"
    target.write_bytes(document.read_bytes())
    src = SourceDocument(source_id="VN.DEMO", path="data/raw/ocop/demo.pdf", source_kind="ocop_framework")
    registry = root / "r.json"
    registry.write_text(json.dumps({"schema_version": 1, "sources": [src.model_dump(mode="json")]}))
    lock = root / "lock.json"
    lock.write_text(json.dumps(snapshot(root, [src])))
    out = root / "out"
    cache = root / "cache"
    result = run_pipeline(
        root, registry=registry, lock=lock, output=out, cache_dir=cache, ocr=False, tables=False
    )
    assert result["complete"] and result["counts"]["pages"] == 1
    result2 = run_pipeline(
        root, registry=registry, lock=lock, output=out, cache_dir=cache, ocr=False, tables=False
    )
    assert result["counts"] == result2["counts"]
    target.write_bytes(b"not pdf")
    with pytest.raises(RuntimeError, match="differs"):
        run_pipeline(root, registry=registry, lock=lock, output=out, cache_dir=cache)


def test_signed_scan_is_not_treated_as_native_legal_content(monkeypatch, tmp_path):
    from PIL import Image
    import fitz

    img = Image.new("RGB", (500, 700), "white")
    buf = __import__("io").BytesIO()
    img.save(buf, format="PNG")
    f = tmp_path / "scan.pdf"
    with fitz.open() as d:
        p = d.new_page(width=500, height=700)
        p.insert_image(p.rect, stream=buf.getvalue())
        p.insert_text((25, 25), "Nguoi ky cong thong tin dien tu chinh phu")
        d.save(f)
    pr = profile_pdf(f, "TEST")[0]
    assert pr["page_class"] == "ocr_candidate"
    monkeypatch.setattr(
        "ocop_ocr.pdf_pipeline.run_easy_viet_ocr",
        lambda *a, **k: (
            OCRResult(
                [
                    {
                        "block_id": "ocr:test",
                        "text": "BANG TIEU CHI *** 15 diem",
                        "bbox": [10, 10, 300, 100],
                        "method": "mock",
                        "confidence": None,
                        "order": 0,
                    }
                ],
                "easyocr_vietocr",
                [],
            ),
            [],
        ),
    )
    with fitz.open(f) as d:
        art = extract_page(d[0], pr, source_id="TEST", enable_tables=False)
    assert "Nguoi ky" not in art["extracted_text"]
    assert "***" in art["extracted_text"]
    assert art["review_status"] == "needs_review"


def test_cross_page_is_not_silently_merged():
    from ocop_contracts.layout import layout_page

    x = [{"bbox": [20, 20, 60, 38], "text": "DIEM 5", "order": 0}]
    ordered, warnings = layout_page(x, 100, 100)
    assert ordered[0]["text"] == "DIEM 5" and ordered[0]["reading_order"] == 0


def test_cross_page_candidate_never_materializes_merge():
    from ocop_ocr.table_continuity import possible_continuations

    pre = {
        "source_id": "VN.TEST",
        "pdf_page": 1,
        "height_pt": 100,
        "tables": [{"table_id": "a", "bbox": [10, 50, 100, 95], "col_count": 3, "row_count": 4}],
    }
    cur = {
        "source_id": "VN.TEST",
        "pdf_page": 2,
        "height_pt": 100,
        "tables": [{"table_id": "b", "bbox": [10, 5, 100, 80], "col_count": 3, "row_count": 4}],
    }
    c = possible_continuations(pre, cur)
    assert c and c[0]["status"] == "needs_review"
    assert not possible_continuations(pre, {**cur, "pdf_page": 3})


def test_native_bbox_overflow_clipped_with_original_retained():
    from ocop_ocr.pdf_pipeline import _validate_boxes

    b = {"bbox": [5, 10, 101, 35]}
    assert _validate_boxes([b], [], 100, 100) == 1
    assert b["bbox"] == [5, 10, 100, 35]
    assert b["bbox_original"] == [5, 10, 101, 35]


def test_page_cache_hit_skips_expensive_extraction(tmp_path, document, monkeypatch):
    import ocop_ocr.pdf_pipeline as pdf_module

    root = tmp_path
    target = root / "data/raw/ocop/test.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(document.read_bytes())
    src = SourceDocument(
        source_id="VN.TEST.CACHE", path="data/raw/ocop/test.pdf", source_kind="ocop_framework"
    )
    registry = root / "sources.json"
    registry.write_text(json.dumps({"schema_version": 1, "sources": [src.model_dump(mode="json")]}))
    lock = root / "source.lock.json"
    lock.write_text(json.dumps(snapshot(root, [src])))
    kw = {
        "registry": registry,
        "lock": lock,
        "output": root / "out",
        "cache_dir": root / "cache",
        "ocr": False,
        "tables": False,
    }
    first = pdf_module.run_pipeline(root, **kw)
    assert first["counts"]["pages"] == 1
    monkeypatch.setattr(
        pdf_module, "extract_page", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cache not used"))
    )
    second = pdf_module.run_pipeline(root, **kw)
    assert second["counts"] == first["counts"]
    assert second["complete"]


def test_real_processed_corpus_complete_if_artifacts_available():
    import os

    root = Path(__file__).resolve().parents[2]
    external = os.environ.get("OCOP_PDF_ARTIFACT_DIR")
    manifest = (Path(external) if external else root / "data/processed/ocop/pages") / "manifest.json"
    if not manifest.exists():
        if external:
            pytest.fail("explicit PDF artifact directory has no manifest")
        pytest.skip("generated corpus is optional for source-only installs")
    data = json.loads(manifest.read_text())
    if not data.get("complete"):
        if external:
            pytest.fail("explicit PDF artifact corpus is incomplete")
        pytest.skip("partial dev-run manifest; no full release available")
    count = 0
    from ocop_contracts.pdf_loader import checked_sources

    _, locked = checked_sources(
        root, root / "configs/ocop_sources.json", root / "configs/ocop_sources.lock.json"
    )
    digests = {s["source_id"]: s["sha256"] for s in locked["sources"]}
    assert data["input_snapshot_sha256"] == locked["aggregate_sha256"]
    for source in data["sources"]:
        p = manifest.parent / source["artifact"]
        records = [json.loads(x) for x in p.read_text(encoding="utf8").splitlines()]
        assert len(records) == source["page_count_expected"]
        assert [r["pdf_page"] for r in records] == list(range(1, len(records) + 1))
        assert all(r["source_id"] == source["source_id"] and not r.get("quarantined") for r in records)
        assert source["source_sha256"] == digests[source["source_id"]]
        assert all(r["source_sha256"] == digests[r["source_id"]] for r in records)
        count += len(records)
    assert count == data["counts"]["pages"] == 583
    assert data["counts"]["ocr_executed"] == 315


def test_worker_init_sets_identical_two_threads_for_serial_and_parallel():
    import torch
    from ocop_ocr.pdf_pipeline import _worker_init

    _worker_init(True)
    assert torch.get_num_threads() == 2
