"""OCOP test path configuration; production dependencies are not monkeypatched."""

from __future__ import annotations
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_LLM_ENV_PREFIXES = ("OCOP_EXTRACT_", "OCOP_ANSWER_")


@pytest.fixture(autouse=True)
def _hermetic_llm_config(monkeypatch):
    """Tests never read the developer's .env (it may hold a paid API key) or inherit its LLM choice."""
    import ai_core.orchestration.ocop.llm as llm

    monkeypatch.setattr(llm, "load_env_file", lambda path=None: None)
    for key in list(os.environ):
        if key.startswith(_LLM_ENV_PREFIXES):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """Exercise the actual application with isolated corpus/session dependencies."""
    from fastapi.testclient import TestClient
    from backend.api import ocop_routes
    from backend.api.ocop_main import app
    from ai_core.orchestration.ocop.sessions import SessionStore

    data = tmp_path / "data/processed/ocop"
    (data / "index").mkdir(parents=True)
    (data / "index/manifest.json").write_text('{"corpus_version":"fixture","source_complete":true}')
    monkeypatch.setattr(ocop_routes, "ROOT", tmp_path)
    monkeypatch.setattr(ocop_routes, "DATA", data)
    monkeypatch.setattr(ocop_routes, "default_store", SessionStore())
    monkeypatch.setattr(ocop_routes.OcopSystemPipeline, "status", lambda *a, **k: {"state": "ready"})
    ocop_routes._agent.cache_clear()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    ocop_routes._agent.cache_clear()
