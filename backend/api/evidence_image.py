"""Render a source PDF page with the cited evidence regions highlighted.

The image is produced from the locked PDF bytes: the file's SHA-256 must equal the registry lock entry (and the
citation's own ``source_sha256`` when the caller sends it), boxes must be finite and inside the page, and nothing
outside ``data/raw/ocop`` is read. Raw evidence boxes are drawn in amber; structural-context boxes (parent
article/clause) in blue, so a reader can tell what the answer quotes from what only locates it.
"""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

MAX_BOXES = 40
EVIDENCE_RGB, CONTEXT_RGB = (245, 166, 35), (47, 111, 214)


class EvidenceImageError(ValueError):
    """Bad request (invalid page/box/SHA) as opposed to infrastructure failure."""


@lru_cache(maxsize=32)
def _digest(path: str, mtime_ns: int, size: int) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def locked_sha256(root: Path, source_id: str) -> str:
    lock = json.loads((root / 'configs/ocop_sources.lock.json').read_text(encoding='utf-8'))
    entry = next((s for s in lock.get('sources', []) if s.get('source_id') == source_id), None)
    if entry is None or not entry.get('sha256'):
        raise EvidenceImageError('source is not in the locked registry')
    return entry['sha256']


def parse_boxes(values: list[str]) -> list[tuple[float, float, float, float]]:
    boxes = []
    for value in values[:MAX_BOXES]:
        try:
            x0, y0, x1, y1 = (float(part) for part in value.split(','))
        except ValueError as exc:
            raise EvidenceImageError('box must be x0,y0,x1,y1') from exc
        if not all(math.isfinite(v) for v in (x0, y0, x1, y1)) or x0 >= x1 or y0 >= y1:
            raise EvidenceImageError('box is empty or not finite')
        boxes.append((x0, y0, x1, y1))
    return boxes


def render_evidence_png(root: Path, pdf: Path, source_id: str, page_number: int, *, evidence: list, context: list,
                        expected_sha: str | None, dpi: int, crop: bool) -> bytes:
    import fitz
    stat = pdf.stat()
    digest = _digest(str(pdf), stat.st_mtime_ns, stat.st_size)
    if digest != locked_sha256(root, source_id):
        raise EvidenceImageError('PDF does not match the locked SHA-256')
    if expected_sha is not None and expected_sha != digest:
        raise EvidenceImageError('citation SHA-256 does not match the PDF')
    if not 72 <= dpi <= 220:
        raise EvidenceImageError('dpi must be 72-220')
    with fitz.open(pdf) as document:
        if not 1 <= page_number <= document.page_count:
            raise EvidenceImageError('page out of range')
        page = document[page_number - 1]
        bounds = page.rect
        for x0, y0, x1, y1 in (*evidence, *context):
            if x0 < bounds.x0 - 1 or y0 < bounds.y0 - 1 or x1 > bounds.x1 + 1 or y1 > bounds.y1 + 1:
                raise EvidenceImageError('box outside the PDF page')
        for boxes, (r, g, b), fill in ((context, CONTEXT_RGB, 0.12), (evidence, EVIDENCE_RGB, 0.30)):
            for rect in boxes:
                page.draw_rect(fitz.Rect(rect), color=(r / 255, g / 255, b / 255), fill=(r / 255, g / 255, b / 255),
                               fill_opacity=fill, stroke_opacity=0.9, width=1.2)
        clip = None
        shown = evidence or context
        if crop and shown:
            region = fitz.Rect(min(b[0] for b in shown), min(b[1] for b in shown), max(b[2] for b in shown), max(b[3] for b in shown))
            region = fitz.Rect(region.x0 - 36, region.y0 - 48, region.x1 + 36, region.y1 + 48) & bounds
            clip = region if not region.is_empty else None
        pixmap = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=clip, alpha=False)
        return pixmap.tobytes('png')
