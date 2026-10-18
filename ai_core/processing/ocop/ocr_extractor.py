"""OCR adapters: PaddleOCR when installed, deterministic Tesseract fallback.

All coordinates returned here are PDF points, *not* rendered pixel coordinates.
OCR output remains unverified for legally critical scores/asterisks.
"""
from __future__ import annotations

import importlib.util
import math
import re
import shutil
import subprocess
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass
from typing import Any

import numpy as np

from ai_core.processing.ocop.registry import sha256_file


def tesseract_runtime_signature() -> dict:
    """Identify the actual engine and traineddata, not just its Python wrapper.

    --list-langs reports Tesseract's resolved tessdata directory, including
    TESSDATA_PREFIX. Changing model bytes must invalidate cached extraction.
    """
    executable = shutil.which("tesseract")
    if executable is None:
        return {"available": False}
    result = subprocess.run([executable, "--list-langs"], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=15, check=True)
    output = result.stdout + result.stderr
    directory = re.search(r'in "([^"]+)"', output)
    if directory is None:
        raise RuntimeError("tesseract_tessdata_directory_not_reported")
    root = Path(directory.group(1))
    return {"available": True, "engine_sha256": sha256_file(Path(executable)),
            "traineddata": {lang: sha256_file(root / f"{lang}.traineddata")
                            if (root / f"{lang}.traineddata").is_file() else None
                            for lang in ("vie", "eng", "osd")}}


@dataclass(frozen=True)
class OCRResult:
    blocks: list[dict]
    engine: str
    warnings: list[str]
    word_blocks: list[dict] | None = None


def _pdf_bbox(pixel_box, *, width_px: int, height_px: int, width_pt: float, height_pt: float):
    try:
        x0, y0, x1, y1 = [float(v) for v in pixel_box]
    except (TypeError,ValueError) as exc:
        raise ValueError("invalid_ocr_bbox") from exc
    if (not all(math.isfinite(v) for v in (x0,y0,x1,y1,width_px,height_px,width_pt,height_pt))
            or min(width_px,height_px,width_pt,height_pt)<=0 or x0>x1 or y0>y1):
        raise ValueError("invalid_ocr_bbox")
    return [round(max(0, min(width_pt, x0 / width_px * width_pt)), 2),
            round(max(0, min(height_pt, y0 / height_px * height_pt)), 2),
            round(max(0, min(width_pt, x1 / width_px * width_pt)), 2),
            round(max(0, min(height_pt, y1 / height_px * height_pt)), 2)]


def _to_bbox(poly):
    pts = np.asarray(poly, dtype=float).reshape(-1, 2)
    return [float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())]


def _tesseract(image, page, lang: str = "vie+eng") -> OCRResult:
    if shutil.which("tesseract") is None:
        raise RuntimeError("tesseract executable not available; install Tesseract with Vietnamese language")
    import pytesseract
    from pytesseract import Output

    available = set(pytesseract.get_languages(config=""))
    missing = sorted(set(lang.split("+")) - available)
    if missing:
        raise RuntimeError("missing_ocr_languages:" + ",".join(missing))
    data = pytesseract.image_to_data(image, lang=lang, config="--psm 3", output_type=Output.DICT, timeout=180)
    w, h = image.size
    groups: dict[tuple[int, int, int], list[int]] = {}
    for i, txt in enumerate(data["text"]):
        if str(txt).strip():
            groups.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(i)
    word_blocks=[]
    for i, txt in enumerate(data["text"]):
        if not str(txt).strip():
            continue
        try:
            conf=float(data["conf"][i])/100.
        except (ValueError,TypeError):
            conf=None
        word_blocks.append({"block_id":f"ocr:word:{i}","text":str(txt).strip(),
             "bbox":_pdf_bbox((data["left"][i], data["top"][i],
                     data["left"][i]+data["width"][i], data["top"][i]+data["height"][i]),
                    width_px=w,height_px=h,width_pt=page.rect.width,height_pt=page.rect.height),
             "method":"tesseract_word","confidence":round(conf,4) if conf is not None and conf>=0 else None})
    blocks = []
    for key, indices in groups.items():
        x0 = min(data["left"][i] for i in indices)
        y0 = min(data["top"][i] for i in indices)
        x1 = max(data["left"][i] + data["width"][i] for i in indices)
        y1 = max(data["top"][i] + data["height"][i] for i in indices)
        confs = []
        for i in indices:
            try:
                score = float(data["conf"][i])
                if score >= 0:
                    confs.append(score / 100.0)
            except (ValueError, TypeError):
                pass
        blocks.append({"block_id": "ocr:%d:%d:%d" % key,
                       "text": " ".join(str(data["text"][i]) for i in indices).strip(),
                       "bbox": _pdf_bbox([x0,y0,x1,y1],width_px=w,height_px=h,
                                         width_pt=page.rect.width,height_pt=page.rect.height),
                       "method": "tesseract", "confidence": round(sum(confs)/len(confs), 4) if confs else None,
                       "order": len(blocks)})
    return OCRResult(blocks, "tesseract", [],word_blocks)


