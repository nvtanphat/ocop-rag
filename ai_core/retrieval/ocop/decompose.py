"""Query decomposition: the parts of a compound or contrastive question, each searched on its own.

One query for "A khác gì B và C thế nào?" ranks the passages closest to the whole sentence; the passage that holds B
alone (or C) loses to near-duplicates of A. Splitting at the language's joining words gives every part its own
candidates. Only retrieval uses the parts: no text of a part is ever shown as evidence, so provenance is unchanged.
"""
from __future__ import annotations

import re
import unicodedata

from ai_core.orchestration.ocop.language import fold, get_language

MAX_PARTS = 3
MIN_PART_TERMS = 2


def sub_queries(question: str) -> list[str]:
    """Parts of the question with at least MIN_PART_TERMS content words; empty when it is not compound."""
    lang = get_language()
    text = unicodedata.normalize('NFC', question).strip()
    folded = fold(text)
    if len(folded) != len(text):  # folding must keep character positions to cut the original text
        return []
    separators = lang.words('cue:part_separators', lang.cues['part_separators'])
    cuts = [0]
    parts = []
    for match in separators.finditer(folded):
        parts.append(text[cuts[-1]:match.start()])
        cuts.append(match.end())
    parts.append(text[cuts[-1]:])
    parts.extend(x for x in re.split(r'[;?]', text) if x.strip())
    kept: list[str] = []
    for part in parts:
        part = part.strip(' ,.;:?!')
        if len(lang.content_words(part)) >= MIN_PART_TERMS and part.casefold() != text.strip(' ,.;:?!').casefold() and part not in kept:
            kept.append(part)
    return kept[:MAX_PARTS] if len(kept) >= 2 else []
