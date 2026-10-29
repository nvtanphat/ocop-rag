"""Claim-level JSON answers: publish what passes every gate, drop the rest, say what is missing."""

import json

from ai_core.orchestration.ocop.answer import assemble


def row(text, *, unit="u1", status="verified", page=2):
    return {
        "source_id": "D",
        "evidence_unit_id": unit,
        "source_spans": [{"pdf_page": page}],
        "review_status": status,
        "text": text,
    }


def results(*rows):
    return [{"tool": "search_regulations", "output": {"results": list(rows)}}]


class Model:
    def __init__(self, payload, *, verdicts=None):
        self.payload = payload
        self.verdicts = verdicts or []
        self.calls = []

    def chat(self, *args, **kwargs):
        raise AssertionError("structured path expected")

    def chat_structured(self, system, user, *, schema, max_tokens=1024):
        self.calls.append(schema)
        if "verdicts" in schema["properties"]:
            return json.dumps({"verdicts": self.verdicts})
        return json.dumps(self.payload)


def test_only_supported_claims_are_published_and_gaps_are_named():
    model = Model(
        {
            "claims": [
                {"text": "Hạt sen được công nhận hạng ba sao", "sources": ["S1"]},
                {"text": "Giá bán là 99 nghìn đồng", "sources": ["S1"]},
            ],
            "missing": ["giá bán"],
        }
    )
    out = assemble(
        "Hạt sen được công nhận hạng nào?", results(row("Hạt sen được công nhận hạng ba sao.")), llm=model
    )
    assert out["status"] == "partial_claims_verified"
    assert "ba sao [S1]" in out["answer"] and "99" not in out["answer"].split("[Đã loại")[0]
    assert "Nguồn chưa trả lời: giá bán" in out["answer"]
    assert out["generation_diagnostics"]["rejected"][0]["claim"].startswith("Giá bán")
    assert model.calls and model.calls[0]["required"] == ["claims", "missing"]


def test_grounded_claim_from_unreviewed_source_is_shown_labelled_never_as_verified():
    model = Model(
        {"claims": [{"text": "Hạt sen được công nhận hạng ba sao", "sources": ["S1"]}], "missing": []}
    )
    out = assemble(
        "Hạt sen hạng nào?",
        results(row("Hạt sen được công nhận hạng ba sao.", status="needs_review")),
        llm=model,
    )
    assert out["status"] == "generated_unverified_claims"
    assert out["answer"].startswith("[LƯU Ý: Nguồn OCR/trích xuất chưa được duyệt")


def test_unreviewed_source_claim_must_still_be_grounded_in_the_cited_excerpt():
    cases = {
        "Hạt sen được nộp 2 bộ hồ sơ": "grounding_numbers_missing",  # number not in the excerpt
        "Hạt sen không được công nhận": "grounding_negation_mismatch",  # negation the excerpt lacks
        "Quy định về bao bì sản phẩm xuất khẩu": "grounding_terms_missing",  # invented content
    }
    for claim, reason in cases.items():
        model = Model({"claims": [{"text": claim, "sources": ["S1"]}], "missing": []})
        out = assemble(
            "Hạt sen hạng nào?",
            results(row("Hạt sen được công nhận hạng ba sao.", status="needs_review")),
            llm=model,
        )
        assert out["status"] == "citation_verification_failed", claim
        assert reason in out["generation_diagnostics"]["reasons"], (
            claim,
            out["generation_diagnostics"]["reasons"],
        )


def test_star_and_score_claims_from_unreviewed_sources_stay_blocked():
    model = Model({"claims": [{"text": "Sản phẩm đạt 4 sao", "sources": ["S1"]}], "missing": []})
    out = assemble(
        "Sản phẩm đạt mấy sao?",
        results(row("Sản phẩm đạt 4 sao theo OCR.", status="needs_review")),
        llm=model,
    )
    assert out["status"] == "citation_verification_failed"
    assert "unsupported_score_or_star_claims" in out["generation_diagnostics"]["reasons"]


def test_claim_without_valid_source_id_is_rejected():
    model = Model(
        {"claims": [{"text": "Hạt sen được công nhận hạng ba sao", "sources": ["S9"]}], "missing": []}
    )
    out = assemble("Hạt sen hạng nào?", results(row("Hạt sen được công nhận hạng ba sao.")), llm=model)
    assert out["status"] == "citation_verification_failed"
    assert "unknown_citation_markers" in out["generation_diagnostics"]["reasons"]


