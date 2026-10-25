"""Single local scan OCR path: EasyOCR CRAFT detection + VietOCR recognition."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import math
import os
import re
from .inference_guard import inference_slot
from pathlib import Path

import numpy as np
from PIL import Image

from ocop_ocr.layout_regions import assign_regions, detect_regions, layout_signature
from ocop_ocr.ocr_types import OCRResult
from ocop_contracts.registry import sha256_file

ENGINE = "easyocr_vietocr"
DETECTOR_FILE = "craft_mlt_25k.pth"
VIETOCR_MODEL = "vgg_transformer"
VIETOCR_CONFIG_FILE = "vietocr_vgg_transformer.json"
TABLE_ROW_SPLIT_EDGE_FRACTION = 0.1


def _model_dir() -> Path:
    configured = os.getenv("OCOP_EASYOCR_MODEL_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".EasyOCR" / "model"


def _vietocr_weights() -> Path:
    configured = os.getenv("OCOP_VIETOCR_WEIGHTS")
    path = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".cache" / "ocop" / "vietocr" / "vgg_transformer.pth"
    )
    if not path.is_file():
        raise RuntimeError(
            "vietocr_weights_missing:set_OCOP_VIETOCR_WEIGHTS_to_local_vgg_transformer_checkpoint"
        )
    return path.resolve()


def _detector_path() -> Path:
    path = _model_dir().resolve() / DETECTOR_FILE
    if not path.is_file():
        raise RuntimeError(f"easyocr_detector_missing:provision_{DETECTOR_FILE}_in_{path.parent}")
    return path


@lru_cache(maxsize=2)
def _load_detector(directory: str, digest: str):
    import torch

    torch.set_num_threads(2)
    import easyocr

    return easyocr.Reader(
        ["vi", "en"],
        gpu=False,
        detector=True,
        recognizer=False,
        model_storage_directory=directory,
        download_enabled=False,
        verbose=False,
        detect_network="craft",
    )


def _detector():
    path = _detector_path()
    return _load_detector(str(path.parent), sha256_file(path))


def _vietocr_config() -> dict:
    config_path = Path(__file__).with_name(VIETOCR_CONFIG_FILE)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["weights"] = str(_vietocr_weights())
    config["device"] = "cpu"
    config["cnn"]["pretrained"] = False
    config["predictor"]["beamsearch"] = False
    return config


@lru_cache(maxsize=2)
def _load_predictor(config_json: str, weights_digest: str):
    import torch

    torch.set_num_threads(2)
    from vietocr.tool.predictor import Predictor

    config = json.loads(config_json)
    predictor = Predictor(config)
    predictor.model.eval()
    return predictor


def _predictor():
    weights = _vietocr_weights()
    config = _vietocr_config()
    return _load_predictor(
        json.dumps(config, sort_keys=True),
        sha256_file(weights),
    )


def asset_signature() -> dict:
    """Fingerprint local OCR assets without loading the models into memory."""
    detector_path = _detector_path()
    weights_path = _vietocr_weights()
    from importlib.metadata import version

    config = _vietocr_config()
    return {
        "engine": ENGINE,
        "detector": "easyocr_craft",
        "recognizer": f"vietocr_{VIETOCR_MODEL}",
        "easyocr": version("easyocr"),
        "vietocr": version("vietocr"),
        "torch": version("torch"),
        "opencv": version("opencv-python-headless"),
        "adapter_sha256": sha256_file(Path(__file__)),
        "detector_sha256": sha256_file(detector_path),
        "weights_sha256": sha256_file(weights_path),
        "config_sha256": sha256_file(Path(__file__).with_name(VIETOCR_CONFIG_FILE)),
        "layout": layout_signature(),
        "config": {
            "device": config["device"],
            "model": VIETOCR_MODEL,
            "image_height": config["dataset"]["image_height"],
            "image_max_width": config["dataset"]["image_max_width"],
            "detector_canvas_size": 3000,
            "detector_mag_ratio": 1.25,
            "free_region_crop": "perspective_rectified",
            "sparse_cell_retry": "2x_last_column_direct_and_craft_candidate",
            "image_marker_candidate": "opencv_repeated_suffix_shape_iou_0.65",
            "noise_candidate_filter": "confidence_lt_0.35_or_height_lt_0.65_median_ascii_fragment",
            "table_vertical_rule_filter": "minimum_contiguous_run_8pct",
            "table_row_split_edge_fraction": TABLE_ROW_SPLIT_EDGE_FRACTION,
            "min_region_size": 12,
            "text_threshold": 0.60,
            "low_text": 0.35,
            "link_threshold": 0.35,
        },
    }


def runtime_signature() -> dict:
    """Load both local models once before processing pages, then return their fingerprint."""
    signature = asset_signature()
    _detector()
    _predictor()
    return signature


def _pixel_bbox(polygon, width: int, height: int) -> list[float]:
    points = np.asarray(polygon, dtype=float)
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError("invalid_easyocr_polygon")
    x0, y0 = points.min(axis=0)
    x1, y1 = points.max(axis=0)
    if x0 >= x1 or y0 >= y1 or x1 <= 0 or y1 <= 0 or x0 >= width or y0 >= height:
        raise ValueError("invalid_easyocr_region")
    x0, y0 = max(0.0, x0), max(0.0, y0)
    x1, y1 = min(float(width), x1), min(float(height), y1)
    return [x0, y0, x1, y1]


def _pdf_bbox(bbox, *, width_px: int, height_px: int, page) -> list[float]:
    values = np.asarray(bbox, dtype=float)
    if values.shape != (4,) or not np.isfinite(values).all():
        raise ValueError("invalid_easyocr_bbox")
    x0, y0, x1, y1 = values
    if x0 >= x1 or y0 >= y1:
        raise ValueError("invalid_easyocr_bbox")
    x0, x1 = max(0.0, x0), min(float(width_px), x1)
    y0, y1 = max(0.0, y0), min(float(height_px), y1)
    if x0 >= x1 or y0 >= y1:
        raise ValueError("invalid_easyocr_bbox")
    return [
        round(x0 / width_px * page.rect.width, 2),
        round(y0 / height_px * page.rect.height, 2),
        round(x1 / width_px * page.rect.width, 2),
        round(y1 / height_px * page.rect.height, 2),
    ]


def _detect_regions(reader, rgb: np.ndarray, *, diagnostics: dict | None = None) -> list[dict]:
    with inference_slot():
        horizontal, free = reader.detect(
            rgb,
            min_size=12,
            text_threshold=0.60,
            low_text=0.35,
            link_threshold=0.35,
            canvas_size=3000,
            mag_ratio=1.25,
            slope_ths=0.12,
            ycenter_ths=0.5,
            height_ths=0.5,
            width_ths=0.5,
            add_margin=0.12,
        )
    if len(horizontal) != 1 or len(free) != 1:
        raise RuntimeError("easyocr_detection_batch_mismatch")
    if diagnostics is not None:
        diagnostics["raw_horizontal_boxes"] = np.asarray(horizontal[0]).tolist()
        diagnostics["raw_free_polygons"] = np.asarray(free[0]).tolist()
    height, width = rgb.shape[:2]
    regions = []
    for left, right, top, bottom in horizontal[0]:
        polygon = [[left, top], [right, top], [right, bottom], [left, bottom]]
        try:
            bbox = _pixel_bbox(polygon, width, height)
        except ValueError:
            continue
        regions.append({"polygon": polygon, "bbox_px": bbox})
    for polygon in free[0]:
        try:
            bbox = _pixel_bbox(polygon, width, height)
        except ValueError:
            continue
        regions.append({"polygon": polygon, "bbox_px": bbox})
    return sorted(
        regions, key=lambda region: ((region["bbox_px"][1] + region["bbox_px"][3]) / 2, region["bbox_px"][0])
    )


def _page_box(region: dict, image: Image.Image, page) -> list[float]:
    x0, y0, x1, y1 = region["bbox_px"]
    return _pdf_bbox([x0, y0, x1, y1], width_px=image.width, height_px=image.height, page=page)


def _table_owner(box: list[float], tables: list[dict]) -> tuple | None:
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    for table_index, table in enumerate(tables):
        bbox = table.get("bbox")
        if not bbox or not (bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]):
            continue
        owners = [
            cell
            for cell in table.get("cells", [])
            if cell["bbox"][0] <= cx <= cell["bbox"][2] and cell["bbox"][1] <= cy <= cell["bbox"][3]
        ]
        if len(owners) == 1:
            cell = owners[0]
            return table_index, cell.get("row"), cell.get("col")
        # Do not merge text across a table when its columns or cells are uncertain.
        return ("unresolved_table_region", table_index)
    return None


def _split_at_table_rows(regions: list[dict], image: Image.Image, page, tables: list[dict]) -> list[dict]:
    result = []
    for region in regions:
        x0, y0, x1, y1 = region["bbox_px"]
        page_box = _page_box(region, image, page)
        height_pt = page_box[3] - page_box[1]
        if height_pt <= 0:
            continue
        cuts = set()
        for table in tables:
            for cell in table.get("cells", []):
                left, top, right, bottom = cell["bbox"]
                if (
                    left <= page_box[0] + 1
                    and right >= page_box[2] - 1
                    and page_box[1] + height_pt * TABLE_ROW_SPLIT_EDGE_FRACTION
                    < bottom
                    < page_box[3] - height_pt * TABLE_ROW_SPLIT_EDGE_FRACTION
                ):
                    cuts.add(int(round(bottom / page.rect.height * image.height)))
        cuts = sorted(
            y
            for y in cuts
            if y0 + (y1 - y0) * TABLE_ROW_SPLIT_EDGE_FRACTION
            < y
            < y1 - (y1 - y0) * TABLE_ROW_SPLIT_EDGE_FRACTION
        )
        if not cuts or (x1 - x0) > 1.8 * (y1 - y0):
            result.append(region)
            continue
        boundaries = [int(math.floor(y0)), *cuts, int(math.ceil(y1))]
        for top, bottom in zip(boundaries, boundaries[1:]):
            if bottom - top >= 0.35 * (y1 - y0) / (len(boundaries) - 1):
                result.append(
                    {
                        "bbox_px": [x0, top, x1, bottom],
                        "polygon": [[x0, top], [x1, top], [x1, bottom], [x0, bottom]],
                    }
                )
    return result


def _line_groups(regions: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for region in sorted(
        regions, key=lambda item: ((item["bbox_px"][1] + item["bbox_px"][3]) / 2, item["bbox_px"][0])
    ):
        _, top, _, bottom = region["bbox_px"]
        center, height = (top + bottom) / 2, bottom - top
        matches = []
        for line in lines:
            centers = [(item["bbox_px"][1] + item["bbox_px"][3]) / 2 for item in line]
            heights = [item["bbox_px"][3] - item["bbox_px"][1] for item in line]
            if abs(float(np.median(centers)) - center) <= 0.48 * min(height, float(np.median(heights))):
                matches.append(line)
        if matches:
            matches[-1].append(region)
        else:
            lines.append([region])
    return [sorted(line, key=lambda item: item["bbox_px"][0]) for line in lines]


def _merge_line_fragments(regions: list[dict], image: Image.Image, page, tables: list[dict]) -> list[dict]:
    output = []
    for line in _line_groups(regions):
        clusters: list[list[dict]] = []
        for region in line:
            box = region["bbox_px"]
            owner = _table_owner(_page_box(region, image, page), tables)
            if clusters:
                previous = clusters[-1][-1]
                prev_box = previous["bbox_px"]
                prev_owner = _table_owner(_page_box(previous, image, page), tables)
                gap = box[0] - prev_box[2]
                max_gap = 0.9 * min(box[3] - box[1], prev_box[3] - prev_box[1])
                same_region = owner == prev_owner and not (
                    isinstance(owner, tuple) and owner and owner[0] == "unresolved_table_region"
                )
                if same_region and isinstance(owner, tuple) and len(owner) == 3:
                    # Cell ownership makes a wider gap safe: CRAFT often omits a short word
                    # between two fragments while both detections remain inside one known cell.
                    max_gap = 1.8 * min(box[3] - box[1], prev_box[3] - prev_box[1])
                if same_region and gap <= max_gap:
                    clusters[-1].append(region)
                    continue
            clusters.append([region])
        for cluster in clusters:
            boxes = [item["bbox_px"] for item in cluster]
            x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
            polygon = cluster[0]["polygon"] if len(cluster) == 1 else [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
            output.append({"bbox_px": [x0, y0, x1, y1], "polygon": polygon})
    return output


def _is_axis_aligned(region: dict) -> bool:
    points = np.asarray(region.get("polygon", []), dtype=np.float32)
    if points.shape != (4, 2):
        return False
    x0, y0, x1, y1 = region["bbox_px"]
    return bool(
        np.allclose(sorted(points[:, 0]), [x0, x0, x1, x1], atol=1.5)
        and np.allclose(sorted(points[:, 1]), [y0, y0, y1, y1], atol=1.5)
    )


def _text_ink_maps(gray: np.ndarray, line_height: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Ink with long table rules removed, the columns of long vertical rules, and the long horizontal rules."""
    import cv2

    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    rule_length = max(40, int(2 * line_height))
    horizontal = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (rule_length, 1))
    )
    vertical = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, rule_length))
    )
    text_ink = cv2.subtract(ink, cv2.dilate(cv2.bitwise_or(horizontal, vertical), np.ones((3, 3), np.uint8)))
    return text_ink, cv2.dilate(vertical, np.ones((1, 3), np.uint8)), horizontal


