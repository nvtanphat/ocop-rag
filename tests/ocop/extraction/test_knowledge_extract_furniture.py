from ai_core.processing.ocop.knowledge_extract import _page_furniture_lines, page_units


SOURCE_SHA256 = "a" * 64


def _page(number: int) -> dict:
    lines = [str(number), "CÔNG BÁO/Số 375 + 376/Ngày 15-02-2018", "Điều 1. Phạm vi điều chỉnh"]
    positions = [
        (64.0, 52.0, 82.0, 68.0),
        (170.0, 52.0, 430.0, 68.0),
        (86.0, 100.0, 360.0, 116.0),
    ]
    blocks = [
        {"block_id": f"b{number}-{i}", "text": text, "bbox": list(box), "order": i}
        for i, (text, box) in enumerate(zip(lines, positions, strict=True))
    ]
    return {
        "source_id": "VN.TEST.LAW",
        "pdf_page": number,
        "source_sha256": SOURCE_SHA256,
        "width_pt": 595.0,
        "height_pt": 842.0,
        "review_status": "machine_extracted",
        "extracted_text": "\n".join(lines),
        "blocks": blocks,
        "tables": [],
    }


def test_repeated_margin_text_and_adjacent_page_number_are_classified_per_source():
    pages = [_page(number) for number in range(1, 5)]

    furniture = _page_furniture_lines(pages)

    assert furniture[("VN.TEST.LAW", 1)] == {
        0: "page_number_adjacent_to_repeated_margin_text",
        1: "repeated_margin_text",
    }
    assert furniture[("VN.TEST.LAW", 4)] == {
        0: "page_number_adjacent_to_repeated_margin_text",
        1: "repeated_margin_text",
    }


def test_sequential_page_numbers_without_repeated_header_are_classified():
    pages = [_page(number) for number in range(1, 5)]
    for page in pages:
        lines = page["extracted_text"].splitlines()
        lines[0] = str(page["pdf_page"] + 10)
        lines.pop(1)
        page["extracted_text"] = "\n".join(lines)
        page["blocks"][0]["text"] = lines[0]
        page["blocks"].pop(1)

    furniture = _page_furniture_lines(pages)

    for page in pages:
        assert furniture[(page["source_id"], page["pdf_page"])][0] == (
            "sequential_page_number_at_consistent_position"
        )


def test_page_units_keep_raw_page_text_but_remove_furniture_from_content_units():
    page = _page(20)
    furniture = _page_furniture_lines([_page(number) for number in range(1, 5)])

    units = page_units(page, source_kind="law", furniture_lines=furniture[(page["source_id"], 1)])

    root = units[0]
    assert "20\nCÔNG BÁO/Số 375 + 376/Ngày 15-02-2018" in root["text"]
    assert root["structured"]["page_furniture"] == [
        {
            "line_index": 0,
            "text": "20",
            "reason": "page_number_adjacent_to_repeated_margin_text",
            "bbox": [64.0, 52.0, 82.0, 68.0],
        },
        {
            "line_index": 1,
            "text": "CÔNG BÁO/Số 375 + 376/Ngày 15-02-2018",
            "reason": "repeated_margin_text",
            "bbox": [170.0, 52.0, 430.0, 68.0],
        },
    ]
    assert root["spans"][0]["bbox"] == [0.0, 0.0, 595.0, 842.0]
    assert root["spans"][0]["source_sha256"] == SOURCE_SHA256

    content = [unit for unit in units if unit["unit_kind"] != "page"]
    assert len(content) == 1
    assert content[0]["unit_kind"] == "article"
    assert content[0]["text"] == "Điều 1. Phạm vi điều chỉnh"
    assert "20" not in content[0]["text"]
    assert "CÔNG BÁO" not in content[0]["text"]


def test_text_geometry_mismatch_fails_closed_and_preserves_all_lines():
    pages = [_page(number) for number in range(1, 5)]
    for page in pages:
        page["extracted_text"] = page["extracted_text"].replace("CÔNG BÁO", "CÔNG BAO")

    assert _page_furniture_lines(pages) == {}
    units = page_units(pages[0], source_kind="law")
    content = [unit for unit in units if unit["unit_kind"] != "page"]
    assert len(content) == 2
    assert "1\nCÔNG BAO/Số 375 + 376/Ngày 15-02-2018" in content[0]["text"]