def test_score_claim_needs_verified_text_support():
    model = Model({"claims": [{"text": "Sản phẩm đạt 90 điểm", "sources": ["S1"]}], "missing": []})
    out = assemble("Sản phẩm đạt bao nhiêu điểm?", results(row("Sản phẩm được đánh giá.")), llm=model)
    assert out["status"] == "citation_verification_failed"


RECOGNITION_ROW = (
    "STT: 13; Tổ chức/cá nhân: Hợp tác xã Thụy Hương; Sản phẩm: Gạo giống HANA; Điểm đánh giá: 74,6; Xếp loại: 4 sao"
)


def _recognition_answer(claim, **kwargs):
    model = Model({"claims": [{"text": claim, "sources": ["S1"]}], "missing": []},
                  verdicts=[{"id": 0, "entails": True, "quote": RECOGNITION_ROW}])
    source = {**row(RECOGNITION_ROW), "source_id": "VN.HAIPHONG.QD525.2026"}
    return assemble("Gạo giống HANA được mấy sao, bao nhiêu điểm?", results(source), llm=model, **kwargs)


def test_a_verified_table_row_supports_a_paraphrase_with_its_label_first_score():
    # "74,6 điểm" is how people say what the cell "Điểm đánh giá: 74,6" holds; the row is verified, so it must publish.
    out = _recognition_answer("Gạo giống HANA của Hợp tác xã Thụy Hương đạt 74,6 điểm và xếp loại 4 sao")
    assert out["status"] == "generated_claims_verified", out["generation_diagnostics"]


def test_the_decision_number_in_the_source_id_is_grounded_for_a_verified_row():
    out = _recognition_answer("Gạo giống HANA của Hợp tác xã Thụy Hương xếp loại 4 sao, VN.HAIPHONG.QD525.2026")
    assert out["status"] == "generated_claims_verified", out["generation_diagnostics"]


def test_a_claim_combining_two_verified_rows_is_checked_against_both_together():
    one = {**row("STT: 10; Sản phẩm: Gạo ST25; Tổ chức: Hợp tác xã Thụy Hương; Xếp loại: 4 sao"), "source_id": "D"}
    two = {**row("STT: 11; Sản phẩm: Gạo Hạt ngọc 9; Tổ chức: Hợp tác xã Thụy Hương; Xếp loại: 4 sao", unit="u2")}
    claim = "Gạo ST25 và Gạo Hạt ngọc 9 đều có Tổ chức là Hợp tác xã Thụy Hương"
    model = Model({"claims": [{"text": claim, "sources": ["S1", "S2"]}], "missing": []},
                  verdicts=[{"id": 0, "entails": True, "quote": one["text"] + "\n" + two["text"]}])
    out = assemble("Hai sản phẩm đó của hợp tác xã nào?", results(one, two), llm=model)
    assert out["status"] == "generated_claims_verified", out["generation_diagnostics"]
    invented = Model({"claims": [{"text": claim + " từ năm 2031", "sources": ["S1", "S2"]}], "missing": []})
    bad = assemble("Hai sản phẩm đó của hợp tác xã nào?", results(one, two), llm=invented)
    assert bad["status"] == "citation_verification_failed"


def _quoted(claim, quote, status="verified", *, entails=False):
    class IndependentReview(Model):
        def chat_structured(self, system, user, *, schema, max_tokens=1024):
            if "verdicts" in schema["properties"]:
                self.calls.append(schema)
                return json.dumps({"verdicts": [{"id": 0, "entails": entails, "quote": quote}]})
            return super().chat_structured(system, user, schema=schema, max_tokens=max_tokens)
    model = IndependentReview({"claims": [{"text": claim, "sources": ["S1"], "quote": quote}], "missing": []})
    source = {**row("Điều 7. Trình tự đánh giá. 2. UBND cấp xã tiếp nhận và đánh giá hồ sơ trong 15 ngày làm việc", status=status)}
    return assemble("UBND cấp xã có bao nhiêu ngày?", results(source), llm=model)