def _tighten_line_boxes(regions: list[dict], image: Image.Image) -> list[dict]:
    """Cut a line box down to its one dominant text line, dropping slivers of the lines above and below.

    CRAFT boxes are taller than the glyphs, and a fragment from a neighbouring row can stretch a merged
    box over several lines; VietOCR then reads pieces of the neighbours ("Công ty TNHH;" read as "2 có
    năm, Trườn,", a line above's checkbox blanking the real first word). Only slivers shorter than half a
    line are cut. A second full line is cut only when another box covers it, so no text line is dropped.
    """
    heights = [r["bbox_px"][3] - r["bbox_px"][1] for r in regions]
    if not heights:
        return regions
    median = float(np.median(heights))
    text_ink, _, rules = _text_ink_maps(np.asarray(image.convert("L")), median)
    output = []
    for index, region in enumerate(regions):
        x0, y0, x1, y1 = (int(round(v)) for v in region["bbox_px"])
        if y1 - y0 <= 0.9 * median or x1 - x0 < 8 or not _is_axis_aligned(region):
            output.append(region)
            continue
        rows = np.count_nonzero(text_ink[y0:y1, x0:x1], axis=1)
        active = np.flatnonzero(rows >= max(2, 0.03 * (x1 - x0)))
        on_rule = np.count_nonzero(rules[y0:y1, x0:x1], axis=1) >= 0.5 * (x1 - x0)
        runs: list[list[int]] = []
        for row in active:
            # a table rule between two rows of ink is a hard line break, however narrow the gap
            if runs and row - runs[-1][1] <= 3 and not on_rule[runs[-1][1] : row].any():
                runs[-1][1] = int(row)
            else:
                runs.append([int(row), int(row)])
        substantial = [run for run in runs if run[1] - run[0] + 1 >= 0.45 * median]
        if not substantial:
            output.append(region)
            continue
        keep = max(substantial, key=lambda run: int(rows[run[0] : run[1] + 1].sum()))
        covered = True
        for run in substantial:
            if run is keep:
                continue
            top, bottom = y0 + run[0], y0 + run[1] + 1
            covered &= any(
                other_index != index
                and min(other["bbox_px"][3], bottom) - max(other["bbox_px"][1], top) >= 0.6 * (bottom - top)
                and min(other["bbox_px"][2], x1) - max(other["bbox_px"][0], x0) >= 0.1 * (x1 - x0)
                for other_index, other in enumerate(regions)
            )
        if not covered:
            output.append(region)
            continue
        # The dominant run was found with a mass threshold, which skips the thin top of capitals and tone
        # marks; take back rows of ink touching it (no blank row between), never crossing a table rule.
        top, bottom = keep
        limit = int(0.35 * median)
        reach = 0
        while top > 0 and reach < limit and rows[top - 1] >= 1 and not on_rule[top - 1]:
            top, reach = top - 1, reach + 1
        reach = 0
        while bottom < len(rows) - 1 and reach < limit and rows[bottom + 1] >= 1 and not on_rule[bottom + 1]:
            bottom, reach = bottom + 1, reach + 1
        new_y0, new_y1 = max(y0, y0 + top - 2), min(y1, y0 + bottom + 3)
        if (new_y0, new_y1) == (y0, y1):
            output.append(region)
            continue
        output.append(
            {
                **region,
                "bbox_px": [x0, new_y0, x1, new_y1],
                "polygon": [[x0, new_y0], [x1, new_y0], [x1, new_y1], [x0, new_y1]],
            }
        )
    return output


