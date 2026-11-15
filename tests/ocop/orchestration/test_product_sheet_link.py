"""A named product reaches the framework's product set (criterion sheet) whose list names it; fabricated graph only."""

from __future__ import annotations

from types import SimpleNamespace

from ai_core.orchestration.ocop.tools import ToolRegistry

LABELS = {
    "s1": "1. Bộ sản phẩm: Rau, củ, quả, hạt tươi",
    "s3": "3. Bộ sản phẩm: Gạo, ngũ cốc, hạt sơ chế khác",
    "s6": "6. Bộ sản phẩm: Chế biến từ gạo, ngũ cốc",
    "s8": "8. Bộ sản phẩm: Chế biến từ thịt, thủy sản, trứng, sữa, các sản phẩm từ mật ong,",
    "s9": "9. Bộ sản phẩm: Tương, nước mắm, gia vị dạng lỏng khác",
    "s16": "16. Bộ sản phẩm: Nước khoáng thiên nhiên, nước uống đóng chai",
}


def _graph():
    nodes = {
        k: {"node_id": k, "node_type": "CriterionSheet", "source_id": "SRC", "label": v} for k, v in LABELS.items()
    }
    nodes["g"] = {"node_id": "g", "node_type": "ProductSubgroup", "source_id": "SRC", "label": "Gia vị"}
    nodes["old"] = {"node_id": "old", "node_type": "CriterionSheet", "source_id": "OLD", "label": "9. Bộ sản phẩm: Nước mắm"}
    edges = [{"relation_type": "USES_SHEET", "source_entity_id": "g", "target_entity_id": "s9"}]
    return SimpleNamespace(nodes=nodes, edges=edges)


def _link(tmp_path, query, slots=None):
    registry = ToolRegistry(tmp_path)
    registry._framework_source = lambda year=None: "SRC"
    found = registry._linked_product_sheets(_graph(), slots or {}, query)
    return None if found is None else [n["node_id"] for n in found]


def test_product_word_links_to_the_set_listing_it_with_its_subgroup(tmp_path):
    assert _link(tmp_path, "Mình làm nước mắm thì chọn nhóm nào?") == ["s9", "g"]


def test_unaccented_question_links_too(tmp_path):
    assert _link(tmp_path, "nuoc mam thuoc nhom nao") == ["s9", "g"]


def test_heading_words_of_the_list_do_not_decide_the_set(tmp_path):
    # "sản phẩm" also appears inside set 8's list; it names the kind of list, not a product.
    assert set(_link(tmp_path, "Gạo ST25 thuộc bộ sản phẩm nào?")) == {"s3", "s6"}


def test_only_the_active_framework_document_is_linked(tmp_path):
    assert "old" not in _link(tmp_path, "nước mắm")


def test_a_syllable_of_a_corpus_compound_is_not_a_product_word(tmp_path):
    # "tiêu" of "tiêu chí" must not pick the spice set listing "tiêu" (pepper).
    graph = _graph()
    graph.nodes["s10"] = {
        "node_id": "s10", "node_type": "CriterionSheet", "source_id": "SRC",
        "label": "10. Bộ sản phẩm: Gia vị khác (muối, hành, tỏi, tiêu,...)",
    }
    index = tmp_path / "data/processed/ocop/index"
    index.mkdir(parents=True)
    (index / "evidence_units.jsonl").write_text(
        "".join('{"text": "Tiêu chí đánh giá số %d"}\n' % i for i in range(50)), encoding="utf-8"
    )
    registry = ToolRegistry(tmp_path)
    registry._framework_source = lambda year=None: "SRC"
    found = registry._linked_product_sheets(graph, {}, "Gạo ST25 nếu tra tiêu chí thì xem bộ sản phẩm nào?")
    assert {n["node_id"] for n in found} == {"s3", "s6"}


def test_no_named_set_is_empty_not_a_guess(tmp_path):
    assert _link(tmp_path, "Bánh tráng thuộc nhóm nào?") == []
