"""adversarial regression tests: citation-level entailment, contradictory records,
malformed provenance, and generation gated by evidence coverage.
These are offline deterministic tests, NOT a claim of semantic SOTA.
"""

from __future__ import annotations

from ai_core.orchestration.ocop.answer import assemble
from ai_core.orchestration.ocop.contracts import Intent, Route
from ai_core.orchestration.ocop.verification import verify_claims
from ai_core.orchestration.ocop.workflow import OcopAgent


def row(text="Hạt sen được công nhận 3 sao.", *, unit="u1", status="verified", page=2):
    return {
        "source_id": "D",
        "evidence_unit_id": unit,
        "source_spans": [{"pdf_page": page}],
        "review_status": status,
        "text": text,
    }


def cite(unit="u1", page=2):
    return {"source_id": "D", "evidence_unit_id": unit, "pdf_page": page}


def result(rows, status=None):
    p = {"results": rows}
    if status:
        p["status"] = status
    return [{"tool": "search_regulations", "output": p}]


class Model:
    def __init__(self, answer):
        self.answer = answer

    def chat(self, *args, **kwargs):
        return self.answer


def test_marker_prefixed_wrong_claim_is_not_skipped():
    q = "[S1] Hạt sen được công nhận 5 sao.\nHạt sen được công nhận 3 sao [S1]."
    verdict = verify_claims(q, [cite()], [row()])
    assert verdict["status"] != "verified"
    assert verdict["unsupported"] >= 1


def test_multiple_claims_with_marker_prefix_are_all_checked():
    q = "[S1] Kết quả công nhận 5 sao.\nHạt sen được công nhận 3 sao [S1]."
    found = verify_claims(q, [cite()], [row()])
    assert len(found["claims"]) == 2


def test_disagreeing_cited_sources_cannot_be_marked_verified():
    a = row(unit="u1")
    b = row("Hạt sen được công nhận 5 sao.", unit="u2")
    found = verify_claims("Hạt sen được công nhận 3 sao [S1][S2].", [cite("u1"), cite("u2")], [a, b])
    assert found["status"] != "verified"
    assert found["unsupported_critical"]


def test_verbatim_two_relevant_verified_sources_can_be_verified():
    a = row(unit="u1")
    b = row(unit="u2")
    found = verify_claims("Hạt sen được công nhận 3 sao [S1][S2].", [cite("u1"), cite("u2")], [a, b])
    assert found["status"] == "verified"


def test_decimal_point_not_interpreted_as_sentence_boundary():
    a = row("Hạt sen được chấm 3.5 điểm.", unit="u1")
    found = verify_claims("Hạt sen được chấm 3.5 điểm [S1].", [cite()], [a])
    assert found["status"] == "verified"
    assert len(found["claims"]) == 1


def test_first_bad_span_falls_back_to_valid_spans():
    a = row()
    a["source_spans"] = [{"pdf_page": 0}, {"pdf_page": 5}]
    out = assemble("Hạt sen?", result([a]))
    assert out["status"] == "retrieval_only"
    assert out["citations"][0]["pdf_page"] == 5


def test_malformed_span_never_crashes_citation_assembly():
    a = row()
    a["source_spans"] = [None, "bad", {"pdf_page": 2}]
    out = assemble("Hạt sen?", result([a]))
    assert out["status"] == "retrieval_only"
    assert out["citations"][0]["pdf_page"] == 2


def test_citation_preserves_source_pdf_bbox_and_sha256():
    a = row()
    a["source_spans"] = [{"pdf_page": 2, "bbox": [10, 20, 30, 40], "source_sha256": "a" * 64}]
    out = assemble("question?", result([a]))
    assert out["citations"][0]["bbox"] == [10, 20, 30, 40]
    assert out["citations"][0]["source_sha256"] == "a" * 64
    assert out["citations"][0]["source_spans"] == [
        {"pdf_page": 2, "bbox": [10.0, 20.0, 30.0, 40.0], "source_sha256": "a" * 64}
    ]


