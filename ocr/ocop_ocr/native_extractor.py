"""Page-native text with stable PDF-point coordinates (no OCR, no legal rewriting)."""

from __future__ import annotations


def extract_native(page) -> list[dict]:
    import fitz

    result: list[dict] = []
    raw = page.get_text("dict", sort=True)
    for block_index, block in enumerate(raw.get("blocks", [])):
        if block.get("type") != 0:
            continue
        for line_index, line in enumerate(block.get("lines", [])):
            spans = line.get("spans", [])
            text = "".join(str(s.get("text", "")) for s in spans).strip()
            if not text:
                continue
            # get_text uses unrotated coordinates; rendered pages and OCR use
            # Page.rect coordinates. Keep all extraction anchors in that frame.
            rect = fitz.Rect(line["bbox"]) * page.rotation_matrix
            bbox = [round(float(v), 2) for v in rect]
            result.append(
                {
                    "block_id": f"native:{block_index}:{line_index}",
                    "text": text,
                    "bbox": bbox,
                    "method": "native",
                    "confidence": None,
                    "order": len(result),
                }
            )
    return result