def test_a_source_label_written_in_a_sentence_is_a_citation_not_content():
    from ai_core.orchestration.ocop.answer import _parse_claims

    claims, _ = _parse_claims(
        json.dumps(
            {
                "claims": [
                    {"text": "Dữ liệu trích xuất S1 ghi QĐ 26/2026 thay thế QĐ 148 [S11]", "sources": [], "quote": ""},
                    {"text": "Gạo ST25 đạt 4 sao", "sources": ["S2"], "quote": ""},
                ],
                "missing": [],
            }
        )
    )
    assert claims[0][1] == [1, 11] and "S1" not in claims[0][0] and "148" in claims[0][0]
    assert claims[1][0] == "Gạo ST25 đạt 4 sao"  # a product code is not a source label


def test_what_the_graph_step_found_steers_which_part_of_a_long_passage_is_shown():
    seen = []

    class Capture(Model):
        def chat_structured(self, system, user, *, schema, max_tokens=1024):
            seen.append(user)
            return super().chat_structured(system, user, schema=schema, max_tokens=max_tokens)

    filler = "Đối với các sản phẩm đã được đánh giá trước đây, văn bản cũ hết hiệu lực khi có quyết định thay thế. " * 8
    clause = "Quyết định số 148/QĐ-TTg và Quyết định số 1489/QĐ-TTg hết hiệu lực sau 60 ngày kể từ ngày có hiệu lực."
    long_row = row(filler + clause + " " + filler)
    relation = {**row("26/2026/QĐ-TTg [REPLACES] 148/QĐ-TTg", unit="u2"), "graph_edge_id": "e1"}
    out = assemble(
        "Quyết định 26 thay thế văn bản nào và khi nào các văn bản đó hết hiệu lực?",
        results(relation, long_row),
        llm=Capture({"claims": [], "missing": []}),
    )
    assert any("hết hiệu lực sau 60 ngày" in prompt for prompt in seen), out


def test_a_review_status_remark_appended_to_a_statement_is_dropped_but_the_statement_is_kept():
    from ai_core.orchestration.ocop.answer import _parse_claims

    def parse(*texts):
        claims, _ = _parse_claims(json.dumps({"claims": [{"text": t, "sources": ["S1"], "quote": ""} for t in texts], "missing": []}))
        return [c[0] for c in claims]

    assert parse("Điều 11 ghi Quyết định có hiệu lực từ ngày 22/5/2026; nội dung nguồn chưa được xác minh.") == [
        "Điều 11 ghi Quyết định có hiệu lực từ ngày 22/5/2026"
    ]
    assert parse("Có. Mục 1.6 nêu tiêu chí về môi trường; nội dung OCR này chưa được xác minh.") == [
        "Có. Mục 1.6 nêu tiêu chí về môi trường"
    ]
    assert parse("Nguồn OCR chưa được xác minh.", "Nội dung trích xuất này chưa được duyệt.") == []  # only a remark
    assert parse("Hồ sơ nộp trong 15 ngày.") == ["Hồ sơ nộp trong 15 ngày."]  # an ordinary claim is untouched


def test_every_structured_output_schema_lists_all_its_properties_as_required():
    # Providers' strict structured-output mode rejects (HTTP 400) any object whose "required" omits a property.
    from ai_core.orchestration.ocop.answer import CLAIMS_SCHEMA
    from ai_core.orchestration.ocop.entailment import SCHEMA as ENTAILMENT_SCHEMA

    def objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                yield node
            for value in node.values():
                yield from objects(value)
        elif isinstance(node, list):
            for value in node:
                yield from objects(value)

    for schema in (CLAIMS_SCHEMA, ENTAILMENT_SCHEMA):
        for obj in objects(schema):
            assert set(obj["properties"]) == set(obj["required"]), obj


def test_a_paraphrase_needs_an_independent_entailment_verdict_and_an_original_quote():
    # the paraphrase shares almost no wording with the source, so word overlap alone would reject it
    out = _quoted(
        "Cơ quan cấp xã được 15 ngày làm việc để xử lý hồ sơ",
        "UBND cấp xã tiếp nhận và đánh giá hồ sơ trong 15 ngày làm việc",
        entails=True,
    )
    assert out["status"] == "generated_claims_verified", out["generation_diagnostics"]
    assert out["claim_verification"]["claims"][0]["anchor_quote"].startswith("UBND cấp xã")
    rejected = _quoted("Cơ quan cấp xã được 15 ngày làm việc để xử lý hồ sơ",
                       "UBND cấp xã tiếp nhận và đánh giá hồ sơ trong 15 ngày làm việc", entails=False)
    assert rejected["status"] == "citation_verification_failed"


