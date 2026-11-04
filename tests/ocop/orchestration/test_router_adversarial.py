"""Router regression tests for historical, safety and multilingual edge cases."""

from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.contracts import Intent
from ai_core.orchestration.ocop.planner import build_plan


def test_tax_question_is_not_hue():
    assert route_query("Mức thuế của sản phẩm OCOP là bao nhiêu?").slots.get("region") is None


def test_generic_product_mention_not_product_name():
    assert "product_name" not in route_query("Tôi muốn đăng ký sản phẩm OCOP tại Quảng Nam").slots


def test_demonstrative_product_not_real_entity():
    assert "product_name" not in route_query("Sản phẩm này cần minh chứng gì?").slots


def test_compare_two_forms_is_not_temporal():
    route = route_query("Mẫu số 02 và mẫu 03 khác nhau ra sao?")
    assert route.intent != Intent.TEMPORAL_COMPARE
    assert "resolve_temporal_applicability" not in build_plan(route).names


def test_compare_two_evidences_is_not_temporal():
    route = route_query("So sánh hai loại giấy tờ cần nộp cho mật ong và cà phê")
    assert route.intent != Intent.TEMPORAL_COMPARE
    assert "resolve_temporal_applicability" not in build_plan(route).names


def test_negated_scoring_must_not_trigger_private_dossier():
    route = route_query("Không tính điểm, chỉ cho biết tiêu chí OCOP")
    assert route.intent == Intent.CRITERIA_LOOKUP
    assert not route.needs_clarification


def test_how_scoring_works_is_public_method_question():
    route = route_query("Tính điểm OCOP như thế nào?")
    assert route.intent == Intent.CRITERIA_LOOKUP
    assert not route.needs_clarification


def test_generic_dossier_instructions_do_not_require_auth():
    route = route_query("Hồ sơ tôi cần chuẩn bị những gì để đăng ký OCOP?")
    assert route.intent == Intent.PROCEDURE_FORM
    assert not route.needs_clarification


def test_year_must_not_be_criterion_id():
    assert "criterion_id" not in route_query("So sánh bộ tiêu chí 2026 với 2025").slots


def test_year_followup_without_keyword_preserves_prior_slots():
    session = {
        "last_query": "Tiêu chí cà phê năm 2026",
        "intent": "CRITERIA_LOOKUP",
        "slots": {"product_name": "cà phê", "years": ["2026"]},
        "capabilities": ["criteria"],
    }
    route = route_query("2025 thì thế nào?", session=session)
    assert route.intent == Intent.FOLLOWUP
    assert route.slots.get("product_name") == "cà phê"
    assert route.slots.get("years") == ["2025"]


def test_non_ocop_query_is_rejected():
    assert route_query("Công nghệ AI mới năm 2026 là gì?").intent == Intent.OUT_OF_SCOPE


def test_ocop_star_listing_is_recognition():
    assert route_query("Danh sách sản phẩm OCOP 4 sao năm 2025 ở Huế").intent == Intent.RECOGNITION_LOOKUP


def test_existing_known_classification_still_passes():
    from ai_core.orchestration.ocop.catalog import EntityCatalog

    catalog = EntityCatalog({"entities": {"product_group": [{"label": "Mật ong", "source_ids": []}]}})
    route = route_query("Mật ong thuộc nhóm nào?", catalog=catalog)
    assert route.intent == Intent.PRODUCT_CLASSIFICATION
    assert route.slots.get("product_name") == "Mật ong"


def test_catalog_name_inside_a_legal_locator_is_not_an_entity():
    from ai_core.orchestration.ocop.catalog import EntityCatalog

    # "Điều" is both the article noun and a product group (cashew) in the corpus catalog.
    catalog = EntityCatalog({"entities": {"product_group": [{"label": "Điều", "source_ids": []}]}})
    article = route_query("QĐ26/2026 Điều 7 có quy định đánh giá lại không?", catalog=catalog)
    assert article.slots["article_id"] == "7" and "product_name" not in article.slots
    assert route_query("Hạt điều thuộc nhóm nào?", catalog=catalog).slots.get("product_name") == "Điều"


def test_one_syllable_catalog_name_needs_an_entity_context():
    from ai_core.orchestration.ocop.catalog import EntityCatalog

    catalog = EntityCatalog({"entities": {"product_group": [{"label": "Điều", "source_ids": []}]}})
    assert "product_name" not in route_query("Điều kiện để sản phẩm được nâng hạng là gì?", catalog=catalog).slots
    assert route_query("Sản phẩm điều rang muối đạt mấy sao?", catalog=catalog).slots.get("product_name") == "Điều"


def test_name_inside_a_statute_title_is_not_a_product():
    from ai_core.orchestration.ocop.catalog import EntityCatalog

    catalog = EntityCatalog({"entities": {"product_group": [{"label": "thực phẩm", "source_ids": []}]}})
    assert "product_name" not in route_query("Chương I của Luật An toàn thực phẩm", catalog=catalog).slots


