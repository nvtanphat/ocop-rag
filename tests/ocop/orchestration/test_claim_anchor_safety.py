"""Deterministic adversarial probes: a real quote is not semantic support."""

import pytest

from ai_core.orchestration.ocop.answer import _judge_claims
from ai_core.orchestration.ocop.entailment import anchored


def judge(claim, source, *, quote=None, question="", status="verified", catalog=None):
    row = {"source_id": "DOC", "evidence_unit_id": "unit", "text": source,
           "review_status": status, "source_spans": [{"pdf_page": 1}]}
    citation = {"source_id": "DOC", "evidence_unit_id": "unit", "pdf_page": 1,
                "review_status": status}
    return _judge_claims([(claim, [1], quote or source)], [citation], [row], catalog=catalog, question=question)


@pytest.mark.parametrize("claim,source,question", [
    ("Đơn vị ALPHA xuất khẩu toàn bộ sản phẩm.", "Đơn vị ALPHA sản xuất sản phẩm.", ""),
    ("Đơn vị BETA là đơn vị sản xuất của sản phẩm ALPHA.",
     "Đơn vị ALPHA là đơn vị sản xuất của sản phẩm BETA.", ""),
    ("Phải nộp bản giấy.", "Không phải nộp bản giấy.", ""),
    ("Quá 90 điểm.", "Không quá 90 điểm.", ""),
    ("Hồ sơ nộp trong 99 ngày.", "Hồ sơ nộp trong 15 ngày.", "Hồ sơ nộp trong 99 ngày phải không?"),
    ("Nộp 2 bản giấy và 1 bản điện tử.", "Nộp 1 bản giấy và 2 bản điện tử.", ""),
    ("Sản phẩm ALPHA đạt 5 sao.", "Sản phẩm ALPHA đạt 3 sao. Sản phẩm BETA đạt 5 sao.", ""),
    ("Sản phẩm ALPHA được công nhận năm 2026.",
     "Quyết định 123/2026. Sản phẩm ALPHA được công nhận năm 2025.", ""),
])
def test_real_quote_does_not_launder_new_facts_negation_or_numeric_roles(claim, source, question):
    accepted, rejected = judge(claim, source, question=question)
    assert not accepted and rejected


def test_quote_matching_preserves_punctuation_instead_of_joining_clauses():
    source = "Không. Hồ sơ được chấp nhận."
    assert not anchored("Hồ sơ không được chấp nhận.", "Không Hồ sơ được chấp nhận", source)


def test_an_invented_provided_quote_is_rejected_even_when_the_claim_itself_is_exact():
    accepted, rejected = judge("Hồ sơ nộp trong 15 ngày.", "Hồ sơ nộp trong 15 ngày.",
                               quote="Đây là một đoạn trích không tồn tại.")
    assert not accepted and rejected


@pytest.mark.parametrize("source", [
    "Hồ sơ nộp trong 15 ngày.",
    "Không phải nộp bản giấy.",
    "Nộp 1 bản giấy và 2 bản điện tử.",
])
def test_exact_source_statement_remains_publishable(source):
    accepted, rejected = judge(source, source)
    assert accepted and not rejected


def test_generic_rule_exception_cannot_override_a_misbound_verified_rating():
    from ai_core.orchestration.ocop.catalog import EntityCatalog

    catalog = EntityCatalog({"entities": {"product": [{"label": "OTHER", "source_ids": []}]}})
    accepted, rejected = judge("Sản phẩm ALPHA đạt 5 sao.",
                               "Sản phẩm ALPHA đạt 3 sao. Sản phẩm BETA đạt 5 sao.", catalog=catalog)
    assert not accepted and rejected


def test_sensitive_guard_keeps_cells_of_the_same_checked_record_together():
    from ai_core.orchestration.ocop.verification import check_sensitive_claims

    rows = [{"source_id": "DOC", "evidence_unit_id": f"u{i}", "text": text,
             "review_status": "verified", "graph_node_ids": ["record"]}
            for i, text in enumerate(["Sản phẩm ALPHA", "4 sao"], 1)]
    citations = [{"source_id": "DOC", "evidence_unit_id": row["evidence_unit_id"]} for row in rows]
    verdict = check_sensitive_claims("Sản phẩm ALPHA đạt 4 sao [S1][S2].", rows, citations)
    assert not verdict["unsupported_score_or_star_claims"]


