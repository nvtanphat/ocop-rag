"""Diacritic post-correction for OCR text, learned from the corpus's own native-text pages.

VietOCR's dominant residual error on OCOP scans is a wrong Vietnamese mark on a correct letter
skeleton (phú/phủ, quân/quản, kêm/kèm). A noisy-channel correction restricted to that confusion is
safe to generalize: candidates share the OCR token's letters once marks are removed, and a bigram
model trained on native (non-OCR) PDF text picks between them from context. Digits are never touched,
a token already attested next to its neighbours is kept, and every change is recorded beside the raw
OCR text so it stays reviewable.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
import re
import unicodedata

from ai_core.processing.ocop.layout import join_blocks_by_line

METHOD = "diacritic_bigram_noisy_channel_v2"
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def skeleton(word: str) -> str:
    """Letters with every Vietnamese mark removed; candidates for a token share its skeleton."""
    word = word.lower().replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", word) if unicodedata.category(c) != "Mn")


class DiacriticModel:
    def __init__(self, unigrams: Counter, bigrams: Counter):
        self.unigrams, self.bigrams = unigrams, bigrams
        self.total = sum(unigrams.values())
        self.by_skeleton: dict[str, list[str]] = defaultdict(list)
        for word in sorted(unigrams):
            self.by_skeleton[skeleton(word)].append(word)
        packed = json.dumps([sorted(unigrams.items()), sorted(bigrams.items())], ensure_ascii=False)
        self.sha256 = hashlib.sha256(packed.encode("utf-8")).hexdigest()

    @classmethod
    def from_lines(cls, lines) -> "DiacriticModel":
        unigrams, bigrams = Counter(), Counter()
        previous = "<s>"
        for line in lines:
            tokens = [t.lower() for t in WORD.findall(unicodedata.normalize("NFC", line))]
            unigrams.update(tokens)
            # Native PDF lines wrap mid-sentence, so context runs across line breaks.
            bigrams.update(zip([previous, *tokens], tokens))
            if tokens:
                previous = tokens[-1]
        return cls(unigrams, bigrams)

    def _log_bigram(self, left: str, right: str) -> float:
        vocabulary = len(self.unigrams) + 1
        backoff = (self.unigrams[right] + 1) / (self.total + vocabulary)
        return math.log((self.bigrams[(left, right)] + 0.1 * backoff) / (self.unigrams[left] + 0.1))

    def best(self, token: str, left: str, right: str, margin: float, channel=None) -> str | None:
        """Best replacement for `token`, or None. `channel(candidate)` is the recognizer's log-odds of
        reading `candidate` instead of `token` (None when it never considered those characters)."""
        candidates = self.by_skeleton.get(skeleton(token), [])
        if len(token) < 2 or not candidates or self.bigrams[(left, token)] + self.bigrams[(token, right)]:
            return None

        def context(word: str) -> float:
            return self._log_bigram(left, word) + self._log_bigram(word, right)

        scored = []
        for word in candidates:
            if word == token or self.bigrams[(left, word)] + self.bigrams[(word, right)] < 2:
                continue
            odds = 0.0 if channel is None else channel(word)
            if odds is not None:
                scored.append((context(word) - context(token) + odds, word))
        if not scored:
            return None
        gain, choice = max(scored)
        return choice if gain > margin else None


def _cased(original: str, replacement: str) -> str:
    if len(original) > 1 and original.isupper():
        return replacement.upper()
    return replacement[:1].upper() + replacement[1:] if original[:1].isupper() else replacement


def _channel(text: str, start: int, token: str, alternatives: dict[int, dict[str, float]]):
    """Log-odds that the recognizer read each differing character of a candidate instead of the OCR one."""
    def odds(candidate: str) -> float | None:
        if len(candidate) != len(token):
            return None
        total = 0.0
        for k, (ocr_char, new_char) in enumerate(zip(token, candidate)):
            if ocr_char == new_char:
                continue
            weighed = {c.lower(): p for c, p in alternatives.get(start + k, {}).items()}
            if new_char not in weighed or ocr_char not in weighed:
                return None
            total += math.log(weighed[new_char] / weighed[ocr_char])
        return total
    return odds


def correct_texts(texts: list[str], model: DiacriticModel, *, margin: float = 0.0,
                  alternatives: list[list[dict]] | None = None) -> tuple[list[str], list[list[dict]]]:
    """Correct a reading-ordered sequence of texts, using context across their boundaries.

    With `alternatives` (per text, VietOCR's per-character alternatives) only characters the recognizer
    itself weighed may change, and its own odds enter the score; without them every same-skeleton
    candidate is open (used for text with no recognizer posteriors).
    """
    spans = [[(m.start(), m.end(), m.group()) for m in WORD.finditer(text)] for text in texts]
    weighed = None if alternatives is None else [
        {a["i"]: {c: p for c, p in a["alts"]} for a in row} for row in alternatives]
    stream = [(i, j, w.lower()) for i, row in enumerate(spans) for j, (_, _, w) in enumerate(row)]
    chosen = {}
    for k, (i, j, token) in enumerate(stream):
        left = chosen.get(k - 1, stream[k - 1][2]) if k else "<s>"
        right = stream[k + 1][2] if k + 1 < len(stream) else "</s>"
        channel = None if weighed is None else _channel(texts[i], spans[i][j][0], token, weighed[i])
        if weighed is not None and not weighed[i]:
            continue
        replacement = model.best(token, left, right, margin, channel)
        if replacement is not None:
            chosen[k] = replacement
    corrected, changes = list(texts), [[] for _ in texts]
    for k in sorted(chosen, reverse=True):
        i, j, _ = stream[k]
        start, end, original = spans[i][j]
        value = _cased(original, chosen[k])
        corrected[i] = corrected[i][:start] + value + corrected[i][end:]
        changes[i].insert(0, {"from": original, "to": value})
    return corrected, changes


def _center_inside(box, cell) -> bool:
    return cell[0] <= (box[0] + box[2]) / 2 <= cell[2] and cell[1] <= (box[1] + box[3]) / 2 <= cell[3]


def postcorrect_artifact(artifact: dict, model: DiacriticModel, *, margin: float = 0.0) -> dict:
    """Apply diacritic correction to an OCR page artifact; raw OCR text is kept on each changed item.

    Blocks are corrected with the recognizer's alternatives; a table cell takes the corrected text of
    the blocks it contains, so cells and blocks never disagree.
    """
    if not artifact.get("ocr_engine") or artifact.get("quarantined"):
        return artifact
    count = 0
    blocks = [b for b in artifact.get("blocks", []) if isinstance(b.get("text"), str)]
    texts, changes = correct_texts([b.get("ocr_raw_text", b["text"]) for b in blocks], model, margin=margin,
                                   alternatives=[b.get("uncertain_chars") or [] for b in blocks])
    for block, text, change in zip(blocks, texts, changes):
        if change:
            block.setdefault("ocr_raw_text", block["text"])
            block["text"], block["postcorrections"] = text, change
            count += len(change)
    corrected = [b for b in blocks if b.get("postcorrections") and b.get("bbox")]
    for table in artifact.get("tables", []):
        for cell in table.get("cells", []):
            if not isinstance(cell.get("text"), str) or not cell.get("bbox"):
                continue
            text = cell.get("ocr_raw_text", cell["text"])
            inherited = []
            for block in corrected:
                if _center_inside(block["bbox"], cell["bbox"]) and block["ocr_raw_text"] in text:
                    text = text.replace(block["ocr_raw_text"], block["text"], 1)
                    inherited.extend(block["postcorrections"])
            if inherited:
                cell.setdefault("ocr_raw_text", cell["text"])
                cell["text"], cell["postcorrections"] = text, inherited
    artifact["extracted_text"] = join_blocks_by_line(artifact.get("blocks", []))
    artifact["postcorrection"] = {"method": METHOD, "model_sha256": model.sha256, "margin": margin,
                                  "changes": count, "review_status": "needs_review"}
    return artifact
