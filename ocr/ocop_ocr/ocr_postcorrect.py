"""Conservative post-correction for OCR text, learned from native-text pages.

VietOCR's dominant residual error on OCOP scans is a wrong Vietnamese mark on a correct letter
skeleton (phú/phủ, quân/quản, kêm/kèm). A noisy-channel correction restricted to that confusion is
safe to generalize: candidates share the OCR token's letters once marks are removed, differ only where
the recognizer itself weighed another character, and a bigram model trained on native (non-OCR) PDF
text scores them in context together with the recognizer's odds. Score digits are never changed. One
separate OCR-symbol rule handles an isolated `2` immediately before a percentage as a likely `≥`;
every change is recorded beside the raw OCR text so it stays reviewable.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
import re
import unicodedata

from ocop_contracts.layout import join_blocks_by_line

METHOD = "diacritic_bigram_noisy_channel"
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
PERCENT_THRESHOLD_SYMBOL = re.compile(r"(?<![\d.,])2(?=\s+\d{1,2}\s*%)")
SAFE_OCOP_SPELLINGS = (
    (re.compile(r"\bhồ so\b", re.IGNORECASE), "hồ sơ"),
    (re.compile(r"\bxử ly\b", re.IGNORECASE), "xử lý"),
    (re.compile(r"\btrông phổ biến\b", re.IGNORECASE), "trồng phổ biến"),
    (re.compile(r"\bsản phẩn\b", re.IGNORECASE), "sản phẩm"),
    (re.compile(r"\bcông ty INHH\b", re.IGNORECASE), "công ty TNHH"),
    (re.compile(r"\bsử dung\b", re.IGNORECASE), "sử dụng"),
    (re.compile(r"\bđặc trưng của tinh\b", re.IGNORECASE), "đặc trưng của tỉnh"),
)
ASTERISK_MARKER_NOISE_SUFFIX = re.compile(r"(?:ese\?|\(tt|tsr|ver\.|['\"“”‘’])\s*$", re.IGNORECASE)


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

    def best(self, token: str, left: str, right: str, margin: float, channel) -> str | None:
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
            odds = channel(word)
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


def _correct_percentage_threshold_symbol(text: str) -> tuple[str, list[dict]]:
    """Correct OCR's `2 75%` rendering of `≥ 75%`, leaving the percentage digits untouched."""
    matches = list(PERCENT_THRESHOLD_SYMBOL.finditer(text))
    if not matches:
        return text, []
    corrected = PERCENT_THRESHOLD_SYMBOL.sub("≥", text)
    return corrected, [
        {"from": match.group(), "to": "≥", "reason": "isolated_2_before_percentage_threshold"}
        for match in matches
    ]


