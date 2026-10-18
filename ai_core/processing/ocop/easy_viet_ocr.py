"""EasyOCR detection/recognition and optional Vietnamese line recognition.

Models stay outside the repository. Recognition confidence never verifies a fact.
"""

from __future__ import annotations

import json
import math
import os
from statistics import median
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path

import numpy as np
from PIL import Image

from ai_core.processing.ocop.registry import sha256_file


def _weights() -> Path:
    path = Path(os.environ.get("OCOP_VIETOCR_WEIGHTS", ""))
    if not path.is_file():
        raise RuntimeError("vietocr_weights_missing:set_OCOP_VIETOCR_WEIGHTS_to_local_checkpoint")
    return path


def _config() -> dict:
    model = os.environ.get("OCOP_VIETOCR_MODEL", "vgg_seq2seq")
    if model not in ("vgg_seq2seq", "vgg_transformer"):
        raise ValueError("unsupported_vietocr_model:" + model)
    name = "vietocr_config.json" if model == "vgg_seq2seq" else "vietocr_transformer_config.json"
    config = json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))
    config["device"] = "cpu"
    config["weights"] = str(_weights())
    return config


def _reader(hybrid: bool):
    from easyocr.config import MODULE_PATH

    root = Path(MODULE_PATH) / "model"
    names = ["craft_mlt_25k.pth"] + ([] if hybrid else ["latin_g2.pth"])
    digests = tuple(sha256_file(root / name) for name in names)
    return _load_reader(hybrid, str(root), digests)


@lru_cache(maxsize=2)
def _load_reader(hybrid: bool, model_directory: str, digests: tuple):
    import easyocr

    return easyocr.Reader(
        ["vi", "en"],
        gpu=False,
        recognizer=not hybrid,
        verbose=False,
        download_enabled=False,
        model_storage_directory=model_directory,
    )


def _predictor():
    config = json.dumps(_config(), sort_keys=True)
    return _load_predictor(config, sha256_file(_weights()))


@lru_cache(maxsize=1)
def _load_predictor(config: str, digest: str):
    from vietocr.tool.predictor import Predictor

    return Predictor(json.loads(config))


def runtime_signature(engine: str) -> dict:
    """Fail before processing when models are unavailable; hash actual local bytes."""
    hybrid = engine in ("easyocr_vietocr", "ensemble")
    if hybrid:
        _weights()
    reader = _reader(hybrid)
    root = Path(reader.model_storage_directory)
    names = ["craft_mlt_25k.pth"] + ([] if hybrid else ["latin_g2.pth"])
    signature = {
        "adapter_sha256": sha256_file(Path(__file__)),
        "easyocr": version("easyocr"),
        "torch": version("torch"),
        "models": {name: sha256_file(root / name) for name in names},
    }
    if hybrid:
        # Reject incompatible checkpoints before quarantining an entire corpus.
        _predictor()
        signature.update(vietocr=version("vietocr"), config=_config(), weights_sha256=sha256_file(_weights()))
    if engine == "ensemble":
        _reader(False)
        from ai_core.processing.ocop import ocr_consensus

        signature["latin_g2_sha256"] = sha256_file(root / "latin_g2.pth")
        signature["consensus_sha256"] = sha256_file(Path(ocr_consensus.__file__))
    return signature


def _blocks(lines, image, page, engine):
    from ai_core.processing.ocop.ocr_extractor import OCRResult, _pdf_bbox

    width, height = image.size
    blocks = []
    for polygon, text, score in lines:
        points = np.asarray(polygon, dtype=float)
        if points.shape != (4, 2) or not np.isfinite(points).all():
            raise ValueError("invalid_easyocr_polygon")
        confidence = float(score)
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("invalid_easyocr_confidence")
        if not isinstance(text, str):
            raise ValueError("invalid_easyocr_text")
        if not text.strip():
            continue
        x0, y0 = points.min(axis=0)
        x1, y1 = points.max(axis=0)
        if x0 >= x1 or y0 >= y1 or x1 <= 0 or y1 <= 0 or x0 >= width or y0 >= height:
            raise ValueError("invalid_easyocr_region")
        bbox = _pdf_bbox(
            [x0, y0, x1, y1],
            width_px=width,
            height_px=height,
            width_pt=page.rect.width,
            height_pt=page.rect.height,
        )
        quad = [
            [round(float(x) / width * page.rect.width, 2), round(float(y) / height * page.rect.height, 2)]
            for x, y in points
        ]
        blocks.append(
            {
                "block_id": f"ocr:{engine}:{len(blocks)}",
                "text": text.strip(),
                "bbox": bbox,
                "polygon": quad,
                "method": engine,
                "confidence": confidence,
                "review_status": "needs_review",
                "order": len(blocks),
            }
        )
    # EasyOCR appends free-form regions after horizontal ones. Sort before table assignment.
    lines = _group_lines(blocks)
    blocks = [block for line in lines for block in line]
    for order, block in enumerate(blocks):
        block["order"] = order
    return OCRResult(blocks, engine, ["ocr_candidates_require_source_verification"], list(blocks))


