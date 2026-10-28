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


def test_existing_known_exact_document_still_passes():
    route = route_query("Điều 6 QĐ26/2026 quy định gì?")
    assert route.intent == Intent.EXACT_LOOKUP
    assert route.slots["document_code"] == "26/2026"
