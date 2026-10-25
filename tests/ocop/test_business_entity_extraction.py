"""Evidence-bound semantic extraction contracts, independent of OCR models."""

from __future__ import annotations
import fitz
from pathlib import Path
from ocop_ocr.table_parser import native_tables
from ai_core.processing.ocop.business_candidates import candidates
from ai_core.knowledge.ocop.extractor import extract_semantics


def _recognition_fixture():
    # One explicit two-row rowspan, two products. No row-order guessing allowed.
    cells = [
        {"row": 0, "col": 0, "text": "STT", "bbox": [0, 0, 10, 10]},
        {"row": 0, "col": 1, "text": "Tổ chức/cá nhân", "bbox": [10, 0, 80, 10]},
        {"row": 0, "col": 2, "text": "Sản phẩm", "bbox": [80, 0, 200, 10]},
        {"row": 0, "col": 3, "text": "Địa chỉ", "bbox": [200, 0, 260, 10]},
        {"row": 0, "col": 4, "text": "Chủ thể", "bbox": [260, 0, 320, 10]},
        {"row": 0, "col": 5, "text": "Điểm đánh giá", "bbox": [320, 0, 360, 10]},
        {"row": 0, "col": 6, "text": "Xếp loại", "bbox": [360, 0, 400, 10]},
        {"row": 1, "col": 0, "text": "1", "bbox": [0, 10, 10, 20]},
        {
            "row": 1,
            "col": 1,
            "text": "HTX Sen Huế",
            "rowspan": 2,
            "bbox": [10, 10, 80, 30],
            "merged_extent_unknown": False,
        },
        {"row": 1, "col": 2, "text": "Hạt sen", "bbox": [80, 10, 200, 20]},
        {
            "row": 1,
            "col": 3,
            "text": "Thôn A",
            "rowspan": 2,
            "bbox": [200, 10, 260, 30],
            "merged_extent_unknown": False,
        },
        {
            "row": 1,
            "col": 4,
            "text": "Nguyễn An",
            "rowspan": 2,
            "bbox": [260, 10, 320, 30],
            "merged_extent_unknown": False,
        },
        {"row": 1, "col": 5, "text": "83,8", "bbox": [320, 10, 360, 20]},
        {"row": 1, "col": 6, "text": "4 sao", "bbox": [360, 10, 400, 20]},
        {"row": 2, "col": 0, "text": "2", "bbox": [0, 20, 10, 30]},
        {"row": 2, "col": 2, "text": "Trà sen", "bbox": [80, 20, 200, 30]},
        {"row": 2, "col": 5, "text": "84,1", "bbox": [320, 20, 360, 30]},
        {"row": 2, "col": 6, "text": "4 sao", "bbox": [360, 20, 400, 30]},
    ]
    return {
        "unit_id": "unit:table:0001",
        "source_id": "LOCAL.UNKNOWN.DECISION",
        "unit_kind": "table",
        "text": "STT | Tổ chức/cá nhân | Sản phẩm | Địa chỉ | Chủ thể | Điểm đánh giá | Xếp loại\n"
        "1 | HTX Sen Huế | Hạt sen | Thôn A | Nguyễn An | 83,8 | 4 sao\n"
        "2 | Trà sen | 84,1 | 4 sao",
        "spans": [{"pdf_page": 3, "table_id": "table:native:0", "bbox": [0, 0, 400, 30]}],
        "structured": {"table_id": "table:native:0", "cells": cells},
    }


def test_merged_rowspan_is_provenance_bound_not_last_seen():
    from ai_core.processing.ocop.business_candidates import _row_text

    unit = _recognition_fixture()
    rows = _row_text(unit["structured"]["cells"])
    assert rows[2]["resolved_columns"]["1"]["text"] == "HTX Sen Huế"
    assert rows[2]["resolved_columns"]["1"]["row"] == 1
    assert rows[2]["resolved_columns"]["1"]["inherited"]
    owner_cell = next(c for c in unit["structured"]["cells"] if c["row"] == 1 and c["col"] == 1)
    owner_cell.pop("rowspan")
    rows = _row_text(unit["structured"]["cells"])
    assert "1" not in rows[2]["resolved_columns"]


