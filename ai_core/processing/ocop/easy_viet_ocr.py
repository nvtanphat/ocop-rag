"""Single local scan OCR path: EasyOCR CRAFT detection + VietOCR recognition."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image

from ai_core.processing.ocop.layout_regions import assign_regions, detect_regions, layout_signature
from ai_core.processing.ocop.ocr_types import OCRResult
from ai_core.processing.ocop.registry import sha256_file

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
    path = Path(configured).expanduser() if configured else Path.home() / ".cache" / "ocop" / "vietocr" / "vgg_transformer.pth"
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
            "free_region_crop": "perspective_rectified_v1",
            "sparse_cell_retry": "2x_last_column_direct_and_craft_candidate_v3",
            "image_marker_candidate": "opencv_repeated_suffix_shape_iou_0.65_v1",
            "table_vertical_rule_filter": "minimum_contiguous_run_8pct_v1",
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
    return sorted(regions, key=lambda region: ((region["bbox_px"][1] + region["bbox_px"][3]) / 2,
                                                region["bbox_px"][0]))


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
        owners = [cell for cell in table.get("cells", [])
                  if cell["bbox"][0] <= cx <= cell["bbox"][2]
                  and cell["bbox"][1] <= cy <= cell["bbox"][3]]
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
                if (left <= page_box[0] + 1 and right >= page_box[2] - 1
                        and page_box[1] + height_pt * TABLE_ROW_SPLIT_EDGE_FRACTION < bottom
                        < page_box[3] - height_pt * TABLE_ROW_SPLIT_EDGE_FRACTION):
                    cuts.add(int(round(bottom / page.rect.height * image.height)))
        cuts = sorted(y for y in cuts
                      if y0 + (y1 - y0) * TABLE_ROW_SPLIT_EDGE_FRACTION < y
                      < y1 - (y1 - y0) * TABLE_ROW_SPLIT_EDGE_FRACTION)
        if not cuts or (x1 - x0) > 1.8 * (y1 - y0):
            result.append(region)
            continue
        boundaries = [int(math.floor(y0)), *cuts, int(math.ceil(y1))]
        for top, bottom in zip(boundaries, boundaries[1:]):
            if bottom - top >= 0.35 * (y1 - y0) / (len(boundaries) - 1):
                result.append({"bbox_px": [x0, top, x1, bottom],
                               "polygon": [[x0, top], [x1, top], [x1, bottom], [x0, bottom]]})
    return result


def _line_groups(regions: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for region in sorted(regions, key=lambda item: ((item["bbox_px"][1] + item["bbox_px"][3]) / 2,
                                                     item["bbox_px"][0])):
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
                if same_region and gap <= max_gap:
                    clusters[-1].append(region)
                    continue
            clusters.append([region])
        for cluster in clusters:
            boxes = [item["bbox_px"] for item in cluster]
            x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
            polygon = cluster[0]["polygon"] if len(cluster) == 1 else [
                [x0, y0], [x1, y0], [x1, y1], [x0, y1]
            ]
            output.append({"bbox_px": [x0, y0, x1, y1],
                           "polygon": polygon})
    return output


def _split_long_regions(regions: list[dict], image: Image.Image, maximum_ratio: float = 15.5) -> list[dict]:
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
        margin = max(1, height // 10)
        projection = np.count_nonzero(ink[margin:max(margin + 1, height - margin)], axis=0)
        blank = projection == 0
        cuts = []
        start = 0
        while width - start > max_width:
            lower = start + int(max_width * 0.55)
            upper = min(width - 1, start + max_width)
            candidates = np.flatnonzero(blank[lower:upper + 1]) + lower
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
                cut = int(np.argmin(projection[lower:upper + 1]) + lower)
            if cut <= start:
                break
            cuts.append(cut)
            start = cut
        bounds = [0, *cuts, width]
        for left, right in zip(bounds, bounds[1:]):
            if right > left:
                box = [x0 + left, y0, x0 + right, y1]
                output.append({"bbox_px": box,
                               "polygon": [[box[0], box[1]], [box[2], box[1]],
                                           [box[2], box[3]], [box[0], box[3]]],
                               "cut_edges": [side for side, cut in (("left", left > 0), ("right", right < width))
                                             if cut]})
    return output


def _mask_iou(left: np.ndarray, right: np.ndarray) -> float:
    import cv2

    left = cv2.resize(left, (32, 32), interpolation=cv2.INTER_NEAREST) > 0
    right = cv2.resize(right, (32, 32), interpolation=cv2.INTER_NEAREST) > 0
    union = np.count_nonzero(left | right)
    return float(np.count_nonzero(left & right) / union) if union else 0.0


def _repeated_asterisk_suffixes(gray_crop: np.ndarray) -> list[tuple[str, float]]:
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
        if height < 7 or width < 4 or area < 15 or not 0.35 <= width / height <= 2.0:
            continue
        components.append((int(x), int(y), int(width), int(height), ink[y:y + height, x:x + width]))
    if len(components) < 3:
        return []

    median_height = float(np.median([component[3] for component in components]))
    glyphs = [
        component for component in components
        if 0.60 * median_height <= component[3] <= 1.40 * median_height
        and component[2] >= 0.55 * median_height
    ]
    lines: list[list[tuple]] = []
    for component in sorted(glyphs, key=lambda item: item[1] + item[3] / 2):
        center_y = component[1] + component[3] / 2
        owner = next((
            line for line in lines
            if abs(np.median([item[1] + item[3] / 2 for item in line]) - center_y) <= 0.48 * median_height
        ), None)
        if owner is None:
            lines.append([component])
        else:
            owner.append(component)

    suffixes = []
    for line in lines:
        line.sort(key=lambda item: item[0])
        suffix = []
        for component in reversed(line):
            if suffix:
                previous = suffix[-1]
                gap = previous[0] - (component[0] + component[2])
                dimensions_match = (
                    abs(component[2] - previous[2]) <= 0.17 * median_height
                    and abs(component[3] - previous[3]) <= 0.17 * median_height
                )
                if (
                    gap > 0.50 * median_height
                    or not dimensions_match
                    or _mask_iou(component[4], previous[4]) < 0.65
                ):
                    break
            suffix.append(component)
        if len(suffix) >= 3:
            center_y = float(np.median([item[1] + item[3] / 2 for item in suffix]))
            suffixes.append(("*" * len(suffix), center_y))
    return sorted(suffixes, key=lambda item: item[1])


def _recover_image_marker_candidates(image: Image.Image, page, tables: list[dict]) -> int:
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
            for text, _ in _repeated_asterisk_suffixes(gray[py0:py1, px0:px1]):
                candidates = cell.setdefault("image_marker_candidates", [])
                candidates.append({
                    "text": text,
                    "bbox": list(box),
                    "table_id": table.get("table_id"),
                    "cell_id": f"{table.get('table_id')}:{cell.get('row')}:{cell.get('col')}",
                    "method": "opencv_repeated_asterisk_suffix_v1",
                    "candidate_only": True,
                    "review_status": "needs_review",
                })
                added += 1
    return added


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
    candidates = [i for i in range(1, count)
                  if stats[i, cv2.CC_STAT_AREA] >= 6 and 8 <= stats[i, cv2.CC_STAT_WIDTH] < 0.15 * width
                  and stats[i, cv2.CC_STAT_HEIGHT] >= 8
                  and stats[i, cv2.CC_STAT_TOP] > 0
                  and stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] < height]
    if not candidates:
        return crop
    first = min(candidates, key=lambda i: stats[i, cv2.CC_STAT_LEFT])
    left, top, box_w, box_h, area = (int(v) for v in stats[first])
    if left > 0.2 * width or not (0.22 * height <= box_h <= 0.95 * height) or not (0.75 <= box_w / box_h <= 1.35):
        return crop
    component = labels[top:top + box_h, left:left + box_w] == first
    margin = max(2, box_h // 8)
    corners = (component[:margin, :margin], component[:margin, -margin:],
               component[-margin:, :margin], component[-margin:, -margin:])
    interior = component[box_h // 4:-(box_h // 4), box_w // 4:-(box_w // 4)]
    if not all(corner.any() for corner in corners) or interior.size == 0 or interior.mean() > 0.05:
        return crop
    cleared = np.asarray(crop.convert("RGB")).copy()
    cleared[:, :left + box_w + 2] = 255
    return Image.fromarray(cleared)


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
    axis_aligned = np.array([[bounds[0], bounds[1]], [bounds[2], bounds[1]],
                             [bounds[2], bounds[3]], [bounds[0], bounds[3]]], dtype=np.float32)
    if np.allclose(ordered, axis_aligned, atol=0.01):
        pad = max(1, int((y1 - y0) * 0.06))
        left, right = max(0, x0 - pad), min(image.width, x1 + pad)
        crop = image.convert("RGB").crop((left, max(0, y0 - pad), right, min(image.height, y1 + pad)))
        edges = region.get("cut_edges") or ()
        if edges:
            # Padding beyond an artificial cut would show the neighbouring piece's glyphs.
            pixels = np.asarray(crop).copy()
            if "left" in edges:
                pixels[:, :x0 - left] = 255
            if "right" in edges:
                pixels[:, pixels.shape[1] - (right - x1):] = 255
            crop = Image.fromarray(pixels)
        return crop

    top_width = float(np.linalg.norm(ordered[1] - ordered[0]))
    bottom_width = float(np.linalg.norm(ordered[2] - ordered[3]))
    left_height = float(np.linalg.norm(ordered[3] - ordered[0]))
    right_height = float(np.linalg.norm(ordered[2] - ordered[1]))
    width, height = int(round(max(top_width, bottom_width))), int(round(max(left_height, right_height)))
    if width < 2 or height < 2:
        return image.convert("RGB").crop((max(0, x0), max(0, y0), min(image.width, x1), min(image.height, y1)))

    import cv2

    destination = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
                           dtype=np.float32)
    transform = cv2.getPerspectiveTransform(ordered, destination)
    source = rgb if rgb is not None else np.asarray(image.convert("RGB"))
    rectified = cv2.warpPerspective(source, transform, (width, height), flags=cv2.INTER_CUBIC,
                                    borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    pad = max(2, int(height * 0.06))
    rectified = cv2.copyMakeBorder(rectified, pad, pad, pad, pad, cv2.BORDER_CONSTANT,
                                   value=(255, 255, 255))
    return Image.fromarray(rectified)


def _recover_sparse_cell_candidates(image: Image.Image, page, tables: list[dict], detector, predictor) -> int:
    """Retry sparse cells at 2x input size and keep numeric readings as review-only candidates."""
    import re

    added = 0
    inset_x = max(1, int(round(1.2 * image.width / page.rect.width)))
    inset_y = max(1, int(round(1.2 * image.height / page.rect.height)))
    for table in tables:
        columns = table.get("col_count")
        table_box = table.get("bbox")
        if (not isinstance(columns, int) or columns < 2 or not isinstance(table_box, list)
                or len(table_box) != 4 or table_box[2] <= table_box[0]):
            continue
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
            if ((x1 - x0) > 0.35 * (table_box[2] - table_box[0]) or y1 - y0 > 36):
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
                if (re.fullmatch(r"\d{1,2}", candidate_text) and candidate_confidence is not None
                        and candidate_confidence >= 0.55):
                    predictions.append((candidate_text, candidate_confidence,
                                        "easyocr_craft+vietocr_vgg_transformer_2x_cell_crop"))

            # A tight score-cell crop is an independent view. It can retain glyph
            # context lost by CRAFT; store disagreement as another review candidate.
            if primary_text:
                try:
                    text, confidence = predictor.predict(crop, return_prob=True)
                except Exception:
                    text, confidence = "", None
                candidate_text = "".join(text.split()) if isinstance(text, str) else ""
                candidate_confidence = _confidence(confidence)
                if (re.fullmatch(r"\d{1,2}", candidate_text) and candidate_confidence is not None
                        and candidate_confidence >= 0.55):
                    predictions.append((candidate_text, candidate_confidence,
                                        "vietocr_vgg_transformer_2x_direct_cell_crop"))

            for candidate_text, candidate_confidence, method in predictions:
                if any(candidate.get("text") == candidate_text for candidate in candidates):
                    continue
                candidates = cell.setdefault("score_ocr_candidates", candidates)
                candidates.append({
                    "text": candidate_text,
                    "bbox": list(box),
                    "method": method,
                    "confidence": candidate_confidence,
                    "candidate_only": True,
                    "review_status": "needs_review",
                })
                added += 1
    return added


def _speckle_regions(readings: list[tuple[int, float | None]], *, minimum_regions: int = 8,
                     height_ratio: float = 0.3, confidence_limit: float = 0.6) -> set[int]:
    """Indices of tiny, low-confidence crops: scan speckle that VietOCR reads as nonsense.

    Measured on QD148 p25 and QD26 p29 (median crop height 84 px): such crops were 12-20 px tall at
    confidence 0.24-0.57, while the shortest real reading was 40 px. Empirical thresholds, not constants.
    """
    if len(readings) < minimum_regions:
        return set()
    heights = sorted(height for height, _ in readings)
    median = heights[len(heights) // 2]
    return {index for index, (height, confidence) in enumerate(readings)
            if confidence is not None and confidence < confidence_limit and height < height_ratio * median}


ALTERNATIVE_PROBABILITY = 0.01


def _recognize(predictor, crop: Image.Image) -> tuple[str, float, list[dict]]:
    """VietOCR greedy decoding that also keeps the recognizer's own alternatives for unsure characters.

    The loop matches vietocr.tool.translate.translate, so text and confidence are unchanged; the
    top-5 posteriors it discards become `alternatives`: one entry per output character where the model
    gave a second character at least ALTERNATIVE_PROBABILITY, listing the characters it weighed there.
    """
    model, vocab, config = getattr(predictor, "model", None), getattr(predictor, "vocab", None), getattr(predictor, "config", None)
    if model is None or vocab is None or not isinstance(config, dict):
        text, confidence = predictor.predict(crop, return_prob=True)
        return text, confidence, []
    import torch
    from torch.nn.functional import softmax
    from vietocr.tool.translate import process_input

    dataset = config["dataset"]
    image = process_input(crop, dataset["image_height"], dataset["image_min_width"], dataset["image_max_width"])
    image = image.to(config["device"])
    model.eval()
    ids, probabilities, alternatives = [], [], []
    with torch.no_grad():
        memory = model.transformer.forward_encoder(model.cnn(image))
        sentence = [vocab.go]
        while len(sentence) <= 129 and sentence[-1] != vocab.eos:
            output, memory = model.transformer.forward_decoder(torch.LongTensor([[t] for t in sentence]), memory)
            values, indices = torch.topk(softmax(output, dim=-1)[0, -1], 5)
            best = int(indices[0])
            sentence.append(best)
            if best > 3:
                position = len(ids)
                ids.append(best)
                probabilities.append(float(values[0]))
                considered = [[vocab.i2c[int(k)], round(float(v), 4)]
                              for v, k in zip(values, indices) if int(k) > 3 and float(v) >= ALTERNATIVE_PROBABILITY]
                if len(considered) > 1:
                    alternatives.append({"i": position, "alts": considered})
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


def run_easy_viet_ocr(
    image, page, *, detect_tables: bool = True, trace: dict | None = None
) -> tuple[OCRResult, list[dict]]:
    """Detect text with CRAFT, recognize line crops with one VietOCR model."""
    from ai_core.processing.ocop.table_parser import raster_tables

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
    regions = _split_long_regions(merged_regions, image)
    if trace is not None:
        trace["recognition_regions"] = deepcopy(regions)
    predictor = _predictor()
    blocks = []
    raw_recognitions = []
    recognized = []
    warnings = ["ocr_candidates_require_source_verification"]
    for region_index, region in enumerate(regions):
        crop = _recognition_crop(image, region, rgb)
        if crop.width < 2 or crop.height < 2:
            continue
        crop = _blank_leading_checkbox(crop)
        try:
            text, confidence, alternatives = _recognize(predictor, crop)
        except Exception as exc:
            warnings.append("vietocr_region_recognition_failed")
            if trace is not None:
                raw_recognitions.append({
                    "region_index": region_index,
                    "bbox_px": list(region["bbox_px"]),
                    "crop_size_px": [crop.width, crop.height],
                    "raw_text": None,
                    "confidence": None,
                    "error": f"{type(exc).__name__}:{str(exc)[:240]}",
                })
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
        recognized.append((region_index, region, crop.height, text, confidence, raw_entry, alternatives))
    speckle = _speckle_regions([(height, _confidence(confidence)) for _, _, height, _, confidence, _, _ in recognized])
    if speckle:
        warnings.append(f"speckle_regions_dropped:{len(speckle)}")
    for position, (region_index, region, _, text, confidence, raw_entry, alternatives) in enumerate(recognized):
        if position in speckle:
            raw_entry["dropped_as"] = "speckle_region"
            continue
        raw_entry["block_id"] = f"ocr:{ENGINE}:{len(blocks)}"
        bbox = _pdf_bbox(region["bbox_px"], width_px=image.width, height_px=image.height, page=page)
        polygon = [[round(float(x) / image.width * page.rect.width, 2),
                    round(float(y) / image.height * page.rect.height, 2)]
                   for x, y in region["polygon"]]
        blocks.append({
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
        })
    layout, layout_warning = detect_regions(rgb)
    if layout_warning:
        warnings.append(layout_warning)
    page_regions = [{**region, "bbox": _pdf_bbox(region["bbox_px"], width_px=image.width,
                                                 height_px=image.height, page=page)} for region in layout]
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
        marker_count = _recover_image_marker_candidates(image, page, tables)
        if marker_count:
            warnings.append(f"image_marker_candidates_require_review:{marker_count}")
        candidate_count = _recover_sparse_cell_candidates(image, page, tables, _detector(), predictor)
        if candidate_count:
            warnings.append(f"sparse_cell_ocr_candidates_require_review:{candidate_count}")
    if not blocks:
        warnings.append("empty_ocr_result")
    return OCRResult(blocks, ENGINE, sorted(set(warnings))), tables
