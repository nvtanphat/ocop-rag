"""Recoverable chunk limits and explicit terminal omissions through proposer API."""

import json

import pytest

from ai_core.knowledge.ocop.llm_proposals import propose
from ai_core.orchestration.ocop.llm import ModelOutputTruncated
from tests.ocop.test_legal_structure import unit


def test_truncated_maximum_response_splits_chunk_and_resumes_from_cache(tmp_path):
    class Client:
        model = "test"
        calls = 0

        def chat(self, system, user, **kwargs):
            self.calls += 1
            if len(user) > 100:
                raise ModelOutputTruncated("response truncated")
            return json.dumps({"entities": [], "relations": [], "rules": []})

    client = Client()
    units = [unit("DOC.CURRENT", 1, "Nội dung nguồn pháp luật. " * 12)]
    result = propose(units, client, cache_dir=tmp_path)
    assert result["errors"] == []
    assert result["processed_unit_count"] == 1
    before = client.calls
    propose(units, client, cache_dir=tmp_path)
    assert client.calls == before


@pytest.mark.parametrize("response", ["[]", "filtered"])
def test_terminal_omission_is_cached_and_not_counted_as_transport_failure(tmp_path, response):
    class Client:
        model = "test"
        calls = 0

        def chat(self, *args, **kwargs):
            self.calls += 1
            if response == "filtered":
                raise RuntimeError("Configured OpenAI-compatible response filtered")
            return response

    client = Client()
    units = [unit("DOC.CURRENT", 1, "Nội dung nguồn được giữ lại để truy vết.")]
    result = propose(units, client, cache_dir=tmp_path)
    assert result["errors"] == []
    assert result["omissions"] and result["omissions"][0]["permanent"] is True
    assert result["processed_unit_count"] == 1
    propose(units, client, cache_dir=tmp_path)
    assert client.calls == 1
