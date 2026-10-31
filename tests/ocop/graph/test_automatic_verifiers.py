"""Deterministic checks that replace the approval step: star bands, score markers, numbers and folded children."""

from ai_core.graph.ocop.grounding import _entails, _literal_numbers, _star_band_literal
from ai_core.graph.ocop.roles import project

BAND = "a) Hạng 5 sao: Tổng điểm trung bình đạt từ 90 đến 100 điểm"
LEGEND = "Ghi chú: Dấu sao là yêu cầu tối thiểu phải đạt theo các cấp độ sao (*** - 3 sao; **** - 4 sao)"


def _star(quote, level=5, low=90, high=100):
    return {"node_id": "s", "node_type": "StarLevel", "label": f"{level} sao", "citations": [{"quote": quote}],
            "properties": {"star_level": level, "min_points": low, "max_points": high, "min_inclusive": True}}


def test_a_star_level_needs_its_label_and_every_bound_in_one_citation():
    assert _star_band_literal(_star(BAND))
    assert not _star_band_literal(_star(BAND, high=99))
    assert not _star_band_literal(_star("Tổng điểm trung bình đạt từ 90 đến 100 điểm"))


def test_numbers_are_exposed_only_when_written_in_the_citation():
    assert _literal_numbers(_star(BAND)) == {"star_level": 5, "min_points": 90, "max_points": 100, "min_inclusive": True}
    option = {"node_type": "ScoreOption", "citations": [{"quote": "Có công bố tiêu chuẩn | 3"}],
              "properties": {"points_candidate": 4}}
    assert _literal_numbers(option) == {}
    option["properties"]["points_candidate"] = 3
    assert _literal_numbers(option) == {"points": 3}


def test_a_minimum_star_marker_needs_the_marker_in_the_option_and_the_legend_mapping():
    edge = {"relation_type": "MINIMUM_FOR",
            "properties": {"marker_observed": "****", "marker_observed_in": "ocr_text"},
            "citations": [{"quote": "Có chỉ dẫn địa lý****"}, {"quote": LEGEND}]}
    star = _star(LEGEND, level=4)
    assert _entails(edge, {}, star, {})
    assert not _entails({**edge, "properties": {**edge["properties"], "marker_observed_in": "image_marker_candidate"}},
                        {}, star, {})
    assert not _entails({**edge, "citations": [{"quote": "Có chỉ dẫn địa lý***"}, {"quote": LEGEND}]}, {}, star, {})


def test_an_edge_from_a_folded_score_option_speaks_through_its_criterion():
    def node(identity, kind):
        return {"node_id": identity, "node_type": kind, "label": identity, "check": "passed", "citations": [],
                "evidence_unit_ids": [], "properties": {}}

    nodes = [node("c", "Criterion"), node("o", "ScoreOption"), node("s", "StarLevel")]
    edges = [{"edge_id": "e1", "relation_type": "HAS_OPTION", "source_entity_id": "c", "target_entity_id": "o"},
             {"edge_id": "e2", "relation_type": "MINIMUM_FOR", "source_entity_id": "o", "target_entity_id": "s"}]
    _, out = project(nodes, edges)
    assert [(e["source_entity_id"], e["relation_type"], e["target_entity_id"]) for e in out] == [("c", "SCORES_TO", "s")]
