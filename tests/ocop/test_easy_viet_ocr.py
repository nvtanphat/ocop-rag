"""Contracts for optional real-model OCR adapters, independent of model downloads."""

from types import SimpleNamespace
import sys

import pytest
from PIL import Image

from ai_core.processing.ocop.easy_viet_ocr import _blocks, _weights, run_easy_ocr


def page():
    return SimpleNamespace(rect=SimpleNamespace(width=100, height=200))


def test_free_regions_sorted_before_table_assignment_and_scaled():
    image = Image.new("RGB", (200, 400))
    result = _blocks(
        [
            ([[20, 200], [80, 200], [80, 220], [20, 220]], "sau", 0.9),
            ([[20, 20], [80, 20], [80, 40], [20, 40]], "trước", 0.8),
        ],
        image,
        page(),
        "easyocr_vietocr",
    )
    assert [b["text"] for b in result.word_blocks] == ["trước", "sau"]
    assert result.blocks[0]["bbox"] == [10, 10, 40, 20]
    assert result.blocks[0]["polygon"][2] == [40, 20]
    assert all(b["review_status"] == "needs_review" for b in result.blocks)


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), -1, 1.1])
def test_invalid_confidence_fails(confidence):
    with pytest.raises(ValueError, match="confidence"):
        _blocks(
            [([[1, 1], [20, 1], [20, 10], [1, 10]], "x", confidence)],
            Image.new("RGB", (200, 400)),
            page(),
            "easyocr",
        )


@pytest.mark.parametrize(
    "polygon", [[], [[1, 1]], [[1, 1]] * 4, [[float("nan"), 1]] * 4, [[300, 1], [320, 1], [320, 5], [300, 5]]]
)
def test_invalid_geometry_fails(polygon):
    with pytest.raises(ValueError, match="(polygon|region)"):
        _blocks([(polygon, "x", 0.9)], Image.new("RGB", (200, 400)), page(), "easyocr")


def test_missing_checkpoint_fails_without_network(monkeypatch):
    monkeypatch.delenv("OCOP_VIETOCR_WEIGHTS", raising=False)
    with pytest.raises(RuntimeError, match="vietocr_weights_missing"):
        _weights()


def test_hybrid_uses_detection_crops_and_recognition_confidence(monkeypatch):
    from ai_core.processing.ocop import easy_viet_ocr as adapter

    class Detector:
        def detect(self, pixels):
            return [[[10, 60, 20, 40]]], [[]]

    class Recognizer:
        def predict(self, image, return_prob):
            assert return_prob and image.mode == "RGB"
            return "Điểm", 0.85

    monkeypatch.setattr(adapter, "_reader", lambda hybrid: Detector())
    monkeypatch.setattr(adapter, "_predictor", lambda: Recognizer())
    monkeypatch.setattr(adapter, "_split_row_regions", lambda crops, image, page: crops)
    monkeypatch.setattr(adapter, "_merge_line_regions", lambda crops, image, page: crops)
    utils = SimpleNamespace(
        get_image_list=lambda horizontal, free, pixels: (
            [([[10, 20], [60, 20], [60, 40], [10, 40]], pixels[20:40, 10:60])],
            50,
        )
    )
    monkeypatch.setitem(sys.modules, "easyocr.utils", utils)
    result = run_easy_ocr(Image.new("RGB", (200, 400)), page(), "easyocr_vietocr")
    assert result.blocks[0]["text"] == "Điểm"
    assert result.blocks[0]["confidence"] == 0.85


def test_model_bytes_change_cache_identity(tmp_path, monkeypatch):
    from ai_core.processing.ocop import easy_viet_ocr as adapter

    monkeypatch.setattr(adapter, "_reader", lambda hybrid: SimpleNamespace(model_storage_directory=tmp_path))
    monkeypatch.setattr(adapter, "version", lambda package: "test")
    monkeypatch.setattr(adapter, "_predictor", lambda: None)
    (tmp_path / "craft_mlt_25k.pth").write_bytes(b"detector")
    checkpoint = tmp_path / "vgg_seq2seq.pth"
    checkpoint.write_bytes(b"first")
    monkeypatch.setenv("OCOP_VIETOCR_WEIGHTS", str(checkpoint))
    first = adapter.runtime_signature("easyocr_vietocr")
    checkpoint.write_bytes(b"second")
    second = adapter.runtime_signature("easyocr_vietocr")
    assert first["weights_sha256"] != second["weights_sha256"]
    assert first["config"]["cnn"]["pretrained"] is False