def test_tool_error_status_cannot_sneak_evidence_into_answer():
    out = assemble(
        "Hạt sen?",
        result([row()], status="tool_unavailable"),
        llm=Model("Hạt sen được công nhận 3 sao [S1]."),
    )
    assert out["status"] == "insufficient_evidence"
    assert not out["citations"]


def test_source_identity_collision_with_conflicting_text_fails_closed():
    a = row("Hạt sen được công nhận 3 sao.")
    b = row("Hạt sen được công nhận 5 sao.")
    out = assemble("Mức sao của hạt sen?", result([a, b]), llm=Model("Hạt sen được công nhận 3 sao [S1]."))
    assert out["status"] != "generated_claims_verified"


def test_same_identity_with_mixed_review_status_fails_closed():
    a = row()
    b = row(status="needs_review")
    out = assemble("Mức sao?", result([a, b]), llm=Model("Hạt sen được công nhận 3 sao [S1]."))
    assert out["status"] != "generated_claims_verified"


def test_citation_only_claim_does_not_validate_answer():
    out = assemble("?", result([row()]), llm=Model("[S1]"))
    assert out["status"] == "citation_verification_failed"


def test_failure_fallback_never_exposes_unverified_llm_claim():
    out = assemble("?", result([row()]), llm=Model("Hạt sen được công nhận 99 sao [S1]."))
    assert out["status"] == "citation_verification_failed"
    assert "99 sao" not in out["answer"]


def test_partial_coverage_cannot_label_generated_answer_fully_verified(tmp_path):
    agent = OcopAgent(tmp_path, llm=Model("Hạt sen được công nhận 3 sao [S1]."))
    r = Route(intent=Intent.RECOGNITION_LOOKUP, strategy="structured", required_tools=["lookup_recognition"])
    state = {
        "query": "Hạt sen mấy sao?",
        "route": r.model_dump(mode="json"),
        "results": result([row()]),
        "evidence_coverage": {
            "status": "partial",
            "tools": [{"name": "lookup_recognition", "has_source_evidence": False}],
            "missing_tools": ["lookup_recognition"],
        },
    }
    ans = agent.answer(state)["answer"]
    assert ans["status"] != "generated_claims_verified"
    assert "lookup_recognition" not in ans["answer"]  # the gap is in the status, not by tool name


def test_hidden_tail_of_long_document_cannot_support_claim():
    text = "Chương trình OCOP. " * 100 + "Hạt sen được công nhận 3 sao."
    assert len(text) > 1250
    out = assemble("?", result([row(text)]), llm=Model("Hạt sen được công nhận 3 sao [S1]."))
    assert out["status"] == "citation_verification_failed"


def test_ocr_candidate_fields_are_not_treated_as_verified_legal_prose():
    r = row("Hồ sơ có tài liệu đính kèm.")
    r["fields_candidate"] = ["được công nhận 5 sao"]
    out = assemble("?", result([r]), llm=Model("Các trường OCR dự kiến: được công nhận 5 sao [S1]."))
    assert out["status"] == "citation_verification_failed"


def test_repeated_identical_evidence_unit_is_deduplicated():
    a = row()
    out = assemble("?", result([a, dict(a)]), llm=Model("Hạt sen được công nhận 3 sao [S1]."))
    assert out["status"] == "generated_claims_verified"
    assert len(out["citations"]) == 1


def test_llm_non_string_payload_is_rejected_without_crash():
    out = assemble("?", result([row()]), llm=Model(None))
    assert out["status"] in ("citation_verification_failed", "model_unavailable_retrieval_only")


def test_llm_timeout_returns_evidence_only_not_fabricated_answer():
    class TimeoutModel:
        def chat(self, *args, **kwargs):
            raise TimeoutError("offline")

    out = assemble("?", result([row()]), llm=TimeoutModel())
    assert out["status"] == "model_unavailable_retrieval_only"
    assert out["citations"][0]["source_id"] == "D"


def test_invalid_pdf_page_never_enters_generation():
    out = assemble("?", result([row(page=0)]), llm=Model("Hạt sen được công nhận 3 sao [S1]."))
    assert out["status"] == "insufficient_evidence"