@lru_cache(maxsize=1)
def _paddle_model():
    from paddleocr import PaddleOCR
    try:
        return PaddleOCR(lang="vi", use_textline_orientation=True)
    except TypeError:
        return PaddleOCR(lang="vi", use_angle_cls=True, show_log=False)


def _valid_confidence(score):
    try:
        value=float(score)
    except (ValueError,TypeError) as exc:
        raise RuntimeError("invalid_paddle_ocr_confidence") from exc
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise RuntimeError("invalid_paddle_ocr_confidence")
    return value


def _paddle(image, page, model: Any = None) -> OCRResult:
    """Accept PaddleOCR 3.x predict() and 2.x ocr(); fail explicitly on incompatible APIs."""
    from numpy import asarray
    if model is None:
        model = _paddle_model()
    pixels = asarray(image.convert("RGB"))
    lines = []
    if hasattr(model, "predict"):
        outputs = model.predict(pixels)
        for obj in outputs:
            payload = getattr(obj, "json", obj)
            if callable(payload):
                payload = payload()
            if isinstance(payload, dict) and "res" in payload:
                payload = payload["res"]
            if not isinstance(payload, dict):
                raise RuntimeError("unsupported PaddleOCR predict result; pin adapter to installed version")
            polygons=payload.get("rec_polys", [])
            texts=payload.get("rec_texts", [])
            scores=payload.get("rec_scores", [])
            if not (isinstance(polygons,list) and isinstance(texts,list) and isinstance(scores,list)):
                raise RuntimeError("paddleocr_field_type_mismatch")
            if not (len(polygons)==len(texts)==len(scores)):
                raise RuntimeError("paddleocr_result_length_mismatch")
            for poly, txt, score in zip(polygons,texts,scores):
                lines.append((poly, txt, score))
    else:
        outputs = model.ocr(pixels, cls=True)
        for group in outputs or []:
            for line in group or []:
                if len(line) >= 2:
                    lines.append((line[0], line[1][0], line[1][1]))
    w,h = image.size
    blocks = []
    for poly, txt, score in lines:
        if not str(txt).strip():
            continue
        blocks.append({"block_id": f"ocr:paddle:{len(blocks)}", "text": str(txt).strip(),
                       "bbox": _pdf_bbox(_to_bbox(poly),width_px=w,height_px=h,
                                         width_pt=page.rect.width,height_pt=page.rect.height),
                       "method": "paddle", "confidence": _valid_confidence(score),
                       "order": len(blocks)})
    return OCRResult(blocks,"paddle",[],list(blocks))


def run_ocr(image, page, engine: str = "auto", paddle_model=None) -> OCRResult:
    if engine not in ("auto", "paddle", "tesseract", "easyocr", "easyocr_vietocr", "ensemble"):
        raise ValueError(f"unsupported OCR engine: {engine}")
    if engine in ("easyocr", "easyocr_vietocr", "ensemble"):
        from ai_core.processing.ocop.easy_viet_ocr import run_easy_ocr
        result = run_easy_ocr(image, page, "easyocr_vietocr" if engine == "ensemble" else engine)
        return OCRResult(result.blocks, engine, result.warnings, result.word_blocks)
    if engine == "paddle":
        return _paddle(image,page,paddle_model)
    if engine == "tesseract":
        return _tesseract(image,page)
    if paddle_model is not None or importlib.util.find_spec("paddleocr") is not None:
        try:
            return _paddle(image,page,paddle_model)
        except Exception as exc:
            fallback = _tesseract(image,page)
            return OCRResult(fallback.blocks, fallback.engine,[f"paddle_fallback:{type(exc).__name__}:{str(exc)[:180]}"],fallback.word_blocks)
    fallback = _tesseract(image,page)
    return OCRResult(fallback.blocks, fallback.engine,["paddle_not_installed:tesseract_baseline"],fallback.word_blocks)
