from ai_core.orchestration.ocop.evidence_grader import grade_evidence, tokens, uncovered_parts


def _row(text, unit="u1"):
    return {
        "source_id": "VN.X.2026",
        "evidence_unit_id": unit,
        "text": text,
        "review_status": "needs_review",
        "source_spans": [{"pdf_page": 3}],
    }


def test_part_without_evidence_is_reported_and_covered_part_is_not():
    rows = [tokens("Gạo ruộng rươi giống HANA do Hợp tác xã Thụy Hương sản xuất")]
    missed = uncovered_parts(
        "Sản phẩm HANA do đơn vị nào sản xuất, và cơ quan nào ban hành quyết định công nhận?", rows
    )
    assert len(missed) == 1 and "ban hành" in missed[0]


def test_non_compound_question_has_no_parts_to_miss():
    assert uncovered_parts("Sản phẩm HANA do đơn vị nào sản xuất?", [tokens("khác hẳn")]) == []


def test_grade_is_partial_when_a_part_is_uncovered_even_without_a_missing_tool():
    results = [
        {
            "tool": "search_regulations",
            "output": {"results": [_row("Gạo ruộng rươi giống HANA do Hợp tác xã Thụy Hương sản xuất")]},
        }
    ]
    grade = grade_evidence(
        "Sản phẩm HANA do đơn vị nào sản xuất, và cơ quan nào ban hành quyết định công nhận?", results
    )
    assert (
        grade["status"] == "partial" and grade["missing_tools"] == [] and len(grade["uncovered_parts"]) == 1
    )
    covered = grade_evidence("Sản phẩm HANA do đơn vị nào sản xuất?", results)
    assert covered["status"] == "sufficient_for_generation" and covered["uncovered_parts"] == []
