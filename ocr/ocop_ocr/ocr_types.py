"""Shared shape for machine-extracted OCR candidates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OCRResult:
    blocks: list[dict]
    engine: str
    warnings: list[str]
    word_blocks: list[dict] | None = None
    noise_candidates: list[dict] | None = None
