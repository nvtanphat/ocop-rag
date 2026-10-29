"""Resolve document identities from the current source registry without discarding type."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ai_core.orchestration.ocop.language import fold, get_language


def document_pattern(language):
    def alternatives(values):
        return "|".join(r"\s+".join(re.escape(word) for word in fold(value).split())
                        for value in sorted(values, key=len, reverse=True))

    aliases = alternatives([word for words in language.document_types.values() for word in words])
    number_words = alternatives(language.structure_nouns.get("number", []))
    prefix = r"(?:(?:" + number_words + r")\s*)?" if number_words else ""
    number = r"(\d{1,4}(?:[/.-]\d{2,4})?(?:[/.-][a-z]+\d*)*)"
    return re.compile(r"(?<![a-z0-9])(?:" + aliases + r")\s*" + prefix + number)


class DocumentResolver:
    def __init__(self, root: Path | None = None, *, language=None):
        default = Path(__file__).resolve().parents[3]
        self.root = Path(root or os.environ.get("OCOP_ROOT") or default)
        self.language = language or get_language()

    def _sources(self):
        registry = self.root / "configs/ocop_sources.json"
        if registry.is_file():
            return json.loads(registry.read_text(encoding="utf8")).get("sources", [])
        for relative in ("data/processed/ocop/index/chunks.jsonl",
                         "data/processed/ocop/index/evidence_units.jsonl",
                         "data/processed/ocop/graph/nodes.jsonl"):
            path = self.root / relative
            if not path.is_file():
                continue
            with path.open(encoding="utf8") as stream:
                ids = {json.loads(line)["source_id"] for line in stream if line.strip()}
            if ids:
                return [{"source_id": source} for source in sorted(ids)]
        return []

    def _kind(self, prefix: str):
        text = fold(prefix).strip()
        for kind, aliases in self.language.document_types.items():
            if any(re.match(re.escape(fold(alias)) + r"(?=\s|\d|$)", text) for alias in aliases):
                return kind
        return None

    def _matches_kind(self, source, kind):
        words = set(re.findall(r"[a-z]+", fold(" ".join(str(source.get(key) or "")
                                                      for key in ("source_id", "document_number", "source_kind")))))
        aliases = {fold(alias) for alias in self.language.document_types[kind] if " " not in fold(alias)}
        return bool(words & (aliases | {fold(kind)}))

    def candidates(self, code: str):
        text = fold(str(code)).strip()
        match = document_pattern(self.language).fullmatch(text)
        kind = self._kind(text[:match.start(1)]) if match else None
        body = match.group(1) if match else text
        numbers = re.findall(r"\d+", body)
        letters = "".join(re.findall(r"[a-z]+", body))
        found = []
        for source in self._sources():
            if kind and not self._matches_kind(source, kind):
                continue
            if body == fold(str(source["source_id"])):
                found.append(source)
                continue
            declared = source.get("document_number")
            if not numbers or ("document_number" in source and not declared):
                continue
            sequences = [re.findall(r"\d+", str(value)) for value in (declared, source["source_id"]) if value]
            if not any(sequence[:len(numbers)] == numbers for sequence in sequences):
                continue
            declared_letters = "".join(re.findall(r"[a-z]+", fold(str(declared or ""))))
            if letters and letters != declared_letters:
                continue
            found.append(source)
        return found

    def resolve(self, code: str | None):
        if not code:
            return None
        ids = {source["source_id"] for source in self.candidates(str(code))}
        return next(iter(ids)) if len(ids) == 1 else None

    def qualify(self, code: str, prefix: str) -> str:
        """Keep existing number slots unless dropping the explicit type loses identity."""
        kind = self._kind(prefix)
        candidates = self.candidates(code)
        if kind and candidates and any(not self._matches_kind(source, kind) for source in candidates):
            alias = min(self.language.document_types[kind], key=len)
            return alias + " " + code
        return code
