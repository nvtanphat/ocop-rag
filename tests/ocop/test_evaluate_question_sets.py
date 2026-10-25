import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "evaluate_question_sets", Path(__file__).parents[2] / "tools" / "evaluate_question_sets.py"
)
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


class _Inner:
    model = "inner"

    def chat(self, system, user, **kwargs):
        return "answer text"

    def chat_structured(self, system, user, **kwargs):
        return "{}"

    def route(self, question):
        return {"intent": "x"}


def test_real_client_records_the_source_prompt_it_was_sent():
    client = evaluator.RecordingClient(_Inner())
    assert client.chat("sys", "[S1] Quyết định 26, PDF p.29") == "answer text"
    client.chat_structured("sys", "[S2] Quyết định 148, PDF p.3", schema={})
    assert evaluator.prompt_pages(client.prompts) == {29, 3}
    assert evaluator.first_page(client.prompts) == 29


def test_recording_client_delegates_unwrapped_attributes_without_recording_routes():
    client = evaluator.RecordingClient(_Inner())
    assert client.model == "inner"
    assert client.route("q") == {"intent": "x"}
    assert client.prompts == []