def test_recognition_continuation_uses_adjacent_header_but_not_missing_owner():
    from copy import deepcopy

    header = _recognition_fixture()
    continuation = deepcopy(header)
    continuation["unit_id"] = "unit:continuation"
    continuation["spans"][0]["pdf_page"] = 4
    continuation["structured"]["table_id"] = "table:next"
    continuation["structured"]["cells"] = [c for c in continuation["structured"]["cells"] if c["row"] == 1]
    continuation["text"] = "1 | HTX Sen Huế | Hạt sen | Thôn A | Nguyễn An | 83,8 | 4 sao"
    kinds = {header["source_id"]: "recognition_decision"}
    rows = candidates([header, continuation], kinds)["recognition_candidates"]
    match = next(r for r in rows if r["evidence_unit_id"] == "unit:continuation")
    assert match["producer_candidate"] == "HTX Sen Huế" and match["product_candidate"] == "Hạt sen"
    continuation["spans"][0]["pdf_page"] = 6
    rows = candidates([header, continuation], kinds)["recognition_candidates"]
    assert next(r for r in rows if r["evidence_unit_id"] == "unit:continuation")["producer_candidate"] is None


def test_header_grounded_recognition_inherited_owner_with_proof():
    unit = _recognition_fixture()
    sid = unit["source_id"]
    unit["source_id"] = sid
    kind = {sid: "recognition_decision"}
    extract = candidates([unit], kind)
    result = extract_semantics([unit], kind, extract)
    products = [r["label"] for r in result["business_entities"] if r["kind"] == "Product"]
    assert sorted(products) == ["Hạt sen", "Trà sen"]
    row2 = next(r for r in extract["recognition_candidates"] if r["row"] == 2)
    assert row2["layout_columns"] == {
        "sequence": 0,
        "producer": 1,
        "product": 2,
        "address": 3,
        "representative": 4,
        "score": 5,
        "star": 6,
    }
    assert row2["score_candidate"] == "84,1" and row2["star_candidate"] == 4
    header = next(r for r in extract["recognition_candidates"] if r["row"] == 0)
    assert header["score_candidate"] is None and header["producer_candidate"] is None
    records = [r for r in result["business_entities"] if r["kind"] == "RecognitionRecord"]
    assert len(records) == 2
    assert any(r["attributes"]["owner_inherited_from_merge"] for r in records)
    inherited_record = next(r for r in records if r["attributes"]["row_number"] == "2")
    assert inherited_record["attributes"]["score_candidate"] == "84,1"
    assert inherited_record["attributes"]["star_rating_candidate"] == 4
    assert inherited_record["attributes"]["producer_address_candidate"] == "Thôn A"
    assert inherited_record["attributes"]["representative_candidate"] == "Nguyễn An"
    assert all(r["status"] == "candidate" for r in records)
    owners = [r for r in result["business_entities"] if r["kind"] == "Organization"]
    assert len(owners) == 1 and len(owners[0]["evidence"]) == 1
    assert owners[0]["evidence"][0]["cell_id"] == "table:native:0:r1:c1"
    assert owners[0]["evidence"][0]["bbox"] == [10, 10, 80, 30]
    links = [r for r in result["business_relations"] if r["relation_type"] == "DECLARED_BY"]
    assert len(links) == 2 and all(len(r["evidence"]) == 2 for r in links)
    assert all(any(e["cell_id"] == "table:native:0:r1:c1" for e in r["evidence"]) for r in links)


def test_hue_recognition_layout_is_inferred_from_its_header():
    sid = "LOCAL.ANOTHER-REGION.DECISION"
    cells = []
    header = ["TT", "Tên sản phẩm", "Tên chủ thể", "Địa chỉ", "Phân hạng"]
    row = ["1", "Mứt Atiso đỏ", "HTX Hoa Huế", "Phường Phong Thái", "4 sao"]
    for col, text in enumerate(header):
        cells.append({"row": 0, "col": col, "text": text, "bbox": [col * 80, 0, (col + 1) * 80, 10]})
    for col, text in enumerate(row):
        cells.append({"row": 1, "col": col, "text": text, "bbox": [col * 80, 10, (col + 1) * 80, 20]})
    unit = {
        "unit_id": "unit:hue:1",
        "source_id": sid,
        "unit_kind": "table",
        "text": "TT | Tên sản phẩm | Tên chủ thể | Địa chỉ | Phân hạng\n1 | Mứt Atiso đỏ | HTX Hoa Huế | Phường Phong Thái | 4 sao",
        "spans": [{"pdf_page": 1, "table_id": "table:hue:0", "bbox": [0, 0, 400, 20]}],
        "structured": {"table_id": "table:hue:0", "cells": cells},
    }
    layer = candidates([unit], {sid: "recognition_decision"})
    result = extract_semantics([unit], {sid: "recognition_decision"}, layer)
    assert layer["recognition_candidates"][1]["layout_columns"] == {
        "sequence": 0,
        "product": 1,
        "producer": 2,
        "address": 3,
        "star": 4,
    }
    assert [e["label"] for e in result["business_entities"] if e["kind"] == "Product"] == ["Mứt Atiso đỏ"]
    assert [e["label"] for e in result["business_entities"] if e["kind"] == "Organization"] == ["HTX Hoa Huế"]
    assert not any(e["attributes"].get("score_candidate") for e in result["business_entities"])


