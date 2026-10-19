from ai_core.retrieval.ocop.structure_chunker import plan_chunks


def _cell(row, col, text, **extra):
    return {"row": row, "col": col, "text": text,
            "bbox": [col * 100, row * 20, (col + 1) * 100, (row + 1) * 20], **extra}


def _table(cells):
    return {
        "unit_id": "unit:table",
        "source_id": "VN.TEST.RECOGNITION",
        "unit_kind": "table",
        "review_status": "needs_review",
        "text": "table rows",
        "spans": [{"pdf_page": 3, "bbox": [0, 0, 400, 200],
                   "source_sha256": "a" * 64, "table_id": "table:test"}],
        "structured": {"table_id": "table:test", "cells": cells},
    }


def test_infers_wrapped_table_header_from_multiple_header_cells():
    unit = _table([
        _cell(0, 0, "TT"), _cell(0, 1, "Tên sản\nphẩm"),
        _cell(0, 2, "Tên chủ thể"), _cell(0, 3, "Phân hạng"),
        _cell(1, 0, "1"), _cell(1, 1, "Mứt Atiso đỏ"),
        _cell(1, 2, "Công ty Hichagol"), _cell(1, 3, "4 sao"),
    ])

    chunks = plan_chunks(unit)

    assert len(chunks) == 1
    assert chunks[0].header_inferred is True
    assert chunks[0].row_ids == (1,)
    assert "Tên sản" in chunks[0].text and "phẩm" in chunks[0].text
    assert "Mứt Atiso đỏ" in chunks[0].text
    assert "TT | Tên sản" not in chunks[0].raw_text


def test_infers_common_tt_and_measurement_headers():
    unit = _table([
        _cell(0, 0, "TT"), _cell(0, 1, "Đơn vị đo"),
        _cell(0, 2, "Cách thể hiện"),
        _cell(1, 0, "1"), _cell(1, 1, "Khối lượng"),
        _cell(1, 2, "Kilôgam, gam"),
    ])

    chunks = plan_chunks(unit)

    assert len(chunks) == 1 and chunks[0].header_inferred is True
    assert chunks[0].row_ids == (1,)
    assert "Đơn vị đo: Khối lượng" in chunks[0].text
    assert "Cách thể hiện: Kilôgam, gam" in chunks[0].text


def test_infers_tt_header_when_other_cells_have_column_labels():
    unit = _table([
        _cell(0, 0, "TT"), _cell(0, 1, "Nội dung"),
        _cell(0, 2, "Kiểm tra thường"),
        _cell(1, 0, "1"), _cell(1, 1, "Mặt hàng"),
        _cell(1, 2, "Đạt"),
    ])

    assert plan_chunks(unit)[0].header_inferred is True


def test_finds_header_after_a_form_preface_row():
    unit = _table([
        _cell(0, 0, "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"),
        _cell(0, 1, "Số: ........ ngày ....."),
        _cell(1, 0, "STT"), _cell(1, 1, "Tên sản phẩm"),
        _cell(1, 2, "Số, ký hiệu của giấy tiếp nhận"),
        _cell(2, 0, "1"), _cell(2, 1, "Mứt Atiso đỏ"),
        _cell(2, 2, "Số 123"),
    ])

    chunks = plan_chunks(unit)

    assert len(chunks) == 1 and chunks[0].header_inferred is True
    assert chunks[0].table_headers[0].startswith("STT | Tên sản phẩm")
    assert chunks[0].row_ids == (0, 2)
    assert any(span.get("cell_id") == "table:test:r1:c1" for span in chunks[0].spans)


def test_finds_form_header_when_ocr_splits_a_header_cell():
    unit = _table([
        _cell(0, 0, "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"),
        _cell(0, 1, "Số: ........ ngày ....."),
        _cell(1, 0, "STT"), _cell(1, 1, "Tên sả"), _cell(1, 2, "n"),
        _cell(1, 3, "Số, ký hiệu của giấy tiếp nhận"),
        _cell(2, 0, "1"), _cell(2, 1, "Mứt Atiso đỏ"),
        _cell(2, 2, ""), _cell(2, 3, "Số 123"),
    ])

    chunks = plan_chunks(unit)

    assert chunks[0].header_inferred is True
    assert chunks[0].table_headers[0].startswith("STT | Tên sả")
    assert 1 not in chunks[0].row_ids


def test_table_chunk_ends_before_a_new_merged_row_group():
    unit = _table([
        _cell(0, 0, "STT", is_header=True),
        _cell(0, 1, "Tổ chức/cá nhân", is_header=True),
        _cell(0, 2, "Sản phẩm", is_header=True),
        _cell(1, 0, "1"), _cell(1, 1, "Công ty Quang Hải", rowspan=4),
        _cell(1, 2, "Nước mắm A"),
        _cell(2, 0, "2"), _cell(2, 2, "Nước mắm B"),
        _cell(3, 0, "3"), _cell(3, 2, "Nước mắm C"),
        _cell(4, 0, "4"), _cell(4, 2, "Nước mắm D"),
        _cell(5, 0, "5"), _cell(5, 1, "Công ty Song Hải", rowspan=2),
        _cell(5, 2, "Nước mắm E"),
        _cell(6, 0, "6"), _cell(6, 2, "Nước mắm F"),
    ])

    chunks = plan_chunks(unit)

    assert [chunk.row_ids for chunk in chunks] == [(1, 2, 3, 4), (5, 6)]
    assert "Nước mắm E" not in chunks[0].text
    assert "Tổ chức/cá nhân: Công ty Quang Hải" in chunks[0].text
    assert "Tổ chức/cá nhân: Công ty Song Hải" in chunks[1].text
    assert any(span.get("cell_id") == "table:test:r1:c1" for span in chunks[0].spans)
    assert any(span.get("cell_id") == "table:test:r5:c1" for span in chunks[1].spans)


def test_legal_prose_chunk_starts_next_clause_without_cross_clause_overlap():
    clause_one = " ".join(["cơ quan quản lý thực hiện kiểm tra an toàn thực phẩm"] * 3)
    clause_two = " ".join(["cơ quan nước xuất khẩu gửi hồ sơ đăng ký"] * 3)
    unit = {
        "unit_id": "unit:article",
        "source_id": "VN.TEST.LAW",
        "unit_kind": "article",
        "text": f"Điều 22. Thủ tục\n1. {clause_one}.\n2. {clause_two}.",
        "spans": [{"pdf_page": 18, "bbox": [0, 0, 500, 700],
                   "source_sha256": "b" * 64, "block_id": "native:0"}],
    }

    chunks = plan_chunks(unit, token_budget=64, counter=lambda text: len(text.split()))

    assert len(chunks) >= 2
    assert chunks[0].raw_text.rstrip().endswith(".")
    assert chunks[1].raw_text.lstrip().startswith("2.")
    assert chunks[1].char_start == unit["text"].index("\n2.") + 1
