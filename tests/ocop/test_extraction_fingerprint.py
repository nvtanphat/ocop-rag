"""Extraction fingerprint and response-cache identity (provider, endpoint, model revision, parameters)."""
import pytest

from ai_core.knowledge.ocop.llm_proposals import _Cache, client_identity, semantic_profile
from ai_core.orchestration.ocop import llm as llm_mod


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(llm_mod, "load_env_file", lambda path=None: None)
    for key in ("OCOP_EXTRACT_LLM_PROVIDER", "OCOP_EXTRACT_LLM_MODEL", "OCOP_EXTRACT_OPENAI_BASE_URL", "OCOP_EXTRACT_OPENAI_API_KEY",
                "OCOP_EXTRACT_LLM_REVISION", "OCOP_OLLAMA_URL"):
        monkeypatch.delenv(key, raising=False)


def _identity(**changes):
    base = {"provider": "openai", "endpoint": "https://gateway.example/v1", "model": "m", "revision": "r1",
            "params": {"temperature": 0.1, "reasoning_budget": 2048}}
    return {**base, **changes}


@pytest.mark.parametrize("change", [{"provider": "ollama"}, {"endpoint": "https://other.example/v1"}, {"model": "m2"},
                                    {"revision": "r2"}, {"params": {"temperature": 0.7, "reasoning_budget": 2048}}])
def test_every_identity_field_changes_the_fingerprint_and_the_cache_key(change):
    assert semantic_profile(_identity(), None, 1) != semantic_profile(_identity(**change), None, 1)
    assert _Cache(None).key(_identity(), "text") != _Cache(None).key(_identity(**change), "text")


def test_gleanings_and_unit_limit_change_the_fingerprint_but_not_the_workers():
    base = semantic_profile(_identity(), None, 1)
    assert semantic_profile(_identity(), None, 2) != base and semantic_profile(_identity(), 10, 1) != base
    assert semantic_profile(_identity(), None, 1) == base      # identical run, identical fingerprint


def test_identity_of_a_client_equals_the_identity_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("OCOP_EXTRACT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OCOP_EXTRACT_LLM_MODEL", "gpt-x")
    monkeypatch.setenv("OCOP_EXTRACT_OPENAI_BASE_URL", "https://user:pw@gateway.example/v1/?token=abc")
    monkeypatch.setenv("OCOP_EXTRACT_OPENAI_API_KEY", "sk-secret-key")
    monkeypatch.setenv("OCOP_EXTRACT_LLM_REVISION", "2026-10-01")
    client = llm_mod.make_extraction_client()
    assert client_identity(client) == llm_mod.extraction_identity()
    text = repr(llm_mod.extraction_identity())
    assert "sk-secret-key" not in text and "pw" not in text and "token=abc" not in text
    assert llm_mod.extraction_identity()["endpoint"] == "https://gateway.example/v1"


def test_ollama_identity_without_credentials_needs_no_client_construction():
    assert llm_mod.extraction_identity()["provider"] == "ollama"
    assert client_identity(llm_mod.make_extraction_client()) == llm_mod.extraction_identity()