def test_semantic_review_cannot_quote_synthetic_context_appended_to_original_text():
    import json
    from ai_core.orchestration.ocop.entailment import review

    source = "Hồ sơ nộp trong 15 ngày."
    excerpt = source + "\nDOC.2026"
    class Judge:
        def chat_structured(self, *args, **kwargs):
            return json.dumps({"verdicts": [{"id": 0, "entails": True, "quote": excerpt}]})
    assert review(Judge(), [{"claim": source, "excerpt": excerpt, "quote_sources": [source]}]) == {}


def _locator_judge(claim, locator):
    source = "Hồ sơ nộp trong 15 ngày."
    row = {"source_id": "VN.OCOP.QD26.2026", "evidence_unit_id": "unit", "text": source, "review_status": "verified",
           "source_spans": [{"pdf_page": 1}], **({"resolved_locator": locator} if locator else {})}
    citation = {"source_id": "VN.OCOP.QD26.2026", "evidence_unit_id": "unit", "pdf_page": 1, "review_status": "verified"}
    return _judge_claims([(claim, [1], source)], [citation], [row], question="")[1][0]["reasons"]


def test_the_article_a_tool_resolved_grounds_a_claim_that_names_it_but_a_wrong_article_is_not_grounded():
    claim = "Điều 6 quy định hồ sơ nộp trong 15 ngày."
    assert _locator_judge(claim, None) == ["grounding_numbers_missing"]  # nothing says the passage sits in Điều 6
    assert _locator_judge(claim, {"article_id": "6"}) == ["needs_semantic_entailment_check"]  # numbers pass; meaning is reviewed
    assert _locator_judge(claim.replace("Điều 6", "Điều 7"), {"article_id": "6"}) == ["grounding_numbers_missing"]


def test_the_sheet_and_criterion_a_tool_resolved_ground_a_claim_that_names_them():
    claim = "Phiếu 1 mục 1.1: hồ sơ nộp trong 15 ngày."
    assert _locator_judge(claim, None) == ["grounding_numbers_missing"]
    assert _locator_judge(claim, {"sheet_number": "1", "criterion_id": "1.1"}) == ["needs_semantic_entailment_check"]
    wrong = claim.replace("Phiếu 1", "Phiếu 3")
    assert _locator_judge(wrong, {"sheet_number": "2", "criterion_id": "1.1"}) == ["grounding_numbers_missing"]


def test_the_semantic_review_is_told_which_document_a_deictic_reference_points_to():
    import json

    from ai_core.orchestration.ocop.answer import _document_label
    from ai_core.orchestration.ocop.entailment import review

    assert _document_label("VN.OCOP.QD26.2026") == "26/2026/QĐ-TTg"
    assert _document_label("NO.SUCH.SOURCE") == "NO.SUCH.SOURCE"
    seen = []

    class Judge:
        def chat_structured(self, system, user, **kwargs):
            seen.append((system, user))
            return json.dumps({"verdicts": []})

    item = {"claim": "Quyết định 26/2026 có hiệu lực từ ngày 22/5/2026.", "excerpt": "Quyết định này có hiệu lực."}
    review(Judge(), [{**item, "document": "26/2026/QĐ-TTg"}])
    review(Judge(), [item])
    assert "VĂN BẢN CHỨA ĐOẠN TRÍCH: 26/2026/QĐ-TTg" in seen[0][1] and "VĂN BẢN CHỨA ĐOẠN TRÍCH" not in seen[1][1]
    assert "Quyết định này" in seen[0][0]


def test_a_legal_unit_lookup_marks_each_passage_with_the_article_it_was_fetched_under():
    from pathlib import Path

    from ai_core.orchestration.ocop.tools import ToolRegistry

    root = Path(__file__).resolve().parents[3]
    out = ToolRegistry(root).dispatch(
        "lookup_legal_unit",
        query="Điều 6 Quyết định 26/2026",
        slots={"document_code": "26/2026", "article_id": "6"},
        context={"retrieval_mode": "sparse"},
    )
    assert out["results"] and all(r["resolved_locator"] == {"article_id": "6"} for r in out["results"])


def test_a_sheet_number_shared_by_several_documents_asks_which_one_instead_of_guessing():
    from pathlib import Path

    from ai_core.orchestration.ocop.tools import ToolRegistry

    tools = ToolRegistry(Path(__file__).resolve().parents[3])
    asked = {"sheet_number": "1", "criterion_id": "1.6"}
    out = tools.dispatch("lookup_criterion", query="Tiêu chí 1.6 trong phiếu 1", slots=asked)
    assert out["status"] == "sheet_document_ambiguous" and not out["results"]
    assert len(out["candidate_documents"]) >= 2
    pinned = tools.dispatch(
        "lookup_criterion", query="Tiêu chí 1.6 trong phiếu 1", slots={**asked, "document_code": "26/2026"}
    )
    assert pinned["results"] and pinned["status"] != "sheet_document_ambiguous"


