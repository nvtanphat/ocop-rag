"""Import a whole-document reviewed Markdown file (one ``## <source_id> — trang N`` section per page).

Prose becomes the page ``extracted_text``; ``**Bảng N**`` pipe tables replace the table cells. OCR
blocks, raw ``ocr_text``/``ocr_hash`` and bbox of every cell that can still be matched are kept. Each
changed page is appended to ``review/corrections.jsonl`` before the dataset is republished.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import html
import json
from pathlib import Path
import re
import unicodedata

from .artifact_cache import write_json
from .review import _manifest, _pages, recover_import

PAGE_HEADING = re.compile(r"^## (\S+) — trang (\d+)\s*$")
# Any bold "Bảng ..." caption ("Bảng 1", "Bảng tiêu chí đánh giá", "Bảng 2 (tiếp theo)") marks a table.
TABLE_HEADING = re.compile(r"^\*\*Bảng\b[^*]*\*\*\s*$")
SEPARATOR = re.compile(r"^\|\s*:?-{3,}")


def parse_reviewed(path: Path) -> dict[tuple[str, int], tuple[str, list[list[list[str]]]]]:
    """Return ``{(source_id, pdf_page): (prose, tables)}``; each table is a list of rows of cell texts."""
    sections: dict[tuple[str, int], list[str]] = {}
    key = None
    for line in path.read_text(encoding="utf-8").splitlines():
        match = PAGE_HEADING.match(line)
        if match:
            key = (match[1], int(match[2]))
            if key in sections:
                raise ValueError(f"duplicate page section: {key}")
            sections[key] = []
        elif key is not None:
            sections[key].append(line)
    parsed = {}
    for key, lines in sections.items():
        prose, tables, current = [], [], None
        for index, line in enumerate(lines):
            if TABLE_HEADING.match(line):
                current = []
                tables.append(current)
            elif current is None and line.startswith("|") and _starts_table(lines, index):
                # A pipe table without a caption is still a table, not prose.
                current = []
                tables.append(current)
                current.append(_cells(line))
            elif current is not None and line.startswith("|"):
                if not SEPARATOR.match(line):
                    current.append(_cells(line))
            elif current is not None and not line.strip():
                continue
            else:
                current = None
                prose.append(_plain(line))
        parsed[key] = ("\n".join(prose).strip("\n"), tables)
    return parsed


def _plain(line: str) -> str:
    """Drop Markdown presentation the reviewer added (``# heading``, whole-line ``**bold**``).

    Only whole-line bold is unwrapped: ``****`` inside a line is the star-level marker and must stay.
    """
    text = re.sub(r"^(\s*)#{1,6}\s+", r"\1", line)
    match = re.match(r"^(\s*)\*\*([^*].*?[^*])\*\*(\s*)$", text)
    return match[1] + match[2] + match[3] if match else text


def _cells(line: str) -> list[str]:
    inner = line.strip()[1:-1] if line.strip().endswith("|") else line.strip()[1:]
    return [html.unescape(c.strip()) for c in re.split(r"(?<!\\)\|", inner)]


def _starts_table(lines: list[str], index: int) -> bool:
    """A Markdown table header: this pipe row is followed by a ``| --- |`` separator row."""
    following = next((ln for ln in lines[index + 1 :] if ln.strip()), "")
    return bool(SEPARATOR.match(following.strip()))


def _fold_tokens(text: str) -> list[str]:
    folded = []
    for word in text.split():
        word = unicodedata.normalize("NFD", word.casefold()).replace("đ", "d")
        word = re.sub(r"[^a-z0-9]", "", "".join(c for c in word if not unicodedata.combining(c)))
        if word:
            folded.append(word)
    return folded


def align_line_blocks(prose: str, blocks: list[dict]) -> list[list[dict]]:
    """For each reviewed prose line, the OCR blocks (id and bbox) it was read from.

    The reviewer re-flows lines and fixes characters, so the text no longer equals the OCR block stream. Tokens are
    aligned monotonically; a block belongs to the line holding most of its matched tokens. Lines with no matching
    block keep an empty list and fall back to page-level citation.
    """
    lines = prose.splitlines()
    ocr_blocks = [b for b in blocks if isinstance(b, dict) and isinstance(b.get("text"), str) and b.get("bbox")]
    line_tokens, line_of = [], []
    for index, line in enumerate(lines):
        for token in _fold_tokens(line):
            line_tokens.append(token)
            line_of.append(index)
    block_tokens, block_of = [], []
    for index, block in enumerate(ocr_blocks):
        for token in _fold_tokens(block["text"]):
            block_tokens.append(token)
            block_of.append(index)
    votes: dict[int, dict[int, int]] = {}
    for a, b, size in SequenceMatcher(None, line_tokens, block_tokens, autojunk=False).get_matching_blocks():
        for k in range(size):
            tally = votes.setdefault(block_of[b + k], {})
            tally[line_of[a + k]] = tally.get(line_of[a + k], 0) + 1
    result: list[list[dict]] = [[] for _ in lines]
    for index, tally in sorted(votes.items()):
        line = max(tally, key=tally.get)
        if tally[line] >= max(1, len(_fold_tokens(ocr_blocks[index]["text"])) // 2):
            block = ocr_blocks[index]
            result[line].append({"block_id": block.get("block_id"), "bbox": block["bbox"], "text": block["text"]})
    return result


def _cell_texts(rows: list[list[str]], width: int) -> list[list[str]]:
    return [(row + [""] * width)[:width] for row in rows]


def _apply_table(table: dict, rows: list[list[str]]) -> str:
    """Write reviewed grid into ``table``; returns how it was matched."""
    width = max((len(r) for r in rows), default=0)
    grid = _cell_texts(rows, width)
    old_rows, old_cols = table["row_count"], table["col_count"]
    shift = 0
    mode = "cells"
    if (len(grid), width) == (old_rows, old_cols):
        pass
    elif (len(grid), width) == (old_rows + 1, old_cols):
        shift = 1  # reviewer added a header row above the detected rows
        mode = "cells+header"
    else:
        mode = "rebuilt"
    if mode == "rebuilt":
        box = table.get("bbox")
        table["cells"] = [
            {
                "row": r,
                "col": c,
                "text": text,
                "ocr_text": "",
                **({"bbox": box} if box else {}),
                "reviewed": True,
                "grid_rebuilt": True,
            }
            for r, row in enumerate(grid)
            for c, text in enumerate(row)
            if text
        ]
        table["row_count"], table["col_count"] = len(grid), width
        return mode
    kept = []
    for cell in table["cells"]:
        cell["row"] += shift
        if cell["row"] >= len(grid) or cell["col"] >= width:
            raise ValueError("reviewed grid smaller than detected cells")
        cell["text"] = grid[cell["row"]][cell["col"]]
        cell["reviewed"] = True
        kept.append(cell)
    if shift:
        present = {(c["row"], c["col"]) for c in kept}
        header = [
            {"row": 0, "col": c, "text": t, "ocr_text": "", "is_header": True, "reviewed": True}
            for c, t in enumerate(grid[0])
            if t and (0, c) not in present
        ]
        table["cells"] = header + kept
        table["row_count"] = len(grid)
    return mode


def _union(boxes: list) -> list | None:
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _new_table(rows: list[list[str]], blocks: list[dict], index: int) -> dict:
    """A table the reviewer typed but OCR never detected: each row takes the bbox of the OCR blocks it was read from."""
    width = max((len(r) for r in rows), default=0)
    grid = _cell_texts(rows, width)
    aligned = align_line_blocks("\n".join(" ".join(c for c in row if c) for row in grid), blocks)
    cells, row_boxes = [], []
    for r, (row, found) in enumerate(zip(grid, aligned)):
        box = _union([block["bbox"] for block in found])
        row_boxes.append(box)
        cells.extend(
            {
                "row": r,
                "col": c,
                "text": text,
                "ocr_text": "",
                **({"bbox": box} if box else {}),
                "reviewed": True,
                "grid_rebuilt": True,
            }
            for c, text in enumerate(row)
            if text
        )
    table = {
        "table_id": f"table:reviewed:{index}",
        "row_count": len(grid),
        "col_count": width,
        "cells": cells,
        "method": "reviewed_markdown",
        "warnings": ["cell_bbox_is_row_bbox"],
    }
    whole = _union(row_boxes)
    if whole:
        table["bbox"] = whole
    return table


def import_reviewed_text(root: Path, markdown: Path) -> dict:
    recover_import(root)
    manifest = _manifest(root)
    sources_pages = _pages(root, manifest)
    reviewed = parse_reviewed(markdown)
    known = {(p["source_id"], p["pdf_page"]) for _, pages in sources_pages for p in pages}
    if set(reviewed) != known:
        raise ValueError(
            f"reviewed file pages differ from dataset: missing={sorted(known - set(reviewed))[:5]} "
            f"unknown={sorted(set(reviewed) - known)[:5]}"
        )
    corrections, modes, changed = [], {}, 0
    for _, pages in sources_pages:
        for page in pages:
            prose, tables = reviewed[(page["source_id"], page["pdf_page"])]
            before = deepcopy(page)
            new = deepcopy(page)
            new.setdefault("ocr_extracted_text", before.get("extracted_text", ""))
            new["extracted_text"] = prose
            new["reviewed_text"] = True
            detected = new.get("tables", [])
            if len(tables) != len(detected):
                modes["table_count_changed"] = modes.get("table_count_changed", 0) + 1
            new["tables"] = detected[: len(tables)]
            for table, rows in zip(new["tables"], tables):
                mode = _apply_table(table, rows)
                modes[mode] = modes.get(mode, 0) + 1
            for index in range(len(new["tables"]), len(tables)):
                new["tables"].append(_new_table(tables[index], before.get("blocks", []), index))
                modes["added_from_review"] = modes.get("added_from_review", 0) + 1
            new["reviewed"] = True
            for block in new.get("blocks", []):
                block["reviewed"] = True
            new["line_blocks"] = align_line_blocks(prose, before.get("blocks", []))
            if new == before:
                continue
            if {k: v for k, v in new.items() if k != "line_blocks"} != {k: v for k, v in before.items() if k != "line_blocks"}:
                corrections.append(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_id": page["source_id"],
                        "pdf_page": page["pdf_page"],
                        "source_sha256": page["source_sha256"],
                        "ocr_hash": page["ocr_hash"],
                        "reviewed": True,
                        "kind": "reviewed_page_text",
                        "old_text": before.get("extracted_text", ""),
                        "text": prose,
                        "old_tables": [[c.get("text", "") for c in t.get("cells", [])] for t in before.get("tables", [])],
                        "new_tables": [[c.get("text", "") for c in t.get("cells", [])] for t in new.get("tables", [])],
                    }
                )
            changed += 1
            page.clear()
            page.update(new)
    if not changed:
        return manifest
    ledger = root / "review/corrections.jsonl"
    prior = ledger.read_bytes() if ledger.exists() else b""
    write_json(
        root / ".pending-import.json",
        {
            "ledger_before_size": len(prior),
            "ledger_before_sha256": hashlib.sha256(prior).hexdigest(),
            "ledger_append": "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in corrections),
            "manifest": manifest,
            "sources_pages": sources_pages,
        },
    )
    result = recover_import(root)
    result["import_text_summary"] = {"pages_changed": changed, "text_corrections": len(corrections), "tables": modes}
    return result
