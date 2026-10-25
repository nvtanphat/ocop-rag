from ai_core.retrieval.ocop.decompose import sub_queries


def test_contrastive_question_is_split_into_its_sides():
    parts = sub_queries("Hồ sơ đánh giá lại khác gì hồ sơ lần đầu và nộp trước thời điểm nào?")
    assert "Hồ sơ đánh giá lại" in parts and "hồ sơ lần đầu" in parts


def test_simple_question_is_not_split():
    assert sub_queries("Điều 6 quy định hồ sơ lần đầu ra sao?") == []


def test_parts_without_enough_content_are_dropped():
    assert sub_queries("UBND cấp xã và tỉnh") == []


def test_unaccented_question_keeps_original_spelling_in_parts():
    parts = sub_queries("ho so danh gia lai khac gi ho so lan dau")
    assert parts == ["ho so danh gia lai", "ho so lan dau"]


def test_every_document_named_in_a_comparison_becomes_a_slot():
    from ai_core.orchestration.ocop.router import extract_slots

    slots = extract_slots("So sánh QĐ148/2023 và QĐ26/2026 về cơ quan công nhận")
    assert slots["document_codes"] == ["148/2023", "26/2026"]
    assert "document_codes" not in extract_slots("QĐ26/2026 quy định gì?")


def test_per_document_lookup_reports_absent_document_instead_of_substituting(tmp_path):
    from ai_core.orchestration.ocop.tools import ToolRegistry

    class Stub(ToolRegistry):
        def dispatch(self, name, *, query, slots, context=None, auth=None):
            if slots.get("document_codes"):
                return self._per_document(name, query, slots, context or {}, auth, slots["document_codes"])
            if slots["document_code"] == "26/2026":
                return {"results": [{"source_id": "S26", "text": "x"}]}
            return {"results": [], "status": "document_not_found_or_ambiguous"}

    out = Stub(tmp_path).dispatch(
        "search_regulations", query="q", slots={"document_codes": ["148/2023", "26/2026"]}
    )
    assert [r["source_id"] for r in out["results"]] == ["S26"]
    assert (
        out["unresolved_documents"] == ["148/2023"] and out.get("status") != "document_not_found_or_ambiguous"
    )


def test_a_part_that_says_that_document_inherits_the_source_that_holds_the_named_entity(
    tmp_path, monkeypatch
):
    from ai_core.orchestration.ocop import tools as tools_module
    from ai_core.orchestration.ocop.tools import ToolRegistry

    registry = ToolRegistry(tmp_path)
    hits = [
        {"source_id": "VN.HAIPHONG.QD525.2026", "raw_text": "Gạo ruộng rươi giống HANA"},
        {"source_id": "VN.HAIPHONG.QD525.2026", "raw_text": "HANA – Hợp tác xã Thụy Hương"},
        {"source_id": "VN.OCOP.QD26.2026", "raw_text": "không nhắc tên sản phẩm"},
    ]
    monkeypatch.setattr(tools_module, "search", lambda *a, **k: hits)
    earlier = [
        {"source_id": "VN.OCOP.QD26.2026"}
    ] * 4  # the parts before drifted to another document: the entity decides
    assert (
        registry._anaphoric_source("văn bản đó do cơ quan nào ban hành", earlier, ("HANA",))
        == "VN.HAIPHONG.QD525.2026"
    )
    assert (
        registry._anaphoric_source("cơ quan nào ban hành quyết định", earlier, ("HANA",)) is None
    )  # no pointer back
    # no named entity: the dominant source of the earlier parts, and only when it is clear
    assert registry._anaphoric_source("văn bản đó do cơ quan nào ban hành", earlier) == "VN.OCOP.QD26.2026"
    assert (
        registry._anaphoric_source("quyết định này do ai ký", [{"source_id": "A"}, {"source_id": "B"}])
        is None
    )
    assert registry._anaphoric_source("văn bản đó do cơ quan nào ban hành", []) is None
