"""Routing preserves entity identity and the cardinality of conversational references."""

import unicodedata

import pytest

from ai_core.orchestration.ocop import memory
from ai_core.orchestration.ocop.catalog import EntityCatalog
from ai_core.orchestration.ocop.router import extract_slots, route_query


PRODUCTS = ["Gạo giống ALPHA", "Gạo giống BETA", "Gạo giống GAMMA"]


def catalog():
    return EntityCatalog(
        {
            "entities": {
                "product": [{"label": label} for label in PRODUCTS],
                "organization": [{"label": "Hợp tác xã Thụy Hương"}],
            }
        }
    )


@pytest.mark.parametrize("query", ["Thúy Hương có sản phẩm nào?", "Thuy Huong có sản phẩm nào?"])
def test_partial_link_does_not_fold_accents_in_an_accented_question(query):
    assert catalog().link("organization", query) == []


@pytest.mark.parametrize(
    "query",
    [
        "Thụy Hương có sản phẩm nào?",
        "Thuy Huong co san pham nao?",
        unicodedata.normalize("NFD", "Thụy Hương có sản phẩm nào?"),
    ],
)
def test_partial_link_preserves_supported_accent_and_unicode_policy(query):
    assert [m.label for m in catalog().link("organization", query)] == ["Hợp tác xã Thụy Hương"]


@pytest.mark.parametrize(
    "query",
    [
        "ALPHA và BETA được mấy sao?",
        "alpha và beta được mấy sao?",
        "Gạo giống ALPHA và BETA được mấy sao?",
        "Gạo giống ALPHA và Gạo giống BETA được mấy sao?",
    ],
)
def test_all_explicit_products_survive_slot_extraction(query):
    slots = extract_slots(query, catalog=catalog())
    assert slots["product_names"] == PRODUCTS[:2]
    assert slots["product_name"] == PRODUCTS[0]


@pytest.mark.parametrize("separator", [", ", "; ", "\n"])
def test_list_boundaries_do_not_extend_the_previous_proper_name(separator):
    query = "ALPHA" + separator + "BETA và GAMMA được mấy sao?"
    assert extract_slots(query, catalog=catalog())["product_names"] == PRODUCTS


def test_a_partial_name_cannot_cross_a_list_boundary():
    assert catalog().link("organization", "Thụy, Hương có sản phẩm nào?") == []


@pytest.mark.parametrize("code,found", [("ABC-88", True), ("ABC-99", False)])
def test_hyphenated_codes_still_reject_a_conflicting_suffix(code, found):
    entities = EntityCatalog({"entities": {"product": [{"label": "Gạo giống ABC-88"}]}})
    assert bool(entities.link("product", code)) == found


def state_for(labels):
    state = memory.empty()
    for label in labels:
        state = memory.update(
            state,
            slots={"product_name": label},
            standalone=label + " đạt mấy sao?",
            citations=[],
            corpus_version="v",
        )
    return state


@pytest.mark.parametrize("phrase,count", [("Hai", 2), ("Ba", 3), ("3", 3), ("Cả ba", 3), ("Các", 3)])
def test_plural_reference_respects_its_quantity(phrase, count):
    slots = memory.plural_referents(phrase + " sản phẩm đó của ai?", state_for(PRODUCTS), {})
    assert slots["product_names"] == PRODUCTS[-count:]


def test_three_referents_cannot_resolve_from_two_discussed_products():
    state = state_for(PRODUCTS[:2])
    assert memory.plural_referents("Ba sản phẩm đó của ai?", state, {}) == {}
    assert memory.dangling_reference("Ba sản phẩm đó của ai?", state, {}) == "product"


def test_product_names_within_the_slot_limit_survive_memory_sanitizing():
    labels = ["Sản phẩm " + char * 65 for char in ("A", "B")]
    state = state_for(labels)
    assert memory.plural_referents("Hai sản phẩm đó của ai?", state, {})["product_names"] == labels
    assert memory.sanitize({"referents": {"product": ["X" * 129]}})["referents"]["product"] == []


def test_named_pair_is_available_to_the_next_plural_turn():
    slots = extract_slots("ALPHA và BETA được mấy sao?", catalog=catalog())
    state = memory.update(
        None, slots=slots, standalone="ALPHA và BETA được mấy sao?", citations=[], corpus_version="v"
    )
    route = route_query(
        "Hai sản phẩm đó của ai?",
        catalog=catalog(),
        session={"last_query": state["standalone"], "slots": slots, "memory": state},
    )
    assert route.slots["product_names"] == PRODUCTS[:2]