def test_recognition_without_unambiguous_header_is_not_mapped():
    sid = "LOCAL.NO-HEADER.DECISION"
    cells = [
        {"row": 0, "col": 0, "text": "STT", "bbox": [0, 0, 20, 10]},
        {"row": 0, "col": 1, "text": "Mô tả", "bbox": [20, 0, 100, 10]},
        {"row": 1, "col": 0, "text": "1", "bbox": [0, 10, 20, 20]},
        {"row": 1, "col": 1, "text": "Không rõ cột", "bbox": [20, 10, 100, 20]},
    ]
    unit = {
        "unit_id": "unit:unknown:1",
        "source_id": sid,
        "unit_kind": "table",
        "text": "STT | Mô tả\n1 | Không rõ cột",
        "spans": [{"pdf_page": 1, "table_id": "table:unknown:0", "bbox": [0, 0, 100, 20]}],
        "structured": {"table_id": "table:unknown:0", "cells": cells},
    }
    layer = candidates([unit], {sid: "recognition_decision"})
    result = extract_semantics([unit], {sid: "recognition_decision"}, layer)
    assert all(not row["layout_columns"] for row in layer["recognition_candidates"])
    assert result["business_entities"] == [] and result["business_relations"] == []
    assert {"reason": "recognition_unknown_layout", "count": 2} in result["business_omissions"]


def test_scoring_candidates_are_never_verified():
    sid = "VN.OCOP.QD26.2026"
    unit = {
        "unit_id": "unit:score:0001",
        "source_id": sid,
        "unit_kind": "criterion_table_candidate",
        "text": "1.1. Chất lượng sản phẩm | 3\nCó chứng nhận hợp lệ *** | 2",
        "spans": [{"pdf_page": 20, "table_id": "table:1", "bbox": [0, 0, 100, 100]}],
        "structured": {
            "table_id": "table:1",
            "cells": [
                {"row": 0, "col": 0, "text": "1.1. Chất lượng sản phẩm", "bbox": [0, 0, 80, 40]},
                {"row": 0, "col": 1, "text": "3", "bbox": [80, 0, 100, 40]},
                {"row": 1, "col": 0, "text": "Có chứng nhận hợp lệ ***", "bbox": [0, 40, 80, 80]},
                {"row": 1, "col": 1, "text": "2", "bbox": [80, 40, 100, 80]},
            ],
        },
    }
    c = candidates([unit], {sid: "ocop_framework"})
    s = extract_semantics([unit], {sid: "ocop_framework"}, c)
    assert any(e["kind"] == "Criterion" for e in s["business_entities"])
    assert any(
        e["kind"] == "ScoreOption" and e["attributes"]["points_candidate"] == 2
        for e in s["business_entities"]
    )
    assert any(r["relation_type"] == "HAS_OPTION" for r in s["business_relations"])
    assert any(r["relation_type"] == "HAS_CONDITION" for r in s["business_relations"])
    assert all(e["status"] == "candidate" for e in s["business_entities"])
    assert all(r["status"] == "candidate" for r in s["business_relations"])
    assert all(not r["if_all"] and not r["consequence"] for r in s["business_rules"])


def test_wrapped_legal_rule_keeps_sentence_and_matching_bbox():
    from ai_core.knowledge.ocop.extractor import extract_semantics

    sid = "VN.ND.43.2017"
    text = (
        "Điều 11. Tên hàng hóa\n"
        "Tên hàng hóa phải ở vị trí dễ thấy, dễ đọc trên nhãn hàng hóa. Chữ viết tên\n"
        "hàng hóa phải là chữ có kích thước lớn nhất so với các nội dung bắt buộc khác trên\n"
        "nhãn hàng hóa."
    )
    lines = text.splitlines()
    spans = [
        {
            "pdf_page": 6,
            "bbox": [10 + i, 10 * i, 90 + i, 10 * i + 8],
            "block_id": f"native:0:{i}",
            "source_sha256": "a" * 64,
        }
        for i, _ in enumerate(lines)
    ]
    unit = {
        "unit_id": "unit:label-rule:1",
        "source_id": sid,
        "unit_kind": "article",
        "text": text,
        "spans": spans,
        "structured": {"heading": "Điều 11. Tên hàng hóa"},
    }
    result = extract_semantics([unit], {sid: "labeling_decree"}, {})
    rule = next(r for r in result["business_rules"] if r["kind"] == "obligation")
    expected = "\n".join(lines[1:])
    assert rule["statement"] == expected
    assert rule["evidence"][0]["quote"] == expected
    assert rule["evidence"][0]["bbox"] == [11.0, 10.0, 93.0, 38.0]
    assert rule["status"] == "candidate" and not rule["if_all"] and not rule["consequence"]