def test_a_quote_that_is_not_in_the_excerpt_or_lacks_the_claims_numbers_proves_nothing():
    invented = _quoted("Chính quyền cơ sở xử lý hồ sơ nhanh chóng", "UBND cấp xã có thể xử lý hồ sơ nhanh chóng ngay")
    anchored_ok = _quoted(
        "Chính quyền cơ sở xử lý hồ sơ nhanh chóng", "UBND cấp xã tiếp nhận và đánh giá hồ sơ trong 15 ngày làm việc"
    )
    assert anchored_ok["status"] == "citation_verification_failed"  # the source does not establish "nhanh chóng"
    assert invented["status"] == "citation_verification_failed"
    missing_number = _quoted("Cơ quan cấp xã được 30 ngày làm việc", "UBND cấp xã tiếp nhận và đánh giá hồ sơ")
    assert missing_number["status"] == "citation_verification_failed"


def test_a_claim_may_name_the_heading_label_above_the_quoted_sentence():
    body = "UBND cấp xã tiếp nhận và đánh giá hồ sơ trong 15 ngày làm việc"
    source = {**row(body), "context": {"parent_chain": ["Điều 7. Trình tự đánh giá"]}}
    model = Model(
        {"claims": [{"text": "Điều 7 quy định cấp xã có 15 ngày làm việc để tiếp nhận hồ sơ", "sources": ["S1"], "quote": body}], "missing": []},
        verdicts=[{"id": 0, "entails": True, "quote": body}],
    )
    out = assemble("UBND cấp xã có bao nhiêu ngày?", results(source), llm=model)
    assert out["status"] == "generated_claims_verified", out["generation_diagnostics"]
    wrong = Model(
        {"claims": [{"text": "Điều 9 quy định cấp xã có 15 ngày làm việc để tiếp nhận hồ sơ", "sources": ["S1"], "quote": body}], "missing": []}
    )
    assert assemble("UBND cấp xã có bao nhiêu ngày?", results(source), llm=wrong)["status"] == "citation_verification_failed"


def test_a_quote_never_overrides_the_score_and_star_check():
    out = _quoted("Hồ sơ đạt 90 điểm", "UBND cấp xã tiếp nhận và đánh giá hồ sơ trong 15 ngày làm việc")
    assert out["status"] == "citation_verification_failed"


def test_names_taken_from_a_source_id_and_the_corpus_vocabulary_are_not_new_entities():
    from ai_core.orchestration.ocop.entailment import anchored

    excerpt = "Sản phẩm: Gạo ruộng rươi ST25; Xếp loại: 4 sao\nVN.HAIPHONG.QD525.2026"
    quote = "Sản phẩm: Gạo ruộng rươi ST25; Xếp loại: 4 sao"
    claim = "Gạo ruộng rươi ST25 xếp loại 4 sao theo Quyết định 525/2026 của Hải Phòng"
    assert anchored(claim, quote, excerpt, asked="VN.HAIPHONG.QD525.2026")
    assert not anchored(claim.replace("Hải Phòng", "Đà Nẵng"), quote, excerpt, asked="VN.HAIPHONG.QD525.2026")


def test_an_uncited_unreviewed_source_does_not_label_an_answer_backed_by_verified_rows():
    model = Model({"claims": [{"text": "Gạo giống HANA xếp loại 4 sao", "sources": ["S1"]}], "missing": []},
                  verdicts=[{"id": 0, "entails": True, "quote": RECOGNITION_ROW}])
    other = row("Gạo giống ST25 xếp loại 4 sao theo OCR", unit="u2", status="needs_review")
    out = assemble("Gạo giống HANA mấy sao?", results(row(RECOGNITION_ROW), other), llm=model)
    assert out["status"] == "generated_claims_verified" and "LƯU Ý" not in out["answer"]


def test_a_wrong_score_for_a_verified_row_is_still_rejected():
    for claim in ("Gạo giống HANA đạt 76,3 điểm", "Gạo giống HANA xếp loại 5 sao"):
        out = _recognition_answer(claim)
        assert out["status"] == "citation_verification_failed", claim
        assert "unsupported_score_or_star_claims" in out["generation_diagnostics"]["reasons"]


