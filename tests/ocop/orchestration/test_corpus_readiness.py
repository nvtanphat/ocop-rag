"""Explicit partial corpus mode cannot enter the production HTTP contract."""

import json
import pytest
from fastapi.testclient import TestClient
from ai_core.orchestration.ocop.workflow import OcopAgent
from backend.api.ocop_main import app


def partial_root(tmp_path):
    index = tmp_path / "data/processed/ocop/index"
    index.mkdir(parents=True)
    (index / "manifest.json").write_text(
        json.dumps(
            {
                "status": "partial_debug_not_production",
                "source_complete": False,
                "corpus_version": "synthetic-partial",
            }
        ),
        encoding="utf8",
    )
    return tmp_path


def test_partial_corpus_requires_explicit_constructor_opt_in(tmp_path):
    with pytest.raises(RuntimeError, match="partial"):
        OcopAgent(partial_root(tmp_path)).ask("Xin chào")


def test_partial_debug_marks_even_clarification_and_ignores_context_override(tmp_path):
    agent = OcopAgent(partial_root(tmp_path), allow_partial_debug=True)
    answer = agent.ask("Xem hồ sơ riêng của tôi", context={"allow_partial_debug": False})
    assert answer.status == "partial_debug_corpus"
    assert answer.claim_verification["answer_status"] in ("clarify", "out_of_scope")
    assert "partial_debug_corpus" in answer.answer
    assert answer.tools_used == []


def test_production_api_rejects_partial_debug_flag():
    response = TestClient(app).post(
        "/api/ocop/query", json={"query": "OCOP là gì", "allow_partial_debug": True}
    )
    assert response.status_code == 422
