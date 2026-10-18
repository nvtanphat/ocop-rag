"""Conservative table-cell OCR refinement for OCOP right-hand scoring columns.

The page OCR often reads narrow cells as broken lines or ignores isolated digits.
Keep nonempty original evidence. Empty cells can receive unverified crop text;
neither original OCR nor supplementary readings become verified domain facts.
"""

from __future__ import annotations
import re
import math

_VALUE = re.compile(r"^(?:[0-9]{1,3})$")


def _prepare_scoring_crop(crop):
    """Remove border-connected rulings, then recognize the isolated text line.

    No digit whitelist: it can force a non-digit heading into a score. Raw-line
    mode avoids Tesseract's page-layout assumptions on a single small cell.
    """
    import cv2
    import numpy as np
    from PIL import Image, ImageOps

    pixels = np.asarray(crop.convert("L"))
    _, ink = cv2.threshold(pixels, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink)
    height, width = ink.shape
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if x <= 1 or y <= 1 or x + w >= width - 1 or y + h >= height - 1 or w > width * 0.65 or area < 3:
            ink[labels == index] = 0
    points = cv2.findNonZero(ink)
    if points is None:
        return None
    x, y, w, h = cv2.boundingRect(points)
    prepared = Image.fromarray(255 - ink[y : y + h, x : x + w]).resize((w * 2, h * 2))
    prepared = ImageOps.expand(prepared, border=20, fill=255)
    return prepared


def _read_scoring_crop(crop):
    import pytesseract

    prepared = _prepare_scoring_crop(crop)
    if prepared is None:
        return []
    data = pytesseract.image_to_data(
        prepared, lang="eng", config="--psm 13", output_type=pytesseract.Output.DICT, timeout=30
    )
    words = [
        (str(text).strip(), float(score) / 100.0)
        for text, score in zip(data["text"], data["conf"])
        if str(text).strip()
    ]
    if not words:
        return []
    # Treat the whole recognition as one reading; never pick a digit out of
    # surrounding nonnumeric text such as a heading or legal qualifier.
    return [(" ".join(text for text, _ in words), min(score for _, score in words))]


def recover_scoring_cells(
    image,
    page,
    tables: list[dict],
    *,
    min_confidence: float = 0.60,
    ocr_reader=None,
    limit: int = 75,
    fill_empty: bool = False,
    fill_invalid: bool = False,
    image_view: str = "source",
) -> dict:
    if ocr_reader is None:
        ocr_reader = _read_scoring_crop
    ww, hh = image.size
    examined = added = filled = empty_filled = 0
    for table in tables:
        cols = table.get("col_count")
        if not cols or cols < 2 or not table.get("bbox"):
            continue
        box = table["bbox"]
        width = box[2] - box[0]
        for cell in table.get("cells", []):
            if examined >= limit:
                break
            if cell.get("col") != cols - 1 or cell.get("bbox") is None:
                continue
            bb = cell["bbox"]
            # Refine only a genuine narrow scoring column, not a description cell.
            if bb[2] - bb[0] > width * 0.31:
                continue
            current = str(cell.get("text") or "").strip()
            if _VALUE.fullmatch(current):
                continue
            x0 = max(0, int(bb[0] / page.rect.width * ww))
            y0 = max(0, int(bb[1] / page.rect.height * hh))
            x1 = min(ww, int(bb[2] / page.rect.width * ww))
            y1 = min(hh, int(bb[3] / page.rect.height * hh))
            if x1 - x0 < 7 or y1 - y0 < 7:
                continue
            examined += 1
            crop = image.crop((x0, y0, x1, y1))
            try:
                readings = ocr_reader(crop)
            except (RuntimeError, ValueError, OSError) as exc:
                cell.setdefault("warnings", []).append(f"score_cell_ocr_error:{type(exc).__name__}")
                continue
            valid = [
                (text, confidence)
                for text, confidence in readings
                if _VALUE.fullmatch(str(text))
                and 0 <= int(text) <= 100
                and math.isfinite(confidence)
                and min_confidence <= confidence <= 1
            ]
            if not valid:
                continue
            for guess, confidence in valid:
                cell.setdefault("score_ocr_candidates", []).append(
                    {
                        "text": str(guess),
                        "confidence": round(confidence, 4),
                        "method": "tesseract_english_scoring_crop",
                        "bbox": list(bb),
                        "review_status": "needs_review",
                        "image_view": image_view,
                    }
                )
                added += 1
            if ((fill_empty and not current) or fill_invalid) and len({str(text) for text, _ in valid}) == 1:
                guess, confidence = max(valid, key=lambda c: c[1])
                cell.update(
                    {
                        "text": str(guess),
                        "text_original": cell.get("text", ""),
                        "text_method": "tesseract_english_scoring_crop",
                        "text_confidence": round(confidence, 4),
                        "text_image_view": image_view,
                        "review_status": "needs_review",
                    }
                )
                filled += 1
                empty_filled += int(not current)
            # Primary text can change only with explicit opt-in. Its original
            # value is retained and neither reading becomes a verified fact.
    return {
        "scoring_cells_examined": examined,
        "score_candidates_added": added,
        "empty_score_cells_filled": empty_filled,
        "invalid_score_cells_recovered": filled - empty_filled,
        "score_candidates_are_unverified": True,
    }
