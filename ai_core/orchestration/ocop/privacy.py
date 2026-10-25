"""Masking of identifiers in text that is persisted (session memory, workflow checkpoints)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

_ROOT = Path(__file__).resolve().parents[3]


class Redaction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    pattern: str
    replacement: str

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value):
        re.compile(value)
        return value


class PrivacyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int
    redactions: list[Redaction]

    def regex(self, name: str) -> re.Pattern:
        return re.compile(next(r.pattern for r in self.redactions if r.name == name))


@lru_cache(maxsize=2)
def _load(path: str, mtime: int) -> PrivacyConfig:
    return PrivacyConfig.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def get_privacy(root: Path | None = None) -> PrivacyConfig:
    base = Path(root).resolve() if root else _ROOT
    for parent in [base, *base.parents, _ROOT]:
        candidate = parent / "configs" / "ocop_privacy.yaml"
        if candidate.is_file():
            return _load(str(candidate), candidate.stat().st_mtime_ns)
    raise FileNotFoundError("configs/ocop_privacy.yaml not found")


def redact(text: str) -> str:
    for item in get_privacy().redactions:
        text = re.sub(item.pattern, item.replacement, text)
    return text
