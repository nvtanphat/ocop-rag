from pathlib import Path
from types import SimpleNamespace

from ai_core.orchestration.ocop.tools import ToolRegistry
from ai_core.orchestration.ocop.workflow import OcopAgent


def _slots(question: str) -> dict:
    agent = OcopAgent(Path("."), llm=None, retrieval_mode="sparse")
    return agent.route({"query": question, "session": {}})["route"]["slots"]


def test_the_process_of_assessing_in_a_year_names_that_years_rules_not_an_assessment_year():
    slots = _slots("So sánh quy trình đánh giá năm 2023 với năm 2026 giúp tôi.")
    assert len(slots["document_codes"]) == 2 and not slots.get("assessment_year")


def test_a_year_something_was_assessed_in_is_still_an_event_year():
    slots = _slots("Sản phẩm được đánh giá năm 2025 có sao?")
    assert slots["assessment_year"] == 2025 and not slots.get("document_codes")


def test_a_comparison_gives_each_document_turns_in_the_head_of_the_results():
    tools = ToolRegistry.__new__(ToolRegistry)
    rows = {"A": [{"n": f"A{i}"} for i in range(3)], "B": [{"n": f"B{i}"} for i in range(3)]}
    tools.dispatch = lambda name, query, slots, context, auth: {"results": list(rows[slots["document_code"]]), "status": "ok"}
    merged = tools._per_document("search_regulations", "q", {}, {}, SimpleNamespace(), ["A", "B"])
    assert [r["n"] for r in merged["results"]] == ["A0", "B0", "A1", "B1", "A2", "B2"]
