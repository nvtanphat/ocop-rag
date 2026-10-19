from __future__ import annotations

import numpy as np
from PIL import Image

from ai_core.processing.ocop.easy_viet_ocr import (
    _extend_line_ends,
    _is_checkbox_glyph,
    _marker_follows_ocr_text,
    _tighten_line_boxes,
    _without_table_rules,
)
from ai_core.processing.ocop.ocr_postcorrect import (
    _correct_community_share_threshold_pair,
    _correct_safe_ocop_spellings,
)


def _line_image(words, *, width=400, height=120, rule_x=None):
    pixels = np.full((height, width), 255, np.uint8)
    for left, right in words:
        for x in range(left, right, 4):  # strokes, like glyphs: never a solid bar a rule filter would remove
            pixels[40:62, x:x + 2] = 0
    if rule_x is not None:
        pixels[:, rule_x] = 0
    return Image.fromarray(pixels).convert("RGB")


def _region(x0, y0, x1, y1):
    return {"bbox_px": [x0, y0, x1, y1], "polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


def test_line_box_grows_over_missed_first_and_last_words():
    image = _line_image([(30, 50), (58, 100), (108, 160), (168, 200), (208, 230)])
    extended = _extend_line_ends([_region(58, 38, 200, 64)], image)[0]["bbox_px"]
    assert extended[0] <= 30 and extended[2] >= 230


def test_line_box_does_not_cross_blank_gap_table_rule_or_neighbour():
    image = _line_image([(30, 100), (200, 230), (300, 330)], rule_x=250)
    box = _extend_line_ends([_region(30, 38, 100, 64)], image)[0]["bbox_px"]
    assert box == [30, 38, 100, 64]  # 100px gap is wider than a word space
    image = _line_image([(30, 100), (108, 160), (170, 230)], rule_x=250)
    box = _extend_line_ends([_region(30, 38, 100, 64), _region(165, 38, 240, 64)], image)[0]["bbox_px"]
    assert box[2] < 165  # stops before the neighbouring line box


def test_vertical_table_rule_is_removed_before_recognition():
    image = _line_image([(30, 100)], rule_x=20)
    cleaned = np.asarray(_without_table_rules(image, [_region(30, 38, 100, 64)]).convert("L"))
    assert cleaned[:, 20].min() == 255
    assert cleaned[40:62, 30:100].min() == 0


def test_marker_belongs_to_its_own_wrapped_line_not_the_previous_one():
    blocks = [{"bbox": [90, 282, 481, 303], "text": "first line of the cell"},
              {"bbox": [90, 295, 357, 316], "text": "second line"}]
    marker = [359, 299.5, 380, 305]
    assert _marker_follows_ocr_text(marker, [89, 280, 484, 318], blocks)


def test_misread_company_prefix_and_noise_before_threshold_are_corrected():
    text, _ = _correct_safe_ocop_spellings("Công ty INHH, hoặc doanh nghiệp, sử dung, của tinh")
    assert text.startswith("Công ty TNHH")
    assert "sử dụng" in text
    artifact = {
        "blocks": [{"text": "cộng đồng người địa phương 551%", "bbox": [10, 10, 100, 20]},
                   {"text": "vốn góp của cộng đồng người địa phương 251%", "bbox": [10, 30, 100, 40]}],
        "tables": [{"col_count": 2, "cells": [
            {"row": 0, "col": 0, "bbox": [0, 0, 120, 25],
             "text": "Công ty INHH, hoặc cộng đồng người địa phương 551%"},
            {"row": 1, "col": 0, "bbox": [0, 25, 120, 50],
             "text": "HTX tổ chức vốn góp của cộng đồng người địa phương 251%"}]}],
    }
    assert _correct_community_share_threshold_pair(artifact) == 2
    assert artifact["blocks"][0]["text"].endswith("địa phương <51%")
    assert artifact["blocks"][1]["text"].endswith("địa phương ≥ 51%")


def test_horizontal_table_rule_under_text_is_removed_before_recognition():
    pixels = np.full((120, 400), 255, np.uint8)
    for x in range(30, 100, 4):
        pixels[40:62, x:x + 2] = 0
    pixels[63, :] = 0  # the cell border touching the line's descenders
    cleaned = np.asarray(_without_table_rules(Image.fromarray(pixels).convert("RGB"),
                                              [_region(30, 38, 100, 64)]).convert("L"))
    assert cleaned[63, 200] == 255 and cleaned[45:60, 30:100].min() == 0


def test_over_tall_box_is_cut_to_its_line_only_when_neighbours_cover_the_rest():
    pixels = np.full((200, 300), 255, np.uint8)
    for top, stroke in ((20, 2), (70, 3), (120, 2)):  # the middle line carries the most ink
        for x in range(30, 250, 4):
            pixels[top:top + 22, x:x + stroke] = 0
    image = Image.fromarray(pixels).convert("RGB")
    tall, above, below = _region(30, 15, 250, 148), _region(30, 15, 250, 45), _region(30, 115, 250, 148)
    kept = _tighten_line_boxes([tall, above, below, _region(30, 66, 250, 96)], image)[0]["bbox_px"]
    assert 60 <= kept[1] and kept[3] <= 100  # the middle line only
    assert _tighten_line_boxes([tall], image)[0]["bbox_px"] == [30, 15, 250, 148]  # nothing else covers them


def test_a_lone_hollow_square_is_a_checkbox_but_a_zero_is_not():
    box = np.full((18, 18), 255, np.uint8)
    box[2:16, 2:16] = 0
    box[4:14, 4:14] = 255
    assert _is_checkbox_glyph(Image.fromarray(box).convert("RGB"))
    zero = np.full((18, 14), 255, np.uint8)
    zero[1:17, 3:11] = 0
    zero[4:14, 5:9] = 255
    zero[1:3, 3:5] = zero[1:3, 9:11] = zero[15:17, 3:5] = zero[15:17, 9:11] = 255  # rounded corners
    assert not _is_checkbox_glyph(Image.fromarray(zero).convert("RGB"))


def test_a_table_rule_splits_a_line_from_the_ink_just_below_it():
    pixels = np.full((120, 300), 255, np.uint8)
    for x in range(30, 250, 4):
        pixels[20:42, x:x + 2] = 0   # the line the box belongs to
        pixels[47:60, x:x + 2] = 0   # top of the next row, 5px under the rule
    pixels[44, :] = 0                # table rule between them
    image = Image.fromarray(pixels).convert("RGB")
    tall = _region(30, 15, 250, 62)
    kept = _tighten_line_boxes([tall, _region(30, 45, 250, 75)], image)[0]["bbox_px"]
    assert kept[3] <= 46
