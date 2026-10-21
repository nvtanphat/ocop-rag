# -*- coding: utf-8 -*-
"""Regression tests for model loading environment safety (BUG-ENV-01)."""
from __future__ import annotations
import os
import sys
from unittest.mock import MagicMock


def test_load_embedding_sets_transformers_no_tf(monkeypatch):
    monkeypatch.delenv("TRANSFORMERS_NO_TF", raising=False)
    monkeypatch.delenv("USE_TF", raising=False)
    from ai_core.retrieval.ocop.index_pipeline import _load_embedding
    _load_embedding.cache_clear()
    
    mock_st = MagicMock()
    monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)
    _load_embedding("dummy-model")
    
    assert os.environ.get("TRANSFORMERS_NO_TF") == "1"
    assert os.environ.get("USE_TF") == "0"


def test_load_reranker_sets_transformers_no_tf(monkeypatch):
    monkeypatch.delenv("TRANSFORMERS_NO_TF", raising=False)
    monkeypatch.delenv("USE_TF", raising=False)
    from ai_core.retrieval.ocop.search import _load_reranker
    _load_reranker.cache_clear()
    
    mock_st = MagicMock()
    monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)
    _load_reranker("dummy-model")
    
    assert os.environ.get("TRANSFORMERS_NO_TF") == "1"
    assert os.environ.get("USE_TF") == "0"


def test_load_model_preserves_user_env(monkeypatch):
    monkeypatch.setenv("TRANSFORMERS_NO_TF", "custom_val")
    monkeypatch.setenv("USE_TF", "custom_tf")
    from ai_core.retrieval.ocop.index_pipeline import _load_embedding
    _load_embedding.cache_clear()
    
    mock_st = MagicMock()
    monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)
    _load_embedding("dummy-model")
    
    assert os.environ.get("TRANSFORMERS_NO_TF") == "custom_val"
    assert os.environ.get("USE_TF") == "custom_tf"
