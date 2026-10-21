"""OCR dataset and Markdown edits preserve source-owned geometry."""
import json

import pytest

from ocop_contracts.dataset import read_dataset
from ocop_ocr.review import create_dataset, export_markdown, import_markdown


@pytest.fixture
def dataset(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    page = {"source_id": "TEST", "source_sha256": "a" * 64, "pdf_page": 1,
            "width_pt": 595, "height_pt": 842, "extracted_text": "Old text",
            "blocks": [{"text": "Old text", "bbox": [1, 2, 30, 40]}],
            "tables": [{"table_id": "t1", "bbox": [1, 50, 100, 100], "row_count": 1, "col_count": 2,
                        "cells": [{"row": 0, "col": 0, "text": "Criterion", "bbox": [1, 50, 80, 100]},
                                  {"row": 0, "col": 1, "text": "", "bbox": [80, 50, 100, 100]}]}],
            "review_status": "needs_review"}
    (raw / "one.jsonl").write_text(json.dumps(page) + "\n", encoding="utf-8")
    (raw / "manifest.json").write_text(json.dumps({"complete": True, "parser_version": "test",
        "sources": [{"source_id": "TEST", "source_sha256": "a" * 64,
                     "artifact": "one.jsonl", "page_count_expected": 1}]}), encoding="utf-8")
    output = tmp_path / "dataset"
    create_dataset(raw, output)
    export_markdown(output)
    return output, {"sources": [{"source_id": "TEST", "sha256": "a" * 64}]}


def test_export_edit_import_keeps_bbox_and_original_text(dataset):
    root, locked = dataset
    file = root / "review/TEST/p001.md"
    file.write_text(file.read_text(encoding="utf-8").replace("Old text", "Corrected text"), encoding="utf-8")
    import_markdown(root)
    manifest, pages = read_dataset(root, locked)
    assert pages[0]["blocks"][0]["text"] == "Corrected text"
    assert pages[0]["blocks"][0]["ocr_text"] == "Old text"
    assert pages[0]["blocks"][0]["bbox"] == [1, 2, 30, 40]
    assert manifest["da_duyet"] == 0
    assert len((root / "review/corrections.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    import_markdown(root)
    assert len((root / "review/corrections.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_no_edits_preserve_page_bytes(dataset):
    root, _ = dataset
    before = (root / "pages/TEST.jsonl").read_bytes()
    import_markdown(root)
    assert (root / "pages/TEST.jsonl").read_bytes() == before


def test_table_cell_edit_keeps_original_geometry_and_blank_text(dataset):
    root, locked = dataset
    file = root / "review/TEST/p001.md"
    file.write_text(file.read_text(encoding="utf-8").replace("<!-- blank -->", "10"), encoding="utf-8")
    import_markdown(root)
    _, pages = read_dataset(root, locked)
    cell = pages[0]["tables"][0]["cells"][1]
    assert cell["text"] == "10"
    assert cell["ocr_text"] == ""
    assert cell["bbox"] == [80, 50, 100, 100]
    assert cell["reviewed"] is False


def test_added_column_is_rejected_before_any_write(dataset):
    root, _ = dataset
    file = root / "review/TEST/p001.md"
    file.write_text(file.read_text(encoding="utf-8").replace("<!-- blank -->", "10 | extra"), encoding="utf-8")
    before = (root / "pages/TEST.jsonl").read_bytes()
    with pytest.raises(ValueError, match="row/column"):
        import_markdown(root)
    assert (root / "pages/TEST.jsonl").read_bytes() == before
    assert not (root / "review/corrections.jsonl").exists()


def test_marking_text_reviewed_does_not_verify_domain_facts(dataset):
    from ai_core.processing.ocop.knowledge_extract import page_units
    root, locked = dataset
    file = root / "review/TEST/p001.md"
    file.write_text(file.read_text(encoding="utf-8").replace('"chua_duyet"', 'da_duyet'), encoding="utf-8")
    import_markdown(root)
    manifest, pages = read_dataset(root, locked)
    assert manifest["da_duyet"] == 1
    units = page_units(pages[0])
    assert all(u["structured"]["text_reviewed"] is True for u in units)
    assert all(u["review_status"] != "verified" for u in units)


def test_invalid_markdown_does_not_append_corrections(dataset):
    root, _ = dataset
    file = root / "review/TEST/p001.md"
    file.write_text(file.read_text(encoding="utf-8") + "\nUnexpected block\n", encoding="utf-8")
    before = (root / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match=r"p001.md:\d+"):
        import_markdown(root)
    assert (root / "manifest.json").read_bytes() == before
    assert not (root / "review/corrections.jsonl").exists()


def test_changed_ocr_hash_rejects_edits(dataset):
    root, _ = dataset
    file = root / "review/TEST/p001.md"
    text = file.read_text(encoding="utf-8").replace("Old text", "New")
    lines = text.splitlines()
    lines = ['ocr_hash: "wrong"' if line.startswith("ocr_hash:") else line for line in lines]
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ocr_hash"):
        import_markdown(root)


def test_interrupted_import_recovers_without_duplicate_ledger_entries(dataset, monkeypatch):
    from ocop_ocr import review
    root, locked = dataset
    file = root / "review/TEST/p001.md"
    file.write_text(file.read_text(encoding="utf-8").replace("Old text", "Recovered"), encoding="utf-8")
    real_write = review._jsonl
    def fail_write(*args, **kwargs):
        raise OSError("simulated disk interruption after ledger append")
    monkeypatch.setattr(review, "_jsonl", fail_write)
    with pytest.raises(OSError, match="interruption"):
        import_markdown(root)
    with pytest.raises(ValueError, match="interrupted"):
        read_dataset(root, locked)
    monkeypatch.setattr(review, "_jsonl", real_write)
    import_markdown(root)
    _, pages = read_dataset(root, locked)
    assert pages[0]["blocks"][0]["text"] == "Recovered"
    assert len((root / "review/corrections.jsonl").read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize("field,value", [("complete", False), ("schema_version", 99)])
def test_rag_reader_rejects_incomplete_or_unknown_schema(dataset, field, value):
    root, locked = dataset
    file = root / "manifest.json"
    manifest = json.loads(file.read_text(encoding="utf-8"))
    manifest[field] = value
    file.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        read_dataset(root, locked)