def _group_lines(blocks):
    """Use region centers: diacritics change top edges within the same line."""
    lines = []
    for block in sorted(blocks, key=lambda b: ((b["bbox"][1] + b["bbox"][3]) / 2, b["bbox"][0])):
        y0, y1 = block["bbox"][1], block["bbox"][3]
        center, height = (y0 + y1) / 2, y1 - y0
        matches = [
            line
            for line in lines
            if abs(median((b["bbox"][1] + b["bbox"][3]) / 2 for b in line) - center)
            <= 0.5 * min(height, median(b["bbox"][3] - b["bbox"][1] for b in line))
        ]
        if matches:
            matches[-1].append(block)
        else:
            lines.append([block])
    return [sorted(line, key=lambda b: b["bbox"][0]) for line in lines]


def _split_row_regions(crops, image, page):
    """Split detector regions crossing observed table rows before recognition.

    CRAFT can join vertically adjacent digits along a ruling. Assigning its one
    transcription by midpoint would move the second row's score into the first.
    Only split when each side occupies at least 20% of the detected region.
    """
    from ai_core.processing.ocop.table_parser import raster_tables

    width, height = image.size
    cells = [cell for table in raster_tables(image, page, []) for cell in table["cells"]]
    pixels = np.asarray(image.convert("L"))
    result = []
    for polygon, crop in crops:
        points = np.asarray(polygon, dtype=float)
        if points.shape != (4, 2) or not np.isfinite(points).all():
            raise ValueError("invalid_easyocr_polygon")
        x0, y0 = points.min(axis=0)
        x1, y1 = points.max(axis=0)
        # A page-wide row estimate can intersect a skewed horizontal sentence.
        # Restrict recovery to tall regions that a horizontal recognizer would
        # otherwise rotate; never cut ordinary legal lines at estimated rules.
        if x1 - x0 >= y1 - y0:
            result.append((polygon, crop))
            continue
        cuts = set()
        for cell in cells:
            left, top, right, bottom = cell["bbox"]
            left, right = left * width / page.rect.width, right * width / page.rect.width
            boundary = bottom * height / page.rect.height
            if left <= x0 + 2 and right >= x1 - 2 and y0 + 0.2 * (y1 - y0) < boundary < y1 - 0.2 * (y1 - y0):
                cuts.add(int(round(boundary)))
        if not cuts:
            result.append((polygon, crop))
            continue
        x0, x1 = max(0, int(math.floor(x0))), min(width, int(math.ceil(x1)))
        boundaries = [max(0, int(math.floor(y0))), *sorted(cuts), min(height, int(math.ceil(y1)))]
        for top, bottom in zip(boundaries, boundaries[1:]):
            if bottom <= top or x1 <= x0:
                raise ValueError("invalid_easyocr_region")
            result.append(([[x0, top], [x1, top], [x1, bottom], [x0, bottom]], pixels[top:bottom, x0:x1]))
    return result


