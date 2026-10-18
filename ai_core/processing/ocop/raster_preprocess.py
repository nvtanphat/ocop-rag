"""Conservative raster deskew with reversible source geometry.

Never erase small components: Vietnamese tone marks and footnote stars are ink.
Expanded white canvas preserves all four original page corners.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class PreparedRaster:
    image: Image.Image
    source_size: tuple[int, int]
    transform: np.ndarray
    angle_degrees: float
    supporting_lines: int

    def metadata(self) -> dict:
        return {
            "method": "conservative_ruling_deskew",
            "angle_degrees": self.angle_degrees,
            "supporting_lines": self.supporting_lines,
            "source_size_px": list(self.source_size),
            "processed_size_px": list(self.image.size),
            "source_to_processed": self.transform.tolist(),
        }

    def source_points(self, points, width_pt: float, height_pt: float) -> list[list[float]]:
        """Processed PDF-like points -> original PDF points, without rounding loss."""
        scale = np.array([self.source_size[0] / width_pt, self.source_size[1] / height_pt])
        pixels = np.asarray(points, dtype=float) * scale
        if pixels.ndim != 2 or pixels.shape[1] != 2 or not np.isfinite(pixels).all():
            raise ValueError("invalid_preprocessed_polygon")
        inverse = np.linalg.inv(self.transform)
        mapped = np.c_[pixels, np.ones(len(pixels))] @ inverse.T
        return (mapped[:, :2] / scale).tolist()


def prepare_raster(image: Image.Image) -> PreparedRaster:
    import cv2

    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    if min(width, height) < 2:
        raise ValueError("raster_too_small")
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 80, 180)
    detected = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 1800,
        threshold=max(30, width // 15),
        minLineLength=max(30, int(width * 0.3)),
        maxLineGap=max(5, width // 90),
    )
    candidates = []
    for x0, y0, x1, y1 in () if detected is None else detected.reshape(-1, 4):
        angle = math.degrees(math.atan2(y1 - y0, x1 - x0))
        if abs(angle) <= 5:
            candidates.append((angle, math.hypot(x1 - x0, y1 - y0)))
    angle = 0.0
    if len(candidates) >= 3:
        values = np.array(sorted(candidates))
        weights = np.cumsum(values[:, 1])
        median = float(values[np.searchsorted(weights, weights[-1] / 2), 0])
        # Conflicting long-line directions are not evidence of a reliable skew.
        deviations = np.array(sorted((abs(value - median), length) for value, length in candidates))
        cumulative = np.cumsum(deviations[:, 1])
        mad = float(deviations[np.searchsorted(cumulative, cumulative[-1] / 2), 0])
        support = sum(length for value, length in candidates if abs(value - median) <= max(0.3, 3 * mad))
        if mad <= 0.3 and support >= 0.8 * sum(length for _, length in candidates) and abs(median) >= 0.1:
            angle = median
            # Hough endpoints on thick, rasterized rules can bias the slope.
            # Refine around the supported direction by horizontal ink projection.
            ratio = min(1.0, 1000 / width)
            ink = cv2.resize(
                (gray < 160).astype(np.uint8), None, fx=ratio, fy=ratio, interpolation=cv2.INTER_NEAREST
            )
            ih, iw = ink.shape
            scores = []
            for candidate in np.linspace(max(-5, angle - 0.3), min(5, angle + 0.3), 13):
                matrix = cv2.getRotationMatrix2D((iw / 2, ih / 2), float(candidate), 1)
                aligned = cv2.warpAffine(ink, matrix, (iw, ih), flags=cv2.INTER_NEAREST)
                projection = aligned.sum(axis=1, dtype=np.float64)
                scores.append((float(projection @ projection), float(candidate)))
            angle = max(scores, key=lambda pair: pair[0])[1]
    if angle == 0:
        return PreparedRaster(image.convert("RGB"), image.size, np.eye(3), 0.0, len(candidates))
    affine = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
    corners = np.array([[0, 0, 1], [width, 0, 1], [width, height, 1], [0, height, 1]]) @ affine.T
    low = np.floor(corners.min(axis=0))
    high = np.ceil(corners.max(axis=0))
    affine[:, 2] -= low
    size = tuple(int(v) for v in high - low)
    output = cv2.warpAffine(rgb, affine, size, flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    transform = np.vstack([affine, [0, 0, 1]])
    return PreparedRaster(Image.fromarray(output), image.size, transform, angle, len(candidates))


def restore_geometry(prepared: PreparedRaster, blocks, tables, width_pt: float, height_pt: float):
    """Restore each mutable object once; word/line lists may share dictionaries."""
    seen = set()
    for obj in [*blocks, *tables, *(cell for table in tables for cell in table["cells"])]:
        if id(obj) in seen or obj.get("bbox") is None:
            continue
        seen.add(id(obj))
        x0, y0, x1, y1 = obj["bbox"]
        polygon = obj.get("polygon") or [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        mapped = prepared.source_points(polygon, width_pt, height_pt)
        points = np.asarray(mapped)
        obj["bbox_processed"] = list(obj["bbox"])
        obj["polygon"] = [[round(x, 4), round(y, 4)] for x, y in mapped]
        obj["bbox"] = [round(float(v), 2) for v in (*points.min(axis=0), *points.max(axis=0))]
        for candidate in [*obj.get("score_ocr_candidates", []), *obj.get("image_marker_candidates", [])]:
            candidate["bbox"] = list(obj["bbox"])
