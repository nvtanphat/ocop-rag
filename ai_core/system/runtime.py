"""Explicit dependency checks for strict full-end-to-end mode; never download models."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def verify_ollama_model(url: str, model: str) -> None:
    base = url.rstrip("/")
    try:
        with urllib.request.urlopen(base + "/api/tags", timeout=5) as response:
            payload = json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError("Ollama unavailable; start Ollama and pull qwen3.5:2b") from exc
    names = {str(item.get("name", "")) for item in payload.get("models", [])}
    if model not in names and model + ":latest" not in names:
        raise RuntimeError(f"Ollama model {model} not installed; run ollama pull {model}")
