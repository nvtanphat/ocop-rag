"""Optional layout regions (PP-DocLayout) that group OCR blocks for reading order.

Text from a seal, a received-stamp or a signature panel sits beside or inside body text, and a
y-band sort interleaves it line by line with the body. Docling-style assembly avoids that: each OCR
block is assigned to the detected layout region that contains it, and regions are read in order.
The model is loaded only from local files; when it is absent the OCR path runs unchanged and the
page records `layout_model_unavailable`.
"""
from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

import numpy as np

from ocop_contracts.registry import sha256_file

MODEL_NAME = "PP-DocLayout_plus-L"
MIN_SCORE = 0.5


def model_dir() -> Path:
    configured = os.getenv("OCOP_LAYOUT_MODEL_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".paddlex" / "official_models" / MODEL_NAME


def layout_signature() -> dict | None:
    params = model_dir() / "inference.pdiparams"
    if not params.is_file():
        return None
    from importlib.metadata import version
    return {"model": MODEL_NAME, "params_sha256": sha256_file(params), "paddleocr": version("paddleocr"),
            "adapter_sha256": sha256_file(Path(__file__)), "min_score": MIN_SCORE}


@lru_cache(maxsize=1)
def _model(directory: str):
    # paddleocr imports transformers, whose TensorFlow branch breaks on some installs.
    for key, value in (("USE_TF", "0"), ("TRANSFORMERS_NO_TF", "1"), ("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")):
        os.environ.setdefault(key, value)
    from paddleocr import LayoutDetection
    # oneDNN is disabled: Paddle 3 on Windows fails on this model's attributes with it enabled.
    return LayoutDetection(model_name=MODEL_NAME, model_dir=directory, enable_mkldnn=False)


def detect_regions(rgb: np.ndarray) -> tuple[list[dict], str | None]:
    """Layout regions in pixel coordinates of `rgb`, or a warning when the model cannot run."""
    if layout_signature() is None:
        return [], "layout_model_unavailable"
    try:
        result = _model(str(model_dir())).predict(np.ascontiguousarray(rgb[:, :, ::-1]))[0]
    except Exception as exc:  # optional stage: OCR must not fail because layout did
        return [], f"layout_model_failed:{type(exc).__name__}"
    return [{"label": str(box["label"]), "score": round(float(box["score"]), 3),
             "bbox_px": [float(v) for v in box["coordinate"]]}
            for box in result["boxes"] if float(box["score"]) >= MIN_SCORE], None


def _area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _intersection(a, b) -> float:
    return _area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def _reading_order(boxes: list[list[float]]) -> list[int]:
    """Indices in reading order: rows of vertically overlapping regions, each row left to right."""
    rows: list[list[int]] = []
    for index in sorted(range(len(boxes)), key=lambda i: (boxes[i][1], boxes[i][0])):
        box = boxes[index]
        if rows:
            first = boxes[rows[-1][0]]
            overlap = min(box[3], first[3]) - max(box[1], first[1])
            if overlap >= 0.5 * min(box[3] - box[1], first[3] - first[1]):
                rows[-1].append(index)
                continue
        rows.append([index])
    return [i for row in rows for i in sorted(row, key=lambda i: boxes[i][0])]


def assign_regions(blocks: list[dict], regions: list[dict]) -> int:
    """Tag each block with its containing region and a region reading-order index; returns blocks placed.

    `blocks[i]["bbox"]` and `regions[j]["bbox"]` must share one coordinate frame. A block belongs to the
    smallest region covering at least half of it; any other block forms a region of its own.
    """
    groups: list[dict] = [dict(region, members=[]) for region in regions]
    placed = 0
    for block in blocks:
        box = block.get("bbox")
        if not box or _area(box) <= 0:
            continue
        covering = [g for g in groups[:len(regions)] if _intersection(box, g["bbox"]) >= 0.5 * _area(box)]
        if covering:
            min(covering, key=lambda g: _area(g["bbox"]))["members"].append(block)
            placed += 1
        else:
            groups.append({"label": "unassigned", "score": None, "bbox": list(box), "members": [block]})
    occupied = [g for g in groups if g["members"]]
    for order, position in enumerate(_reading_order([g["bbox"] for g in occupied])):
        group = occupied[position]
        for block in group["members"]:
            block["layout_region"] = {"order": order, "label": group["label"], "score": group["score"]}
    return placed