def test_cross_row_digit_regions_split_before_recognition(monkeypatch):
    import numpy as np
    from ai_core.processing.ocop import table_parser
    from ai_core.processing.ocop.easy_viet_ocr import _split_row_regions

    monkeypatch.setattr(
        table_parser,
        "raster_tables",
        lambda *args: [
            {
                "cells": [
                    {"bbox": [10, 10, 40, 20]},
                    {"bbox": [10, 20, 40, 30]},
                ]
            }
        ],
    )
    image = Image.new("RGB", (200, 400))
    polygon = [[25, 25], [35, 25], [35, 55], [25, 55]]
    regions = _split_row_regions([(polygon, np.zeros((64, 75), dtype=np.uint8))], image, page())
    assert len(regions) == 2
    assert regions[0][0] == [[25, 25], [35, 25], [35, 40], [25, 40]]
    assert regions[1][0] == [[25, 40], [35, 40], [35, 55], [25, 55]]
    assert regions[0][1].shape == (15, 10)


def test_horizontal_legal_line_not_split_by_approximate_grid(monkeypatch):
    import numpy as np
    from ai_core.processing.ocop import table_parser
    from ai_core.processing.ocop.easy_viet_ocr import _split_row_regions

    monkeypatch.setattr(
        table_parser,
        "raster_tables",
        lambda *args: [
            {
                "cells": [
                    {"bbox": [0, 0, 100, 20]},
                    {"bbox": [0, 20, 100, 40]},
                ]
            }
        ],
    )
    image = Image.new("RGB", (200, 400))
    polygon = [[20, 25], [180, 25], [180, 55], [20, 55]]
    regions = _split_row_regions([(polygon, np.zeros((64, 340), dtype=np.uint8))], image, page())
    assert len(regions) == 1
    assert regions[0][0] == polygon


def test_diacritics_do_not_move_middle_words_before_line_start():
    from ai_core.processing.ocop.layout import layout_page

    result = _blocks(
        [
            ([[20, 40], [45, 40], [45, 64], [20, 64]], "Vùng", 0.9),
            ([[50, 34], [95, 34], [95, 66], [50, 66]], "nguyên liệu", 0.9),
            ([[100, 38], [150, 38], [150, 62], [100, 62]], "được cấp", 0.9),
        ],
        Image.new("RGB", (200, 400)),
        page(),
        "easyocr_vietocr",
    )
    assert [b["text"] for b in result.blocks] == ["Vùng", "nguyên liệu", "được cấp"]
    ordered, _ = layout_page(result.blocks, 100, 200, preserve_order=True)
    assert [b["text"] for b in ordered] == ["Vùng", "nguyên liệu", "được cấp"]


def test_loaded_easyocr_model_changes_with_checkpoint_bytes(tmp_path, monkeypatch):
    from ai_core.processing.ocop import easy_viet_ocr as adapter

    model = tmp_path / "model" / "craft_mlt_25k.pth"
    model.parent.mkdir()
    model.write_bytes(b"first detector")

    def reader(*args, **kwargs):
        return SimpleNamespace(loaded=model.read_bytes())

    monkeypatch.setitem(sys.modules, "easyocr", SimpleNamespace(Reader=reader))
    monkeypatch.setitem(sys.modules, "easyocr.config", SimpleNamespace(MODULE_PATH=str(tmp_path)))
    first = adapter._reader(True)
    model.write_bytes(b"second detector")
    second = adapter._reader(True)
    assert first.loaded == b"first detector"
    assert second.loaded == b"second detector"