def test_statute_section_is_not_a_scoring_criterion():
    assert "criterion_id" not in route_query("Mục 1 Chương II Luật 17/2023 quy định gì?").slots
    assert route_query("Phiếu 1 QĐ26 tiêu chí 1.1 là gì?").slots.get("criterion_id") == "1.1"


def test_scoring_sheet_question_without_catalog_hit_is_in_scope():
    assert route_query("Mật ong rừng được chấm theo phiếu nào?").intent != Intent.OUT_OF_SCOPE


def test_asking_the_rating_of_a_named_product_is_a_recognition_lookup():
    from ai_core.orchestration.ocop.catalog import EntityCatalog

    catalog = EntityCatalog({"entities": {"product": [{"label": "Gạo giống HANA", "source_ids": []}]}})
    route = route_query("Gạo giống HANA được mấy sao?", catalog=catalog)
    assert route.intent == Intent.RECOGNITION_LOOKUP and "lookup_recognition" in build_plan(route).names
    # thresholds that define a rating are criteria, not a product's record
    assert route_query("Tiêu chí để đạt mấy sao?", catalog=catalog).intent == Intent.CRITERIA_LOOKUP


def _catalog_with(products=(), organizations=()):
    from ai_core.orchestration.ocop.catalog import EntityCatalog

    return EntityCatalog(
        {
            "entities": {
                "product": [{"label": x, "source_ids": []} for x in products],
                "organization": [{"label": x, "source_ids": []} for x in organizations],
            }
        }
    )


def test_entity_linking_uses_a_run_of_words_that_only_one_label_contains():
    catalog = _catalog_with(
        organizations=["Hợp tác xã nông nghiệp Thụy Hương", "Hợp tác xã dịch vụ Phước An", "Công ty Hichagol"]
    )
    assert [m.label for m in catalog.link("organization", "Sản phẩm của Thụy Hương có gì?")] == [
        "Hợp tác xã nông nghiệp Thụy Hương"
    ]
    # a phrase shared by several labels is a category, not a name
    assert catalog.link("organization", "Hợp tác xã là gì?") == []


def test_entity_linking_ignores_ordinary_words_and_partial_names():
    catalog = _catalog_with(
        products=["Sản phẩm từ tinh bột và sản phẩm thay thế chế biến"],
        organizations=["Hộ kinh doanh Nguyễn Thị Huyền"],
    )
    # "thay thế" occurs in one label only, but as plain description, not as a name
    assert "product_name" not in route_query("QĐ26/2026 thay thế những văn bản nào?", catalog=catalog).slots
    # "Nguyễn Thị" is the start of a longer name that the label does not have
    assert not catalog.link("organization", "Nguyễn Thị Hà là người đại diện hay chủ thể?")
    assert [m.label for m in catalog.link("organization", "Nguyễn Thị Huyền đại diện cho đơn vị nào?")] == [
        "Hộ kinh doanh Nguyễn Thị Huyền"
    ]


def test_a_question_naming_a_catalogued_entity_is_a_lookup_of_its_record():
    catalog = _catalog_with(
        products=["Gạo ruộng rươi ST25", "Mứt Atiso đỏ"], organizations=["Hợp tác xã nông nghiệp Thụy Hương"]
    )
    for q, slot in (
        ("Gạo ruộng rươi ST25 được bao nhiêu điểm?", "product_name"),
        ("Mứt Atiso đỏ của công ty nào sản xuất?", "product_name"),
        ("Thụy Hương có những sản phẩm nào đạt 4 sao?", "organization_name"),
    ):
        route = route_query(q, catalog=catalog)
        assert route.intent == Intent.RECOGNITION_LOOKUP and slot in route.slots, q
    # a stronger signal in the same question still wins
    assert route_query("Tiêu chí của Mứt Atiso đỏ là gì?", catalog=catalog).intent == Intent.CRITERIA_LOOKUP


def test_a_complete_off_topic_question_is_out_of_scope_but_a_fragment_asks_for_a_topic(monkeypatch):
    measured = lambda text: 0.3  # noqa: E731  long enough to measure, not found in the corpus
    unmeasurable = lambda text: None  # noqa: E731
    assert route_query("Hôm nay thời tiết Hà Nội thế nào?", indexed_content_bigram_coverage=measured).intent == Intent.OUT_OF_SCOPE
    assert route_query("Hôm nay thời tiết Hà Nội thế nào?", indexed_content_bigram_coverage=unmeasurable).intent == Intent.CLARIFY