def _extend_line_ends(regions: list[dict], image: Image.Image, maximum_gap_ratio: float = 0.8) -> list[dict]:
    """Grow each axis-aligned line box along contiguous ink until a blank gap, a table rule or a neighbour.

    CRAFT sometimes stops a line box short of its last word or first word, so the recognizer never sees
    it ("cấp xã" read as "cấp", a leading "Có" lost). The scan only crosses gaps shorter than a word space,
    never crosses a ruled table border, and never enters another line box on the same text line.
    """
    gray = np.asarray(image.convert("L"))
    heights = [r["bbox_px"][3] - r["bbox_px"][1] for r in regions]
    if not heights:
        return regions
    text_ink, rule_columns, _ = _text_ink_maps(gray, float(np.median(heights)))
    width = gray.shape[1]
    output = []
    for index, region in enumerate(regions):
        x0, y0, x1, y1 = (int(round(v)) for v in region["bbox_px"])
        height = y1 - y0
        if not _is_axis_aligned(region) or height < 12:
            output.append(region)
            continue
        band_top, band_bottom = y0 + int(0.3 * height), y0 + int(0.85 * height)
        if band_bottom <= band_top:
            output.append(region)
            continue
        left_limit, right_limit = 0, width - 1
        for other_index, other in enumerate(regions):
            if other_index == index:
                continue
            ox0, oy0, ox1, oy1 = other["bbox_px"]
            if min(oy1, band_bottom) - max(oy0, band_top) < 0.5 * (band_bottom - band_top):
                continue
            if ox0 >= x1 - 1:
                right_limit = min(right_limit, int(ox0) - 1)
            elif ox1 <= x0 + 1:
                left_limit = max(left_limit, int(ox1) + 1)
        text_columns = np.count_nonzero(text_ink[band_top:band_bottom], axis=0) > 0
        blocked = np.count_nonzero(rule_columns[band_top:band_bottom], axis=0) >= 0.5 * (
            band_bottom - band_top
        )
        maximum_gap = max(6, int(maximum_gap_ratio * height))

        def scan(start: int, step: int, limit: int) -> int:
            edge, blank, position = start, 0, start + step
            while (position <= limit) if step > 0 else (position >= limit):
                if blocked[position]:
                    break
                if text_columns[position]:
                    edge, blank = position, 0
                else:
                    blank += 1
                    if blank > maximum_gap:
                        break
                position += step
            return edge

        right_edge = scan(min(x1, width - 1), 1, right_limit)
        new_x1 = right_edge + 1 if right_edge > x1 else x1
        # A trailing star run is an image-marker candidate, not text: stop before it (whether CRAFT included
        # it or the scan reached it) so VietOCR never reads it as letters or digits and the marker detector
        # still finds it after the text.
        marker_crop = gray[y0:y1, x0:new_x1]
        for _, _, marker_box in _repeated_asterisk_suffixes(marker_crop):
            cut = x0 + marker_box[0] - max(2, height // 10)
            if marker_box[2] >= marker_crop.shape[1] - 0.5 * height and cut - x0 >= 0.5 * height:
                new_x1 = cut
                break
        new_x0 = min(x0, scan(max(x0, 0), -1, left_limit))
        if (new_x0, new_x1) == (x0, x1):
            output.append(region)
            continue
        output.append(
            {
                **region,
                "bbox_px": [new_x0, region["bbox_px"][1], new_x1, region["bbox_px"][3]],
                "polygon": [
                    [new_x0, region["bbox_px"][1]],
                    [new_x1, region["bbox_px"][1]],
                    [new_x1, region["bbox_px"][3]],
                    [new_x0, region["bbox_px"][3]],
                ],
            }
        )
    return output


def _without_table_rules(image: Image.Image, regions: list[dict]) -> Image.Image:
    """White out long table rules so a cell border beside or under a line is not read as a letter ('l', 'titm')."""
    import cv2

    heights = [r["bbox_px"][3] - r["bbox_px"][1] for r in regions]
    if not heights:
        return image
    gray = np.asarray(image.convert("L"))
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    length = max(40, int(2 * float(np.median(heights))))
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, length)))
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1)))
    if not vertical.any() and not horizontal.any():
        return image
    mask = (cv2.dilate(vertical, np.ones((1, 3), np.uint8)) > 0) | (
        cv2.dilate(horizontal, np.ones((3, 1), np.uint8)) > 0
    )
    cleaned = np.asarray(image.convert("RGB")).copy()
    cleaned[mask] = 255
    return Image.fromarray(cleaned)


