"""Synthetic sheet/index and arithmetic fixtures; no OCR gold labels."""

from copy import deepcopy
from tests.fixtures.legal import unit, extract
from ai_core.knowledge.ocop.quality import audit_knowledge


from tests.fixtures.criteria import fixture


def test_index_groups_parts_and_cross_page_option_are_source_grounded():
    units = fixture()
    result = extract(units)
    es = {e["entity_id"]: e for e in result["business_entities"]}
    assert len([e for e in es.values() if e["kind"] == "CriterionSheet"]) == 26
    assert len([e for e in es.values() if e["kind"] == "ProductGroup"]) == 6
    assert not any(e["kind"] == "ScoreOption" and e["label"].startswith("Chỉ áp dụng") for e in es.values())
    assert len([r for r in result["business_relations"] if r["relation_type"] == "HAS_CRITERION"]) == 3
    high = next(e for e in es.values() if e["label"] == "Phương án cao")
    edge = next(
        r
        for r in result["business_relations"]
        if r["relation_type"] == "HAS_OPTION" and r["target_entity_id"] == high["entity_id"]
    )
    assert es[edge["source_entity_id"]]["label"] == "1.1, Tiêu chí"
    assert {e["pdf_page"] for e in edge["evidence"]} == {3, 4}
    assert not audit_knowledge(units, result)["arithmetic_mismatches"]


def test_sheet_title_without_bo_requires_explicit_classification():
    units = fixture()
    units[4] = unit(
        "DOC.CURRENT", 3, "13. Sản phẩm cà phê tổng hợp\n(Sản phẩm: Thực phẩm. Nhóm: Cà phê)", "paragraph"
    )
    result = extract(units)
    sheets = {e["entity_id"]: e for e in result["business_entities"] if e["kind"] == "CriterionSheet"}
    parents = {
        r["source_entity_id"] for r in result["business_relations"] if r["relation_type"] == "HAS_CRITERION"
    }
    assert {sheets[p]["attributes"]["sheet_number"] for p in parents} == {"13"}
    assert not [
        v
        for v in audit_knowledge(units, result)["shapes"]["violations"]
        if v.get("entity_id") in parents and v.get("severity") == "pending_source"
    ]
    units[4] = unit("DOC.CURRENT", 3, "13. Sản phẩm cà phê phải đăng ký theo quy định.", "paragraph")
    assert not any(r["relation_type"] == "HAS_CRITERION" for r in extract(units)["business_relations"])


def test_arithmetic_reports_actual_candidate_difference_without_repair():
    units = fixture(high=41)
    result = extract(units)
    before = deepcopy(result)
    report = audit_knowledge(units, result)
    assert result == before
    errors = report["arithmetic_mismatches"]
    assert len(errors) == 1
    assert errors[0]["check"] == "criterion_option_max"
    assert errors[0]["observed_candidate"] == 40 and errors[0]["expected_from_candidates"] == 41
    assert {e["pdf_page"] for e in errors[0]["evidence"]} == {3, 4}
    assert errors[0]["values_changed"] is False


def test_missing_continuity_does_not_guess_parent_for_top_row():
    result = extract(fixture(continuity=False))
    high = next(e for e in result["business_entities"] if e["label"] == "Phương án cao")
    assert not any(
        r["relation_type"] == "HAS_OPTION" and r["target_entity_id"] == high["entity_id"]
        for r in result["business_relations"]
    )
    assert {"reason": "score_option_without_continuation_parent", "count": 1} in result["business_omissions"]


def test_table_continuity_can_propose_two_columns_without_changing_default():
    from ocop_ocr.table_continuity import possible_continuations

    pre = {
        "source_id": "DOC.CURRENT",
        "pdf_page": 3,
        "height_pt": 700,
        "tables": [{"table_id": "before", "bbox": [0, 300, 500, 690], "col_count": 2, "row_count": 4}],
    }
    cur = {
        "source_id": "DOC.CURRENT",
        "pdf_page": 4,
        "height_pt": 700,
        "tables": [{"table_id": "after", "bbox": [0, 0, 500, 600], "col_count": 2, "row_count": 9}],
    }
    assert possible_continuations(pre, cur) == []
    assert len(possible_continuations(pre, cur, min_columns=2)) == 1


def test_reference_parts_do_not_bleed_into_next_part_and_group_quote_stays_literal():
    units = fixture()
    units[0]["text"] = (
        "Điều 2. Có 06 nhóm sản phẩm: thực phẩm; đồ uống, được liệu và sản phẩm từ dược liệu; hàng thủ công mỹ nghệ; sinh vật cảnh; dịch vụ du lịch cộng đồng, du lịch sinh thái và điểm du lịch. Danh mục kèm theo."
    )
    units[1]["text"] = units[1]["text"].replace("40 điểm", "40 điêm")
    result = extract(units)
    assert len([e for e in result["business_entities"] if e["kind"] == "ProductGroup"]) == 6
    assert any(
        e["label"].startswith("được liệu") for e in result["business_entities"] if e["kind"] == "ProductGroup"
    )
    assert not audit_knowledge(units, result)["arithmetic_mismatches"]
