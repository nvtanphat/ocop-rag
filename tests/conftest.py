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
