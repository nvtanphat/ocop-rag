"""Page units: merged line fragments keep block spans, table text is not duplicated, blank score cells show candidates."""

from ai_core.processing.ocop.knowledge_extract import page_units
from ocop_contracts.layout import join_blocks_by_line
from ai_core.retrieval.ocop.index_pipeline import build_chunks


def _block(block_id, text, bbox):
    return {"block_id": block_id, "text": text, "bbox": bbox}


def _page(blocks, tables=()):
    return {
        "source_id": "VN.TEST.QD26.2026",
        "pdf_page": 29,
        "source_sha256": "a" * 64,
        "extracted_text": join_blocks_by_line(blocks),
        "blocks": blocks,
        "tables": list(tables),
        "width_pt": 600,
        "height_pt": 800,
        "review_status": "needs_review",
    }


def test_merged_line_fragments_keep_every_block_span():
    blocks = [
        _block("b0", "Công tác đánh", [10, 10, 100, 30]),
        _block("b1", "giá, phân hạng", [100, 10, 200, 30]),
        _block("b2", "Dòng kế tiếp", [10, 40, 120, 60]),
    ]
    unit = next(u for u in page_units(_page(blocks)) if u["unit_kind"] == "paragraph")
    assert "Công tác đánh giá, phân hạng" in unit["text"]
    assert [s["block_id"] for s in unit["spans"]] == ["b0", "b1", "b2"]
    assert all(s["bbox"] is not None for s in unit["spans"])


def _table_page(score_cell):
    blocks = [
        _block("n", "13", [300, 5, 320, 20]),
        _block("c0", "Có hồ sơ môi trường", [20, 100, 380, 130]),
        _block("c1", "Không rõ nội dung", [20, 140, 380, 170]),
    ]
    cells = [
        {"row": 0, "col": 0, "bbox": [20, 100, 400, 130], "text": "Có hồ sơ môi trường"},
        {"row": 0, "col": 1, "bbox": [400, 100, 500, 130], "text": "2"},
        {"row": 1, "col": 0, "bbox": [20, 140, 400, 170], "text": "Khác hẳn"},
        {"row": 1, "col": 1, "bbox": [400, 140, 500, 170], **score_cell},
    ]
    return _page(blocks, [{"table_id": "t0", "bbox": [10, 90, 510, 180], "cells": cells}])


def test_text_already_in_table_cells_is_not_duplicated_as_paragraph():
    units = page_units(_table_page({"text": "1"}))
    paragraph = " ".join(u["text"] for u in units if u["unit_kind"] == "paragraph")
    assert "13" not in paragraph
    assert "Không rõ nội dung" in paragraph  # not found in any cell, so it is kept
    table = next(u for u in units if u["unit_kind"] == "table")
    assert "Có hồ sơ môi trường | 2" in table["text"]


def test_near_matching_ocr_block_inside_table_is_not_duplicated_as_paragraph():
    block = _block("b-ocr", "minh chứng về công trình thu gom và xử ly chất thải", [20, 110, 380, 128])
    table = {
        "table_id": "t-ocr",
        "bbox": [10, 90, 510, 180],
        "cells": [
            {
                "row": 0,
                "col": 0,
                "bbox": [20, 100, 400, 140],
                "text": "Có hồ sơ minh chứng về công trình thu gom và xử lý chất thải",
            },
        ],
    }
    units = page_units(_page([block], [table]))
    paragraph = " ".join(u["text"] for u in units if u["unit_kind"] == "paragraph")

    assert "minh chứng về công trình thu gom" not in paragraph
    assert any("xử lý chất thải" in unit["text"] for unit in units if unit["unit_kind"] == "table")


def test_blank_score_cell_exposes_candidate_as_unverified():
    cell = {"text": "", "score_ocr_candidates": [{"text": "0", "candidate_only": True}]}
    units = page_units(_table_page(cell))
    table = next(u for u in units if u["unit_kind"] == "table")
    assert "[ứng viên OCR chưa xác minh: 0]" in table["text"]
    chunks = [c for c in build_chunks(units, "scratch") if c["evidence_unit_id"] == table["unit_id"]]
    assert any("ứng viên OCR chưa xác minh: 0" in c["text_for_bm25"] for c in chunks)
    assert table["structured"]["cells"][-1]["text"] == ""


def test_rowspan_cells_are_inherited_by_covered_rows_in_chunk_text():
    cells = [
        {"row": 0, "col": 0, "text": "STT", "is_header": True},
        {"row": 0, "col": 1, "text": "Chủ thể", "is_header": True},
        {"row": 0, "col": 2, "text": "Sản phẩm", "is_header": True},
        {"row": 1, "col": 0, "text": "1"},
        {"row": 1, "col": 1, "text": "Công ty Quang Hải", "rowspan": 2},
        {"row": 1, "col": 2, "text": "Nước mắm A"},
        {"row": 2, "col": 0, "text": "2"},
        {"row": 2, "col": 2, "text": "Nước mắm B"},
    ]
    page = _page(
        [_block("n", "9", [1, 1, 5, 5])], [{"table_id": "t0", "bbox": [0, 0, 100, 100], "cells": cells}]
    )
    units = page_units(page)
    table = next(u for u in units if u["unit_kind"] == "table")
    chunk = next(c for c in build_chunks(units, "scratch") if c["evidence_unit_id"] == table["unit_id"])
    assert "STT: 2 | Chủ thể: Công ty Quang Hải | Sản phẩm: Nước mắm B" in chunk["text_for_bm25"]
    assert any(s.get("cell_id") == "t0:r1:c1" for s in chunk["spans"])


def test_blank_cell_without_candidate_keeps_explicit_unverified_placeholder():
    units = page_units(_table_page({"text": ""}))
    table = next(u for u in units if u["unit_kind"] == "table")
    assert "[ứng viên OCR chưa xác minh: ]" in table["text"]
    chunks = [c for c in build_chunks(units, "scratch") if c["evidence_unit_id"] == table["unit_id"]]
    assert any("[ứng viên OCR chưa xác minh: ]" in c["text_for_bm25"] for c in chunks)


def test_margin_page_number_and_distribution_block_are_separate_units():
    blocks = [
        _block("page-number", "13", [300, 5, 315, 20]),
        _block("article", "Điều 3. Các cơ quan chịu trách nhiệm thi hành Quyết định.", [50, 200, 350, 220]),
        _block("recipient", "Ban Bí thư Trung ương Đảng;", [50, 340, 280, 360]),
        _block("marker", "Nơi nhận:", [50, 312, 120, 327]),
        _block("signature", "THỦ TƯỚNG", [430, 309, 530, 330]),
    ]
    units = page_units(_page(blocks))
    body = " ".join(u["text"] for u in units if u["unit_kind"] in ("article", "paragraph"))
    root = units[0]
    furniture = root["structured"]["page_furniture"]
    furniture_text = " ".join(item["text"] for item in furniture)
    assert all(block["text"] in furniture_text for block in (blocks[0], blocks[2], blocks[3], blocks[4]))
    assert all(block["text"] not in body for block in (blocks[0], blocks[2], blocks[3], blocks[4]))
    assert all(item.get("bbox") for item in furniture)
    assert root["spans"][0].get("source_sha256") == "a" * 64 and root["spans"][0].get("bbox")