def test_an_article_number_alone_asks_which_document_when_the_corpus_has_several():
    from ai_core.orchestration.ocop.catalog import EntityCatalog

    many = EntityCatalog({"entities": {"document": [{"label": "26/2026/QĐ-TTg"}, {"label": "17/2023/QH15"}]}})
    one = EntityCatalog({"entities": {"document": [{"label": "26/2026/QĐ-TTg"}]}})
    asked = route_query("Điều 5 quy định gì?", catalog=many)
    assert asked.intent == Intent.CLARIFY and asked.missing_slots == ["document_for_locator"]
    assert route_query("Điều 5 quy định gì?", catalog=one).intent != Intent.CLARIFY
    assert route_query("Điều 5 Luật Hợp tác xã quy định gì?", catalog=many).intent != Intent.CLARIFY
    assert route_query("Điều 5 QĐ26/2026 quy định gì?", catalog=many).intent == Intent.EXACT_LOOKUP
    session = {"last_query": "QĐ26/2026 Điều 6?", "slots": {"document_code": "26/2026", "article_id": "6"}}
    assert route_query("Còn Điều 7?", catalog=many, session=session).slots["document_code"] == "26/2026"


def test_asking_what_the_assistant_can_do_is_a_conversation_act():
    for q in ("Bạn có thể giúp tôi những việc gì?", "Bạn giúp được gì?", "Bạn hỗ trợ tôi những gì?"):
        assert route_query(q).intent == Intent.CONVERSATION, q


def test_a_code_word_names_the_one_product_that_carries_it():
    from ai_core.orchestration.ocop.catalog import EntityCatalog

    labels = ["Gạo ruộng rươi giống HANA", "Gạo ruộng rươi ST25", "Gạo ruộng rươi Nếp nhung"]
    catalog = EntityCatalog({"entities": {"product": [{"label": x, "source_ids": []} for x in labels]}})
    assert route_query("Còn ST25 thì sao?", catalog=catalog).slots.get("product_name") == "Gạo ruộng rươi ST25"
    assert route_query("HANA đạt mấy sao?", catalog=catalog).slots.get("product_name") == "Gạo ruộng rươi giống HANA"
    # ordinary words are shared by several labels or are not codes at all
    assert "product_name" not in route_query("Gạo ruộng rươi là gì?", catalog=catalog).slots
    assert "product_name" not in route_query("Nếp nung thế nào?", catalog=catalog).slots


def test_asking_how_long_a_certificate_lasts_is_not_a_version_applicability_question():
    route = route_query("Giấy chứng nhận OCOP có hiệu lực bao lâu?")
    assert route.intent != Intent.TEMPORAL_COMPARE and "resolve_temporal_applicability" not in build_plan(route).names
    # a question about whether a rule is still valid keeps the applicability check
    assert route_query("Quyết định 148 còn hiệu lực hay hết hiệu lực?").intent == Intent.TEMPORAL_COMPARE


def test_a_question_phrase_is_not_a_product_name():
    route = route_query("Quyết định 525 công nhận những sản phẩm mấy sao?")
    assert "product_name" not in route.slots


def test_a_locality_matches_its_source_tag_without_the_administrative_prefix():
    from ai_core.orchestration.ocop.tools import _jurisdiction_key

    assert _jurisdiction_key("Thành phố Huế") == _jurisdiction_key("Huế") == "hue"
    assert _jurisdiction_key("Hải Phòng") == "haiphong"


def test_existing_known_exact_document_still_passes():
    route = route_query("Điều 6 QĐ26/2026 quy định gì?")
    assert route.intent == Intent.EXACT_LOOKUP
    assert route.slots["document_code"] == "26/2026"


def test_a_star_level_with_a_named_place_asks_for_recorded_recognitions_unless_it_asks_for_a_rule_or_procedure():
    from ai_core.orchestration.ocop.router import route_query
    from ai_core.orchestration.ocop.contracts import Intent

    for question in ("Hải Phòng có những sản phẩm OCOP 4 sao nào?", "Những sản phẩm 4 sao của Hải Phòng là gì?"):
        route = route_query(question)
        assert route.intent == Intent.RECOGNITION_LOOKUP and "lookup_recognition" in route.required_tools
    for question in (
        "Điều kiện để sản phẩm ở Hải Phòng đạt 4 sao là gì?",
        "Hà Tĩnh nhận hồ sơ OCOP 4 sao đến khi nào?",
    ):
        assert "lookup_recognition" not in route_query(question).required_tools[:1]


PRIOR_DOSSIER = {
    "last_query": "Hồ sơ đăng ký lần đầu gồm những gì?",
    "slots": {},
    "intent": "PROCEDURE_FORM",
    "capabilities": ["procedure_form"],
}


def _scope(label, seen=None):
    def propose(text):
        if seen is not None:
            seen.append(text)
        if isinstance(label, Exception):
            raise label
        return {"intent": label}

    return propose