def test_native_table_row_coordinates_not_column_major():
    # Native text table with contrasting column coordinates.
    with fitz.open() as pdf:
        page = pdf.new_page(width=400, height=300)
        for y, row in enumerate([("STT", "Sản phẩm"), ("1", "Hạt sen"), ("2", "Cà phê")]):
            for x, txt in enumerate(row):
                page.insert_text((30 + x * 130, 50 + y * 40), txt)

        # Instead of depending on auto detector, simulate its table contract.
        class Row:
            def __init__(self, cells):
                self.cells = cells

        class Table:
            row_count = 2
            col_count = 2
            bbox = (20, 40, 300, 120)
            rows = [
                Row([(20, 40, 100, 70), (100, 40, 300, 70)]),
                Row([(20, 70, 100, 120), (100, 70, 300, 120)]),
            ]
            cells = [(20, 40, 100, 70), (20, 70, 100, 120), (100, 40, 300, 70), (100, 70, 300, 120)]

            def extract(self):
                return [["STT", "Sản phẩm"], ["1", "Hạt sen"]]

        class Finder:
            tables = [Table()]

        class Page:
            def find_tables(self, **kwargs):
                assert kwargs == {"strategy": "lines_strict"}
                return Finder()

        table = native_tables(Page())[0]
        assert table["cells"][1]["row"] == 0 and table["cells"][1]["col"] == 1
        assert table["cells"][1]["bbox"] == [100.0, 40.0, 300.0, 70.0]
        assert table["cells"][1]["text"] == "Sản phẩm"


def test_semantic_quality_does_not_promote_machine_candidates():
    from ai_core.knowledge.ocop.quality import audit_knowledge

    sid = "VN.OCOP.QD26.2026"
    unit = {"unit_id": "unit:1", "source_id": sid, "spans": [{"pdf_page": 20}]}
    ent = {
        "entity_id": "ent:1",
        "source_id": sid,
        "kind": "Criterion",
        "status": "candidate",
        "evidence": [{"evidence_unit_id": "unit:1", "source_id": sid, "pdf_page": 20, "quote": "a"}],
    }
    report = audit_knowledge(
        [unit], {"business_entities": [ent], "business_relations": [], "business_rules": []}
    )
    assert report["issues"] == {} and report["machine_verified_facts"] == 0
    assert report["manual_gold_required"]


def test_native_real_hai_phong_coordinates_and_rowspan():
    file = (
        Path(__file__).resolve().parents[2]
        / "data/raw/ocop/recognition_decisions/qd-cong-nhan-san-pham-ocop-2025-1-..signed639060091328998926.pdf"
    )
    if not file.is_file():
        return
    with fitz.open(file) as pdf:
        table = native_tables(pdf[2])[0]
    owner = next(c for c in table["cells"] if c["row"] == 1 and c["col"] == 1)
    product = next(c for c in table["cells"] if c["row"] == 1 and c["col"] == 2)
    assert owner["bbox"][0] < product["bbox"][0]
    assert owner["rowspan"] == 4
    assert owner["text"].startswith("Công ty Trách") and "Côngty" not in owner["text"]


def test_score_option_has_cell_level_pdf_provenance():
    sid = "VN.OCOP.QD26.2026"
    unit = {
        "unit_id": "unit:score:source",
        "source_id": sid,
        "unit_kind": "criterion_table_candidate",
        "text": "1.1. Chất lượng | 3\nCó tài liệu chứng minh | 2",
        "spans": [{"pdf_page": 18, "table_id": "t:1", "bbox": [0, 0, 100, 80]}],
        "structured": {
            "table_id": "t:1",
            "cells": [
                {"row": 0, "col": 0, "text": "1.1. Chất lượng", "bbox": [0, 0, 70, 40]},
                {"row": 0, "col": 1, "text": "3", "bbox": [70, 0, 100, 40]},
                {"row": 1, "col": 0, "text": "Có tài liệu chứng minh", "bbox": [0, 40, 70, 80]},
                {"row": 1, "col": 1, "text": "2", "bbox": [70, 40, 100, 80]},
            ],
        },
    }
    layer = extract_semantics([unit], {sid: "ocop_framework"}, candidates([unit], {sid: "ocop_framework"}))
    option = next(e for e in layer["business_entities"] if e["kind"] == "ScoreOption")
    assert len(option["evidence"]) == 2
    score_source = option["evidence"][1]
    assert score_source["quote"] == "2"
    assert score_source["bbox"] == [70.0, 40.0, 100.0, 80.0]
    assert score_source["pdf_page"] == 18 and score_source["cell_id"] == "t:1:r1:c1"
    assert option["status"] == "candidate"