def test_generation_is_skipped_when_the_prompt_source_does_not_cover_the_question():
    model = Model({"claims": [], "missing": []})
    out = assemble(
        "Thời hạn nộp hồ sơ đánh giá lại bao lâu?",
        results(row("Danh sách thành viên hội đồng thẩm định.")),
        llm=model,
    )
    assert out["status"] == "insufficient_context_for_generation" and not model.calls


def _catalog(**kinds):
    from ai_core.orchestration.ocop.catalog import EntityCatalog

    return EntityCatalog(
        {"entities": {k: [{"label": v, "source_ids": []} for v in vs] for k, vs in kinds.items()}}
    )


def test_generic_legal_rule_naming_star_levels_may_be_shown_when_unreviewed_and_grounded():
    text = "UBND cấp tỉnh quyết định công nhận sản phẩm OCOP 3 sao, 4 sao."
    model = Model(
        {
            "claims": [
                {"text": "UBND cấp tỉnh quyết định công nhận sản phẩm OCOP 3 sao, 4 sao", "sources": ["S1"]}
            ],
            "missing": [],
        }
    )
    out = assemble(
        "Cơ quan nào công nhận?",
        results(row(text, status="needs_review")),
        llm=model,
        catalog=_catalog(product=["Mứt Dâu"]),
    )
    assert out["status"] == "generated_unverified_claims"
    blocked = assemble(
        "Cơ quan nào công nhận?", results(row(text, status="needs_review")), llm=model
    )  # no catalog: stay blocked
    assert blocked["status"] == "citation_verification_failed"


def test_rating_of_a_catalogued_product_in_prose_stays_blocked_until_verified():
    text = "Công nhận sản phẩm Mứt Dâu đạt 4 sao."
    model = Model({"claims": [{"text": "Sản phẩm Mứt Dâu đạt 4 sao", "sources": ["S1"]}], "missing": []})
    out = assemble(
        "Mứt Dâu mấy sao?",
        results(row(text, status="needs_review")),
        llm=model,
        catalog=_catalog(product=["Mứt Dâu"]),
    )
    assert out["status"] == "citation_verification_failed"
    assert "unsupported_score_or_star_claims" in out["generation_diagnostics"]["reasons"]


def test_review_status_disclaimers_are_not_claims():
    model = Model(
        {
            "claims": [
                {"text": "Hạt sen được công nhận hạng ba sao", "sources": ["S1"]},
                {"text": "Bản OCR của tài liệu chưa được xác minh", "sources": ["S1"]},
            ],
            "missing": ["Nội dung OCR chưa được xác minh"],
        }
    )
    out = assemble(
        "Hạt sen hạng nào?",
        results(row("Hạt sen được công nhận hạng ba sao.", status="needs_review")),
        llm=model,
    )
    assert (
        out["status"] == "generated_unverified_claims"
        and "Đã loại" not in out["answer"]
        and "Nguồn chưa trả lời" not in out["answer"]
    )


def test_grounding_compares_dates_by_value_not_format():
    from ai_core.orchestration.ocop.verification import grounded_in_excerpt

    source = "Quyết định này có hiệu lực kể từ ngày 22/05/2026 và thay thế Quyết định số 1489/QĐ-TTg."
    ok, _ = grounded_in_excerpt(
        "Quyết định có hiệu lực từ ngày 22 tháng 5 năm 2026 và thay thế Quyết định số 1489/QĐ-TTg.",
        source,
        min_term_coverage=0.8,
    )
    assert ok
    bad, reason = grounded_in_excerpt(
        "Quyết định có hiệu lực từ ngày 23 tháng 5 năm 2026.", source, min_term_coverage=0.8
    )
    assert not bad and reason == "grounding_numbers_missing"


def test_numbers_in_the_cited_document_identity_are_grounded():
    unit = row("Quyết định này có hiệu lực thi hành từ ngày 22 tháng 5 năm 2026.", status="needs_review")
    unit["source_id"] = "VN.OCOP.QD26.2026"
    model = Model(
        {
            "claims": [
                {"text": "Quyết định 26/2026 có hiệu lực từ ngày 22 tháng 5 năm 2026", "sources": ["S1"]}
            ],
            "missing": [],
        }, verdicts=[{"id": 0, "entails": True, "quote": unit["text"]}],
    )
    out = assemble("QĐ26/2026 có hiệu lực từ ngày nào?", results(unit), llm=model)
    assert out["status"] == "generated_unverified_claims"