def _case_like(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _correct_safe_ocop_spellings(text: str) -> tuple[str, list[dict]]:
    changes = []
    for pattern, replacement in SAFE_OCOP_SPELLINGS:

        def replace(match):
            value = _case_like(match.group(), replacement)
            changes.append({"from": match.group(), "to": value, "reason": "safe_ocop_spelling_map"})
            return value

        text = pattern.sub(replace, text)
    return text, changes


def _has_same_line_asterisk_candidate(block: dict, tables: list[dict]) -> bool:
    box = block.get("bbox")
    if not isinstance(box, list) or len(box) != 4:
        return False
    block_height = max(0.0, float(box[3]) - float(box[1]))
    for table in tables:
        for cell in table.get("cells", []):
            if not _center_inside(box, cell.get("bbox") or []):
                continue
            for candidate in cell.get("image_marker_candidates", []):
                marker_box = candidate.get("marker_bbox")
                if (
                    candidate.get("candidate_only") is not True
                    or candidate.get("review_status") != "needs_review"
                    or not re.fullmatch(r"\*{3,}", str(candidate.get("text", "")))
                    or not isinstance(marker_box, list)
                    or len(marker_box) != 4
                ):
                    continue
                vertical_overlap = min(box[3], marker_box[3]) - max(box[1], marker_box[1])
                marker_height = max(0.0, float(marker_box[3]) - float(marker_box[1]))
                horizontal_gap = max(0.0, box[0] - marker_box[2], marker_box[0] - box[2])
                if vertical_overlap >= 0.5 * min(block_height, marker_height) and horizontal_gap <= max(
                    2.0, 0.75 * block_height
                ):
                    return True
    return False


def _strip_asterisk_marker_noise(block: dict, text: str, tables: list[dict]) -> tuple[str, list[dict]]:
    match = ASTERISK_MARKER_NOISE_SUFFIX.search(text)
    if match is None or not _has_same_line_asterisk_candidate(block, tables):
        return text, []
    return text[: match.start()].rstrip(), [
        {
            "from": match.group().strip(),
            "to": "",
            "reason": "same_line_asterisk_image_candidate",
        }
    ]


def _correct_community_share_threshold_pair(artifact: dict) -> int:
    """Recover the missing < and ≥ only in the adjacent OCOP community-share rule rows."""
    blocks = artifact.get("blocks", [])
    changes_count = 0
    for table in artifact.get("tables", []):
        columns = table.get("col_count")
        cells = table.get("cells", [])
        if not isinstance(columns, int) or columns < 2:
            continue
        for company in cells:
            if not isinstance(company.get("row"), int) or company.get("col", columns) >= columns - 1:
                continue
            company_text = str(company.get("text", "")).casefold()
            if not (
                re.search(r"công ty [ti]nhh", company_text)
                and "cộng đồng người địa phương" in company_text
                and "51%" in company_text
            ):
                continue
            cooperative = next(
                (
                    cell
                    for cell in cells
                    if cell.get("row") == company["row"] + 1 and cell.get("col") == company.get("col")
                ),
                None,
            )
            if cooperative is None:
                continue
            cooperative_text = str(cooperative.get("text", "")).casefold()
            if not (
                "htx" in cooperative_text
                and "cộng đồng người địa phương" in cooperative_text
                and "51%" in cooperative_text
            ):
                continue

            for cell, is_company in ((company, True), (cooperative, False)):
                for block in blocks:
                    if (
                        not isinstance(block.get("text"), str)
                        or "51%" not in block["text"]
                        or not _center_inside(block.get("bbox") or [], cell.get("bbox") or [])
                    ):
                        continue
                    text = block["text"]
                    if is_company:
                        match = re.search(r"(?<!\d)[?25]?\s*51%", text)
                        if match is None or re.search(r"[<≤≥=>]\s*$", text[: match.start()]):
                            continue
                        corrected = text[: match.start()].rstrip() + " <51%" + text[match.end() :]
                    else:
                        match = re.search(r"(?<!\d)[-–—?25]?\s*51%", text)
                        if match is None or re.search(r"[<≤≥=>]\s*$", text[: match.start()]):
                            continue
                        corrected = text[: match.start()].rstrip() + " ≥ 51%" + text[match.end() :]
                    block.setdefault("ocr_raw_text", text)
                    block["text"] = corrected
                    block.setdefault("postcorrections", []).append(
                        {
                            "from": text,
                            "to": corrected,
                            "reason": "adjacent_community_share_threshold_pair",
                        }
                    )
                    changes_count += 1
    return changes_count


def _channel(start: int, token: str, alternatives: dict[int, dict[str, float]]):
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


def correct_texts(
    texts: list[str], alternatives: list[list[dict]], model: DiacriticModel, *, margin: float = 0.0
) -> tuple[list[str], list[list[dict]]]:
    """Correct a reading-ordered sequence of texts, using context across their boundaries.

    `alternatives[i]` holds VietOCR's per-character alternatives for `texts[i]`. Only characters the
    recognizer itself weighed may change, and its own odds enter the score: context alone changed correct
    words that the small corpus model had not seen ("đánh giá tại" to "tài").
    """
    spans = [[(m.start(), m.end(), m.group()) for m in WORD.finditer(text)] for text in texts]
    weighed = [{a["i"]: {c: p for c, p in a["alts"]} for a in row} for row in alternatives]
    stream = [(i, j, w.lower()) for i, row in enumerate(spans) for j, (_, _, w) in enumerate(row)]
    chosen = {}
    for k, (i, j, token) in enumerate(stream):
        left = chosen.get(k - 1, stream[k - 1][2]) if k else "<s>"
        right = stream[k + 1][2] if k + 1 < len(stream) else "</s>"
        if not weighed[i]:
            continue
        replacement = model.best(token, left, right, margin, _channel(spans[i][j][0], token, weighed[i]))
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
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return False
    if not isinstance(cell, (list, tuple)) or len(cell) != 4:
        return False
    try:
        x0, y0, x1, y1 = [float(value) for value in box]
        cx0, cy0, cx1, cy1 = [float(value) for value in cell]
    except (TypeError, ValueError, OverflowError):
        return False
    return cx0 <= (x0 + x1) / 2 <= cx1 and cy0 <= (y0 + y1) / 2 <= cy1


def postcorrect_artifact(artifact: dict, model: DiacriticModel, *, margin: float = 0.0) -> dict:
    """Apply diacritic correction to an OCR page artifact; raw OCR text is kept on each changed item.

    Blocks are corrected with the recognizer's alternatives; a table cell takes the corrected text of
    the blocks it contains, so cells and blocks never disagree.
    """
    if not artifact.get("ocr_engine") or artifact.get("quarantined"):
        return artifact
    count = 0
    blocks = [b for b in artifact.get("blocks", []) if isinstance(b.get("text"), str)]
    texts, changes = correct_texts(
        [b.get("ocr_raw_text", b["text"]) for b in blocks],
        [b.get("uncertain_chars") or [] for b in blocks],
        model,
        margin=margin,
    )
    for block, text, change in zip(blocks, texts, changes):
        normalized = text
        applied = []
        for operation in block.get("ocr_normalizations") or []:
            if operation.get("kind") == "remove_leading_checkbox_token":
                token = str(operation.get("token") or "")
                prefix = token + " "
                if token and normalized.startswith(prefix):
                    normalized = normalized[len(prefix) :]
                    applied.append(operation)
        if applied:
            block["ocr_normalizations_applied"] = applied
        normalized, symbol_changes = _correct_percentage_threshold_symbol(normalized)
        normalized, spelling_changes = _correct_safe_ocop_spellings(normalized)
        normalized, marker_changes = _strip_asterisk_marker_noise(
            block, normalized, artifact.get("tables", [])
        )
        if change or normalized != block["text"]:
            block.setdefault("ocr_raw_text", block["text"])
            block["text"] = normalized
            if change or symbol_changes or spelling_changes or marker_changes:
                block["postcorrections"] = [
                    *block.get("postcorrections", []),
                    *change,
                    *symbol_changes,
                    *spelling_changes,
                    *marker_changes,
                ]
            count += len(change) + len(symbol_changes) + len(spelling_changes) + len(marker_changes)
    count += _correct_community_share_threshold_pair(artifact)
    corrected = [
        b
        for b in blocks
        if (b.get("postcorrections") or b.get("ocr_normalizations_applied")) and b.get("bbox")
    ]
    for table in artifact.get("tables", []):
        for cell in table.get("cells", []):
            if not isinstance(cell.get("text"), str) or not cell.get("bbox"):
                continue
            text = cell.get("ocr_raw_text", cell["text"])
            inherited = []
            normalizations = []
            changed = False
            for block in corrected:
                if _center_inside(block["bbox"], cell["bbox"]) and block["ocr_raw_text"] in text:
                    text = text.replace(block["ocr_raw_text"], block["text"], 1)
                    inherited.extend(block.get("postcorrections", []))
                    normalizations.extend(block.get("ocr_normalizations_applied", []))
                    changed = True
            if changed:
                cell.setdefault("ocr_raw_text", cell["text"])
                cell["text"] = text
                if inherited:
                    cell["postcorrections"] = inherited
                if normalizations:
                    cell["ocr_normalizations_applied"] = normalizations
    artifact["extracted_text"] = join_blocks_by_line(artifact.get("blocks", []))
    artifact["postcorrection"] = {
        "method": METHOD,
        "model_sha256": model.sha256,
        "margin": margin,
        "changes": count,
        "review_status": "needs_review",
    }
    return artifact