def _merge_line_regions(crops, image, page):
    """Restore adjacent horizontal/free fragments without crossing table columns."""
    from ai_core.processing.ocop.table_parser import raster_tables

    width, height = image.size
    tables = raster_tables(image, page, [])
    pixels = np.asarray(image.convert("L"))
    entries = []
    for index, (polygon, crop) in enumerate(crops):
        points = np.asarray(polygon, dtype=float)
        x0, y0 = points.min(axis=0)
        x1, y1 = points.max(axis=0)
        cx, cy = (x0 + x1) / 2 / width * page.rect.width, (y0 + y1) / 2 / height * page.rect.height
        owners = {
            (i, cell["col"])
            for i, table in enumerate(tables)
            for cell in table["cells"]
            if cell["bbox"][0] <= cx <= cell["bbox"][2] and cell["bbox"][1] <= cy <= cell["bbox"][3]
        }
        owner = next(iter(owners)) if len(owners) == 1 else ("ambiguous", index) if owners else None
        entries.append({"bbox": [x0, y0, x1, y1], "owner": owner, "region": (polygon, crop)})
    result = []
    for line in _group_lines(entries):
        clusters = []
        for entry in line:
            previous = clusters[-1][-1] if clusters else None
            box = entry["bbox"]
            if previous is not None:
                prior = previous["bbox"]
                gap = box[0] - prior[2]
                adjacent = gap <= min(box[3] - box[1], prior[3] - prior[1])
            else:
                adjacent = False
            if adjacent and entry["owner"] == previous["owner"]:
                clusters[-1].append(entry)
            else:
                clusters.append([entry])
        for cluster in clusters:
            if len(cluster) == 1:
                result.append(cluster[0]["region"])
                continue
            x0 = max(0, int(math.floor(min(b["bbox"][0] for b in cluster))))
            y0 = max(0, int(math.floor(min(b["bbox"][1] for b in cluster))))
            x1 = min(width, int(math.ceil(max(b["bbox"][2] for b in cluster))))
            y1 = min(height, int(math.ceil(max(b["bbox"][3] for b in cluster))))
            result.append(([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], pixels[y0:y1, x0:x1]))
    return result


def _split_line_windows(crops):
    """Keep inference within the pretrained 512/32 width/height regime.

    Long lines can emit EOS early even when their bounding box is complete.
    Cut only at measured whitespace; project every window back to its source quad.
    Pixels used for recognition remain unchanged.
    """
    import cv2

    result = []
    for polygon, crop in crops:
        height, width = crop.shape[:2]
        maximum = height * 16
        if width <= maximum:
            result.append((polygon, crop))
            continue
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY) if crop.ndim == 3 else crop
        _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        rulings = cv2.morphologyEx(
            ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(24, width // 3), 1))
        )
        count, labels, stats, _ = cv2.connectedComponentsWithStats(rulings)
        for index in range(1, count):
            if stats[index, cv2.CC_STAT_HEIGHT] > max(2, height // 12):
                rulings[labels == index] = 0
        foreground = cv2.bitwise_and(ink, cv2.bitwise_not(rulings))
        margin = max(1, height // 10)
        blank = np.flatnonzero(np.count_nonzero(foreground[margin : height - margin], axis=0) == 0)
        runs = np.split(blank, np.where(np.diff(blank) > 1)[0] + 1)
        gaps = [int((run[0] + run[-1]) // 2) for run in runs if len(run) >= max(2, height // 12)]
        boundaries = [0]
        while width - boundaries[-1] > maximum:
            start = boundaries[-1]
            choices = [gap for gap in gaps if start + maximum // 2 <= gap <= start + maximum]
            if not choices:
                raise RuntimeError("overlong_ocr_region_without_safe_word_gap")
            boundaries.append(max(choices))
        boundaries.append(width)
        source = np.asarray(polygon, dtype=np.float32)
        if source.shape != (4, 2) or not np.isfinite(source).all():
            raise ValueError("invalid_easyocr_polygon")
        rectangle = np.array(
            [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32
        )
        inverse = cv2.getPerspectiveTransform(rectangle, source)
        for left, right in zip(boundaries, boundaries[1:]):
            window = np.array(
                [[[left, 0], [right - 1, 0], [right - 1, height - 1], [left, height - 1]]], dtype=np.float32
            )
            mapped = cv2.perspectiveTransform(window, inverse)[0].tolist()
            result.append((mapped, crop[:, left:right]))
    return result


def run_easy_ocr(image, page, engine: str):
    if engine not in ("easyocr", "easyocr_vietocr"):
        raise ValueError(f"unsupported OCR engine: {engine}")
    hybrid = engine == "easyocr_vietocr"
    reader = _reader(hybrid)
    pixels = np.asarray(image.convert("RGB"))
    if not hybrid:
        lines = reader.readtext(pixels, detail=1, paragraph=False, batch_size=4, workers=0)
    else:
        from easyocr.utils import get_image_list

        horizontal, free = reader.detect(pixels)
        if len(horizontal) != 1 or len(free) != 1:
            raise RuntimeError("easyocr_detection_batch_mismatch")
        crops, _ = get_image_list(horizontal[0], free[0], np.asarray(image.convert("L")))
        crops = _split_row_regions(crops, image, page)
        crops = _merge_line_regions(crops, image, page)
        crops = _split_line_windows(crops)
        predictor = _predictor()
        lines = [
            (polygon, *predictor.predict(Image.fromarray(crop).convert("RGB"), return_prob=True))
            for polygon, crop in crops
        ]
    return _blocks(lines, image, page, engine)
