"""A complete synthetic native-PDF corpus; never used as OCOP domain truth."""

import json
from pathlib import Path

import fitz

from ocop_contracts.registry import load_registry, snapshot


def create_native_corpus(root: Path) -> Path:
    (root / "configs").mkdir()
    pdf = root / "data/raw/ocop/reference.pdf"
    pdf.parent.mkdir(parents=True)
    with fitz.open() as document:
        page = document.new_page()
        for row in range(18):
            page.insert_text((40, 60 + row * 24), "OCOP program registration requires product evidence.")
        document.save(pdf)
    registry = root / "configs/ocop_sources.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sources": [
                    {
                        "source_id": "SYNTHETIC.OCOP.REFERENCE",
                        "path": "data/raw/ocop/reference.pdf",
                        "source_kind": "ocop_framework",
                        "document_number": "REFERENCE",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "configs/ocop_sources.lock.json").write_text(
        json.dumps(snapshot(root, load_registry(registry))), encoding="utf-8"
    )
    return pdf
