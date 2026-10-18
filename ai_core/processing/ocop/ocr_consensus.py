"""Source-local OCR agreement for missing Vietnamese accents and literal markers.

No dictionary/legal substitutions. Numbers, base letters and existing tone marks
cannot change. All supplemental readings remain unverified OCR candidates.
"""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import re
import math
import unicodedata

import numpy as np
from PIL import ImageOps

WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def _letters(word):
    letters = []
    for char in unicodedata.normalize("NFD", word.casefold()):
        if unicodedata.combining(char) and letters:
            letters[-1][1].add(char)
        else:
            letters.append((char, set()))
    return letters


def _base(word):
    return "".join(char for char, marks in _letters(word))


def _adds_marks(original, candidate):
    old, new = _letters(original), _letters(candidate)
    return (
        len(old) == len(new)
        and old != new
        and all(a == b and old_marks <= new_marks for (a, old_marks), (b, new_marks) in zip(old, new))
    )


def accent_consensus(text: str, supporters: list[str]) -> tuple[str, list[dict]]:
    """Require agreement of two auxiliary recognizers on a uniquely aligned word."""
    text = unicodedata.normalize("NFC", text)
    words = list(WORD.finditer(text))
    keys = [_base(word.group()) for word in words]
    counts = Counter(keys)
    mappings = []
    for supporter in supporters:
        tokens = WORD.findall(unicodedata.normalize("NFC", supporter))
        folded = [_base(token) for token in tokens]
        frequency = Counter(folded)
        mapping = {}
        for match in SequenceMatcher(a=keys, b=folded, autojunk=False).get_matching_blocks():
            for offset in range(match.size):
                index, target = match.a + offset, match.b + offset
                if counts[keys[index]] == 1 and frequency[folded[target]] == 1:
                    mapping[index] = tokens[target]
        mappings.append(mapping)
    changes = []
    if len(mappings) < 2:
        return text, changes
    for index, word in enumerate(words):
        proposals = [mapping.get(index) for mapping in mappings]
        if any(value is None for value in proposals) or len({value.casefold() for value in proposals}) != 1:
            continue
        candidate = proposals[0]
        if word.group().isupper() or not _adds_marks(word.group(), candidate):
            continue
        if word.group().istitle():
            candidate = candidate.title()
        elif word.group().islower():
            candidate = candidate.lower()
        changes.append(
            {
                "start": word.start(),
                "end": word.end(),
                "text_original": word.group(),
                "text": candidate,
                "supporters": proposals,
                "review_status": "needs_review",
            }
        )
    for change in reversed(changes):
        text = text[: change["start"]] + change["text"] + text[change["end"] :]
    return text, changes