def test_criterion_groups_unscored_options_and_image_markers():
    sid = "VN.OCOP.QD26.2026"
    rows = [
        ("2. PHÁT TRIỂN SẢN PHẨM", "10", None),
        ("2.1. Nguồn gốc ý tưởng sản phẩm", "3", None),
        ("Sản phẩm được trồng ở nhiều nơi trên địa bàn", "3", "****"),
        ("Ghi chú: Không đánh giá những sản phẩm phổ biến", "", None),
        ("3. SỨC MẠNH CỘNG ĐỒNG", "12", None),
        ("3.2. Đại diện pháp luật của chủ thể", "", None),
        ("Đại diện pháp luật của chủ thể không phải nữ", "", None),
    ]
    cells = []
    for i, (label, score, marker) in enumerate(rows):
        left = {"row": i, "col": 0, "text": label, "bbox": [0, i * 20, 80, i * 20 + 20]}
        if marker:
            left["image_marker_candidates"] = [
                {"text": marker, "candidate_only": True, "review_status": "needs_review"}
            ]
        right = {"row": i, "col": 1, "text": score, "bbox": [80, i * 20, 100, i * 20 + 20]}
        if i == 6:
            right["score_ocr_candidates"] = [{"text": "0", "confidence": 0.9, "candidate_only": True}]
        cells += [left, right]
    unit = {
        "unit_id": "unit:score:0002",
        "source_id": sid,
        "unit_kind": "criterion_table_candidate",
        "text": "\n".join(" | ".join(x for x in (label, score) if x) for label, score, _ in rows),
        "spans": [{"pdf_page": 29, "table_id": "table:1", "bbox": [0, 0, 100, 140]}],
        "structured": {"table_id": "table:1", "cells": cells},
    }
    s = extract_semantics([unit], {sid: "ocop_framework"}, candidates([unit], {sid: "ocop_framework"}))
    by_id = {e["entity_id"]: e for e in s["business_entities"]}
    edges = {
        (
            r["relation_type"],
            by_id[r["source_entity_id"]]["label"][:4],
            by_id[r["target_entity_id"]]["label"][:10],
        )
        for r in s["business_relations"]
    }
    assert ("HAS_SUBCRITERION", "2. P", "2.1. Nguồn") in edges
    assert ("HAS_SUBCRITERION", "3. S", "3.2. Đại d") in edges
    assert not any(
        t == "HAS_OPTION" and d.startswith(("2. P", "3. S")) for t, _, d in edges
    )  # groups are not options
    assert (
        "HAS_CONDITION",
        "2.1.",
        "Dấu **** (",
    ) in edges  # legacy visual context, not a criterion requirement
    # No sheet legend is present: a raw visual marker must not assert a star minimum.
    assert not any(t == "MINIMUM_FOR" for t, _, _ in edges)
    unscored = next(
        e for e in s["business_entities"] if e["kind"] == "ScoreOption" and "không phải nữ" in e["label"]
    )
    assert unscored["attributes"]["points_candidate"] is None
    assert unscored["attributes"]["crop_points_candidate"] == "0"  # kept apart, never promoted
    assert not any("Ghi chú" in e["label"] for e in s["business_entities"] if e["kind"] == "ScoreOption")


def test_article_heading_that_starts_a_sentence_keeps_its_subject():
    from ai_core.knowledge.ocop.extractor import _rule_sentences

    text = (
        "Điều 2. Quyết định này có hiệu lực kể từ ngày ký ban hành.\n"
        "Điều 3. Bộ trưởng, Thủ trưởng cơ quan ngang bộ, Thủ trưởng cơ quan\n"
        "thuộc Chính phủ chịu trách nhiệm thi hành Quyết định này./\n"
        "Điều 4. Phạm vi điều chỉnh"
    )
    sentences = _rule_sentences(text)
    assert sentences[0] == "Điều 2. Quyết định này có hiệu lực kể từ ngày ký ban hành."
    assert sentences[1].startswith("Điều 3. Bộ trưởng") and "chịu trách nhiệm thi hành" in sentences[1]
    assert sentences[2] == "Điều 4. Phạm vi điều chỉnh"
