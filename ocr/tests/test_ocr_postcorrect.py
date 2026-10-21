"""Diacritic post-correction: recognizer-weighed marks chosen by context, raw OCR kept, digits and native pages untouched."""
import pytest

from ocop_ocr.ocr_postcorrect import DiacriticModel, correct_texts, postcorrect_artifact, skeleton

NATIVE = ["Quyết định của Thủ tướng Chính phủ về việc quản lý chương trình mục tiêu quốc gia.",
          "Chính phủ về việc quản lý hồ sơ kèm theo Phụ lục kèm theo.",
          "Thủ tướng Chính phủ ban hành quy định quản lý; hồ sơ được chuyển hồ sơ lên cấp tỉnh."] * 3


def _unsure(text, char, *alts, nth=0):
    index = -1
    for _ in range(nth + 1):
        index = text.index(char, index + 1)
    return {"i": index, "alts": [list(a) for a in alts]}


def test_skeleton_drops_every_vietnamese_mark():
    assert skeleton("Phủ") == skeleton("phú") == "phu"
    assert skeleton("đường") == "duong"


def test_weighed_wrong_marks_are_corrected_from_context_and_case_is_kept():
    model = DiacriticModel.from_lines(NATIVE)
    first, second = "Thú tướng Chính phú về việc quân lý", "Phụ lục kêm theo"
    alternatives = [[_unsure(first, "ú", ("ú", 0.6), ("ủ", 0.3)),
                     _unsure(first, "ú", ("ú", 0.5), ("ủ", 0.4), nth=1),
                     _unsure(first, "â", ("â", 0.6), ("ả", 0.3))],
                    [_unsure(second, "ê", ("ê", 0.6), ("è", 0.3))]]
    texts, changes = correct_texts([first, second], alternatives, model)
    assert texts == ["Thủ tướng Chính phủ về việc quản lý", "Phụ lục kèm theo"]
    assert changes[1] == [{"from": "kêm", "to": "kèm"}]


def test_context_crosses_block_boundaries():
    model = DiacriticModel.from_lines(NATIVE)
    texts, _ = correct_texts(["hồ sơ được", "chuyên hồ sơ"],
                             [[], [_unsure("chuyên hồ sơ", "ê", ("ê", 0.6), ("ể", 0.3))]], model)
    assert texts[1] == "chuyển hồ sơ"


def test_only_characters_the_recognizer_weighed_can_change():
    model = DiacriticModel.from_lines(NATIVE)
    text = "Chính phú về việc quân lý"
    texts, changes = correct_texts([text], [[_unsure(text, "ú", ("ú", 0.6), ("ủ", 0.3))]], model)
    assert texts == ["Chính phủ về việc quân lý"] and changes[0] == [{"from": "phú", "to": "phủ"}]
    assert correct_texts([text], [[]], model)[0] == [text]


def test_strong_recognizer_odds_outweigh_weak_context():
    model = DiacriticModel.from_lines(NATIVE)
    text = "Chính phú về việc"
    assert correct_texts([text], [[_unsure(text, "ú", ("ú", 0.98), ("ủ", 1e-15))]], model)[0] == [text]


def test_unknown_words_attested_tokens_and_digits_are_left_alone():
    model = DiacriticModel.from_lines(NATIVE)
    original = ["Bảng điểm 83,8 và 4 sao", "Chính phủ về việc", "Nhãn hiệu sản phẩm"]
    alternatives = [[{"i": i, "alts": [[c, 0.5], ["x", 0.4]]} for i, c in enumerate(text)] for text in original]
    texts, changes = correct_texts(original, alternatives, model)
    assert texts == original and not any(changes)


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



def test_checkbox_normalization_keeps_raw_recognition_and_updates_table_cells():
    model=DiacriticModel.from_lines(NATIVE)
    raw="\u1edf C\u00f3 n\u1ed9i dung"
    clean="C\u00f3 n\u1ed9i dung"
    normalization={"kind":"remove_leading_checkbox_token","token":"\u1edf"}
    block={"block_id":"b-checkbox","text":clean,"ocr_raw_text":raw,
           "ocr_normalizations":[normalization],"bbox":[0,0,100,10]}
    page={"ocr_engine":"easyocr_vietocr","blocks":[block],"tables":[{"cells":[
        {"row":0,"col":0,"text":raw,"bbox":[0,0,120,12]}]}]}

    out=postcorrect_artifact(page,model)

    assert out["blocks"][0]["text"]==clean
    assert out["blocks"][0]["ocr_raw_text"]==raw
    assert out["blocks"][0]["ocr_normalizations_applied"]==[normalization]
    assert out["tables"][0]["cells"][0]["text"]==clean
    assert out["tables"][0]["cells"][0]["ocr_raw_text"]==raw


