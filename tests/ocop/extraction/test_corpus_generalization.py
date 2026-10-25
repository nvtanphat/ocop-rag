"""Source variants must not be limited to the previously inspected OCOP pages."""

from tests.fixtures.legal import extract, unit
from tests.fixtures.criteria import fixture


def test_historical_sheet_tree_and_normalized_sheet_numbers_remain_candidates():
    units = fixture()
    units[4]["text"] = units[4]["text"].replace("1. Bộ", "01. Bộ")
    result = extract(units, kinds={"DOC.CURRENT": "ocop_historical"})
    sheets = [e for e in result["business_entities"] if e["kind"] == "CriterionSheet"]
    assert {e["attributes"]["sheet_number"] for e in sheets} == {str(n) for n in range(1, 27)}
    assert any(r["relation_type"] == "HAS_OPTION" for r in result["business_relations"])
    assert all(e["status"] == "candidate" for e in result["business_entities"])


def test_law_issuer_effective_date_and_legal_bases_are_source_grounded():
    registry = {
        "DOC.LAW": {"document_number": "17/2023/QH15"},
        "DOC.BASE": {"document_number": "55/2010/QH12"},
    }
    units = [
        unit("DOC.LAW", 1, "QUỐC HỘI\nSố: 17/2023/QH15\nLUẬT\nCăn cứ Luật số 55/2010/QH12;", "paragraph"),
        unit(
            "DOC.LAW",
            2,
            "Điều 99. Hiệu lực thi hành\nLuật này có hiệu lực thi hành từ ngày 01 tháng 7 năm 2024.",
        ),
    ]
    result = extract(
        units, kinds={"DOC.LAW": "cooperative_law", "DOC.BASE": "food_safety_law"}, registry=registry
    )
    law = next(
        e
        for e in result["business_entities"]
        if e["kind"] == "SourceDocument" and e["source_id"] == "DOC.LAW"
    )
    assert law["attributes"]["issuer_candidate"] == "QUỐC HỘI"
    assert law["attributes"]["effective_from"] == "2024-07-01"
    assert any(r["relation_type"] == "BASED_ON" for r in result["business_relations"])


def test_procedure_article_title_and_authority_do_not_depend_on_known_numbers():
    result = extract(
        [
            unit(
                "DOC.CURRENT",
                2,
                "Điều 48. Trình tự đánh giá\n1. Sở Nông nghiệp và Môi trường tiếp nhận hồ sơ đăng ký.",
            )
        ]
    )
    assert any(r["relation_type"] == "RESPONSIBLE_FOR" for r in result["business_relations"])


def test_repealed_document_title_is_not_a_new_ministry_responsibility():
    text = (
        "Chương II Thông tư liên tịch số 13/2014/TTLT-BYT-BNNPTNT-BCT ngày 09\n"
        "tháng 4 năm 2014 của Bộ Y tế, Bộ Nông nghiệp và Phát triển nông thôn, Bộ Công\n"
        "Thương hướng dẫn việc phân công, phối hợp trong quản lý nhà nước về an toàn thực\n"
        "phẩm."
    )
    result = extract([unit("DOC.ND", 34, text, "paragraph")], kinds={"DOC.ND": "food_safety_decree"})
    assert not any(r["relation_type"] == "RESPONSIBLE_FOR" for r in result["business_relations"])
    from ai_core.knowledge.ocop.procedures import _subjects

    assert not _subjects(text)


def test_recognition_decision_keeps_explicit_implementation_responsibility():
    result = extract(
        [
            unit(
                "DOC.LOCAL",
                2,
                "Điều 3. Tổ chức thực hiện\n"
                "1. Giao Sở Nông nghiệp và Môi trường tổ chức công bố công khai sản phẩm được xếp hạng.",
            )
        ],
        kinds={"DOC.LOCAL": "recognition_decision"},
    )
    assert any(r["relation_type"] == "RESPONSIBLE_FOR" for r in result["business_relations"])