def _split_long_regions(regions: list[dict], image: Image.Image, maximum_ratio: float = 12.0) -> list[dict]:
    import cv2

    source = np.asarray(image.convert("L"))
    output = []
    for region in regions:
        x0, y0, x1, y1 = [int(round(x)) for x in region["bbox_px"]]
        width, height = x1 - x0, y1 - y0
        max_width = max(32, int(height * maximum_ratio))
        if width <= max_width:
            output.append(region)
            continue
        crop = source[y0:y1, x0:x1]
        _, ink = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        # Table rules and underlines crossing the line crop leave no blank column between words, forcing
        # a cut through a glyph; no letter stroke is this long, so remove such strokes before projecting.
        rules = cv2.morphologyEx(
            ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(1.5 * height)), 1))
        )
        ink = cv2.subtract(ink, rules)
        margin = max(1, height // 10)
        projection = np.count_nonzero(ink[margin : max(margin + 1, height - margin)], axis=0)
        blank = projection == 0
        cuts = []
        start = 0
        while width - start > max_width:
            lower = start + int(max_width * 0.55)
            upper = min(width - 1, start + max_width)
            candidates = np.flatnonzero(blank[lower : upper + 1]) + lower
            if len(candidates):
                runs = np.split(candidates, np.where(np.diff(candidates) > 1)[0] + 1)
                safe = [run for run in runs if len(run) >= max(2, height // 14)]
            else:
                safe = []
            if safe:
                # Cut mid-gap: at the gap's edge the crop padding reaches the next word's first glyph.
                widest = max(safe, key=lambda run: (len(run), int(run[-1])))
                cut = int(widest[len(widest) // 2])
            else:
                cut = int(np.argmin(projection[lower : upper + 1]) + lower)
            if cut <= start:
                break
            cuts.append((cut, bool(safe)))
            start = cut
        bounds = [(0, False), *cuts, (width, False)]
        for (left, left_gap), (right, right_gap) in zip(bounds, bounds[1:]):
            if right > left:
                box = [x0 + left, y0, x0 + right, y1]
                # Only a cut in a blank gap gets blank padding; a cut through a glyph keeps the overlap,
                # which lets both pieces still see the split letter.
                output.append(
                    {
                        "bbox_px": box,
                        "polygon": [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]],
                        "cut_edges": [
                            side for side, gap in (("left", left_gap), ("right", right_gap)) if gap
                        ],
                    }
                )
    return output


def _mask_iou(left: np.ndarray, right: np.ndarray) -> float:
    import cv2

    left = cv2.resize(left, (32, 32), interpolation=cv2.INTER_NEAREST) > 0
    right = cv2.resize(right, (32, 32), interpolation=cv2.INTER_NEAREST) > 0
    union = np.count_nonzero(left | right)
    return float(np.count_nonzero(left & right) / union) if union else 0.0


def _looks_like_asterisk(mask: np.ndarray) -> bool:
    """A marker glyph has diagonal ink in all quadrants and a crossed center."""
    import cv2

    if mask.ndim != 2 or min(mask.shape) < 4:
        return False
    normalized = cv2.resize((mask > 0).astype(np.uint8), (9, 9), interpolation=cv2.INTER_NEAREST) > 0
    quadrants = (normalized[:4, :4], normalized[:4, 5:], normalized[5:, :4], normalized[5:, 5:])
    return (
        all(np.count_nonzero(quadrant) for quadrant in quadrants)
        and np.count_nonzero(normalized[3:6, 3:6]) >= 2
        and np.count_nonzero(np.diag(normalized)) >= 3
        and np.count_nonzero(np.diag(np.fliplr(normalized))) >= 3
        and np.count_nonzero(normalized[4, :]) >= 3
        and np.count_nonzero(normalized[4, :3]) > 0
        and np.count_nonzero(normalized[4, 6:]) > 0
    )


def _repeated_asterisk_suffixes(gray_crop: np.ndarray) -> list[tuple[str, float, list[int]]]:
    """Return only repeated, matching glyphs at a text line's right edge.

    This is a review candidate detector, not a recognizer. A suffix must have
    at least three connected glyphs with matching dimensions, spacing, and
    normalized shape; single or double asterisks are intentionally not guessed.
    """
    import cv2

    if gray_crop.ndim != 2 or min(gray_crop.shape) < 8:
        return []
    _, ink = cv2.threshold(gray_crop, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    count, _, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    components = []
    for x, y, width, height, area in stats[1:count]:
        if height < 4 or width < 3 or area < 7 or not 0.35 <= width / height <= 2.0:
            continue
        mask = ink[y : y + height, x : x + width]
        if _looks_like_asterisk(mask):
            components.append((int(x), int(y), int(width), int(height), mask))
    if len(components) < 3:
        return []

    # Group by vertical overlap first and size glyphs per line: specks from the line above (a few pixels
    # tall at 300 DPI) must not set the expected star height of the line that carries the stars.
    lines: list[list[tuple]] = []
    for component in sorted(components, key=lambda item: item[1] + item[3] / 2):
        owner = next(
            (
                line
                for line in lines
                if min(max(item[1] + item[3] for item in line), component[1] + component[3])
                - max(min(item[1] for item in line), component[1])
                >= 0.5 * component[3]
            ),
            None,
        )
        if owner is None:
            lines.append([component])
        else:
            owner.append(component)

    suffixes = []
    for line in lines:
        median_height = float(np.median([component[3] for component in line]))
        line = sorted(
            (
                component
                for component in line
                if 0.42 * median_height <= component[3] <= 1.40 * median_height
                and component[2] >= 0.30 * median_height
            ),
            key=lambda item: item[0],
        )
        suffix = []
        for component in reversed(line):
            if suffix:
                previous = suffix[-1]
                gap = previous[0] - (component[0] + component[2])
                dimensions_match = (
                    abs(component[2] - previous[2]) <= 0.32 * median_height
                    and abs(component[3] - previous[3]) <= 0.32 * median_height
                )
                if (
                    gap > 0.75 * median_height
                    or not dimensions_match
                    or _mask_iou(component[4], previous[4]) < 0.45
                ):
                    break
            suffix.append(component)
        if len(suffix) >= 3:
            center_y = float(np.median([item[1] + item[3] / 2 for item in suffix]))
            bbox = [
                min(item[0] for item in suffix),
                min(item[1] for item in suffix),
                max(item[0] + item[2] for item in suffix),
                max(item[1] + item[3] for item in suffix),
            ]
            suffixes.append(("*" * len(suffix), center_y, bbox))
    return sorted(suffixes, key=lambda item: item[1])


def _marker_follows_ocr_text(marker_bbox: list[float], cell_bbox: list[float], blocks: list[dict]) -> bool:
    """Reject asterisk-like connected components that overlap ordinary OCR text."""
    marker_x0, marker_y0, _, marker_y1 = marker_bbox
    cell_x0, cell_y0, cell_x1, cell_y1 = cell_bbox
    marker_center_y = (marker_y0 + marker_y1) / 2
    marker_height = marker_y1 - marker_y0
    line_blocks = []
    for block in blocks:
        box = block.get("bbox")
        if not isinstance(box, list) or len(box) != 4 or not block.get("text"):
            continue
        x0, y0, x1, y1 = [float(value) for value in box]
        center_y = (y0 + y1) / 2
        if (
            x1 <= cell_x0
            or x0 >= cell_x1
            or center_y < cell_y0
            or center_y > cell_y1
            or abs(center_y - marker_center_y) > max(4.0, (y1 - y0) * 0.5)
        ):
            continue
        line_blocks.append(box)
    if not line_blocks:
        return False
    # Stars sit high on their line, so a wrapped cell's previous line also passes the centre test; only
    # the block(s) overlapping the marker most are its own line.
    overlaps = [min(float(box[3]), marker_y1) - max(float(box[1]), marker_y0) for box in line_blocks]
    if max(overlaps) > 0:
        line_blocks = [box for box, overlap in zip(line_blocks, overlaps) if overlap >= 0.8 * max(overlaps)]
    last_text_x = max(float(box[2]) for box in line_blocks)
    return marker_x0 >= last_text_x - max(3.5, marker_height * 0.65)


def _recover_image_marker_candidates(image: Image.Image, page, tables: list[dict], blocks: list[dict]) -> int:
    """Attach repeated-star image candidates to source table cells without editing OCR text."""
    gray = np.asarray(image.convert("L"))
    scale_x, scale_y = image.width / page.rect.width, image.height / page.rect.height
    inset_x, inset_y = max(2, round(scale_x * 0.8)), max(2, round(scale_y * 0.8))
    added = 0
    for table in tables:
        columns = table.get("col_count")
        if not isinstance(columns, int) or columns < 2:
            continue
        for cell in table.get("cells", []):
            if not isinstance(cell.get("col"), int) or cell["col"] >= columns - 1:
                continue
            box = cell.get("bbox")
            if not isinstance(box, list) or len(box) != 4:
                continue
            x0, y0, x1, y1 = [float(value) for value in box]
            px0 = max(0, round(x0 * scale_x) + inset_x)
            py0 = max(0, round(y0 * scale_y) + inset_y)
            px1 = min(image.width, round(x1 * scale_x) - inset_x)
            py1 = min(image.height, round(y1 * scale_y) - inset_y)
            if px1 - px0 < 8 or py1 - py0 < 8:
                continue
            for text, _, marker_box in _repeated_asterisk_suffixes(gray[py0:py1, px0:px1]):
                marker_bbox = [
                    round((px0 + marker_box[0]) / scale_x, 2),
                    round((py0 + marker_box[1]) / scale_y, 2),
                    round((px0 + marker_box[2]) / scale_x, 2),
                    round((py0 + marker_box[3]) / scale_y, 2),
                ]
                if not _marker_follows_ocr_text(marker_bbox, box, blocks):
                    continue
                candidates = cell.setdefault("image_marker_candidates", [])
                candidates.append(
                    {
                        "text": text,
                        "bbox": list(box),
                        "marker_bbox": marker_bbox,
                        "table_id": table.get("table_id"),
                        "cell_id": f"{table.get('table_id')}:{cell.get('row')}:{cell.get('col')}",
                        "method": "opencv_repeated_asterisk_suffix",
                        "candidate_only": True,
                        "review_status": "needs_review",
                    }
                )
                added += 1
    return added


def _is_hollow_square(component: np.ndarray) -> bool:
    """A printed checkbox: ink along most of all four straight sides and an empty middle.

    Side coverage, not corner pixels, separates it from a round 'O' or '0' (whose curves leave the ends of
    each side bare) and still accepts a scanned box with a nicked corner.
    """
    box_h, box_w = component.shape
    if box_h < 6 or box_w < 6 or not 0.75 <= box_w / box_h <= 1.35:
        return False
    band = max(2, min(box_h, box_w) // 6)
    sides = (
        component[:band].any(axis=0),
        component[-band:].any(axis=0),
        component[:, :band].any(axis=1),
        component[:, -band:].any(axis=1),
    )
    interior = component[box_h // 4 : box_h - box_h // 4, box_w // 4 : box_w - box_w // 4]
    return bool(all(side.mean() >= 0.8 for side in sides) and interior.size and interior.mean() <= 0.05)


def _blank_leading_checkbox(crop: Image.Image) -> Image.Image:
    """White out a printed checkbox that starts a line; VietOCR otherwise reads it as 'O', '0', 'a,' or noise.

    Only a hollow, roughly square outline with ink in all four corners at the left edge qualifies,
    so a leading letter O or digit 0 (rounded, empty corners) is kept.
    """
    import cv2

    gray = np.asarray(crop.convert("L"))
    height, width = gray.shape
    if height < 12 or width < 40:
        return crop
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    # Skip table rules and slivers of neighbouring rows: they are long or touch the crop's top/bottom edge.
    candidates = [
        i
        for i in range(1, count)
        if stats[i, cv2.CC_STAT_AREA] >= 6
        and 8 <= stats[i, cv2.CC_STAT_WIDTH] < 0.15 * width
        and stats[i, cv2.CC_STAT_HEIGHT] >= 8
        and stats[i, cv2.CC_STAT_TOP] > 0
        and stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] < height
    ]
    if not candidates:
        return crop
    first = min(candidates, key=lambda i: stats[i, cv2.CC_STAT_LEFT])
    left, top, box_w, box_h, area = (int(v) for v in stats[first])
    if left > 0.2 * width or not (0.18 * height <= box_h <= 0.95 * height):
        return crop
    if not _is_hollow_square(labels[top : top + box_h, left : left + box_w] == first):
        return crop
    cleared = np.asarray(crop.convert("RGB")).copy()
    cleared[:, : left + box_w + 2] = 255
    return Image.fromarray(cleared)


def _is_checkbox_glyph(crop: Image.Image) -> bool:
    """True for a crop holding only a hollow, roughly square checkbox outline (never read as '0' or 'O')."""
    import cv2

    gray = np.asarray(crop.convert("L"))
    height, width = gray.shape
    if height < 8 or width < 8 or width > 2 * height:
        return False
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    rows, columns = np.nonzero(ink)
    if not len(rows):
        return False
    return _is_hollow_square(ink[rows.min() : rows.max() + 1, columns.min() : columns.max() + 1] > 0)


def _recognition_crop(image: Image.Image, region: dict, rgb: np.ndarray | None = None) -> Image.Image:
    """Rectify CRAFT's free-form quadrilateral before VietOCR sees its line crop."""
    x0, y0, x1, y1 = [int(round(value)) for value in region["bbox_px"]]
    points = np.asarray(region.get("polygon", []), dtype=np.float32)
    if points.shape != (4, 2) or not np.isfinite(points).all():
        points = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)

    center = points.mean(axis=0)
    order = np.argsort(np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0]))
    ordered = points[order]
    start = int(np.argmin(ordered.sum(axis=1)))
    ordered = np.roll(ordered, -start, axis=0)

    bounds = [points[:, 0].min(), points[:, 1].min(), points[:, 0].max(), points[:, 1].max()]
    axis_aligned = np.array(
        [[bounds[0], bounds[1]], [bounds[2], bounds[1]], [bounds[2], bounds[3]], [bounds[0], bounds[3]]],
        dtype=np.float32,
    )
    if np.allclose(ordered, axis_aligned, atol=0.01):
        pad = max(1, int((y1 - y0) * 0.06))
        left, right = max(0, x0 - pad), min(image.width, x1 + pad)
        crop = image.convert("RGB").crop((left, max(0, y0 - pad), right, min(image.height, y1 + pad)))
        edges = region.get("cut_edges") or ()
        if edges:
            # Padding beyond an artificial cut would show the neighbouring piece's glyphs.
            pixels = np.asarray(crop).copy()
            if "left" in edges:
                pixels[:, : x0 - left] = 255
            if "right" in edges:
                pixels[:, pixels.shape[1] - (right - x1) :] = 255
            crop = Image.fromarray(pixels)
        return crop

    top_width = float(np.linalg.norm(ordered[1] - ordered[0]))
    bottom_width = float(np.linalg.norm(ordered[2] - ordered[3]))
    left_height = float(np.linalg.norm(ordered[3] - ordered[0]))
    right_height = float(np.linalg.norm(ordered[2] - ordered[1]))
    width, height = int(round(max(top_width, bottom_width))), int(round(max(left_height, right_height)))
    if width < 2 or height < 2:
        return image.convert("RGB").crop(
            (max(0, x0), max(0, y0), min(image.width, x1), min(image.height, y1))
        )

    import cv2

    destination = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32
    )
    transform = cv2.getPerspectiveTransform(ordered, destination)
    source = rgb if rgb is not None else np.asarray(image.convert("RGB"))
    rectified = cv2.warpPerspective(
        source,
        transform,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
    pad = max(2, int(height * 0.06))
    rectified = cv2.copyMakeBorder(rectified, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    return Image.fromarray(rectified)


def _tight_score_cell_crop(crop: Image.Image) -> Image.Image | None:
    """Return a padded crop around centered ink in a score cell, excluding table rules."""
    import cv2

    gray = np.asarray(crop.convert("L"))
    height, width = gray.shape
    if height < 12 or width < 8:
        return None

    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    horizontal = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, int(width * 0.35)), 1)),
    )
    vertical = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(5, int(height * 0.35)))),
    )
    ink = cv2.subtract(ink, cv2.max(horizontal, vertical))
    count, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    components = []
    minimum_area = max(4, int(height * width * 0.0005))
    for x, y, box_width, box_height, area in stats[1:count]:
        if (
            area < minimum_area
            or box_width < 2
            or box_width > 0.5 * width
            or box_height < max(5, 0.12 * height)
            or x <= 0
            or y <= 0
            or x + box_width >= width
            or y + box_height >= height
        ):
            continue
        components.append((int(x), int(y), int(box_width), int(box_height)))
    if not components:
        return None

    # Numeric cell content is usually one centered glyph or a short, horizontally grouped value.
    # Group similarly tall components so values such as "10" stay together while isolated specks drop out.
    median_height = float(np.median([component[3] for component in components]))
    components = [
        component for component in components if 0.55 * median_height <= component[3] <= 1.8 * median_height
    ]
    groups: list[list[tuple[int, int, int, int]]] = []
    for component in sorted(components, key=lambda item: item[0]):
        x, y, box_width, box_height = component
        center_y = y + box_height / 2
        group = next(
            (
                items
                for items in groups
                if abs(np.median([item[1] + item[3] / 2 for item in items]) - center_y)
                <= 0.45 * median_height
                and x - max(item[0] + item[2] for item in items) <= 0.8 * median_height
            ),
            None,
        )
        if group is None:
            groups.append([component])
        else:
            group.append(component)
    if not groups:
        return None

    center_x = width / 2
    selected = min(
        groups,
        key=lambda items: abs(
            (min(item[0] for item in items) + max(item[0] + item[2] for item in items)) / 2 - center_x
        ),
    )
    left = min(item[0] for item in selected)
    top = min(item[1] for item in selected)
    right = max(item[0] + item[2] for item in selected)
    bottom = max(item[1] + item[3] for item in selected)
    padding = max(2, round(float(np.median([item[3] for item in selected])) * 0.25))
    return crop.crop(
        (
            max(0, left - padding),
            max(0, top - padding),
            min(width, right + padding),
            min(height, bottom + padding),
        )
    )


