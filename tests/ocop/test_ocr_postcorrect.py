"""Diacritic post-correction: context-chosen marks only, raw OCR kept, digits and native pages untouched."""
from ai_core.processing.ocop.ocr_postcorrect import DiacriticModel, correct_texts, postcorrect_artifact, skeleton

NATIVE = ["Quyết định của Thủ tướng Chính phủ về việc quản lý chương trình mục tiêu quốc gia.",
          "Chính phủ về việc quản lý hồ sơ kèm theo Phụ lục kèm theo.",
          "Thủ tướng Chính phủ ban hành quy định quản lý; hồ sơ được chuyển hồ sơ lên cấp tỉnh."] * 3


def test_skeleton_drops_every_vietnamese_mark():
    assert skeleton("Phủ") == skeleton("phú") == "phu"
    assert skeleton("đường") == "duong"


def test_wrong_mark_is_corrected_from_context_and_case_is_kept():
    model = DiacriticModel.from_lines(NATIVE)
    texts, changes = correct_texts(["Thú tướng Chính phú về việc quân lý", "Phụ lục kêm theo"], model)
    assert texts == ["Thủ tướng Chính phủ về việc quản lý", "Phụ lục kèm theo"]
    assert {"from": "kêm", "to": "kèm"} in changes[1]


def test_context_crosses_block_boundaries():
    model = DiacriticModel.from_lines(NATIVE)
    texts, _ = correct_texts(["hồ sơ được", "chuyên hồ sơ"], model)
    assert texts[1] == "chuyển hồ sơ"


def test_unknown_words_attested_tokens_and_digits_are_left_alone():
    model = DiacriticModel.from_lines(NATIVE)
    original = ["Bảng điểm 83,8 và 4 sao", "Chính phủ về việc", "Nhãn hiệu sản phẩm"]
    texts, changes = correct_texts(original, model)
    assert texts == original and not any(changes)


def _unsure(text, char, *alts):
    return {"i": text.index(char), "alts": [list(a) for a in alts]}


def test_only_characters_the_recognizer_weighed_can_change():
    model = DiacriticModel.from_lines(NATIVE)
    text = "Chính phú về việc quân lý"
    weighed = [[_unsure(text, "ú", ("ú", 0.6), ("ủ", 0.3))]]  # nothing weighed for "quân"
    texts, changes = correct_texts([text], model, alternatives=weighed)
    assert texts == ["Chính phủ về việc quân lý"] and changes[0] == [{"from": "phú", "to": "phủ"}]
    assert correct_texts([text], model, alternatives=[[]])[0] == [text]


def test_strong_recognizer_odds_outweigh_weak_context():
    model = DiacriticModel.from_lines(NATIVE)
    text = "Chính phú về việc"
    weighed = [[_unsure(text, "ú", ("ú", 0.98), ("ủ", 1e-15))]]
    assert correct_texts([text], model, alternatives=weighed)[0] == [text]


def test_artifact_keeps_raw_ocr_text_cells_follow_blocks_and_native_pages_are_skipped():
    model = DiacriticModel.from_lines(NATIVE)
    raw = "Chính phú về việc"
    block = {"block_id": "b0", "text": raw, "bbox": [0, 0, 100, 10],
             "uncertain_chars": [_unsure(raw, "ú", ("ú", 0.6), ("ủ", 0.3))]}
    page = {"ocr_engine": "easyocr_vietocr", "blocks": [block], "tables": [{"cells": [
        {"row": 0, "col": 0, "text": raw, "bbox": [0, 0, 120, 12]},
        {"row": 0, "col": 1, "text": "2", "bbox": [120, 0, 160, 12]}]}]}
    out = postcorrect_artifact(page, model)
    assert out["blocks"][0]["text"] == "Chính phủ về việc" and out["blocks"][0]["ocr_raw_text"] == raw
    assert out["extracted_text"] == "Chính phủ về việc"
    cells = out["tables"][0]["cells"]
    assert cells[0]["text"] == "Chính phủ về việc" and cells[0]["ocr_raw_text"] == raw and cells[1]["text"] == "2"
    assert out["postcorrection"]["review_status"] == "needs_review"
    assert postcorrect_artifact(out, model)["blocks"][0]["text"] == "Chính phủ về việc"  # idempotent
    native = {"ocr_engine": None, "blocks": [{"text": "Chính phú"}], "tables": []}
    assert postcorrect_artifact(native, model)["blocks"][0]["text"] == "Chính phú"