def test_failure_status_no_results_with_stale_rows_is_not_grounding():
    out = assemble("?", result([row()], status="no_results"), llm=Model("Hạt sen được công nhận 3 sao [S1]."))
    assert out["status"] == "insufficient_evidence"


def test_split_claims_attaches_trailing_markers():
    from ai_core.orchestration.ocop.verification import _split_claims

    # 1. Period followed by marker
    assert _split_claims("Câu A. [S1] Câu B.") == ["Câu A. [S1]", "Câu B."]
    # 2. Marker before period
    assert _split_claims("Câu A [S1]. Câu B.") == ["Câu A [S1].", "Câu B."]
    # 3. Multiple adjacent markers after period
    assert _split_claims("Câu A. [S1][S2] Câu B.") == ["Câu A. [S1][S2]", "Câu B."]
    # 4. Marker at end of paragraph
    assert _split_claims("Câu A. [S1]") == ["Câu A. [S1]"]
    # 5. Spaced markers after period
    assert _split_claims("Câu A. [S1] [S2] Câu B.") == ["Câu A. [S1] [S2]", "Câu B."]


def test_verify_claims_assigns_citations_correctly_when_placed_after_period():
    row_lotus = row("Hạt sen được công nhận 3 sao.", unit="u1", page=2)
    row_tea = row("Chè xanh được công nhận 4 sao.", unit="u2", page=3)
    c1 = cite(unit="u1", page=2)
    c2 = cite(unit="u2", page=3)
    answer = "Hạt sen được công nhận 3 sao. [S1] Chè xanh được công nhận 4 sao. [S2]"
    v = verify_claims(answer, [c1, c2], [row_lotus, row_tea])
    assert len(v["claims"]) == 2
    assert v["claims"][0]["cited"] == [1]
    assert v["claims"][1]["cited"] == [2]
    assert v["claims"][0]["status"] == "supported"
    assert v["claims"][1]["status"] == "supported"


def test_star_claim_is_checked_against_the_source_it_cites_not_a_pool_of_verified_sources():
    from ai_core.orchestration.ocop.verification import check_sensitive_claims

    citations = [{"source_id": "a", "evidence_unit_id": "u1"}, {"source_id": "b", "evidence_unit_id": "u2"}]
    rows = [
        {
            "source_id": "a",
            "evidence_unit_id": "u1",
            "review_status": "verified",
            "text": "Sản phẩm X đạt 3 sao.",
        },
        {
            "source_id": "b",
            "evidence_unit_id": "u2",
            "review_status": "verified",
            "text": "Sản phẩm Y đạt 5 sao.",
        },
    ]
    pooled = check_sensitive_claims("Sản phẩm X đạt 5 sao [S1].", rows)
    assert pooled["unsupported_score_or_star_claims"] == []  # the old pooled check let this through
    cited = check_sensitive_claims("Sản phẩm X đạt 5 sao [S1].", rows, citations)
    assert cited["unsupported_score_or_star_claims"] == ["5 sao"]
    assert (
        check_sensitive_claims("Sản phẩm X đạt 3 sao [S1]. Sản phẩm Y đạt 5 sao [S2].", rows, citations)[
            "unsupported_score_or_star_claims"
        ]
        == []
    )
    assert check_sensitive_claims("Sản phẩm X đạt 3 sao.", rows, citations)[
        "unsupported_score_or_star_claims"
    ] == ["3 sao"]


def test_a_score_stated_in_a_table_cell_may_be_bound_to_points_in_a_claim():
    from ai_core.orchestration.ocop.verification import numeric_binding_conflict

    source = (
        "Cột: Các tiêu chí | Thang điểm\n2.2. Bao bì, ghi nhãn sản phẩm | 4\n"
        "Có nhãn, ghi nhãn hàng hóa đầy đủ | 1\nGhi nhãn đẹp và có mã truy xuất | 4\n"
        "Phần A SẢN PHẨM (40 Điểm)"
    )
    assert not numeric_binding_conflict("Tiêu chí có thang điểm 4: nhãn đầy đủ được 1 điểm; có mã truy xuất được 4 điểm.", source)
    assert numeric_binding_conflict("Nhãn đầy đủ được 7 điểm.", "Nhãn đầy đủ được 1 điểm.")
