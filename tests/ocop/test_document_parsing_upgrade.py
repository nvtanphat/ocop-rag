"""Contracts for the fixed EasyOCR detector + VietOCR recognizer path."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from ai_core.processing.ocop.artifact_cache import PARSER_VERSION
from ai_core.processing.ocop.easy_viet_ocr import _pdf_bbox, run_easy_viet_ocr
from ai_core.processing.ocop.pdf_quality import score_page_quality
from ai_core.processing.ocop.ocr_types import OCRResult


def _page(width=500, height=700):
    return SimpleNamespace(rect=SimpleNamespace(width=width, height=height))


def test_pixel_bbox_maps_to_pdf_points_and_rejects_invalid_geometry():
    assert _pdf_bbox([200, 100, 500, 350], width_px=1000, height_px=1000,
                     page=_page()) == [100.0, 70.0, 250.0, 245.0]
    with pytest.raises(ValueError, match="bbox"):
        _pdf_bbox([20, 10, float("nan"), 30], width_px=100, height_px=100, page=_page())


def test_easyocr_detection_regions_are_merged_and_recognized_by_vietocr(monkeypatch):
    import ai_core.processing.ocop.easy_viet_ocr as adapter

    class Detector:
        def detect(self, image, **kwargs):
            assert kwargs["canvas_size"] == 3000
            assert kwargs["min_size"] == 12
            assert kwargs["text_threshold"] == 0.60
            assert kwargs["low_text"] == 0.35
            assert kwargs["link_threshold"] == 0.35
            return ([[[10, 65, 20, 45], [69, 145, 20, 45]]], [[]])

    class Recognizer:
        def __init__(self):
            self.crops = []

        def predict(self, crop, return_prob=False):
            self.crops.append(crop)
            assert return_prob is True
            return "  OCR text  ", 0.94

    recognizer = Recognizer()
    monkeypatch.setattr(adapter, "_detector", lambda: Detector())
    monkeypatch.setattr(adapter, "_predictor", lambda: recognizer)
    monkeypatch.setattr(adapter, "detect_regions", lambda rgb: ([], None))
    monkeypatch.setattr("ai_core.processing.ocop.table_parser.raster_tables", lambda *a, **k: [])

    trace = {}
    result, tables = run_easy_viet_ocr(
        Image.new("RGB", (200, 100), "white"), _page(200, 100), trace=trace
    )

    assert len(recognizer.crops) == 1
    assert tables == []
    assert result.engine == "easyocr_vietocr"
    assert result.blocks[0]["text"] == "OCR text"
    assert result.blocks[0]["bbox"] == [10.0, 20.0, 145.0, 45.0]
    assert result.blocks[0]["confidence"] == 0.94
    assert result.blocks[0]["review_status"] == "needs_review"
    assert result.blocks[0]["candidate_only"] is True
    assert trace["easyocr_craft"]["raw_horizontal_boxes"] == [[10, 65, 20, 45], [69, 145, 20, 45]]
    assert trace["easyocr_craft"]["role"] == "text_region_detector_only"
    assert trace["vietocr_raw_recognitions"][0]["raw_text"] == "  OCR text  "
    assert trace["ocr_blocks_before_table_parser"][0]["text"] == "OCR text"


def test_fragments_in_separate_score_columns_are_not_merged():
    from ai_core.processing.ocop.easy_viet_ocr import _merge_line_fragments

    regions = [
        {"bbox_px": [10, 20, 35, 40], "polygon": []},
        {"bbox_px": [40, 20, 55, 40], "polygon": []},
    ]
    table = {"bbox": [0, 0, 100, 100], "cells": [
        {"row": 0, "col": 0, "bbox": [0, 0, 39, 50]},
        {"row": 0, "col": 1, "bbox": [39, 0, 100, 50]},
    ]}
    merged = _merge_line_fragments(regions, Image.new("RGB", (100, 100)), _page(100, 100), [table])
    assert len(merged) == 2


def test_table_row_split_keeps_boundary_near_the_region_edge():
    from ai_core.processing.ocop.easy_viet_ocr import _split_at_table_rows

    region = {"bbox_px": [50, 18, 60, 82],
              "polygon": [[50, 18], [60, 18], [60, 82], [50, 82]]}
    table = {"cells": [
        {"row": 0, "col": 0, "bbox": [0, 0, 100, 30]},
        {"row": 1, "col": 0, "bbox": [0, 30, 100, 50]},
        {"row": 2, "col": 0, "bbox": [0, 50, 100, 70]},
        {"row": 3, "col": 0, "bbox": [0, 70, 100, 100]},
    ]}

    regions = _split_at_table_rows([region], Image.new("RGB", (100, 100)), _page(100, 100), [table])

    assert [item["bbox_px"] for item in regions] == [
        [50, 18, 60, 30], [50, 30, 60, 50], [50, 50, 60, 70], [50, 70, 60, 82],
    ]


def test_single_skewed_detection_keeps_polygon_for_recognition_crop():
    from ai_core.processing.ocop.easy_viet_ocr import _merge_line_fragments

    polygon = [[20, 34], [70, 20], [76, 40], [26, 54]]
    regions = [{"bbox_px": [20, 20, 76, 54], "polygon": polygon}]
    merged = _merge_line_fragments(regions, Image.new("RGB", (100, 100)), _page(100, 100), [])

    assert len(merged) == 1
    assert merged[0]["polygon"] == polygon


def test_skewed_detection_is_rectified_before_recognition():
    from ai_core.processing.ocop.easy_viet_ocr import _recognition_crop

    crop = _recognition_crop(Image.new("RGB", (100, 100), "white"), {
        "bbox_px": [20, 20, 76, 54],
        "polygon": [[20, 34], [70, 20], [76, 40], [26, 54]],
    })

    assert crop.width > crop.height
    assert crop.height < 34


def test_sparse_cell_retry_adds_only_unverified_numeric_candidates(monkeypatch):
    import ai_core.processing.ocop.easy_viet_ocr as adapter

    class Recognizer:
        def __init__(self):
            self.predictions = iter([("1", 0.91), ("1", 0.89), ("1", 0.92), ("Q", 0.92), ("0", 0.88)])

        def predict(self, crop, return_prob=False):
            assert return_prob is True
            return next(self.predictions)

    cell = {"row": 0, "col": 1, "bbox": [140, 100, 200, 134], "text": "o"}
    blank = {"row": 1, "col": 1, "bbox": [140, 150, 200, 184], "text": ""}
    q_misread = {"row": 2, "col": 1, "bbox": [140, 190, 200, 224], "text": "Q"}
    table = {"col_count": 2, "bbox": [0, 0, 200, 240], "cells": [cell, blank, q_misread]}
    image = Image.new("RGB", (300, 300), "white")
    page = _page(300, 300)

    def detect(reader, rgb):
        assert rgb.shape[:2] == (64, 116)
        return [{"bbox_px": [20, 20, 80, 80], "polygon": [[20, 20], [80, 20], [80, 80], [20, 80]]}]

    monkeypatch.setattr(adapter, "_detect_regions", detect)

    count = adapter._recover_sparse_cell_candidates(image, page, [table], object(), Recognizer())

    assert count == 3
    assert cell["text"] == "o" and blank["text"] == "" and q_misread["text"] == "Q"
    assert cell["score_ocr_candidates"][0]["text"] == "1"
    assert q_misread["score_ocr_candidates"][0]["text"] == "0"
    assert q_misread["score_ocr_candidates"][0]["method"] == "vietocr_vgg_transformer_2x_direct_cell_crop"
    assert all(candidate["candidate_only"] and candidate["review_status"] == "needs_review"
               for target in (cell, blank, q_misread) for candidate in target["score_ocr_candidates"])


def test_asset_signature_changes_with_local_model_bytes_without_loading_them(tmp_path, monkeypatch):
    import ai_core.processing.ocop.easy_viet_ocr as adapter

    detector = tmp_path / "craft_mlt_25k.pth"
    weights = tmp_path / "vgg_transformer.pth"
    detector.write_bytes(b"detector one")
    weights.write_bytes(b"recognizer one")
    monkeypatch.setattr(adapter, "_detector_path", lambda: detector)
    monkeypatch.setattr(adapter, "_vietocr_weights", lambda: weights)
    monkeypatch.setattr(adapter, "_detector", lambda: pytest.fail("asset check loaded detector"))
    monkeypatch.setattr(adapter, "_predictor", lambda: pytest.fail("asset check loaded recognizer"))

    first = adapter.asset_signature()
    weights.write_bytes(b"recognizer two")
    second = adapter.asset_signature()

    assert first["detector_sha256"] == second["detector_sha256"]
    assert first["weights_sha256"] != second["weights_sha256"]
    assert first["config_sha256"] == second["config_sha256"]


def test_vietocr_architecture_config_is_loaded_locally_without_remote_loader(tmp_path, monkeypatch):
    import ai_core.processing.ocop.easy_viet_ocr as adapter
    from vietocr.tool.config import Cfg

    weights = tmp_path / "vgg_transformer.pth"
    weights.write_bytes(b"recognizer checkpoint")
    monkeypatch.setattr(adapter, "_vietocr_weights", lambda: weights)
    monkeypatch.setattr(
        Cfg,
        "load_config_from_name",
        lambda *_args, **_kwargs: pytest.fail("VietOCR attempted to load remote config"),
    )

    config = adapter._vietocr_config()

    assert config["seq_modeling"] == "transformer"
    assert config["backbone"] == "vgg19_bn"
    assert {"Đ", "ă", "ấ", "9"} <= set(config["vocab"])
    assert config["device"] == "cpu"


def test_scan_page_uses_one_ocr_result_for_text_and_table_candidates(monkeypatch):
    import fitz
    import ai_core.processing.ocop.pdf_pipeline as pipeline

    result = OCRResult([{
        "block_id": "ocr:easyocr_vietocr:0", "text": "Tiêu chí 3", "bbox": [10, 10, 80, 40],
        "method": "easyocr_craft+vietocr_vgg_transformer", "order": 0, "confidence": 0.9,
        "review_status": "needs_review", "candidate_only": True,
    }], "easyocr_vietocr", ["ocr_candidates_require_source_verification"])
    table = {"table_id": "table:raster:0", "method": "opencv_grid_candidate",
             "bbox": [10, 60, 200, 300], "row_count": 1, "col_count": 2,
             "cells": [], "review_status": "needs_review"}
    calls = []

    def fake(*args, **kwargs):
        calls.append(kwargs)
        return result, [table]

    monkeypatch.setattr(pipeline, "run_easy_viet_ocr", fake)
    trace = {}
    with fitz.open() as document:
        page = document.new_page(width=500, height=700)
        page.insert_image(page.rect, stream=_white_png())
        profile = {"pdf_page": 1, "page_class": "ocr_candidate", "needs_ocr_review": True,
                   "largest_image_area_ratio": 1.0, "width_pt": 500.0, "height_pt": 700.0}
        artifact = pipeline.extract_page(page, profile, source_id="VN.TEST", trace=trace)

    assert len(calls) == 1
    assert calls[0]["detect_tables"] is True
    assert artifact["extraction_method"] == "easyocr_vietocr"
    assert artifact["tables"][0]["method"] == "opencv_grid_candidate"
    assert artifact["review_status"] == "needs_review"
    assert artifact["blocks"][0]["candidate_only"] is True
    assert trace["source_render"].size == (2084, 2917)
    assert trace["preprocessed_render"].size == trace["source_render"].size
    assert trace["ocr_executed"] is True


def _white_png():
    import io
    stream = io.BytesIO()
    Image.new("RGB", (500, 700), "white").save(stream, format="PNG")
    return stream.getvalue()


def test_quality_reports_blank_score_candidates_without_verifying_them():
    quality = score_page_quality({"page_class": "ocr_candidate"}, [], [{
        "bbox": [0, 0, 500, 300], "row_count": 1, "col_count": 2,
        "cells": [{"row": 0, "col": 0, "text": "Criterion", "bbox": [0, 0, 390, 40]},
                  {"row": 0, "col": 1, "text": "", "bbox": [390, 0, 500, 40]}],
    }])
    assert quality["potential_score_cells_blank"] == 1
    assert quality["requires_manual_score_validation"] is True
    assert quality["quality_is_not_legal_verification"] is True


def test_new_parser_version_invalidates_old_ocr_caches():
    assert PARSER_VERSION == "ocop-pdf-v7.0.0"


def test_extracted_text_joins_same_row_fragments_but_keeps_separate_lines():
    from ai_core.processing.ocop.layout import join_blocks_by_line as _join_blocks_by_line
    blocks = [
        {"text": "Công tác đánh", "bbox": [118.0, 46.5, 431.4, 70.5]},
        {"text": "giá, phân hạng sản", "bbox": [431.4, 46.5, 540.3, 70.5]},
        {"text": "phẩm OCOP được", "bbox": [89.0, 62.9, 309.3, 86.6]},
        {"text": "  ", "bbox": [310.0, 62.9, 320.0, 86.6]},
        {"text": "Cấp tỉnh", "bbox": [309.3, 62.9, 466.2, 86.6]},
    ]
    assert _join_blocks_by_line(blocks) == "Công tác đánh giá, phân hạng sản\nphẩm OCOP được Cấp tỉnh"
    far = [{"text": "A", "bbox": [10, 0, 20, 10]}, {"text": "B", "bbox": [200, 0, 210, 10]}]
    assert _join_blocks_by_line(far) == "A\nB"


def test_speckle_regions_are_tiny_low_confidence_crops_only():
    from ai_core.processing.ocop.easy_viet_ocr import _speckle_regions

    readings = [(84, 0.95)] * 9 + [(17, 0.24), (13, 0.57), (17, 0.9), (40, 0.94), (20, 0.7)]
    assert _speckle_regions(readings) == {9, 10}
    assert _speckle_regions(readings[:5] + [(12, 0.2)]) == set()


def test_leading_checkbox_is_blanked_but_leading_letter_o_is_kept():
    import cv2
    from ai_core.processing.ocop.easy_viet_ocr import _blank_leading_checkbox

    def line(draw_first):
        canvas = np.full((40, 200, 3), 255, dtype=np.uint8)
        draw_first(canvas)
        cv2.rectangle(canvas, (40, 12), (150, 30), (0, 0, 0), -1)  # the text that must survive
        return Image.fromarray(canvas)

    box = line(lambda c: cv2.rectangle(c, (6, 10), (24, 28), (0, 0, 0), 2))
    ring = line(lambda c: cv2.ellipse(c, (15, 19), (8, 10), 0, 0, 360, (0, 0, 0), 2))

    cleared = np.asarray(_blank_leading_checkbox(box))
    assert cleared[:, :30].min() == 255 and cleared[20, 100].max() == 0
    assert np.array_equal(np.asarray(_blank_leading_checkbox(ring)), np.asarray(ring))


def test_long_region_is_cut_mid_gap_and_crop_padding_at_the_cut_is_blank():
    from ai_core.processing.ocop.easy_viet_ocr import _recognition_crop, _split_long_regions

    canvas = np.full((60, 1400, 3), 255, dtype=np.uint8)
    canvas[20:40, 10:690] = 0      # word run before a gap
    canvas[20:40, 710:1390] = 0    # word run after it
    image = Image.fromarray(canvas)
    pieces = _split_long_regions([{"bbox_px": [0, 15, 1400, 45], "polygon": []}], image, maximum_ratio=25)
    assert len(pieces) == 2 and 695 <= pieces[0]["bbox_px"][2] <= 705
    assert pieces[0]["cut_edges"] == ["right"] and pieces[1]["cut_edges"] == ["left"]
    crop = np.asarray(_recognition_crop(image, pieces[0]))
    assert crop[:, -1].min() == 255  # no pixels of the next piece leak into the padding