def test_council_organized_by_an_advisory_team_is_not_the_subject_of_that_report_step():
    from ai_core.knowledge.ocop.procedures import _subjects

    text = (
        "Tổ tư vấn tổng hợp kết quả đánh giá, tính trung bình điểm của các thành viên, "
        "xây dựng báo cáo trình Chủ tịch Hội đồng đánh giá, phân hạng cấp trung ương "
        "để tổ chức Hội đồng cấp trung ương đánh giá, phân hạng."
    )
    assert not _subjects(text)


def test_historical_letter_criteria_are_scoped_to_their_numbered_group():
    from tests.fixtures.criteria import table

    header = unit(
        "DOC.CURRENT",
        3,
        "1. Bộ sản phẩm: Rau củ\n(Sản phẩm: Thực phẩm. Nhóm: Thực phẩm tươi sống)",
        "paragraph",
    )
    rows = table(
        3,
        [
            ("Phần A: SẢN PHẨM", 40),
            ("1. TỔ CHỨC SẢN XUẤT", 18),
            ("a) Nguồn gốc sản phẩm", 5),
            ("Sản phẩm trồng tại xã dưới 50%", 1),
            ("b) Gia tăng giá trị", 3),
            ("Ứng dụng máy móc", 2),
        ],
    )
    result = extract([header, rows], kinds={"DOC.CURRENT": "ocop_historical"})
    entities = {e["entity_id"]: e for e in result["business_entities"]}
    for option, criterion in [
        ("Sản phẩm trồng tại xã dưới 50%", "a) Nguồn gốc sản phẩm"),
        ("Ứng dụng máy móc", "b) Gia tăng giá trị"),
    ]:
        edges = [
            r
            for r in result["business_relations"]
            if r["relation_type"] == "HAS_OPTION" and entities[r["target_entity_id"]]["label"] == option
        ]
        assert edges and {entities[r["source_entity_id"]]["label"] for r in edges} == {criterion}
    assert any(
        r["relation_type"] == "HAS_SUBCRITERION"
        and entities[r["source_entity_id"]]["label"] == "1. TỔ CHỨC SẢN XUẤT"
        and entities[r["target_entity_id"]]["label"] == "a) Nguồn gốc sản phẩm"
        for r in result["business_relations"]
    )


def test_noisy_numbered_heading_stops_cross_page_parent_inheritance():
    from tests.fixtures.criteria import table

    header = unit(
        "DOC.CURRENT",
        3,
        "2. Bộ sản phẩm: Thịt\n(Sản phẩm: Thực phẩm. Nhóm: Thực phẩm tươi sống)",
        "paragraph",
    )
    first = table(
        3,
        [
            ("Phần A: SẢN PHẨM", 40),
            ("1. TỔ CHỨC SẢN XUẤT", 18),
            ("1.5. Liên kết chuỗi", 3),
            ("Có hợp đồng liên kết", 3),
            ("j 1.6. Bảo vệ môi trường trong quá trình sản xuất", 3),
        ],
    )
    second = table(4, [("Có hồ sơ môi trường", 1)])
    second["structured"]["table_continuity"] = [
        {"from_pdf_page": 3, "to_pdf_page": 4, "from_table_id": "table:3", "to_table_id": "table:4"}
    ]
    result = extract([header, first, second])
    entities = {e["entity_id"]: e for e in result["business_entities"]}
    assert not any(
        r["relation_type"] == "HAS_OPTION"
        and entities[r["target_entity_id"]]["label"] == "Có hồ sơ môi trường"
        for r in result["business_relations"]
    )


def test_next_annex_stops_the_last_criterion_sheet():
    from tests.fixtures.criteria import table

    units = fixture()
    units += [
        unit("DOC.CURRENT", 5, "PHỤ LỤC III", "annex"),
        table(5, [("Phần A: MẪU BIỂU", 40), ("1. KHÔNG PHẢI TIÊU CHÍ", 40)]),
    ]
    result = extract(units)
    entities = {e["entity_id"]: e for e in result["business_entities"]}
    assert not any(
        r["relation_type"] == "HAS_CRITERION"
        and entities[r["target_entity_id"]]["evidence"][0]["pdf_page"] == 5
        for r in result["business_relations"]
    )


