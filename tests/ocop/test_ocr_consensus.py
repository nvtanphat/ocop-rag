"""Agreement can add accents, never change numbers or existing legal words."""

from ai_core.processing.ocop.ocr_consensus import accent_consensus


def test_missing_diacritic_requires_two_agreeing_recognizers():
    text = "cấp tinh: 100%"
    assert accent_consensus(text, ["cấp tỉnh: 100%"])[0] == text
    assert accent_consensus(text, ["cấp tỉnh", "cấp tĩnh"])[0] == text
    result, changes = accent_consensus(text, ["cấp tỉnh: 100%", "cấp tỉnh: 100%"])
    assert result == "cấp tỉnh: 100%"
    assert changes[0]["review_status"] == "needs_review"


def test_existing_tones_base_letters_and_scores_cannot_change():
    text = "sản phẩm 100% nguồn gốc 3"
    result, changes = accent_consensus(text, ["sân phẩm 700% nguôn gôc 8"] * 2)
    assert result == text
    assert changes == []


def test_repeated_ambiguous_words_do_not_get_rewritten():
    text = "tinh bột của tinh"
    assert accent_consensus(text, ["tinh bột của tỉnh"] * 2)[0] == text


def test_case_and_punctuation_survive_accent_agreement():
    assert (
        accent_consensus("Tinh, OCOP; 24/02/2023", ["Tỉnh, ÓCÓP; 21/02/2023"] * 2)[0]
        == "Tỉnh, OCOP; 24/02/2023"
    )


def test_refinement_keeps_score_provenance_and_does_not_reuse_old_model_confidence(monkeypatch):
    from types import SimpleNamespace
    from PIL import Image
    import pytesseract
    from ai_core.processing.ocop import easy_viet_ocr
    from ai_core.processing.ocop.ocr_consensus import refine_table_regions

    monkeypatch.setattr(
        pytesseract,
        "image_to_data",
        lambda *args, **kwargs: {
            "text": ["cấp tỉnh", "OCOP*****"],
            "conf": [96, 88],
            "left": [15, 90],
            "top": [14, 14],
            "width": [65, 65],
            "height": [14, 14],
        },
    )

    class Reader:
        def readtext(self, *args, **kwargs):
            return [([[0, 0], [80, 0], [80, 20], [0, 20]], "cấp tỉnh OCOP", 0.9)]

    monkeypatch.setattr(easy_viet_ocr, "_reader", lambda hybrid: Reader())
    blocks = [
        {
            "block_id": "source:line",
            "text": "cấp tinh OCOP",
            "confidence": 0.91,
            "bbox": [20, 20, 190, 45],
            "method": "easyocr_vietocr",
            "order": 0,
        }
    ]
    score = {
        "col": 1,
        "bbox": [200, 10, 250, 60],
        "text": "3",
        "text_original": "",
        "review_status": "needs_review",
    }
    table = {
        "bbox": [10, 10, 250, 60],
        "col_count": 2,
        "cells": [{"col": 0, "bbox": [10, 10, 200, 60], "text": "cấp tinh OCOP"}, score],
    }
    stats = refine_table_regions(
        Image.new("RGB", (400, 200), "white"),
        SimpleNamespace(rect=SimpleNamespace(width=400, height=200)),
        blocks,
        [table],
    )
    assert score["text"] == "3" and score["text_original"] == ""
    changed = next(b for b in blocks if b["block_id"] == "source:line")
    assert changed["text"] == "cấp tỉnh OCOP"
    assert changed["text_original"] == "cấp tinh OCOP"
    assert changed["confidence"] is None and changed["confidence_original"] == 0.91
    assert stats["literal_markers_added"] == 5
    assert all(b["review_status"] == "needs_review" for b in blocks)
    assert "*****" in table["cells"][0]["text"]


def test_deskewed_markers_replace_fragmented_primary_without_changing_scores(monkeypatch):
    from types import SimpleNamespace
    from PIL import Image
    import pytesseract
    from ai_core.processing.ocop.ocr_consensus import refine_table_regions

    monkeypatch.setattr(
        pytesseract,
        "image_to_data",
        lambda *args, **kwargs: {
            "text": ["OCOP"],
            "conf": [99],
            "left": [20],
            "top": [15],
            "width": [50],
            "height": [10],
        },
    )
    blocks = [
        {
            "block_id": "line",
            "text": "OCOP*x**",
            "confidence": 0.9,
            "bbox": [10, 10, 180, 50],
            "method": "easyocr_vietocr",
            "order": 0,
            "review_status": "needs_review",
        }
    ]
    tables = [
        {
            "bbox": [0, 0, 250, 60],
            "col_count": 2,
            "cells": [
                {"col": 0, "bbox": [0, 0, 200, 60], "text": "OCOP*x**"},
                {"col": 1, "bbox": [200, 0, 250, 60], "text": "3"},
            ],
        }
    ]
    marker = {"text": "OCOP*****", "confidence": 0.88, "bbox": [100, 20, 150, 35]}
    stats = refine_table_regions(
        Image.new("RGB", (400, 200), "white"),
        SimpleNamespace(rect=SimpleNamespace(width=400, height=200)),
        blocks,
        tables,
        marker_words=[marker],
    )
    assert stats["literal_markers_added"] == 5
    assert tables[0]["cells"][1]["text"] == "3"
    assert tables[0]["cells"][0]["text"].count("*") == 5
    assert blocks[0]["text_original"] == "OCOP*x**" and blocks[0]["confidence"] is None
    assert all(b["review_status"] == "needs_review" for b in blocks)
