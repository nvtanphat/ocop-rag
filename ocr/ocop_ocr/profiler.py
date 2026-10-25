"""Read-only PDF page profiling. PDF will add OCR/layout/table parsing."""

from __future__ import annotations

from pathlib import Path


def profile_pdf(path: Path, source_id: str, *, min_native_chars: int = 120) -> list[dict]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError('PDF profiling requires: pip install -e ".[pdf]"') from exc

    pages = []
    with fitz.open(path) as doc:
        if doc.is_encrypted:
            raise ValueError(f"encrypted PDF cannot be profiled: {path.name}")
        for idx in range(len(doc)):
            page = doc.load_page(idx)
            content = page.get_text("text", sort=True).strip()
            page_images = page.get_images(full=False)
            image_count = len(page_images)
            native_chars = len(content)
            page_area = max(page.rect.width * page.rect.height, 1)
            # A signed scan has ~149 native characters (signature metadata)
            # over a full-page raster. Character count alone misclassifies it.
            largest_image_area_ratio = 0.0
            for entry in page_images:
                for rect in page.get_image_rects(entry[0]):
                    coverage = (rect * page.rotation_matrix) & page.rect
                    largest_image_area_ratio = max(
                        largest_image_area_ratio,
                        (coverage.width * coverage.height) / page_area,
                    )
            # Heuristic is not an OCR quality evaluation. An image-only page
            # and a sparse text page must both be passed to PDF review.
            if largest_image_area_ratio >= 0.70:
                kind = "ocr_candidate"  # full-page scan, even with digital signature text
            elif native_chars < min_native_chars:
                kind = "ocr_candidate" if image_count else "sparse_or_blank"
            elif image_count:
                kind = "mixed_or_native_with_images"
            else:
                kind = "native_text"
            pages.append(
                {
                    "source_id": source_id,
                    "pdf_page": idx + 1,
                    "width_pt": round(page.rect.width, 2),
                    "height_pt": round(page.rect.height, 2),
                    "rotation_degrees": page.rotation,
                    "native_chars": native_chars,
                    "embedded_image_count": image_count,
                    "largest_image_area_ratio": round(largest_image_area_ratio, 4),
                    "page_class": kind,
                    "needs_ocr_review": kind in ("ocr_candidate", "sparse_or_blank"),
                }
            )
    return pages