def test_grounding_accepts_a_range_member_but_not_a_false_number_from_the_question():
    from ai_core.orchestration.ocop.verification import grounded_in_excerpt

    source = "Sản phẩm OCOP đạt từ 3 sao đến 5 sao trước ngày Quyết định có hiệu lực tiếp tục có giá trị đến hết thời hạn."
    claim = "Sản phẩm OCOP đạt 4 sao trước ngày Quyết định có hiệu lực tiếp tục có giá trị đến hết thời hạn."
    assert grounded_in_excerpt(claim, source, min_term_coverage=0.8)[0]  # 4 lies in the stated 3..5
    assert (
        grounded_in_excerpt(claim.replace("4 sao", "7 sao"), source, min_term_coverage=0.8)[1]
        == "grounding_numbers_missing"
    )
    assert not grounded_in_excerpt(
        claim.replace("4 sao", "7 sao"), source, min_term_coverage=0.8, asked="đạt 7 sao"
    )[0]
    assert (
        grounded_in_excerpt(
            claim.replace("4 sao", "9 sao"), source, min_term_coverage=0.8, asked="đạt 7 sao"
        )[1]
        == "grounding_numbers_missing"
    )


def test_every_sentence_of_a_multi_sentence_claim_is_marked():
    from ai_core.orchestration.ocop.answer import _sentences

    assert _sentences("Có. Sản phẩm tiếp tục có giá trị.") == ["Có.", "Sản phẩm tiếp tục có giá trị."]


def test_grounding_allows_rejecting_the_alternative_the_user_offered():
    from ai_core.orchestration.ocop.verification import grounded_in_excerpt

    source = "Điều 1. Sửa đổi, bổ sung một số nội dung Quyết định số 148/QĐ-TTg ngày 24 tháng 02 năm 2023 của Thủ tướng Chính phủ"
    claim = "Quyết định sửa đổi, bổ sung Quyết định 148/QĐ-TTg, không phải Quyết định 26."
    assert grounded_in_excerpt(
        claim, source, min_term_coverage=0.8, asked="Sửa đổi QĐ148 hay Quyết định 26?"
    )[0]
    assert grounded_in_excerpt(claim, source, min_term_coverage=0.8, asked="QĐ1489 sửa đổi QĐ148 hay QĐ26?")[
        0
    ]
    # an alternative the user never mentioned is a new negative assertion and stays blocked
    assert not grounded_in_excerpt(claim, source, min_term_coverage=0.8, asked="Sửa đổi QĐ148?")[0]


def _unreviewed(text, page=4):
    return {
        "source_id": "VN.X.2026",
        "evidence_unit_id": "u1",
        "review_status": "needs_review",
        "table_backed": False,
        "text": text,
        "source_spans": [{"pdf_page": page}],
        "chunk_id": "c1",
        "pdf_page": page,
    }


class _Fixed:
    def __init__(self, payload, *, verdicts=None):
        self.payload = payload
        self.verdicts = verdicts or []

    def chat_structured(self, system, user, **kw):
        if "verdicts" in kw["schema"]["properties"]:
            return json.dumps({"verdicts": self.verdicts})
        return self.payload


def test_page_number_from_the_source_header_is_grounded():
    out = assemble(
        "Mẫu số 02 nằm ở trang nào?",
        [
            {
                "tool": "search_regulations",
                "output": {
                    "results": [
                        _unreviewed(
                            "Báo cáo tự đánh giá về sản phẩm Mẫu số 02 Phụ lục III ban hành kèm theo Quyết định."
                        )
                    ]
                },
            }
        ],
        llm=_Fixed(
            '{"claims":[{"text":"Mẫu số 02 Phụ lục III ban hành kèm theo Quyết định ở trang 4.","sources":["S1"]}],"missing":[]}',
            verdicts=[{"id": 0, "entails": True, "quote": "Báo cáo tự đánh giá về sản phẩm Mẫu số 02 Phụ lục III ban hành kèm theo Quyết định."}],
        ),
    )
    assert out["status"] == "generated_unverified_claims", out["generation_diagnostics"]


