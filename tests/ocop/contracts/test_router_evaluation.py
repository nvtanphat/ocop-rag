"""Evaluate the actual required tools without erasing the historical lane metric."""

from ai_core.orchestration.ocop.contracts import Intent, Route
from ai_core.orchestration.ocop.retrieval_strategy import RetrievalPath
from tools.evaluate_router import score


def question(**extra):
    return {
        "id": "test", "question": "Sản phẩm được công nhận thế nào?", "history": [], "tags": [],
        "gold_intent": "RECOGNITION_LOOKUP", "gold_lane": "PINPOINT", "gold_clarify": False,
        "in_scope": True, "gold_slots": {}, **extra,
    }


def test_optional_graph_does_not_change_the_required_tool_lane():
    route = Route(
        intent=Intent.RECOGNITION_LOOKUP, strategy="structured", retrieval_path=RetrievalPath.HYBRID_GRAPH,
        required_tools=["lookup_recognition"], secondary_tools=["search_graph", "search_regulations"],
    )
    result = score(question(), route)
    assert result["lane"] == "HYBRID_GRAPH" and not result["lane_ok"]
    assert result["primary_lane"] == "PINPOINT" and result["primary_lane_ok"]
    assert result["required_tools"] == ["lookup_recognition"]
    assert result["tool_gold"] is False


def test_optional_taxonomy_cannot_hide_a_missing_required_lookup():
    route = Route(
        intent=Intent.RECOGNITION_LOOKUP, strategy="hybrid", retrieval_path=RetrievalPath.PINPOINT,
        required_tools=["search_regulations"], secondary_tools=["lookup_product_subgroup"],
    )
    result = score(question(gold_required_tools=["lookup_recognition"]), route)
    assert result["lane_ok"] and not result["primary_lane_ok"]
    assert result["required_tools_hit"] == 0
    assert result["required_tools_total"] == 1


def test_tool_gold_scores_allowable_and_forbidden_tools_separately():
    route = Route(
        intent=Intent.RECOGNITION_LOOKUP, strategy="structured", required_tools=["lookup_recognition"],
        secondary_tools=["search_graph"],
    )
    result = score(question(
        gold_required_tools=["lookup_recognition"], gold_allowed_tools=["lookup_recognition"],
        gold_forbidden_tools=["search_graph"],
    ), route)
    assert result["required_tools_hit"] == result["required_tools_total"] == 1
    assert result["forbidden_tools"] == ["search_graph"]
    assert result["unexpected_tools"] == ["search_graph"]
