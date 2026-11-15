"""Real raster/affine regressions: deskew cannot detach OCR from its source."""

import numpy as np
import pytest
from PIL import Image, ImageDraw

from ocop_ocr.raster_preprocess import prepare_raster, PreparedRaster, restore_geometry


def test_blank_raster_is_unchanged():
    image = Image.new("RGB", (600, 800), "white")
    result = prepare_raster(image)
    assert result.angle_degrees == 0
    assert np.array_equal(np.asarray(image), np.asarray(result.image))


@pytest.mark.parametrize("angle", [-2.0, 1.5])
def test_deskew_preserves_corners_and_inverse_coordinates(angle):
    image = Image.new("RGB", (900, 1200), "white")
    draw = ImageDraw.Draw(image)
    for y in range(200, 1000, 60):
        draw.line((100, y, 800, y), fill="black", width=3)
    image = image.rotate(angle, fillcolor="white")
    result = prepare_raster(image)
    assert result.angle_degrees == pytest.approx(-angle, abs=0.15)
    corners = np.array([[0, 0, 1], [900, 0, 1], [900, 1200, 1], [0, 1200, 1]])
    mapped = (corners @ result.transform.T)[:, :2]
    assert (mapped >= 0).all()
    assert (mapped <= np.array(result.image.size)).all()
    source_points = result.source_points(mapped / 1.5, 600, 800)
    assert np.allclose(source_points, corners[:, :2] / 1.5, atol=1e-6)


def test_shared_word_and_block_are_not_transformed_twice():
    matrix = np.array([[1, 0, 30], [0, 1, 20], [0, 0, 1]])
    prepared = PreparedRaster(Image.new("RGB", (230, 420)), (200, 400), matrix, 0, 3)
    block = {"bbox": [25, 30, 45, 40]}
    cell = {"bbox": [25, 30, 45, 40], "score_ocr_candidates": [{"bbox": [25, 30, 45, 40]}]}
    table = {"bbox": [15, 10, 100, 150], "cells": [cell]}
    restore_geometry(prepared, [block, block], [table], 100, 200)
    assert block["bbox"] == [10, 20, 30, 30]
    assert cell["bbox"] == cell["score_ocr_candidates"][0]["bbox"]


def test_nonfinite_geometry_is_rejected():
    prepared = PreparedRaster(Image.new("RGB", (200, 400)), (200, 400), np.eye(3), 0, 0)
    with pytest.raises(ValueError, match="invalid_preprocessed_polygon"):
        prepared.source_points([[float("nan"), 0]], 100, 200)