def test_loaded_vietocr_model_changes_with_checkpoint_bytes(tmp_path, monkeypatch):
    from ai_core.processing.ocop import easy_viet_ocr as adapter

    checkpoint = tmp_path / "weights.pth"
    checkpoint.write_bytes(b"first recognizer")
    monkeypatch.setenv("OCOP_VIETOCR_WEIGHTS", str(checkpoint))
    monkeypatch.setattr(adapter, "_config", lambda: {"weights": str(checkpoint)})

    def predictor(config):
        return SimpleNamespace(loaded=checkpoint.read_bytes())

    monkeypatch.setitem(sys.modules, "vietocr.tool.predictor", SimpleNamespace(Predictor=predictor))
    first = adapter._predictor()
    checkpoint.write_bytes(b"second recognizer")
    second = adapter._predictor()
    assert first.loaded == b"first recognizer"
    assert second.loaded == b"second recognizer"


def test_explicit_vietocr_architecture_changes_config(monkeypatch, tmp_path):
    from ai_core.processing.ocop.easy_viet_ocr import _config

    checkpoint = tmp_path / "checkpoint.pth"
    checkpoint.write_bytes(b"model")
    monkeypatch.setenv("OCOP_VIETOCR_WEIGHTS", str(checkpoint))
    monkeypatch.setenv("OCOP_VIETOCR_MODEL", "vgg_seq2seq")
    first = _config()
    monkeypatch.setenv("OCOP_VIETOCR_MODEL", "vgg_transformer")
    second = _config()
    assert first["seq_modeling"] == "seq2seq"
    assert second["seq_modeling"] == "transformer"
    assert first["vocab"] == second["vocab"]
    monkeypatch.setenv("OCOP_VIETOCR_MODEL", "unknown")
    with pytest.raises(ValueError, match="unsupported_vietocr_model"):
        _config()


def test_long_line_windows_preserve_all_pixels_and_source_coordinates():
    import numpy as np
    from ai_core.processing.ocop.easy_viet_ocr import _split_line_windows

    crop = np.full((32, 1100), 255, dtype=np.uint8)
    # Distinct source words with visible whitespace. No recognition pixels erased.
    for x in range(10, 1080, 50):
        crop[8:25, x : x + 28] = 0
    regions = _split_line_windows([([[100, 200], [1199, 200], [1199, 231], [100, 231]], crop)])
    assert len(regions) >= 3
    assert np.array_equal(np.concatenate([region for polygon, region in regions], axis=1), crop)
    assert all(region.shape[1] / region.shape[0] <= 16 for polygon, region in regions)
    assert regions[0][0][0] == [100.0, 200.0]
    assert regions[-1][0][1] == [1199.0, 200.0]


def test_long_unbroken_region_fails_instead_of_silently_losing_characters():
    import numpy as np
    from ai_core.processing.ocop.easy_viet_ocr import _split_line_windows

    with pytest.raises(RuntimeError, match="without_safe_word_gap"):
        _split_line_windows(
            [([[0, 0], [1000, 0], [1000, 32], [0, 32]], np.zeros((32, 1000), dtype=np.uint8))]
        )


def test_horizontal_fragments_merge_but_table_columns_remain_separate(monkeypatch):
    import numpy as np
    from ai_core.processing.ocop import table_parser
    from ai_core.processing.ocop.easy_viet_ocr import _merge_line_regions

    monkeypatch.setattr(
        table_parser,
        "raster_tables",
        lambda *args: [
            {
                "cells": [
                    {"col": 0, "bbox": [0, 0, 50, 50]},
                    {"col": 1, "bbox": [50, 0, 100, 50]},
                ]
            }
        ],
    )
    regions = [
        ([[x, 20], [X, 20], [X, 40], [x, 40]], np.zeros((20, X - x), dtype=np.uint8))
        for x, X in [(20, 60), (62, 95), (102, 120)]
    ]
    result = _merge_line_regions(regions, Image.new("RGB", (200, 400)), page())
    assert len(result) == 2
    assert result[0][0] == [[20, 20], [95, 20], [95, 40], [20, 40]]
    assert result[1][0] == regions[2][0]
