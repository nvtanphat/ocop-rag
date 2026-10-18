"""Source geometry regressions using actual PDF parsing, without model mocks."""

from pathlib import Path

import fitz
import pytest

from ai_core.processing.ocop.native_extractor import extract_native
from ai_core.processing.ocop.pdf_pipeline import extract_page
from ai_core.processing.ocop.profiler import profile_pdf
from ai_core.processing.ocop.structure_engine import parse_html_cells
from ai_core.processing.ocop.table_parser import native_tables


def test_native_header_preserves_horizontal_merge():
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=400)
        for y in (60, 100, 140):
            page.draw_line((40, y), (340, y))
        for x in (40, 340):
            page.draw_line((x, 60), (x, 140))
        page.draw_line((190, 100), (190, 140))
        page.insert_text((60, 85), "Score options")
        page.insert_text((60, 125), "Criterion")
        page.insert_text((210, 125), "3")
        table = native_tables(page)[0]
    header = next(c for c in table["cells"] if c["row"] == 0)
    assert header["colspan"] == 2
    assert header["bbox"] == [40.0, 60.0, 340.0, 100.0]
    assert len(table["cells"]) == 3
    assert next(c for c in table["cells"] if c["text"] == "3")["col"] == 1


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_rotated_native_text_matches_rendered_page(tmp_path: Path, rotation: int):
    path = tmp_path / "rotated.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=600)
        for i in range(10):
            page.insert_text((20, 280 + 25 * i), f"Legal clause {i + 1}: source evidence.")
        original = extract_native(page)
        page.set_rotation(rotation)
        expected = [list(fitz.Rect(b["bbox"]) * page.rotation_matrix) for b in original]
        doc.save(path)
    profile = profile_pdf(path, "VN.TEST.ROTATED")[0]
    with fitz.open(path) as doc:
        artifact = extract_page(
            doc[0], profile, source_id="VN.TEST.ROTATED", enable_ocr=False, enable_tables=False
        )
    assert len(artifact["blocks"]) == len(original)
    for block, box in zip(sorted(artifact["blocks"], key=lambda b: b["order"]), expected):
        assert block["bbox"] == pytest.approx(box, abs=0.02)
    assert not any("clipped" in w for w in artifact["warnings"])


def test_html_cells_cannot_overlap_prior_rowspan():
    # A colspan starting in an empty slot still intersects the next occupied slot.
    html = '<table><tr><td>A</td><td rowspan="2">B</td></tr><tr><td colspan="2">C</td></tr></table>'
    with pytest.raises(ValueError, match="overlap"):
        parse_html_cells(html)


def test_page_job_embeds_source_digest_and_rejects_cache_for_other_bytes(tmp_path):
    import ai_core.processing.ocop.pdf_pipeline as pipeline
    from ai_core.processing.ocop.registry import sha256_file

    path = tmp_path / "source.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=600)
        for i in range(10):
            page.insert_text((20, 40 + 25 * i), "Original legal evidence text")
        doc.save(path)
    profile = profile_pdf(path, "VN.TEST.HASH")[0]
    job = (
        str(path),
        "VN.TEST.HASH",
        profile,
        str(tmp_path / "cache.json"),
        False,
        120,
        "tesseract",
        False,
        False,
        "opencv",
        False,
    )
    artifact = pipeline._page_job(job)
    assert artifact["source_sha256"] == sha256_file(path)
    assert pipeline._page_job(job) == artifact
    # Same source ID/page size/profile and same cache path, different PDF bytes.
    with path.open("ab") as stream:
        stream.write(b"\n% changed PDF bytes\n")
    changed = pipeline._page_job(job)
    assert changed["source_sha256"] == sha256_file(path)
    assert changed["source_sha256"] != artifact["source_sha256"]