def refine_table_regions(image, page, blocks, tables, *, marker_words=None):
    """Recognize each printed table line from original pixels, preserving outside text."""
    import pytesseract
    from ai_core.processing.ocop.easy_viet_ocr import _reader, _group_lines

    additions = []
    stats = {"table_lines_examined": 0, "accent_corrections": 0, "literal_markers_added": 0}
    for block in list(blocks):
        x0, y0, x1, y1 = block["bbox"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        inside = any(
            t["bbox"][0] <= cx <= t["bbox"][2] and t["bbox"][1] <= cy <= t["bbox"][3] for t in tables
        )
        if not inside or not WORD.search(block["text"]):
            continue
        left, top = (
            max(0, int(x0 / page.rect.width * image.width) - 2),
            max(0, int(y0 / page.rect.height * image.height) - 2),
        )
        right, bottom = (
            min(image.width, int(x1 / page.rect.width * image.width) + 2),
            min(image.height, int(y1 / page.rect.height * image.height) + 2),
        )
        if right <= left or bottom <= top:
            raise ValueError("invalid_consensus_crop")
        crop = image.crop((left, top, right, bottom))
        border = 10
        data = pytesseract.image_to_data(
            ImageOps.expand(crop, border=border, fill="white"),
            lang="vie",
            config="--psm 6",
            output_type=pytesseract.Output.DICT,
            timeout=30,
        )
        stats["table_lines_examined"] += 1
        recognized = " ".join(str(value).strip() for value in data["text"] if str(value).strip())
        # Only call the additional recognizer if this view suggests missing marks.
        _, proposals = accent_consensus(block["text"], [recognized, recognized])
        if proposals:
            readings = _reader(False).readtext(
                np.asarray(crop), detail=1, paragraph=False, batch_size=4, workers=0
            )
            easy_text = " ".join(text for polygon, text, confidence in readings)
            corrected, changes = accent_consensus(block["text"], [recognized, easy_text])
            if changes:
                block.setdefault("text_original", block["text"])
                block.setdefault("confidence_original", block.get("confidence"))
                block["confidence"] = None
                block["text"] = corrected
                for change in changes:
                    change["recognizers"] = ["tesseract_vie", "easyocr_vi_en"]
                block["ocr_corrections"] = changes
                block["ocr_refinement_method"] = "source_local_consensus"
                block["review_status"] = "needs_review"
                stats["accent_corrections"] += len(changes)
        if marker_words is not None:
            continue
        existing = re.findall(r"\*+", block["text"])
        detected = re.findall(r"\*+", recognized)
        if existing and existing != detected and detected:
            block.setdefault("warnings", []).append("footnote_marker_disagreement")
        if existing:
            continue
        for index, word in enumerate(data["text"]):
            for marker in re.findall(r"\*+", str(word)):
                confidence = float(data["conf"][index]) / 100
                if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                    raise ValueError("invalid_marker_ocr_confidence")
                # Retain the whole supporting word box: do not invent character positions.
                x = (left + data["left"][index] - border) / image.width * page.rect.width
                y = (top + data["top"][index] - border) / image.height * page.rect.height
                X = x + data["width"][index] / image.width * page.rect.width
                Y = y + data["height"][index] / image.height * page.rect.height
                additions.append(
                    {
                        "block_id": block["block_id"] + f":marker:{index}",
                        "text": marker,
                        "bbox": [x, y, X, Y],
                        "method": "tesseract_localized_marker",
                        "confidence": confidence,
                        "confidence_scope": "supporting_word",
                        "review_status": "needs_review",
                        "parent_ocr_block_id": block["block_id"],
                        "supporting_ocr_text": str(word),
                        "order": len(blocks) + len(additions),
                    }
                )
                stats["literal_markers_added"] += len(marker)
    if marker_words is not None:
        stats["marker_view"] = "deskewed_page"
        for word_index, word in enumerate(marker_words):
            markers = re.findall(r"\*+", word["text"])
            if not markers:
                continue
            x, y, X, Y = word["bbox"]
            cx, cy = (x + X) / 2, (y + Y) / 2
            if not any(
                t["bbox"][0] <= cx <= t["bbox"][2] and t["bbox"][1] <= cy <= t["bbox"][3] for t in tables
            ):
                continue
            parents = [
                block
                for block in blocks
                if block["bbox"][0] <= cx <= block["bbox"][2] and block["bbox"][1] <= cy <= block["bbox"][3]
            ]
            if any(re.findall(r"\*+", block["text"]) == markers for block in parents):
                continue
            for parent in parents:
                if "*" in parent["text"]:
                    parent.setdefault("text_original", parent["text"])
                    parent.setdefault("confidence_original", parent.get("confidence"))
                    parent["confidence"] = None
                    parent.setdefault("marker_ocr_candidates", []).append(
                        {"text": parent["text"], "review_status": "needs_review", "method": parent["method"]}
                    )
                    parent["text"] = re.sub(r"\*+", "", parent["text"])
                    parent.setdefault("warnings", []).append("marker_replaced_from_deskewed_source_view")
            parent = (
                min(parents, key=lambda b: abs((b["bbox"][1] + b["bbox"][3]) / 2 - cy)) if parents else None
            )
            for marker_index, marker in enumerate(markers):
                confidence = word.get("confidence")
                if confidence is not None and (not math.isfinite(confidence) or not 0 <= confidence <= 1):
                    raise ValueError("invalid_marker_ocr_confidence")
                additions.append(
                    {
                        "block_id": f"ocr:deskewed_marker:{word_index}:{marker_index}",
                        "text": marker,
                        "bbox": list(word["bbox"]),
                        "polygon": word.get("polygon"),
                        "method": "tesseract_deskewed_marker",
                        "confidence": confidence,
                        "confidence_scope": "supporting_word",
                        "review_status": "needs_review",
                        "parent_ocr_block_id": parent["block_id"] if parent else None,
                        "supporting_ocr_text": word["text"],
                        "order": len(blocks) + len(additions),
                    }
                )
                stats["literal_markers_added"] += len(marker)
    blocks.extend(additions)
    ordered = [block for line in _group_lines(blocks) for block in line]
    for order, block in enumerate(ordered):
        block["order"] = order
    blocks[:] = ordered
    for table in tables:
        for cell in table["cells"]:
            # Preserve numeric crop recovery and all scoring-column primary values.
            if cell.get("col") == table.get("col_count", 0) - 1:
                continue
            a, b, c, d = cell["bbox"]
            snippets = [
                block["text"]
                for block in blocks
                if a <= (block["bbox"][0] + block["bbox"][2]) / 2 <= c
                and b <= (block["bbox"][1] + block["bbox"][3]) / 2 <= d
            ]
            cell.setdefault("text_original", cell.get("text", ""))
            cell["text"] = " ".join(snippets)
            cell["text_method"] = "source_local_ocr_consensus"
            cell["review_status"] = "needs_review"
    return stats
