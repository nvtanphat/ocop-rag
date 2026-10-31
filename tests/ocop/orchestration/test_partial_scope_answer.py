"""A record lookup that finds nothing in scope leaves only its own part of a compound question unanswered."""

from __future__ import annotations

from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.workflow import OcopAgent
from tests.ocop.orchestration.test_router_scope_policy import registry  # noqa: F401  (fixture)


def _state(query: str, results: list[dict]) -> dict:
    return {"query": query, "route": route_query(query).model_dump(mode="json"), "results": results}


SCOPE_MISS = {"tool": "lookup_recognition", "output": {"results": [], "status": "recognition_scope_unverified"}}
TEXT_ROWS = {
    "tool": "search_regulations",
    "optional": True,
    "output": {
        "status": "ok",
        "results": [
            {
                "source_id": "VN.TEST.2026",
                "evidence_unit_id": "backing-1",
                "chunk_id": "c1",
                "text": "Hồ sơ đánh giá cấp tỉnh do UBND cấp tỉnh tiếp nhận.",
                "source_spans": [{"pdf_page": 1}],
            }
        ],
    },
}


def test_compound_question_answers_the_other_part_and_names_the_gap(registry):  # noqa: F811
    query = "Công ty làm mứt ở Huế muốn nâng lên 5 sao, vậy sản phẩm đang ở hạng nào và hồ sơ phải qua cấp nào?"
    answer = OcopAgent(registry.root).answer(_state(query, [SCOPE_MISS, TEXT_ROWS]))["answer"]
    assert answer["status"] != "insufficient_recognition_scope"
    assert "phần hỏi về hạng/công nhận chưa được trả lời" in answer["answer"]


def test_single_part_question_still_abstains(registry):  # noqa: F811
    query = "Danh sách sản phẩm OCOP 3 sao Đà Nẵng"
    answer = OcopAgent(registry.root).answer(_state(query, [SCOPE_MISS, TEXT_ROWS]))["answer"]
    assert answer["status"] == "insufficient_recognition_scope"


def test_own_unnamed_product_star_level_is_a_premise_not_a_record_lookup():
    route = route_query("Sản phẩm bên mình ở Thành Sen đã được 3 sao, giờ xin nâng lên 4 sao thì cần thêm gì?")
    assert "recognition" not in [str(c.value if hasattr(c, "value") else c) for c in route.capabilities]
    assert "lookup_recognition" not in route.required_tools


def test_third_party_star_question_is_still_a_record_lookup():
    route = route_query("Sản phẩm OCOP 3 sao của Huế gồm những gì?")
    assert "lookup_recognition" in route.required_tools
