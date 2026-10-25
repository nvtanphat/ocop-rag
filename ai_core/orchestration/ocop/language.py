"""Vietnamese query vocabulary loaded from configs/ocop_language.yaml (single source of truth).

Text helpers fold accents on demand; vocabulary stays in the config file so adding a cue or a
document type never needs a code change. Matching is on whole words, never substrings.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1


def fold(value: str) -> str:
    """Casefold, drop combining marks and map đ→d (for accent-insensitive matching)."""
    value = unicodedata.normalize("NFD", value).casefold().replace("đ", "d")
    return "".join(c for c in value if unicodedata.category(c) != "Mn")


def has_diacritics(value: str) -> bool:
    """True when the user typed Vietnamese accents (so accented entity matches are required)."""
    decomposed = unicodedata.normalize("NFD", value).casefold()
    return "đ" in decomposed or any(unicodedata.category(c) == "Mn" for c in decomposed)


class Followup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    openers: list[str]
    pronouns: list[str]
    tail_cues: list[str] = []
    generic_question: str = "{target}{scope} nói gì?"
    scope_of: str = "của"


class Messages(BaseModel):
    model_config = ConfigDict(extra="forbid")
    out_of_scope: str
    clarify_prefix: str
    clarify_slots: dict[str, str]


class Language(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int
    stopwords: list[str]
    instruction_words: list[str]
    claim_filler: list[str] = []
    table_words: list[str] = []
    document_types: dict[str, list[str]]
    document_number_markers: dict[str, list[str]]
    structure_nouns: dict[str, list[str]]
    star_noun: list[str]
    star_levels: list[int]
    certified_star_levels: list[int]
    nationwide_labels: list[str]
    localities: list[str]
    locality_markers: list[str]
    locality_marker_blockers: list[str]
    entity_terminators: list[str]
    non_entity_phrases: list[str]
    product_markers: list[str]
    followup: Followup
    cues: dict[str, list[str] | dict[str, list[str]]]
    messages: Messages
    dialogue: dict[str, str] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _version(cls, value):
        if value != SCHEMA_VERSION:
            raise ValueError(f"ocop_language.yaml schema_version must be {SCHEMA_VERSION}")
        return value

    # ---- helpers -------------------------------------------------------------------------
    def _regex(self, key: str, phrases: list[str]) -> re.Pattern:
        cache = self.__dict__.setdefault("_rx", {})
        if key not in cache:
            ordered = sorted({fold(p) for p in phrases}, key=len, reverse=True)
            cache[key] = re.compile(
                r"(?<![a-z0-9])(?:"
                + "|".join(r"\s+".join(re.escape(w) for w in p.split()) for p in ordered)
                + r")(?![a-z0-9])"
            )
        return cache[key]

    def _accented(self, key: str, phrases: list[str]) -> frozenset[str]:
        cache = self.__dict__.setdefault("_acc", {})
        if key not in cache:
            cache[key] = frozenset(
                re.sub(r"\s+", " ", unicodedata.normalize("NFC", p).casefold()) for p in phrases
            )
        return cache[key]

    def hits(self, text: str, cue: str) -> list[str]:
        """Whole-phrase cue matches. Accent policy: a typed segment that carries accents must equal the
        configured accented phrase (so "đại diện" is not the cue "điền"); unaccented segments match folded."""
        phrases = self.cues[cue]
        if isinstance(phrases, dict):
            raise TypeError(f"cue {cue} is a mapping")
        text = unicodedata.normalize("NFC", text)
        accented = self._accented("cue:" + cue, phrases)
        found = []
        for m in self._regex("cue:" + cue, phrases).finditer(fold(text)):
            segment = text[m.start() : m.end()]
            if not has_diacritics(segment) or re.sub(r"\s+", " ", segment.casefold()) in accented:
                found.append(segment)
        return found

    def hit(self, text: str, cue: str) -> bool:
        return bool(self.hits(text, cue))

    def words(self, key: str, values: list[str]) -> re.Pattern:
        return self._regex(key, values)

    @property
    def stop(self) -> frozenset[str]:
        return frozenset(fold(w) for w in [*self.stopwords, *self.instruction_words])

    def content_words(self, text: str) -> list[str]:
        stop = self.stop
        return [w for w in re.findall(r"[a-z0-9]+", fold(text)) if len(w) > 1 and w not in stop]


def _find(root: Path | None) -> Path:
    base = Path(root).resolve() if root else _ROOT
    for parent in [base, *base.parents, _ROOT]:
        candidate = parent / "configs" / "ocop_language.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("configs/ocop_language.yaml not found")


@lru_cache(maxsize=4)
def _load(path: str, mtime: int) -> Language:
    return Language.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def get_language(root: Path | None = None) -> Language:
    path = _find(root)
    return _load(str(path), path.stat().st_mtime_ns)
