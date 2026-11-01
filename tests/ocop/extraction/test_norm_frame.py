"""Norm frame: each field is a verbatim span of the rule sentence and reaches the norm node."""

import json

from ai_core.graph.ocop.semantics import derive_semantics
from ai_core.knowledge.ocop.llm_proposals import propose

SENTENCE = "Chủ thể phải nộp hồ sơ cho Ủy ban nhân dân cấp xã trong thời hạn 15 ngày, trừ trường hợp được miễn."


def _unit(text, uid="unit:test"):
    return {"source_id": "SOURCE.TEST", "unit_id": uid, "unit_kind": "paragraph", "text": text, "structured": {},
            "spans": [{"pdf_page": 1, "bbox": [0, 0, 200, 100], "source_sha256": "a" * 64}]}


class Client:
    model = "offline"

    def __init__(self, response):
        self.response = response

    def chat(self, system, user, **kwargs):
        return json.dumps(self.response)


def test_frame_keeps_only_values_that_are_verbatim_in_the_rule_sentence():
    rule = {"kind": "obligation", "anchor": SENTENCE, "actor": "Chủ thể", "action": "nộp hồ sơ",
            "object": "Ủy ban nhân dân cấp xã", "condition": "", "exception": "trừ trường hợp được miễn",
            "time": "trong thời hạn 30 ngày"}
    result = propose([_unit(SENTENCE)], Client({"entities": [], "relations": [], "rules": [rule]}))
    frame = result["rules"][0]["frame"]
    assert frame == {"actor": "Chủ thể", "action": "nộp hồ sơ", "object": "Ủy ban nhân dân cấp xã",
                     "exception": "trừ trường hợp được miễn"}


def test_the_norm_takes_its_action_condition_and_exception_from_the_frame():
    unit = {"unit_id": "u", "source_id": "D", "unit_kind": "article", "text": SENTENCE,
            "spans": [{"pdf_page": 1, "bbox": [0, 0, 100, 100], "source_sha256": "a" * 64}]}
    frame = {"actor": "Chủ thể", "action": "nộp hồ sơ", "exception": "trừ trường hợp được miễn",
             "time": "trong thời hạn 15 ngày", "condition": "không có trong câu"}
    rule = {"node_id": "rule", "node_type": "RuleCandidate", "label": SENTENCE, "source_id": "D",
            "evidence_unit_ids": ["u"], "check": "passed", "origin": "deterministic",
            "properties": {"modality": "obligation", "frame": frame}, "corpus_version": "fixture",
            "citations": [{**unit["spans"][0], "source_id": "D", "evidence_unit_id": "u", "quote": SENTENCE}]}
    nodes, _, _ = derive_semantics([rule], [], {"u": unit}, {}, "fixture")
    norm = next(n for n in nodes if n["node_type"] == "Obligation")["properties"]
    assert norm["action"] == "nộp hồ sơ" and norm["exception"] == "trừ trường hợp được miễn"
    assert norm["time"] == "trong thời hạn 15 ngày"
    assert norm["condition"] is None and "conditions" in norm["missing_fields"]
    assert "exceptions" not in norm["missing_fields"]


def test_a_reviewed_line_without_ocr_blocks_is_never_dropped_as_table_text():
    from ai_core.processing.ocop.knowledge_extract import _lines_duplicated_in_tables

    page = {
        "extracted_text": "Phụ lục III\nSTT | Nội dung",
        "line_blocks": [[], [{"bbox": [10, 60, 90, 70], "text": "STT | Nội dung"}]],
        "tables": [{"bbox": [0, 50, 100, 100],
                    "cells": [{"row": 0, "col": 0, "text": "STT", "bbox": [10, 60, 40, 70]},
                              {"row": 0, "col": 1, "text": "Nội dung", "bbox": [40, 60, 90, 70]}]}],
    }
    assert 0 not in _lines_duplicated_in_tables(page)


def test_a_bieu_so_heading_starts_a_form_unit():
    from ai_core.processing.ocop.knowledge_extract import _segments

    kinds = [kind for kind, _ in _segments("Mở đầu\nBIỂU SỐ 3. MẪU BÁO CÁO ĐÁNH GIÁ CỦA ỦY BAN NHÂN DÂN CẤP XÃ\nNội dung")]
    assert kinds == ["paragraph", "form"]


def test_a_table_is_chunked_under_the_heading_of_its_page():
    from ai_core.retrieval.ocop.structure_chunker import _legal_heading

    table = {"structured": {"legal_heading": "Phụ lục I", "legal_heading_origin": "same_page_previous_segment"}}
    assert _legal_heading(table, "") == "Phụ lục I"


def test_any_transition_period_length_marks_a_transition():
    from ai_core.processing.ocop.temporal_candidates import _TRIGGERS

    def kinds(text):
        return [name for name, pattern in _TRIGGERS if pattern.search(text)]

    for text in ("có hiệu lực sau 90 ngày kể từ ngày ký", "áp dụng sau 6 tháng", "sau 60 ngày"):
        assert "transition_candidate" in kinds(text), text
    assert "transition_candidate" not in kinds("nộp hồ sơ trước ngày 30")