def test_tesseract_signature_changes_when_model_bytes_change(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import ai_core.processing.ocop.ocr_extractor as adapter

    executable = tmp_path / "tesseract.exe"
    executable.write_bytes(b"engine")
    model = tmp_path / "vie.traineddata"
    model.write_bytes(b"first model")
    monkeypatch.setattr(adapter.shutil, "which", lambda name: str(executable))
    monkeypatch.setattr(
        adapter.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            stdout=f'List of available languages in "{tmp_path}" (1):\nvie\n', stderr=""
        ),
    )
    first = adapter.tesseract_runtime_signature()
    model.write_bytes(b"second model")
    second = adapter.tesseract_runtime_signature()
    assert first["engine_sha256"] == second["engine_sha256"]
    assert first["traineddata"]["vie"] != second["traineddata"]["vie"]


def test_crop_ocr_can_fill_missing_cell_without_verifying_score():
    from PIL import Image, ImageDraw
    from types import SimpleNamespace
    from ai_core.processing.ocop.score_cell_ocr import recover_scoring_cells

    image = Image.new("RGB", (400, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((300, 40, 380, 100), outline="black", width=2)
    draw.text((335, 60), "3", fill="black")
    tables = [
        {
            "bbox": [20, 40, 380, 100],
            "col_count": 2,
            "cells": [{"row": 0, "col": 1, "bbox": [300, 40, 380, 100], "text": ""}],
        }
    ]
    page = SimpleNamespace(rect=SimpleNamespace(width=400, height=200))
    recover_scoring_cells(image, page, tables, ocr_reader=lambda im: [("3", 0.97)], fill_empty=True)
    cell = tables[0]["cells"][0]
    assert cell["text"] == "3" and cell["text_original"] == ""
    assert cell["review_status"] == "needs_review"
    assert cell["score_ocr_candidates"][0]["review_status"] == "needs_review"


def test_conflicting_crop_readings_cannot_fill_empty_cell():
    from PIL import Image
    from types import SimpleNamespace
    from ai_core.processing.ocop.score_cell_ocr import recover_scoring_cells

    table = {
        "bbox": [0, 0, 400, 100],
        "col_count": 2,
        "cells": [{"row": 0, "col": 1, "bbox": [300, 0, 400, 100], "text": ""}],
    }
    page = SimpleNamespace(rect=SimpleNamespace(width=400, height=200))
    recover_scoring_cells(
        Image.new("RGB", (400, 200), "white"),
        page,
        [table],
        ocr_reader=lambda im: [("1", 0.95), ("7", 0.96)],
        fill_empty=True,
    )
    assert table["cells"][0]["text"] == ""


def test_invalid_score_recovery_retains_original_ocr():
    from PIL import Image
    from types import SimpleNamespace
    from ai_core.processing.ocop.score_cell_ocr import recover_scoring_cells

    table = {
        "bbox": [0, 0, 400, 100],
        "col_count": 2,
        "cells": [{"row": 0, "col": 1, "bbox": [300, 0, 400, 100], "text": "| 18 |"}],
    }
    page = SimpleNamespace(rect=SimpleNamespace(width=400, height=200))
    recover_scoring_cells(
        Image.new("RGB", (400, 200), "white"),
        page,
        [table],
        ocr_reader=lambda im: [("18", 0.95)],
        fill_invalid=True,
    )
    cell = table["cells"][0]
    assert cell["text"] == "18" and cell["text_original"] == "| 18 |"
    assert cell["review_status"] == "needs_review"


def test_tesseract_cannot_silently_use_english_when_vietnamese_model_is_missing(monkeypatch):
    import pytesseract
    from PIL import Image
    from types import SimpleNamespace
    import ai_core.processing.ocop.ocr_extractor as adapter

    monkeypatch.setattr(adapter.shutil, "which", lambda name: "tesseract.exe")
    monkeypatch.setattr(pytesseract, "get_languages", lambda **kw: ["eng", "osd"])
    page = SimpleNamespace(rect=SimpleNamespace(width=100, height=100))
    with pytest.raises(RuntimeError, match="missing_ocr_languages.*vie"):
        adapter._tesseract(Image.new("RGB", (100, 100)), page)
