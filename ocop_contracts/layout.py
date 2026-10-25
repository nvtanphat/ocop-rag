"""Conservative reading order and table indicators, never rearrange legal facts silently."""

from __future__ import annotations

import math


def _box(block: dict):
    value = block.get("bbox")
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        box = tuple(float(part) for part in value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(part) for part in box) or box[0] > box[2] or box[1] > box[3]:
        return None
    return box


def _source_order(block: dict, index: int) -> int:
    value = block.get("order")
    return value if isinstance(value, int) and not isinstance(value, bool) else index


def _region_order(block: dict) -> int:
    region = block.get("layout_region")
    order = region.get("order") if isinstance(region, dict) else None
    return order if isinstance(order, int) and not isinstance(order, bool) else -1


def _by_region_lines(positioned: list[tuple]) -> list[tuple]:
    regions: dict[int, list[tuple]] = {}
    for item in positioned:
        regions.setdefault(_region_order(item[1]), []).append(item)
    ordered = []
    for order in sorted(regions):
        lines: list[list[tuple]] = []
        for item in sorted(regions[order], key=lambda item: (item[2][1] + item[2][3]) / 2):
            box = item[2]
            if lines:
                first = lines[-1][0][2]
                overlap = min(box[3], first[3]) - max(box[1], first[1])
                # Tall OCR boxes from neighbouring printed lines can overlap
                # vertically. Text fragments on one line must still occupy
                # separate horizontal ranges (allow two points of box noise).
                horizontal_conflict = item[1].get("layout_region", {}).get("label") == "text" and any(
                    min(box[2], other[2][2]) - max(box[0], other[2][0]) > 2 for other in lines[-1]
                )
                if overlap >= 0.5 * min(box[3] - box[1], first[3] - first[1]) and not horizontal_conflict:
                    lines[-1].append(item)
                    continue
            lines.append([item])
        for line in lines:
            ordered.extend(sorted(line, key=lambda item: item[2][0]))
    return ordered


def layout_page(
    blocks: list[dict], width_pt: float, height_pt: float, *, preserve_order: bool = False
) -> tuple[list[dict], list[str]]:
    warnings = []
    positioned = []
    unpositioned = []
    for index, block in enumerate(blocks):
        box = _box(block)
        if box is None:
            unpositioned.append((index, block))
        else:
            positioned.append((index, block, box))
    if unpositioned:
        warnings.append("blocks_without_valid_bbox")

    if preserve_order:
        ordered = [
            block
            for _, block in sorted(
                [*[(index, block) for index, block, _ in positioned], *unpositioned],
                key=lambda item: (_source_order(item[1], item[0]), item[0]),
            )
        ]
        positioned_ordered = [item for item in positioned]
    else:
        positioned.sort(
            key=lambda item: (
                _region_order(item[1]),
                round(item[2][1] / 7),
                item[2][0],
                _source_order(item[1], item[0]),
                item[0],
            )
        )
        # OCR blocks tagged with a layout region are read region by region (see layout_regions), and
        # inside a region by printed line, so a fragment a few points off its line is not pushed after it.
        if any(_region_order(block) >= 0 for _, block, _ in positioned):
            positioned = _by_region_lines(positioned)
        unpositioned.sort(key=lambda item: (_source_order(item[1], item[0]), item[0]))
        ordered = [block for _, block, _ in positioned] + [block for _, block in unpositioned]
        positioned_ordered = positioned

    if any(
        box[0] < -0.5 or box[1] < -0.5 or box[2] > width_pt + 0.5 or box[3] > height_pt + 0.5
        for _, _, box in positioned_ordered
    ):
        warnings.append("out_of_page_bbox")
    # Two-column pages need review, not aggressive left-right reorder.
    left = [block for _, block, box in positioned_ordered if box[2] < width_pt * 0.48]
    right = [block for _, block, box in positioned_ordered if box[0] > width_pt * 0.52]
    if len(left) >= 6 and len(right) >= 6:
        warnings.append("possible_multi_column_order")
    for i, b in enumerate(ordered):
        b["reading_order"] = i
    return ordered, warnings


def _same_row(previous: dict, block: dict) -> bool:
    if "\n" in previous["text"] or "\n" in block["text"]:
        return False
    previous_box, box = _box(previous), _box(block)
    if previous_box is None or box is None:
        return False
    (_, py0, px1, py1), (x0, y0, _, y1) = previous_box, box
    height = min(py1 - py0, y1 - y0)
    return min(py1, y1) - max(py0, y0) >= 0.8 * height and px1 - 2 <= x0 <= px1 + 2 * height


def group_blocks_by_line(blocks: list[dict]) -> list[list[dict]]:
    """Reading-ordered blocks; fragments of one printed line share a row and form one group."""
    lines: list[list[dict]] = []
    for block in blocks:
        if not block["text"].strip():
            continue
        if lines and _same_row(lines[-1][-1], block):
            lines[-1].append(block)
        else:
            lines.append([block])
    return lines


def join_blocks_by_line(blocks: list[dict]) -> str:
    return "\n".join(
        " ".join(b["text"].strip() for b in line) if len(line) > 1 else line[0]["text"]
        for line in group_blocks_by_line(blocks)
    )