def test_two_headers_on_one_page_select_their_own_table_by_bbox():
    from tests.fixtures.criteria import table

    units = []
    for number, top, name in [(1, 100, "FIRST"), (2, 400, "SECOND")]:
        header = unit(
            "DOC.CURRENT",
            3,
            f"{number}. Bộ sản phẩm: {name}\n(Sản phẩm: Thực phẩm. Nhóm: Ví dụ)",
            "paragraph",
        )
        header["unit_id"] += f":{number}"
        header["spans"][0]["bbox"] = [0, top, 500, top + 50]
        rows = table(3, [(f"Phần A: {name}", 40)])
        rows["unit_id"] += f":{number}"
        rows["structured"]["table_id"] += f":{number}"
        for cell in rows["structured"]["cells"]:
            cell["bbox"][1] += top + 60
            cell["bbox"][3] += top + 60
        units.extend([header, rows])
    result = extract(units)
    entities = {e["entity_id"]: e for e in result["business_entities"]}
    links = [r for r in result["business_relations"] if r["relation_type"] == "HAS_CRITERION"]
    assert {
        (
            entities[r["source_entity_id"]]["attributes"]["sheet_number"],
            entities[r["target_entity_id"]]["label"],
        )
        for r in links
    } == {("1", "Phần A: FIRST"), ("2", "Phần A: SECOND")}


def test_historical_tree_keeps_explicit_replacement_link_without_verifying_it():
    units = fixture()
    for row in units:
        row["source_id"] = "DOC.OLD"
    units.append(
        unit(
            "DOC.CURRENT",
            13,
            "Điều 12. Hiệu lực thi hành\n"
            "Quyết định số 148/QĐ-TTg hết hiệu lực sau 60 ngày kể từ ngày Quyết định này có hiệu lực thi hành.",
        )
    )
    result = extract(units, kinds={"DOC.CURRENT": "ocop_framework", "DOC.OLD": "ocop_historical"})
    historical = [
        e
        for e in result["business_entities"]
        if e["source_id"] == "DOC.OLD" and e["kind"] == "CriterionSheet"
    ]
    assert historical and all(e["attributes"]["superseded_by"] == "DOC.CURRENT" for e in historical)
    assert all(e["attributes"]["supersession_interpretation_verified"] is False for e in historical)


def test_legal_heading_in_native_table_is_not_lost_and_motto_is_not_issuer():
    heading = unit(
        "DOC.CURRENT",
        1,
        "ỦY BAN NHÂN DÂN CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\nTHÀNH PHỐ HUẾ\nSố: 26/2026/QĐ-TTg",
        "table",
    )
    result = extract([heading])
    document = next(e for e in result["business_entities"] if e["kind"] == "SourceDocument")
    assert document["attributes"]["issuer_candidate"] == "ỦY BAN NHÂN DÂN\nTHÀNH PHỐ HUẾ"
    assert document["attributes"]["document_number_candidate"] == "26/2026/QĐ-TTg"


def test_spaced_legal_number_is_parsed_without_rewriting_its_evidence():
    heading = unit("DOC.CURRENT", 1, "THỦ TƯỚNG CHÍNH PHỦ\nSố: 26 /2026/QĐ-TTg", "paragraph")
    result = extract([heading])
    document = next(e for e in result["business_entities"] if e["kind"] == "SourceDocument")
    assert document["attributes"]["document_number_candidate"] == "26/2026/QĐ-TTg"
    assert any("26 /2026/QĐ-TTg" in ref["quote"] for ref in document["evidence"])
    assert "26 /2026/QĐ-TTg" in heading["text"]
