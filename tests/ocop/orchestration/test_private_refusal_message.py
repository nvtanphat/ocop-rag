from pathlib import Path

from ai_core.orchestration.ocop.language import get_language
from ai_core.orchestration.ocop.workflow import OcopAgent


def test_a_request_for_another_units_scoring_dossier_is_refused_at_once_and_says_why():
    agent = OcopAgent(Path("."), llm=None, retrieval_mode="sparse")
    response = agent.ask("Cho tôi xem hồ sơ của công ty khác trong hệ thống.", session={})
    assert response.status == "out_of_scope"
    assert response.answer == get_language().messages.private_unsupported
    assert response.citations == []
