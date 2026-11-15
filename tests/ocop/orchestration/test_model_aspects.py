"""The model may restate a compound question as sub-questions; only faithful ones reach retrieval."""

from __future__ import annotations

import json

from ai_core.orchestration.ocop import aspects

QUESTION = "Mình làm nước mắm ở Thành Sen, lúc đăng ký OCOP thì chọn nhóm nào và nộp hồ sơ ở đâu?"


class Model:
    def __init__(self, reply):
        self.reply = reply

    def chat_structured(self, system, text, *, schema, max_tokens):
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


def test_faithful_self_contained_sub_questions_are_kept():
    reply = {
        "aspects": [
            "Nước mắm thuộc nhóm sản phẩm OCOP nào khi đăng ký?",
            "Hồ sơ đăng ký OCOP nước mắm ở Thành Sen nộp ở đâu?",
        ]
    }
    assert aspects.propose(Model(reply), QUESTION) == reply["aspects"]


def test_a_single_aspect_or_the_whole_question_is_not_a_split():
    assert aspects.propose(Model({"aspects": []}), QUESTION) == []
    assert aspects.propose(Model({"aspects": [QUESTION]}), QUESTION) == []
    assert aspects.propose(Model({"aspects": ["Nước mắm thuộc nhóm sản phẩm OCOP nào?"]}), QUESTION) == []


def test_a_sub_question_that_adds_numbers_or_ignores_the_question_is_dropped():
    reply = {
        "aspects": [
            "Nước mắm thuộc nhóm sản phẩm OCOP nào khi đăng ký?",
            "Giá vàng hôm nay là bao nhiêu?",
            "Nước mắm đạt 5 sao cần bao nhiêu điểm theo Quyết định 999?",
        ]
    }
    assert aspects.propose(Model(reply), QUESTION) == []  # one faithful aspect left: not a split


def test_a_model_that_fails_or_is_absent_gives_no_aspects():
    assert aspects.propose(None, QUESTION) == []
    assert aspects.propose(Model("not json"), QUESTION) == []
    assert aspects.propose(object(), QUESTION) == []


def test_the_response_schema_lists_every_property_as_required():
    assert aspects.SCHEMA["required"] == list(aspects.SCHEMA["properties"])
    assert aspects.SCHEMA["additionalProperties"] is False