def _recover_sparse_cell_candidates(image: Image.Image, page, tables: list[dict], detector, predictor) -> int:
    """Retry sparse cells at 2x input size and keep numeric readings as review-only candidates."""
    import re

    added = 0
    inset_x = max(1, int(round(1.2 * image.width / page.rect.width)))
    inset_y = max(1, int(round(1.2 * image.height / page.rect.height)))
    for table in tables:
        columns = table.get("col_count")
        table_box = table.get("bbox")
        if (
            not isinstance(columns, int)
            or columns < 2
            or not isinstance(table_box, list)
            or len(table_box) != 4
            or table_box[2] <= table_box[0]
        ):
            continue
        score_cell_heights = []
        for candidate_cell in table.get("cells", []):
            candidate_box = candidate_cell.get("bbox")
            if (
                candidate_cell.get("col") == columns - 1
                and isinstance(candidate_box, list)
                and len(candidate_box) == 4
                and candidate_box[3] > candidate_box[1]
            ):
                score_cell_heights.append(float(candidate_box[3]) - float(candidate_box[1]))
        max_cell_height = (
            max(36.0, 3.0 * float(np.median(score_cell_heights))) if score_cell_heights else 36.0
        )
        for cell in table.get("cells", []):
            if cell.get("col") != columns - 1:
                continue
            primary_text = "".join(str(cell.get("text", "")).split())
            if re.fullmatch(r"\d{1,2}", primary_text):
                continue
            if primary_text and (len(primary_text) > 2 or not primary_text.isascii()):
                continue
            box = cell.get("bbox")
            if not isinstance(box, list) or len(box) != 4:
                continue
            x0, y0, x1, y1 = [float(value) for value in box]
            if (x1 - x0) > 0.35 * (table_box[2] - table_box[0]) or y1 - y0 > max_cell_height:
                continue
            px0 = max(0, int(round(x0 / page.rect.width * image.width)) + inset_x)
            py0 = max(0, int(round(y0 / page.rect.height * image.height)) + inset_y)
            px1 = min(image.width, int(round(x1 / page.rect.width * image.width)) - inset_x)
            py1 = min(image.height, int(round(y1 / page.rect.height * image.height)) - inset_y)
            if px1 - px0 < 4 or py1 - py0 < 4:
                continue
            crop = image.convert("RGB").crop((px0, py0, px1, py1))
            crop = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS)
            regions = _detect_regions(detector, np.asarray(crop))
            candidates = cell.get("score_ocr_candidates", [])
            predictions = []
            # Keep CRAFT's localized crop when it produces one unambiguous region.
            if len(regions) == 1:
                try:
                    text, confidence = predictor.predict(
                        _recognition_crop(crop, regions[0]), return_prob=True
                    )
                except Exception:
                    text, confidence = "", None
                candidate_text = "".join(text.split()) if isinstance(text, str) else ""
                candidate_confidence = _confidence(confidence)
                if (
                    re.fullmatch(r"\d{1,2}", candidate_text)
                    and candidate_confidence is not None
                    and candidate_confidence >= 0.55
                ):
                    predictions.append(
                        (
                            candidate_text,
                            candidate_confidence,
                            "easyocr_craft+vietocr_vgg_transformer_2x_cell_crop",
                        )
                    )

            # A tight score-cell crop is an independent view, including when
            # the page OCR left the cell empty. It can retain a numeral missed
            # by CRAFT; store the result only as a review candidate.
            try:
                text, confidence = predictor.predict(crop, return_prob=True)
            except Exception:
                text, confidence = "", None
            candidate_text = "".join(text.split()) if isinstance(text, str) else ""
            candidate_confidence = _confidence(confidence)
            if (
                re.fullmatch(r"\d{1,2}", candidate_text)
                and candidate_confidence is not None
                and candidate_confidence >= 0.55
            ):
                predictions.append(
                    (candidate_text, candidate_confidence, "vietocr_vgg_transformer_2x_direct_cell_crop")
                )

            # A tall row can make a centered one-digit score look like noise to the line recognizer.
            # Retry a padded ink crop, but keep the reading in candidate metadata until reviewed.
            tight_crop = _tight_score_cell_crop(crop)
            if tight_crop is not None:
                try:
                    text, confidence = predictor.predict(tight_crop, return_prob=True)
                except Exception:
                    text, confidence = "", None
                candidate_text = "".join(text.split()) if isinstance(text, str) else ""
                candidate_confidence = _confidence(confidence)
                if (
                    re.fullmatch(r"\d{1,2}", candidate_text)
                    and candidate_confidence is not None
                    and candidate_confidence >= 0.55
                ):
                    predictions.append(
                        (candidate_text, candidate_confidence, "vietocr_vgg_transformer_2x_tight_ink_crop")
                    )

            if not predictions:
                continue

            # CRAFT-localized, direct-cell, and tight-ink crops are independent views of the
            # same score. Keep one primary reading per cell, chosen by vote count then mean
            # confidence; retain every unverified crop reading as provenance on that candidate.
            readings_by_text: dict[str, list[tuple[str, float, str]]] = {}
            for candidate_text, candidate_confidence, method in predictions:
                readings_by_text.setdefault(candidate_text, []).append(
                    (candidate_text, candidate_confidence, method)
                )
            method_priority = {
                "easyocr_craft+vietocr_vgg_transformer_2x_cell_crop": 0,
                "vietocr_vgg_transformer_2x_direct_cell_crop": 1,
                "vietocr_vgg_transformer_2x_tight_ink_crop": 2,
            }
            ordered_readings = sorted(
                readings_by_text.items(),
                key=lambda item: (
                    -len(item[1]),
                    min(method_priority.get(reading[2], 99) for reading in item[1]),
                    -float(np.mean([reading[1] for reading in item[1]])),
                    -max(reading[1] for reading in item[1]),
                    item[0],
                ),
            )
            candidate_text, supporting = ordered_readings[0]
            confidence = round(float(np.mean([reading[1] for reading in supporting])), 4)
            method = supporting[0][2] if len(supporting) == 1 else "vietocr_multi_crop_consensus"
            candidate = {
                "text": candidate_text,
                "bbox": list(box),
                "method": method,
                "confidence": confidence,
                "candidate_only": True,
                "review_status": "needs_review",
                "ocr_observations": [
                    {
                        "text": reading_text,
                        "method": reading_method,
                        "confidence": reading_confidence,
                        "candidate_only": True,
                        "review_status": "needs_review",
                    }
                    for reading_text, reading_confidence, reading_method in predictions
                ],
            }

            existing = cell.setdefault("score_ocr_candidates", candidates)
            retry_methods = {
                "easyocr_craft+vietocr_vgg_transformer_2x_cell_crop",
                "vietocr_vgg_transformer_2x_direct_cell_crop",
                "vietocr_vgg_transformer_2x_tight_ink_crop",
                "vietocr_multi_crop_consensus",
            }
            if any(
                candidate.get("candidate_only") is not True
                or candidate.get("review_status") != "needs_review"
                for candidate in existing
            ):
                # Never replace a value that has already been explicitly reviewed.
                continue
            retained = [candidate for candidate in existing if candidate.get("method") not in retry_methods]
            retained.append(candidate)
            cell["score_ocr_candidates"] = retained
            added += 1
    return added