def test_missing_only_answer_names_the_gap_instead_of_dumping_excerpts():
    out = assemble(
        "Mẫu số 02 nằm ở trang nào?",
        [
            {
                "tool": "search_regulations",
                "output": {
                    "results": [_unreviewed("Báo cáo tự đánh giá về sản phẩm Mẫu số 02 Phụ lục III.")]
                },
            }
        ],
        llm=_Fixed(
            '{"claims":[{"text":"Mẫu 02 nằm ở trang 99 của phụ lục.","sources":["S1"]}],"missing":["trang đặt mẫu số 02"]}'
        ),
    )
    assert out["status"] == "insufficient_evidence"
    assert (
        "trang đặt mẫu số 02" in out["answer"]
        and "[S1]" not in out["answer"]
        and "VN.X.2026" not in out["answer"]
    )


def test_rejected_alternative_may_be_labelled_as_a_table_column():
    from ai_core.orchestration.ocop.verification import grounded_in_excerpt

    source = "Nguyễn Thị Hà là chủ thể của Hợp tác xã Thụy Hương"
    claim = "Nguyễn Thị Hà là chủ thể, không phải cột “người đại diện”."
    assert grounded_in_excerpt(
        claim, source, min_term_coverage=0.8, asked="Nguyễn Thị Hà là người đại diện hay chủ thể?"
    )[0]
    assert not grounded_in_excerpt(claim, source, min_term_coverage=0.8, asked="Nguyễn Thị Hà là chủ thể?")[0]


def test_a_requested_criterion_code_keeps_its_row_when_question_terms_would_pick_other_prose():
    from ai_core.orchestration.ocop.answer import _most_relevant

    prose = [
        (
            (f"S{i}", 6, f"u{i}", f"c{i}"),
            {
                "raw_text": "đánh giá lại hồ sơ yêu cầu đánh giá tiêu chí",
                "text": "đánh giá lại hồ sơ yêu cầu",
            },
            {},
            False,
        )
        for i in range(8)
    ]
    row = (
        (("S9", 28, "u9", "c9")),
        {
            "raw_text": "1.6. Bảo vệ môi trường | 3",
            "text": "1.6. Bảo vệ môi trường | 3",
            "context": {"criterion_codes": ["1.6"]},
        },
        {},
        True,
    )
    kept = _most_relevant(prose + [row], ["danh", "gia", "tieu", "yeu", "cau"], 3, None, ["1.6"])
    assert row in kept
    assert row not in _most_relevant(
        prose + [row], ["danh", "gia", "tieu", "yeu", "cau"], 3, None, []
    )  # without the facet it lost


def test_a_model_that_finds_nothing_and_names_no_gap_gets_a_plain_answer_not_a_raw_dump():
    out = assemble(
        "Điều khoản về hồ sơ?",
        results(row("Điều 1. Công nhận kết quả đánh giá.", status="needs_review")),
        llm=Model({"claims": [], "missing": []}),
    )
    assert out["status"] == "insufficient_evidence" and out["citations"]
    assert "Điều 1. Công nhận" not in out["answer"]  # no excerpt is presented as if it answered


def test_the_best_block_of_each_searched_part_keeps_its_place_even_without_a_shared_question_word():
    from ai_core.orchestration.ocop.answer import _most_relevant

    prose = [
        (
            (f"S{i}", 6, f"u{i}", f"c{i}"),
            {"raw_text": "công nhận sản phẩm đơn vị sản xuất hồ sơ", "text": "công nhận sản phẩm"},
            {},
            False,
        )
        for i in range(8)
    ]
    heading = (
        ("S9", 1, "u9", "c9"),
        {
            "raw_text": "ỦY BAN NHÂN DÂN THÀNH PHỐ HẢI PHÒNG",
            "text": "ỦY BAN NHÂN DÂN",
            "query_part": "văn bản đó do cơ quan nào ban hành",
        },
        {},
        False,
    )
    terms = ["cong", "san", "pham", "don", "vi", "co", "quan", "hanh"]
    assert heading in _most_relevant(prose + [heading], terms, 3)
    plain = (heading[0], {k: v for k, v in heading[1].items() if k != "query_part"}, {}, False)
    assert plain not in _most_relevant(prose + [plain], terms, 3)


