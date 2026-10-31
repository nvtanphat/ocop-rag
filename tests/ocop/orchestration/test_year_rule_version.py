"""A year with no document named scopes the question to that year's national OCOP rule document (registry ocop_* kinds)."""

from __future__ import annotations

from ai_core.orchestration.ocop.contracts import Intent
from ai_core.orchestration.ocop.planner import build_plan, recovery_safe
from ai_core.orchestration.ocop.router import route_query


def test_year_after_a_rules_word_names_that_years_rule_document():
    slots = route_query("Trong quy trình OCOP năm 2023, sản phẩm đạt 4 sao sẽ do cấp nào phê duyệt?").slots
    assert slots["document_code"] == "148/QĐ-TTg" and slots.get("document_from_year")


def test_version_year_is_not_an_assessment_year():
    slots = route_query("Khi đề xuất đánh giá sản phẩm OCOP ở cấp tỉnh theo quy trình năm 2023, hồ sơ gồm gì?").slots
    assert "assessment_year" not in slots and "recognition_year" not in slots
    assert slots["document_code"] == "148/QĐ-TTg"


def test_two_years_compare_two_rule_documents():
    slots = route_query("Phiếu đăng ký đánh giá OCOP theo bộ quy định 2023 và bộ 2026 có giống nhau không?").slots
    assert slots["document_codes"] == ["148/QĐ-TTg", "26/2026/QĐ-TTg"]


def test_recognition_locality_and_typed_documents_keep_their_own_meaning():
    assert "document_code" not in route_query("Sản phẩm được công nhận năm 2026 gồm những gì?").slots
    assert "document_code" not in route_query("Năm 2026 Huế có bao nhiêu sản phẩm OCOP?").slots
    # A law of 2023 is not the 2023 OCOP decision.
    assert route_query("Luật Hợp tác xã năm 2023 quy định gì về quyền?").slots.get("document_code") != "148/QĐ-TTg"


def test_a_year_without_a_rule_document_stays_unpinned():
    assert "document_code" not in route_query("Mẫu 01 năm 2024 là gì?").slots


def test_a_derived_document_does_not_make_an_off_topic_question_in_scope():
    route = route_query("Công nghệ AI mới năm 2026 là gì?")
    assert route.intent == Intent.OUT_OF_SCOPE and "document_code" not in route.slots


def test_followup_year_rereads_the_document_instead_of_keeping_the_derived_one():
    first = route_query("Trong quy trình OCOP năm 2023, ai phê duyệt sản phẩm 4 sao?")
    session = {"last_query": "Trong quy trình OCOP năm 2023, ai phê duyệt sản phẩm 4 sao?", "slots": first.slots,
               "intent": first.intent.value, "capabilities": first.capabilities}
    follow = route_query("Còn quy trình năm 2026 thì sao?", session=session)
    assert not follow.needs_clarification
    assert follow.slots["document_code"] == "26/2026/QĐ-TTg"


def test_recovery_counts_the_resolved_documents_year_as_covered():
    route = route_query("Biểu số 2 trong bộ hồ sơ OCOP năm 2023 dành cho chủ thể báo cáo nội dung gì?")
    plan = build_plan(route)
    if plan.text_recovery:
        assert recovery_safe(route, [], plan)