def _speckle_regions(
    readings: list[tuple[int, float | None]],
    *,
    minimum_regions: int = 8,
    height_ratio: float = 0.3,
    confidence_limit: float = 0.6,
) -> set[int]:
    """Indices of tiny, low-confidence crops: scan speckle that VietOCR reads as nonsense.

    Measured on QD148 p25 and QD26 p29 (median crop height 84 px): such crops were 12-20 px tall at
    confidence 0.24-0.57, while the shortest real reading was 40 px. Empirical thresholds, not constants.
    """
    if len(readings) < minimum_regions:
        return set()
    heights = sorted(height for height, _ in readings)
    median = heights[len(heights) // 2]
    return {
        index
        for index, (height, confidence) in enumerate(readings)
        if confidence is not None and confidence < confidence_limit and height < height_ratio * median
    }


ALTERNATIVE_PROBABILITY = 0.01
BEAM_SEARCH_BELOW = 0.7
BEAM_SIZE = 4


def _recognize(predictor, crop: Image.Image) -> tuple[str, float, list[dict]]:
    """VietOCR greedy decoding that also keeps the recognizer's own alternatives for unsure characters.

    The loop matches vietocr.tool.translate.translate, so text and confidence are unchanged; the
    top-5 posteriors it discards become `alternatives`: one entry per output character where the model
    gave a second character at least ALTERNATIVE_PROBABILITY, listing the characters it weighed there.
    """
    model, vocab, config = (
        getattr(predictor, "model", None),
        getattr(predictor, "vocab", None),
        getattr(predictor, "config", None),
    )
    if model is None or vocab is None or not isinstance(config, dict):
        text, confidence = predictor.predict(crop, return_prob=True)
        return text, confidence, []
    import torch
    from torch.nn.functional import softmax
    from vietocr.tool.translate import process_input

    dataset = config["dataset"]
    image = process_input(
        crop, dataset["image_height"], dataset["image_min_width"], dataset["image_max_width"]
    )
    image = image.to(config["device"])
    model.eval()
    ids, probabilities, alternatives = [], [], []
    with torch.no_grad():
        memory = model.transformer.forward_encoder(model.cnn(image))
        sentence = [vocab.go]
        while len(sentence) <= 129 and sentence[-1] != vocab.eos:
            output, memory = model.transformer.forward_decoder(
                torch.LongTensor([[t] for t in sentence]), memory
            )
            values, indices = torch.topk(softmax(output, dim=-1)[0, -1], 5)
            best = int(indices[0])
            sentence.append(best)
            if best > 3:
                position = len(ids)
                ids.append(best)
                probabilities.append(float(values[0]))
                considered = [
                    [vocab.i2c[int(k)], round(float(v), 4)]
                    for v, k in zip(values, indices)
                    if int(k) > 3 and float(v) >= ALTERNATIVE_PROBABILITY
                ]
                if len(considered) > 1:
                    alternatives.append({"i": position, "alts": considered})
        if BEAM_SEARCH_BELOW is not None and probabilities and min(probabilities) < BEAM_SEARCH_BELOW:
            # Greedy decoding commits to an unsure character for good; a small beam can still take a
            # better-scoring whole line. Only lines with an unsure character pay its cost.
            from vietocr.tool.translate import beamsearch

            beam = beamsearch(
                model.transformer.forward_encoder(model.cnn(image)),
                model,
                image.device,
                beam_size=BEAM_SIZE,
                sos_token=vocab.go,
                eos_token=vocab.eos,
            )
            beam_ids = [int(i) for i in beam[1:] if int(i) > 3]
            # VietOCR's beam sums log-probabilities with no length normalisation, so it favours stopping early
            # ("Công ty TNHH" for the whole line); use it only to re-read characters in place.
            if beam_ids and beam_ids != ids and abs(len(beam_ids) - len(ids)) <= 2:
                if len(beam_ids) != len(ids):
                    alternatives = []  # positions no longer line up with the greedy characters
                ids = beam_ids
    text = "".join(vocab.i2c[i] for i in ids)
    confidence = sum(probabilities) / len(probabilities) if probabilities else 0.0
    return text, confidence, alternatives


def _shift_alternatives(alternatives: list[dict], offset: int) -> list[dict]:
    return [{"i": a["i"] - offset, "alts": a["alts"]} for a in alternatives if a["i"] >= offset]


def _confidence(value) -> float | None:
    if value is None:
        return None
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    values = np.asarray(value, dtype=float)
    values = values[np.isfinite(values)]
    if not len(values):
        return None
    result = float(values.mean())
    return round(result, 4) if 0 <= result <= 1 else None


def _is_low_confidence_short_fragment(
    text: str, confidence: float | None, *, height: float, median_height: float
) -> bool:
    """Separate tiny, low-confidence ASCII speckle from page text, retaining it as a candidate."""
    if confidence is None:
        return False
    token = "".join(text.split())
    if (
        confidence < 0.8
        and median_height > 0
        and height < 0.5 * median_height
        and re.fullmatch(r"[A-Za-z0-9-]*[A-Za-z]{3,}[A-Za-z0-9-]*", token)
    ):
        return (
            True  # half-height Latin-only text in a Vietnamese page: stamp or signature residue ("SUMMERS")
        )
    if confidence >= 0.55:
        return False
    if token and median_height > 0 and height < 0.6 * median_height and confidence < 0.5:
        return True  # a sliver well under line height that the recognizer itself doubts
    if not re.fullmatch(r"[A-Za-z]{7,}|[0-9]{4,}", token):
        return False
    return confidence < 0.35 or (median_height > 0 and height < 0.65 * median_height)


def _strip_leading_checkbox_token(text: str) -> tuple[str, str | None]:
    """Remove a short lowercase OCR token emitted for a detected leading square checkbox."""
    parts = text.strip().split(maxsplit=1)
    if len(parts) == 2 and len(parts[0]) <= 2 and not parts[0][0].isupper():
        return parts[1], parts[0]
    return text, None


def run_easy_viet_ocr(
    image, page, *, detect_tables: bool = True, trace: dict | None = None
) -> tuple[OCRResult, list[dict]]:
    """Detect text with CRAFT, recognize line crops with one VietOCR model."""
    from ocop_ocr.table_parser import raster_tables

    rgb = np.asarray(image.convert("RGB"))
    craft_diagnostics = {}
    regions = _detect_regions(_detector(), rgb, diagnostics=craft_diagnostics)
    if trace is not None:
        trace["easyocr_craft"] = {
            "role": "text_region_detector_only",
            **craft_diagnostics,
            "usable_regions": deepcopy(regions),
        }
    tables_for_layout = raster_tables(image, page, []) if detect_tables else []
    if trace is not None:
        trace["table_layout_candidates"] = deepcopy(tables_for_layout)
    split_regions = _split_at_table_rows(regions, image, page, tables_for_layout)
    if trace is not None:
        trace["regions_after_table_row_split"] = deepcopy(split_regions)
    merged_regions = _merge_line_fragments(split_regions, image, page, tables_for_layout)
    if trace is not None:
        trace["regions_after_line_merge"] = deepcopy(merged_regions)
    extended_regions = _extend_line_ends(_tighten_line_boxes(merged_regions, image), image)
    if trace is not None:
        trace["regions_after_line_end_extension"] = deepcopy(extended_regions)
    # Pieces cut from a long box are re-tightened: a sliver that was a sliver of the whole line is not of its piece.
    regions = _tighten_line_boxes(_split_long_regions(extended_regions, image), image)
    if trace is not None:
        trace["recognition_regions"] = deepcopy(regions)
    predictor = _predictor()
    recognition_image = _without_table_rules(image, regions)
    recognition_rgb = np.asarray(recognition_image.convert("RGB"))
    blocks = []
    raw_recognitions = []
    recognized = []
    warnings = ["ocr_candidates_require_source_verification"]
    for region_index, region in enumerate(regions):
        crop = _recognition_crop(recognition_image, region, recognition_rgb)
        if crop.width < 2 or crop.height < 2:
            continue
        if _is_checkbox_glyph(crop):
            if trace is not None:
                raw_recognitions.append(
                    {
                        "region_index": region_index,
                        "bbox_px": list(region["bbox_px"]),
                        "raw_text": None,
                        "dropped_as": "checkbox_glyph",
                    }
                )
            continue
        raw_crop = crop
        crop = _blank_leading_checkbox(crop)
        checkbox_removed = crop is not raw_crop
        try:
            text, confidence, alternatives = _recognize(predictor, crop)
        except Exception as exc:
            warnings.append("vietocr_region_recognition_failed")
            if trace is not None:
                raw_recognitions.append(
                    {
                        "region_index": region_index,
                        "bbox_px": list(region["bbox_px"]),
                        "crop_size_px": [crop.width, crop.height],
                        "raw_text": None,
                        "confidence": None,
                        "error": f"{type(exc).__name__}:{str(exc)[:240]}",
                    }
                )
            continue
        raw_entry = {
            "region_index": region_index,
            "block_id": None,
            "bbox_px": list(region["bbox_px"]),
            "polygon": deepcopy(region["polygon"]),
            "crop_size_px": [crop.width, crop.height],
            "raw_text": text if isinstance(text, str) else repr(text),
            "confidence": _confidence(confidence),
            "confidence_is_calibrated": False,
        }
        if trace is not None:
            raw_recognitions.append(raw_entry)
        if not isinstance(text, str) or not text.strip():
            continue
        raw_text = text.strip()
        checkbox_noise = None
        if checkbox_removed:
            text, checkbox_noise = _strip_leading_checkbox_token(raw_text)
        if checkbox_noise:
            raw_entry["normalizations"] = [{"kind": "remove_leading_checkbox_token", "token": checkbox_noise}]
        recognized.append(
            (region_index, region, crop.height, text, confidence, raw_entry, alternatives, checkbox_noise)
        )
    speckle = _speckle_regions(
        [(height, _confidence(confidence)) for _, _, height, _, confidence, _, _, _ in recognized]
    )
    if speckle:
        warnings.append(f"speckle_regions_dropped:{len(speckle)}")
    median_region_height = float(np.median([item[2] for item in recognized])) if recognized else 0.0
    noise_candidates = []
    for position, (
        region_index,
        region,
        _,
        text,
        confidence,
        raw_entry,
        alternatives,
        checkbox_noise,
    ) in enumerate(recognized):
        if position in speckle:
            raw_entry["dropped_as"] = "speckle_region"
            continue
        bbox = _pdf_bbox(region["bbox_px"], width_px=image.width, height_px=image.height, page=page)
        polygon = [
            [
                round(float(x) / image.width * page.rect.width, 2),
                round(float(y) / image.height * page.rect.height, 2),
            ]
            for x, y in region["polygon"]
        ]
        if checkbox_noise:
            noise_candidates.append(
                {
                    "block_id": f"ocr:{ENGINE}:checkbox:{region_index}",
                    "text": checkbox_noise,
                    "ocr_raw_text": raw_entry["raw_text"],
                    "bbox": bbox,
                    "polygon": polygon,
                    "confidence": _confidence(confidence),
                    "confidence_is_calibrated": False,
                    "method": "easyocr_craft+vietocr_vgg_transformer",
                    "candidate_only": True,
                    "review_status": "needs_review",
                    "reason": "short_prefix_recognized_in_leading_checkbox_region",
                }
            )
        confidence_value = _confidence(confidence)
        if _is_low_confidence_short_fragment(
            text, confidence_value, height=raw_entry["crop_size_px"][1], median_height=median_region_height
        ):
            raw_entry["dropped_as"] = "low_confidence_short_fragment_candidate"
            noise_candidates.append(
                {
                    "block_id": f"ocr:{ENGINE}:noise:{region_index}",
                    "text": text.strip(),
                    "ocr_raw_text": text.strip(),
                    "bbox": bbox,
                    "polygon": polygon,
                    "confidence": confidence_value,
                    "confidence_is_calibrated": False,
                    "method": "easyocr_craft+vietocr_vgg_transformer",
                    "candidate_only": True,
                    "review_status": "needs_review",
                    "reason": "low_confidence_short_ascii_fragment",
                }
            )
            continue
        raw_entry["block_id"] = f"ocr:{ENGINE}:{len(blocks)}"
        bbox = _pdf_bbox(region["bbox_px"], width_px=image.width, height_px=image.height, page=page)
        polygon = [
            [
                round(float(x) / image.width * page.rect.width, 2),
                round(float(y) / image.height * page.rect.height, 2),
            ]
            for x, y in region["polygon"]
        ]
        block = {
            "block_id": f"ocr:{ENGINE}:{len(blocks)}",
            "text": text.strip(),
            "bbox": bbox,
            "polygon": polygon,
            "uncertain_chars": _shift_alternatives(alternatives, len(text) - len(text.lstrip())),
            "method": "easyocr_craft+vietocr_vgg_transformer",
            "confidence": _confidence(confidence),
            "review_status": "needs_review",
            "candidate_only": True,
            "order": len(blocks),
        }
        if checkbox_noise:
            block["ocr_raw_text"] = raw_entry["raw_text"]
            block["ocr_normalizations"] = [{"kind": "remove_leading_checkbox_token", "token": checkbox_noise}]
        blocks.append(block)
    layout, layout_warning = detect_regions(rgb)
    if layout_warning:
        warnings.append(layout_warning)
    page_regions = [
        {
            **region,
            "bbox": _pdf_bbox(region["bbox_px"], width_px=image.width, height_px=image.height, page=page),
        }
        for region in layout
    ]
    if trace is not None:
        trace["layout_regions"] = deepcopy(page_regions)
    assign_regions(blocks, page_regions)
    if trace is not None:
        trace["vietocr_raw_recognitions"] = raw_recognitions
        trace["ocr_blocks_before_table_parser"] = deepcopy(blocks)
    tables = raster_tables(image, page, blocks) if detect_tables else []
    if trace is not None:
        trace["tables_after_cell_assignment"] = deepcopy(tables)
    if tables:
        marker_count = _recover_image_marker_candidates(image, page, tables, blocks)
        if marker_count:
            warnings.append(f"image_marker_candidates_require_review:{marker_count}")
        candidate_count = _recover_sparse_cell_candidates(image, page, tables, _detector(), predictor)
        if candidate_count:
            warnings.append(f"sparse_cell_ocr_candidates_require_review:{candidate_count}")
    if noise_candidates:
        warnings.append(f"ocr_noise_candidates_require_review:{len(noise_candidates)}")
    if not blocks:
        warnings.append("empty_ocr_result")
    return OCRResult(blocks, ENGINE, sorted(set(warnings)), noise_candidates=noise_candidates), tables