def test_the_model_decides_a_bare_question_inside_a_conversation_between_follow_up_and_off_topic():
    from ai_core.orchestration.ocop.router import route_query
    from ai_core.orchestration.ocop.contracts import Intent

    seen = []
    follow = route_query("Nộp ở đâu vậy bạn?", session=PRIOR_DOSSIER, llm_scope=_scope("FOLLOWUP", seen))
    assert follow.intent == Intent.FOLLOWUP
    assert seen == ["PREVIOUS: Hồ sơ đăng ký lần đầu gồm những gì?\nCURRENT: Nộp ở đâu vậy bạn?"]
    away = route_query("Giá vàng hôm nay bao nhiêu?", session=PRIOR_DOSSIER, llm_scope=_scope("OUT_OF_SCOPE"))
    assert away.intent == Intent.OUT_OF_SCOPE and "model_out_of_scope" in away.reason_codes
    topic = route_query("Mất bao lâu thì có kết quả?", session=PRIOR_DOSSIER, llm_scope=_scope("PROCEDURE_FORM"))
    assert topic.intent not in (Intent.OUT_OF_SCOPE, Intent.CLARIFY)


def test_a_label_the_model_invents_or_a_failing_model_leaves_the_deterministic_route_unchanged():
    from ai_core.orchestration.ocop.router import route_query

    baseline = route_query("Cần nộp mấy bộ?", session=PRIOR_DOSSIER)
    for proposal in ("check_certificate_eligibility", "delete_database", None, RuntimeError("offline")):
        assert route_query("Cần nộp mấy bộ?", session=PRIOR_DOSSIER, llm_scope=_scope(proposal)) == baseline


def test_the_model_is_not_asked_when_the_deterministic_tier_already_knows():
    from ai_core.orchestration.ocop.router import route_query

    calls = []
    ask = _scope("OUT_OF_SCOPE", calls)
    route_query("Điều 6 Quyết định 26/2026/QĐ-TTg quy định gì?", session=PRIOR_DOSSIER, llm_scope=ask)  # domain
    route_query("Thế còn hồ sơ nâng hạng?", session=PRIOR_DOSSIER, llm_scope=ask)  # follow-up opener
    route_query("Cho mình dự báo thời tiết ngày mai", session=PRIOR_DOSSIER, llm_scope=ask)  # explicitly off-topic
    assert calls == []


def test_without_a_conversation_the_model_may_decide_scope_but_cannot_continue_what_does_not_exist():
    from ai_core.orchestration.ocop.router import route_query
    from ai_core.orchestration.ocop.contracts import Intent

    question = "Chỉ mình cách pha cà phê sữa đá ngon nhất với nhé"
    baseline = route_query(question)
    seen = []
    assert route_query(question, llm_scope=_scope("FOLLOWUP", seen)) == baseline  # nothing to follow
    assert seen == ["CURRENT: " + question]
    assert route_query(question, llm_scope=_scope("OUT_OF_SCOPE")).intent == Intent.OUT_OF_SCOPE
    # A bare fragment with no conversation is for the rules to ask about, not for the model to guess.
    fragment = []
    route_query("Nộp ở đâu vậy bạn?", llm_scope=_scope("OUT_OF_SCOPE", fragment))
    assert fragment == []


def test_the_router_model_is_given_only_labels_the_router_accepts():
    from ai_core.orchestration.ocop import scope_model
    from ai_core.orchestration.ocop.contracts import Intent

    assert set(scope_model.INTENTS) <= {intent.value for intent in Intent}
    assert {"FOLLOWUP", "OUT_OF_SCOPE"} <= set(scope_model.INTENTS)
    assert scope_model.SCHEMA["required"] == ["intent", "secondary_intents"]
    assert scope_model.SCHEMA["additionalProperties"] is False

    class Model:
        def chat_structured(self, system, user, *, schema, max_tokens):
            self.schema, self.user = schema, user
            return '{"intent": "FOLLOWUP"}'

    model = Model()
    assert scope_model.propose(model, "CURRENT: Nộp ở đâu?") == {"intent": "FOLLOWUP"}
    assert model.schema == scope_model.SCHEMA
    for broken in (object(), type("Bad", (), {"chat_structured": lambda *a, **k: "not json"})(),
                   type("Off", (), {"chat_structured": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline"))})()):
        assert scope_model.propose(broken, "CURRENT: x") == {}


def test_the_evidence_fingerprint_is_the_one_the_built_corpus_carries():
    """A change to any file hashed by knowledge_extract.VERSION (llm.py among them) renames every evidence unit.

    The model tier of the router therefore lives in scope_model.py. Move this value only with a deliberate rebuild
    of the corpus (docs/DEVELOPMENT.md), never to make a stray edit pass."""
    from ai_core.processing.ocop import knowledge_extract

    assert knowledge_extract.VERSION == "ocop-evidence-b41daefec1f4"