def test_percentage_threshold_symbol_correction_preserves_raw_text_and_score_digits():
    model = DiacriticModel.from_lines(NATIVE)
    raw = "Có sử dụng 2 75% lao động; điều kiện 2 51%; mức chấm 2 điểm."
    block = {"block_id": "b-threshold", "text": raw, "bbox": [0, 0, 220, 12]}
    page = {"ocr_engine": "easyocr_vietocr", "blocks": [block], "tables": [{"cells": [
        {"row": 0, "col": 0, "text": raw, "bbox": [0, 0, 240, 14]},
    ]}]}

    out = postcorrect_artifact(page, model)

    corrected = "Có sử dụng ≥ 75% lao động; điều kiện ≥ 51%; mức chấm 2 điểm."
    assert out["blocks"][0]["text"] == corrected
    assert out["blocks"][0]["ocr_raw_text"] == raw
    assert out["tables"][0]["cells"][0]["text"] == corrected
    assert out["tables"][0]["cells"][0]["ocr_raw_text"] == raw
    assert out["blocks"][0]["postcorrections"] == [
        {"from": "2", "to": "≥", "reason": "isolated_2_before_percentage_threshold"},
        {"from": "2", "to": "≥", "reason": "isolated_2_before_percentage_threshold"},
    ]
    assert out["postcorrection"]["changes"] == 2


def test_safe_ocop_spelling_repairs_preserve_raw_ocr_text():
    model = DiacriticModel.from_lines(NATIVE)
    raw = "Hồ so; xử ly; trông phổ biến; sản phẩn"
    block = {"block_id": "b-spelling", "text": raw, "bbox": [0, 0, 220, 12]}
    page = {"ocr_engine": "easyocr_vietocr", "blocks": [block], "tables": []}

    postcorrect_artifact(page, model)

    assert block["text"] == "Hồ sơ; xử lý; trồng phổ biến; sản phẩm"
    assert block["ocr_raw_text"] == raw
    assert len(block["postcorrections"]) == 4


def test_complementary_community_share_rows_restore_missing_inequality_symbols():
    model = DiacriticModel.from_lines(NATIVE)
    company_raw = "Công ty TNHH có vốn góp của cộng đồng người địa phương 51%"
    cooperative_raw = "HTX tổ chức theo quy định; vốn góp của cộng đồng người địa phương - 51%"
    company = {"block_id": "b-company", "text": company_raw,
               "ocr_raw_text": company_raw, "bbox": [0, 0, 100, 10]}
    cooperative = {"block_id": "b-htx", "text": cooperative_raw,
                   "ocr_raw_text": cooperative_raw, "bbox": [0, 10, 100, 20]}
    table = {"col_count": 2, "cells": [
        {"row": 0, "col": 0, "bbox": [0, 0, 120, 10], "text": company_raw},
        {"row": 1, "col": 0, "bbox": [0, 10, 120, 20], "text": cooperative_raw},
        {"row": 0, "col": 1, "bbox": [120, 0, 140, 10], "text": "2"},
        {"row": 1, "col": 1, "bbox": [120, 10, 140, 20], "text": "3"},
    ]}
    page = {"ocr_engine": "easyocr_vietocr", "blocks": [company, cooperative], "tables": [table]}

    out = postcorrect_artifact(page, model)

    assert company["text"].endswith("<51%")
    assert cooperative["text"].endswith("≥ 51%")
    assert company["ocr_raw_text"] == company_raw
    assert cooperative["ocr_raw_text"] == cooperative_raw
    assert table["cells"][0]["text"].endswith("<51%")
    assert table["cells"][1]["text"].endswith("≥ 51%")
    assert out["postcorrection"]["review_status"] == "needs_review"


@pytest.mark.parametrize("suffix", ["ese?", "(tt", "tsr", "ver.", '"'])
def test_asterisk_marker_noise_suffix_is_removed_only_with_same_line_image_candidate(suffix):
    model = DiacriticModel.from_lines(NATIVE)
    raw = f"Đóng gói sáng tạo, bao bì đẹp{suffix}"
    marker = {"text": "***", "bbox": [0, 0, 150, 30], "marker_bbox": [105, 12, 125, 18],
              "candidate_only": True, "review_status": "needs_review"}
    block = {"block_id": "b-marker", "text": raw, "bbox": [0, 10, 130, 20]}
    page = {"ocr_engine": "easyocr_vietocr", "blocks": [block], "tables": [{"cells": [
        {"row": 0, "col": 0, "bbox": [0, 0, 150, 30], "text": raw,
         "image_marker_candidates": [marker]}
    ]}]}

    out = postcorrect_artifact(page, model)

    assert block["text"] == "Đóng gói sáng tạo, bao bì đẹp"
    assert block["ocr_raw_text"] == raw
    assert out["tables"][0]["cells"][0]["image_marker_candidates"] == [marker]
    no_marker_block = {"text": raw, "bbox": [0, 10, 130, 20]}
    untouched = postcorrect_artifact(
        {"ocr_engine": "easyocr_vietocr", "blocks": [no_marker_block], "tables": []}, model
    )
    assert untouched["blocks"][0]["text"] == raw
