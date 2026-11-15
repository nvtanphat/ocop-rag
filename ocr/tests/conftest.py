"""Fake inference in unit tests must not contend with a real OCR run."""

import pytest


@pytest.fixture(autouse=True)
def isolated_inference_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("OCOP_OCR_PEAK_LOCK", str(tmp_path / "inference.lock"))
