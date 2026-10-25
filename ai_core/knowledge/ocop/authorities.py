"""Candidate authority aliases. Identity stays scoped to its source document."""

import json
from pathlib import Path
import re
import unicodedata


CONFIG = Path(__file__).resolve().parents[3] / "configs/ocop_authorities.json"


def normalize(value):
    value = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    return " ".join("".join(c for c in value if not unicodedata.combining(c)).split())


CATALOG = json.loads(CONFIG.read_text(encoding="utf-8"))["authorities"]
ALIASES = {normalize(alias): row for row in CATALOG for alias in [row["label"], *row["aliases"]]}


def resolve(label):
    return ALIASES.get(normalize(label))


class LiteralMatch:
    def __init__(self, text, start, end):
        self.text = text
        self.first = start
        self.last = end

    def start(self):
        return self.first

    def end(self):
        return self.last

    def __getitem__(self, index):
        if index != 0:
            raise IndexError(index)
        return self.text[self.first : self.last]


PATTERN = re.compile(
    r"(?<!\w)(?:"
    + "|".join(re.escape(alias).replace(r"\ ", r"\s+") for alias in sorted(ALIASES, key=len, reverse=True))
    + r")(?!\w)"
)


def find_authorities(text):
    # Map normalized positions back to original OCR, including combining marks.
    chars = []
    positions = []
    for i, char in enumerate(text):
        normalized = unicodedata.normalize("NFD", char.casefold().replace("đ", "d"))
        for c in normalized:
            if not unicodedata.combining(c):
                chars.append(c)
                positions.append(i)
    for match in PATTERN.finditer("".join(chars)):
        end = positions[match.end() - 1] + 1
        while end < len(text) and unicodedata.combining(text[end]):
            end += 1
        yield LiteralMatch(text, positions[match.start()], end)
