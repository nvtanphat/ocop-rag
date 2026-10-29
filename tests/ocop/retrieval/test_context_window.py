"""Prompt excerpts: question-aware windows, column labels and merged-cell inheritance."""

from ai_core.orchestration.ocop.context import ELLIPSIS, render_row, select_window
from ai_core.retrieval.ocop.settings import get_settings


def test_window_keeps_whole_lines_around_question_terms_and_marks_cuts():
    text = (
        "\n".join(f"Dòng {i} nội dung chung" for i in range(40))
        + "\nHội đồng gồm Bộ Y tế và Bộ Khoa học\n"
        + "\n".join(f"Hậu {i} nội dung chung" for i in range(40))
    )
    window, left, right = select_window(text, ["hoi", "dong", "bo", "y", "khoa", "hoc"], 300)
    assert "Bộ Y tế" in window and left and right and len(window) <= 300
    assert all(line.startswith(("Dòng", "Hậu", "Hội")) for line in window.splitlines())  # no mid-line cut


def _cell(row, col, text, rowspan=1):
    return {"row": row, "col": col, "text": text, "rowspan": rowspan}


def test_table_row_carries_column_labels_and_the_covering_merged_cell():
    cells = [
        _cell(0, 0, "STT"),
        _cell(0, 1, "Tổ chức/cá nhân"),
        _cell(0, 2, "Sản phẩm"),
        _cell(1, 0, "1"),
        _cell(1, 1, "HTX Alpha", rowspan=3),
        _cell(1, 2, "Gạo A"),
        _cell(2, 0, "2"),
        _cell(2, 2, "Gạo B"),
        _cell(3, 0, "3"),
        _cell(3, 2, "Gạo C"),
    ]
    row = {
        "raw_text": "2 | Gạo B",
        "structured": {"cells": cells},
        "source_spans": [{"pdf_page": 3, "row": 2, "table_id": "t"}],
        "context": {"table_id": "t"},
    }
    excerpt = render_row(row, ["gao"], get_settings().context, table_backed=True)
    assert "Tổ chức/cá nhân: HTX Alpha" in excerpt.evidence and "Sản phẩm: Gạo B" in excerpt.evidence
    assert "Gạo A" not in excerpt.evidence and ELLIPSIS not in excerpt.evidence


def test_parent_chain_is_a_separate_short_line_not_part_of_the_evidence():
    row = {
        "raw_text": "Nội dung điều khoản.",
        "context": {"parent_chain": ["Điều 7. Hội đồng"]},
        "source_spans": [{"pdf_page": 1}],
    }
    excerpt = render_row(row, ["noi"], get_settings().context, table_backed=False)
    assert (
        excerpt.display.startswith("Ngữ cảnh: Điều 7. Hội đồng")
        and excerpt.evidence == "Nội dung điều khoản."
    )


def _chunk(cid, text, start, end, **extra):
    return {
        "chunk_id": cid,
        "evidence_unit_id": "U",
        "source_id": "D",
        "review_status": "verified",
        "text": text,
        "raw_text": text,
        "char_start": start,
        "char_end": end,
        "source_spans": [{"pdf_page": 7, "bbox": [0, 0, 1, 1]}],
        **extra,
    }


def test_continuation_chunk_is_merged_into_one_passage_without_duplicating_the_overlap():
    from ai_core.orchestration.ocop.answer import assemble

    full = "Thành viên gồm Bộ Công Thương, Bộ Văn hoá, Thể thao và Du lịch, đại diện cơ quan tham mưu."
    first = _chunk("c1", full[:54], 0, 54)
    second = _chunk(
        "c2", full[46:], 46, len(full), continues_chunk="c1"
    )  # overlaps the first chunk by 8 characters
    out = assemble(
        "Thành viên hội đồng gồm những ai?",
        [{"tool": "search_regulations", "output": {"results": [first, second]}}],
    )
    assert len(out["citations"]) == 1
    assert "Bộ Văn hoá, Thể thao và Du lịch, đại diện cơ quan tham mưu." in out["answer"]
    assert "và Thể thao và" not in out["answer"]


def test_repeated_text_on_the_same_page_is_shown_once_and_blocks_are_capped():
    from ai_core.orchestration.ocop.answer import assemble

    rows = [
        dict(_chunk(f"r{i}", "Điều 7. Trình tự đánh giá", 0, 25), chunk_id=f"r{i}", evidence_unit_id=f"U{i}")
        for i in range(6)
    ]
    rows += [
        dict(_chunk(f"x{i}", f"Nội dung riêng số {i} về hội đồng", 0, 30), evidence_unit_id=f"X{i}")
        for i in range(30)
    ]
    out = assemble(
        "trình tự đánh giá hội đồng?", [{"tool": "search_regulations", "output": {"results": rows}}]
    )
    assert sum("Điều 7. Trình tự đánh giá" in c for c in [out["answer"]]) == 1
    from ai_core.retrieval.ocop.settings import get_settings

    assert len(out["citations"]) <= get_settings().context.max_source_blocks


def _entry(text, page, table_id=None):
    span = {"pdf_page": page, **({"table_id": table_id} if table_id else {})}
    return ((f"doc{page}", page, f"u{page}", None), {"raw_text": text}, span, bool(table_id))


def test_rare_entity_term_outweighs_generic_question_words():
    from ai_core.orchestration.ocop.answer import _most_relevant

    generic = [_entry("quyết định cơ quan ban hành hội đồng", p) for p in range(1, 7)]
    product = _entry("Gạo giống HANA", 9)
    kept = _most_relevant([*generic, product], ["hana", "quyet", "dinh", "co", "quan", "ban", "hanh"], 3)
    assert product in kept


def test_returned_table_siblings_travel_with_the_chosen_row():
    from ai_core.orchestration.ocop.answer import _most_relevant

    generic = [_entry("quyết định cơ quan ban hành", p) for p in range(1, 6)]
    row = _entry("Gạo giống HANA", 9, "t1")
    owner = _entry("Hợp tác xã Thụy Hương", 9, "t1")
    kept = _most_relevant([*generic, row, owner], ["hana", "quyet", "dinh", "co", "quan"], 2)
    assert row in kept and owner in kept


def test_the_kind_of_document_a_question_points_at_is_not_a_term_to_find_in_the_passage():
    from ai_core.orchestration.ocop.context import question_terms

    assert question_terms("Điều 2 Quyết định 525 quy định gì?") == []
    assert question_terms("Quyết định về nhãn hàng hóa là gì?") == ["nhan", "hang", "hoa"]