def test_a_document_code_is_not_a_word_the_passage_must_repeat():
    from ai_core.orchestration.ocop.context import question_terms

    assert question_terms("Điều 6 Quyết định 26/2026/QĐ-TTg quy định gì?") == []
    assert "ttg" not in question_terms("Quyết định 148/QĐ-TTg ban hành bộ tiêu chí nào?")


def test_parallel_tiers_bind_a_claim_only_when_one_tier_states_all_of_its_numbers():
    from ai_core.orchestration.ocop.verification import check_sensitive_claims

    tiers = (
        "a) Hạng 5 sao: Tổng điểm trung bình đạt từ 90 đến 100 điểm, là sản phẩm đặc trưng.\n"
        "b) Hạng 4 sao: Tổng điểm trung bình đạt từ 70 đến dưới 90 điểm, là sản phẩm đặc trưng.\n"
        "c) Hạng 3 sao: Tổng điểm trung bình đạt từ 50 đến dưới 70 điểm, là sản phẩm có đặc thù."
    )
    rows = [{"source_id": "DOC", "evidence_unit_id": "u1", "text": tiers, "review_status": "verified"}]
    citations = [{"source_id": "DOC", "evidence_unit_id": "u1"}]

    def unsupported(claim):
        return check_sensitive_claims(claim + " [S1].", rows, citations)["unsupported_score_or_star_claims"]

    assert not unsupported("Sản phẩm đạt hạng 5 sao khi tổng điểm trung bình đạt từ 90 đến 100 điểm")
    assert not unsupported("Sản phẩm đạt hạng 4 sao khi tổng điểm trung bình đạt từ 70 đến dưới 90 điểm")
    # Numbers of two different tiers, or a range that no tier states, never bind together.
    assert unsupported("Sản phẩm đạt hạng 5 sao khi tổng điểm trung bình đạt từ 70 đến 100 điểm")
    assert unsupported("Sản phẩm đạt hạng 5 sao khi tổng điểm trung bình đạt từ 50 đến 100 điểm")
    assert unsupported("Sản phẩm đạt hạng 4 sao khi tổng điểm trung bình đạt từ 90 đến 100 điểm")


def test_a_quote_differing_only_in_layout_is_verbatim_but_a_changed_word_never_is():
    from ai_core.orchestration.ocop.entailment import verbatim

    source = "**Điều 11. Hiệu lực thi hành**\n1. Quyết định này có hiệu lực\nthi hành từ ngày 22 tháng 5 năm 2026."
    assert verbatim("1. Quyết định này có hiệu lực thi hành từ ngày 22 tháng 5 năm 2026.", source)
    assert verbatim("Điều 11. Hiệu lực thi hành 1. Quyết định này có hiệu lực", source)
    assert not verbatim("1. Quyết định này có hiệu lực thi hành từ ngày 22 tháng 6 năm 2026.", source)
    assert not verbatim("thi hành từ ngày 22 tháng 5 năm 2026. 1. Quyết định này có hiệu lực", source)
    assert not verbatim("hiệu lực", source)  # shorter than a quote must be


def test_the_programme_name_is_not_a_name_a_passage_must_introduce_but_an_invented_one_is():
    from ai_core.orchestration.ocop.entailment import anchored

    record = "STT: 3; Sản phẩm: Nước mắm Cát Hải; Điểm đánh giá: 84,1; Xếp loại: 4 sao"
    assert anchored("Nước mắm Cát Hải được xếp loại OCOP 4 sao.", record, record)
    assert not anchored("Nước mắm Phú Quốc được xếp loại OCOP 4 sao.", record, record)


def test_a_comparison_may_quote_one_line_per_cited_source_but_never_a_line_that_is_not_in_them():
    from ai_core.orchestration.ocop.entailment import quoted_from

    one = "STT: 13; Tổ chức/cá nhân: Hợp tác xã Thụy Hương; Sản phẩm: Gạo giống HANA; Địa chỉ: Thôn Trà Phương"
    two = "STT: 10; Tổ chức/cá nhân: Hợp tác xã Thụy Hương; Sản phẩm: Gạo ST25; Địa chỉ: Thôn Trà Phương"
    sources = one + "\n" + two
    assert quoted_from("Tổ chức/cá nhân: Hợp tác xã Thụy Hương; Sản phẩm: Gạo giống HANA\nTổ chức/cá nhân: Hợp tác xã Thụy Hương; Sản phẩm: Gạo ST25", sources)
    assert not quoted_from("Tổ chức/cá nhân: Hợp tác xã Thụy Hương; Sản phẩm: Gạo giống HANA\nTổ chức/cá nhân: Hợp tác xã Sen Huế; Sản phẩm: Gạo ST25", sources)
    stitched = "\n".join(f"Tổ chức/cá nhân: Hợp tác xã Thụy Hương; Sản phẩm: Gạo giống HANA{'' if i else ''}" for i in range(5))
    assert not quoted_from(stitched, sources)


