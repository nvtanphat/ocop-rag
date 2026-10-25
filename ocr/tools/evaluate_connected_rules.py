from pathlib import Path
import json
import fitz
from PIL import Image
from ocop_contracts.pdf_loader import checked_sources
from ocop_ocr import table_parser
from ocop_ocr.raster_preprocess import prepare_raster


def evaluate_table_rules(root: Path, base: Path, selection: list[tuple[str, int]]):
    """Evaluate raster tables and score column detection across sample pages."""
    sources, _ = checked_sources(
        root, root / "configs/ocop_sources.json", root / "configs/ocop_sources.lock.json"
    )
    sources = {s.source_id: s for s in sources}
    results = []
    for sid, number in selection:
        with fitz.open(root / sources[sid].path) as document:
            page = document[number - 1]
            pix = page.get_pixmap(dpi=300, alpha=False)
            prepared = prepare_raster(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
            tables = table_parser.raster_tables(prepared.image, page, [])
            results.append(
                {
                    "source_id": sid,
                    "pdf_page": number,
                    "tables": [
                        {
                            "rows": t["row_count"],
                            "columns": t["col_count"],
                            "bbox": t["bbox"],
                            "score_column_boxes": [
                                c["bbox"] for c in t["cells"] if c["col"] == t["col_count"] - 1
                            ],
                        }
                        for t in tables
                    ],
                }
            )
    return results


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    base = Path("D:/AgentAI/OCOP-RAG")
    selection = [("VN.OCOP.QD148.2023", n) for n in [23, 24, 28, 29]]
    res = evaluate_table_rules(root, base, selection)
    print(json.dumps(res, indent=2))