def test_the_graph_relation_block_keeps_its_place_when_worded_unlike_the_question():
    from ai_core.orchestration.ocop.answer import _most_relevant

    prose = [
        ((f"S{i}", 6, f"u{i}", f"c{i}"), {"raw_text": "thay thế văn bản quy định", "text": "thay thế"}, {}, False)
        for i in range(8)
    ]
    clause = {"raw_text": "Quyết định số 148/QĐ-TTg hết hiệu lực kể từ ngày này", "text": "hết hiệu lực"}
    terms = ["thay", "the", "van", "ban"]
    relation = (("S9", 13, "u9", "c9"), {**clause, "graph_edge_id": "e1"}, {}, False)
    assert relation in _most_relevant(prose + [relation], terms, 3)
    plain = (relation[0], clause, {}, False)
    assert plain not in _most_relevant(prose + [plain], terms, 3)


def test_claim_may_name_the_parent_heading_shown_above_the_excerpt():
    parent = row(
        "1.1. Nguồn gốc sản phẩm: Yêu cầu: 100% sản phẩm được trồng trên địa bàn cấp tỉnh",
        status="needs_review",
    )
    parent["context"] = {
        "parent_chain": ["Bộ sản phẩm: gạo, ngũ cốc, hạt sơ chế khác", "1.1. Nguồn gốc sản phẩm"]
    }
    claim = "Tiêu chí 1.1 của bộ sản phẩm gạo, ngũ cốc, hạt sơ chế khác có dòng Yêu cầu: 100% sản phẩm được trồng trên địa bàn cấp tỉnh."
    out = assemble(
        "Tiêu chí 1.1 có yêu cầu trồng trong tỉnh không?",
        results(parent),
        llm=Model({"claims": [{"text": claim, "sources": ["S1"]}], "missing": []},
                  verdicts=[{"id": 0, "entails": True, "quote": parent["text"]}]),
    )
    assert out["status"] == "generated_unverified_claims", out["generation_diagnostics"]
    # a word that is neither in the excerpt nor in its headings is still ungrounded
    invented = claim.replace("gạo, ngũ cốc, hạt sơ chế khác", "cà phê, ca cao, hồ tiêu")
    bad = assemble(
        "Tiêu chí 1.1 có yêu cầu trồng trong tỉnh không?",
        results(parent),
        llm=Model({"claims": [{"text": invented, "sources": ["S1"]}], "missing": []}),
    )
    assert bad["status"] == "citation_verification_failed"


def test_consecutive_run_check_finds_a_run_at_a_later_occurrence_of_a_repeated_word():
    from ai_core.orchestration.ocop.verification import grounded_in_excerpt

    source = "Nguồn gốc sản phẩm Yêu cầu 100% sản phẩm trồng địa bàn tỉnh Hà Tĩnh đạt"
    claim = "sản phẩm trồng địa bàn tỉnh Hà Tĩnh"  # the run "sản phẩm trồng địa bàn tỉnh" sits at the second "sản phẩm"
    assert grounded_in_excerpt(claim, source, min_term_coverage=0.8)[0]


def test_a_gap_sharing_a_sentence_with_the_review_remark_is_kept():
    from ai_core.orchestration.ocop.answer import _parse_claims

    claims, missing = _parse_claims(
        json.dumps(
            {
                "claims": [],
                "missing": [
                    "SOURCE không nêu điều khoản về hồ sơ trong Quyết định 525; nội dung OCR chưa được xác minh.",
                    "Các đoạn OCR chưa được xác minh.",
                    "Không có mẫu số 02.",
                ],
            }
        )
    )
    assert missing == ["SOURCE không nêu điều khoản về hồ sơ trong Quyết định 525", "Không có mẫu số 02"]


def test_all_claims_rejected_but_a_gap_named_gives_the_gap_not_a_raw_dump():
    out = assemble(
        "Điều khoản về hồ sơ?",
        results(row("Điều 1. Công nhận kết quả đánh giá.", status="needs_review")),
        llm=Model(
            {
                "claims": [
                    {
                        "text": "Quyết định ghi nhận đề nghị của Hội đồng thẩm định tại Tờ trình riêng.",
                        "sources": ["S1"],
                    }
                ],
                "missing": ["SOURCE không nêu điều khoản về hồ sơ; nội dung OCR chưa được xác minh."],
            }
        ),
    )
    assert out["status"] == "insufficient_evidence" and "không nêu điều khoản về hồ sơ" in out["answer"]
    assert "Điều 1. Công nhận" not in out["answer"]