def test_a_citation_box_comes_from_a_span_of_the_cited_page_when_the_first_span_is_only_a_table():
    from ai_core.orchestration.ocop.answer import _evidence

    row = {"source_id": "D", "evidence_unit_id": "u", "chunk_id": "c", "review_status": "needs_review",
           "text": "Điều kiện về hồ sơ sản phẩm theo quy định.",
           "source_spans": [{"pdf_page": 3, "table_bbox": [1, 2, 3, 4]}, {"pdf_page": 3, "bbox": [10, 20, 30, 40]}]}
    citations, _, _ = _evidence([row], question="Điều kiện về hồ sơ sản phẩm")
    assert citations and citations[0]["pdf_page"] == 3 and citations[0]["bbox"] == [10, 20, 30, 40]


def test_a_quote_copied_with_the_excerpt_framing_is_checked_on_its_source_text():
    from ai_core.orchestration.ocop.entailment import quoted_from

    source = (
        "14. Chất lượng phục vụ | 4\nThái độ phục vụ thân thiện | 1\n"
        "Bộ sản phẩm: Dịch vụ du lịch cộng đồng\nPhần C: CHẤT LƯỢNG SẢN PHẨM (35 Điểm)"
    )
    framed = (
        "26/2026/QĐ-TTg, trang 146: Ngữ cảnh: Bộ sản phẩm: Dịch vụ du lịch cộng đồng > "
        "Phần C: CHẤT LƯỢNG SẢN PHẨM (35 Điểm)\n14. Chất lượng phục vụ | 4"
    )
    assert quoted_from(framed, source)
    assert quoted_from("[S2] 26/2026/QĐ-TTg, trang 146: 14. Chất lượng phục vụ | 4", source)
    assert not quoted_from(framed.replace("| 4", "| 5"), source)
    assert not quoted_from("Ngữ cảnh: Bộ sản phẩm: Rượu trắng > Phần C: CHẤT LƯỢNG SẢN PHẨM (35 Điểm)", source)


def test_a_criterion_score_claim_is_checked_against_the_graph_criterion_on_the_cited_page():
    from ai_core.orchestration.ocop.answer import _states_criterion_points

    citations = [{"source_id": "DOC.CURRENT", "pdf_page": 146}]
    points = {
        ("DOC.CURRENT", 146): [(4.0, "chat luong phuc vu", "dich vu du lich cong dong, du lich sinh thai")],
        ("DOC.CURRENT", 90): [(5.0, "mui", "ruou trang")],
    }
    claim = "Trong bộ Dịch vụ du lịch cộng đồng, tiêu chí 14 «Chất lượng phục vụ» có thang điểm 4."
    assert _states_criterion_points(claim, [1], citations, points)
    assert not _states_criterion_points(claim.replace("điểm 4", "điểm 5"), [1], citations, points)
    assert not _states_criterion_points(claim.replace("Dịch vụ du lịch cộng đồng", "Rượu trắng"), [1], citations, points)
    assert not _states_criterion_points(claim, [1], [{"source_id": "DOC.CURRENT", "pdf_page": 20}], points)


def test_a_criterion_score_claim_without_a_product_set_holds_only_when_every_cited_sheet_agrees():
    from ai_core.orchestration.ocop.answer import _states_criterion_points

    citations = [{"source_id": "DOC", "pdf_page": 20}, {"source_id": "DOC", "pdf_page": 30}]
    same = {("DOC", 20): [(1.0, "dai dien phap luat la nu", "rau, cu")], ("DOC", 30): [(1.0, "dai dien phap luat la nu", "mat ong")]}
    claim = "Tiêu chí 3.2 đại diện pháp luật là nữ được 1 điểm."
    assert _states_criterion_points(claim, [1, 2], citations, same)
    differ = {**same, ("DOC", 30): [(2.0, "dai dien phap luat la nu", "mat ong")]}
    assert not _states_criterion_points(claim, [1, 2], citations, differ)
