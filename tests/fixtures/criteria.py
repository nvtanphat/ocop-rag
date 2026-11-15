"""Small synthetic criterion sheets, including cross-page score candidates."""

from tests.fixtures.legal import unit as unit, extract as extract


def table(page, rows):
    u = unit(
        "DOC.CURRENT",
        page,
        "\n".join(f"{label} | {score}" for label, score in rows),
        "criterion_table_candidate",
    )
    cells = []
    for row, (label, score) in enumerate(rows):
        for col, value in enumerate((label, str(score))):
            cells.append(
                {
                    "row": row,
                    "col": col,
                    "text": value,
                    "bbox": [col * 300, row * 20, col * 300 + 300, row * 20 + 20],
                }
            )
    u["structured"] = {"table_id": f"table:{page}", "cells": cells, "col_count": 2, "row_count": len(rows)}
    u["spans"][0]["table_id"] = f"table:{page}"
    return u


def fixture(high=40, continuity=True):
    groups = unit(
        "DOC.CURRENT",
        1,
        "Điều 2. Sản phẩm\n2. Có 06 nhóm sản phẩm: Thực phẩm; nhóm hai; nhóm ba; nhóm bốn; nhóm năm; nhóm sáu. Danh mục kèm theo.",
    )
    reference = unit(
        "DOC.CURRENT",
        1,
        "Điều 3. Bộ tiêu chí\n1. Phần A: Nội dung (40 điểm); Phần B: Nội dung (25 điểm); Phần C: Nội dung (35 điểm).\n3. Tổng điểm tối đa là 100 điểm.",
    )
    reference["unit_id"] += ":reference"
    index = table(
        2, [(str(n), f"Bộ sản phẩm: {'Ví dụ' if n == 1 else f'Dạng thử {n}'}") for n in range(1, 27)]
    )
    header = unit(
        "DOC.CURRENT",
        3,
        "1. Bộ sản phẩm: Ví dụ\n(Sản phẩm: Thực phẩm. Nhóm: Thực phẩm tươi sống)",
        "paragraph",
    )
    first = table(
        3,
        [
            ("Phần A: SẢN PHẨM", 40),
            ("1. TỔ CHỨC SẢN XUẤT (Nội dung giải thích trong cùng ô)", 40),
            ("1.1, Tiêu chí", 40),
            ("Chỉ áp dụng khi đủ điều kiện", ""),
            ("Ghị chủ: Nội dung giải thích", ""),
            ("Phương án thấp", 20),
        ],
    )
    second = table(
        4,
        [
            ("Phương án cao", high),
            ("Phần B: TIẾP THỊ", 25),
            ("2, TIẾP THỊ", 25),
            ("2.1. Tiêu chí", 25),
            ("Phương án tiếp thị", 25),
            ("Phần C: CHẤT LƯỢNG", 35),
            ("3. CHẤT LƯỢNG", 35),
            ("3.1.Tiêu chí", 35),
            ("Tốt", 35),
        ],
    )
    if continuity:
        second["structured"]["table_continuity"] = [
            {"from_pdf_page": 3, "to_pdf_page": 4, "from_table_id": "table:3", "to_table_id": "table:4"}
        ]
    return [groups, reference, index, unit("DOC.CURRENT", 3, "PHỤ LỤC II", "annex"), header, first, second]
