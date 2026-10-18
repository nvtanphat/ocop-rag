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


def layout_page(blocks: list[dict], width_pt: float, height_pt: float, *,
                preserve_order: bool = False) -> tuple[list[dict],list[str]]:
    warnings=[]
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
        ordered = [block for _, block in sorted(
            [*[(index, block) for index, block, _ in positioned], *unpositioned],
            key=lambda item: (_source_order(item[1], item[0]), item[0]),
        )]
        positioned_ordered = [item for item in positioned]
    else:
        positioned.sort(key=lambda item: (
            round(item[2][1] / 7), item[2][0], _source_order(item[1], item[0]), item[0]
        ))
        unpositioned.sort(key=lambda item: (_source_order(item[1], item[0]), item[0]))
        ordered = [block for _, block, _ in positioned] + [block for _, block in unpositioned]
        positioned_ordered = positioned

    if any(box[0] < -0.5 or box[1] < -0.5 or
           box[2] > width_pt + 0.5 or box[3] > height_pt + 0.5
           for _, _, box in positioned_ordered):
        warnings.append("out_of_page_bbox")
    # Two-column pages need review, not aggressive left-right reorder.
    left=[block for _, block, box in positioned_ordered if box[2] < width_pt*0.48]
    right=[block for _, block, box in positioned_ordered if box[0] > width_pt*0.52]
    if len(left)>=6 and len(right)>=6:
        warnings.append("possible_multi_column_order")
    for i, b in enumerate(ordered):
        b["reading_order"] = i
    return ordered,warnings
