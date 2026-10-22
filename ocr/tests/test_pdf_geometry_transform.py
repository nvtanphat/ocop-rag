"""Source geometry coordinate transformations using actual PDF parsing, without model mocks."""
from pathlib import Path

import fitz
import pytest

from ocop_ocr.native_extractor import extract_native
from ocop_ocr.pdf_pipeline import extract_page
from ocop_ocr.profiler import profile_pdf
from ocop_ocr.table_parser import native_tables


def test_native_header_preserves_horizontal_merge():
    with fitz.open() as document:
        page = document.new_page(width=400, height=400)
        for y in (60, 100, 140):
            page.draw_line((40, y), (340, y))
        for x in (40, 340):
            page.draw_line((x, 60), (x, 140))
        page.draw_line((190, 100), (190, 140))
        page.insert_text((60, 85), "Score options")
        page.insert_text((60, 125), "Criterion")
        page.insert_text((210, 125), "3")
        table = native_tables(page)[0]
    header = next(cell for cell in table["cells"] if cell["row"] == 0)
    assert header["colspan"] == 2
    assert header["bbox"] == [40.0, 60.0, 340.0, 100.0]
    assert len(table["cells"]) == 3
    assert next(cell for cell in table["cells"] if cell["text"] == "3")["col"] == 1


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_rotated_native_text_matches_rendered_page(tmp_path: Path, rotation: int):
    path = tmp_path / "rotated.pdf"
    with fitz.open() as document:
        page = document.new_page(width=300, height=600)
        for i in range(10):
            page.insert_text((20, 280 + 25 * i), f"Legal clause {i + 1}: source evidence.")
        original = extract_native(page)
        page.set_rotation(rotation)
        expected = [list(fitz.Rect(block["bbox"]) * page.rotation_matrix) for block in original]
        document.save(path)
    profile = profile_pdf(path, "VN.TEST.ROTATED")[0]
    with fitz.open(path) as document:
        artifact = extract_page(document[0], profile, source_id="VN.TEST.ROTATED",
                                enable_ocr=False, enable_tables=False)
    assert len(artifact["blocks"]) == len(original)
    for block, box in zip(sorted(artifact["blocks"], key=lambda item: item["order"]), expected):
        assert block["bbox"] == pytest.approx(box, abs=0.02)
    assert not any("clipped" in warning for warning in artifact["warnings"])


def test_page_job_embeds_source_digest_and_rejects_cache_for_other_bytes(tmp_path):
    import ocop_ocr.pdf_pipeline as pipeline
    from ocop_contracts.registry import sha256_file

    path = tmp_path / "source.pdf"
    with fitz.open() as document:
        page = document.new_page(width=300, height=600)
        for i in range(10):
            page.insert_text((20, 40 + 25 * i), "Original legal evidence text")
        document.save(path)
    profile = profile_pdf(path, "VN.TEST.HASH")[0]
    job = (str(path), "VN.TEST.HASH", profile, str(tmp_path / "cache.json"), False, 120, False, False)
    artifact = pipeline._page_job(job)
    assert artifact["source_sha256"] == sha256_file(path)
    assert pipeline._page_job(job) == artifact
    with path.open("ab") as stream:
        stream.write(b"\n% changed PDF bytes\n")
    changed = pipeline._page_job(job)
    assert changed["source_sha256"] == sha256_file(path)
    assert changed["source_sha256"] != artifact["source_sha256"]


def _word_spaced_table(gap: float):
    document = fitz.open()
    page = document.new_page(width=400, height=300)
    for y in (60, 120, 180):
        page.draw_line((40, y), (340, y))
    for x in (40, 190, 340):
        page.draw_line((x, 60), (x, 180))
    x = 50
    for word in ("Cong", "ty", "Trach", "nhiem"):       # positioned words, no space glyphs between them
        page.insert_text((x, 90), word, fontsize=11)
        x += fitz.get_text_length(word, fontsize=11) + gap
    page.insert_text((200, 90), "San pham A")
    page.insert_text((50, 150), "x")
    page.insert_text((200, 150), "y")
    return document, page


def test_native_cell_text_restores_word_spaces_from_glyph_positions():
    document, page = _word_spaced_table(3.2)
    with document:
        cells = native_tables(page)[0]["cells"]
    assert cells[0]["text"] == "Cong ty Trach nhiem"
    assert [c["text"] for c in cells[1:]] == ["San pham A", "x", "y"]


def test_native_cell_text_does_not_invent_spaces_inside_words():
    document, page = _word_spaced_table(0.2)           # tight spacing: one word, kerning only
    with document:
        cells = native_tables(page)[0]["cells"]
    assert cells[0]["text"].replace(" ", "") == "CongtyTrachnhiem" and "Cong ty" not in cells[0]["text"]


def test_native_cell_text_keeps_the_extractor_text_when_the_clip_disagrees():
    from ocop_ocr.table_parser import _cell_text
    document, page = _word_spaced_table(3.2)
    with document:
        assert _cell_text(page, (0, 0, 400, 300), "different characters") == "different characters"
