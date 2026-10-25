"""Regression coverage for the two-stage OCOP router's retrieval-path labels.

The labels describe chosen tool families, not physical database availability.
"""
from ai_core.orchestration.ocop.retrieval_strategy import RetrievalPath, choose_retrieval_path
from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.planner import build_plan


def test_all_five_public_strategy_labels_are_resolvable():
    cases = [
        (['lookup_legal_unit'], RetrievalPath.PINPOINT),
        (['search_regulations'], RetrievalPath.TEXT),
        (['search_graph'], RetrievalPath.GRAPH),
        (['search_graph', 'search_regulations'], RetrievalPath.HYBRID_GRAPH),
        ([], RetrievalPath.NONE),
    ]
    for tools, expected in cases:
        assert choose_retrieval_path(tools) == expected


def test_route_label_matches_selected_tool_plan():
    questions = [
        'Điều 6 QĐ26/2026 quy định gì?',
        'OCOP là gì?',
        'Đối chiếu tiêu chí và minh chứng OCOP cần những gì?',
        'Mẫu số 02 và mẫu 03 khác nhau ra sao?',
        'Công nghệ AI mới năm 2026 là gì?',
    ]
    for query in questions:
        route = route_query(query)
        plan = build_plan(route)
        assert route.retrieval_path == choose_retrieval_path(list(plan.names))
