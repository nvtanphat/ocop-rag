"""Layout regions group OCR blocks so a side panel (seal, signature) is not interleaved with body lines."""
from ocop_contracts.layout import layout_page
from ocop_ocr.layout_regions import assign_regions


def _block(text, bbox):
    return {"text": text, "bbox": bbox}


def test_side_by_side_regions_are_read_one_after_the_other():
    left = [_block(f"Nơi nhận {i}", [10, 100 + 20 * i, 200, 115 + 20 * i]) for i in range(4)]
    right = [_block("KT. THỦ TƯỚNG", [300, 98, 450, 113]), _block("Trần Hồng Hà", [300, 158, 450, 173])]
    regions = [{"label": "text", "score": 0.9, "bbox": [5, 95, 205, 190]},
               {"label": "seal", "score": 0.8, "bbox": [295, 92, 455, 180]}]
    assert assign_regions([*left, *right], regions) == 6
    ordered, _ = layout_page([*right, *left], 600, 800)
    assert [b["text"] for b in ordered] == [*(b["text"] for b in left), "KT. THỦ TƯỚNG", "Trần Hồng Hà"]
    assert right[0]["layout_region"]["label"] == "seal"


def test_smallest_covering_region_wins_and_unassigned_blocks_keep_their_position():
    stamp = _block("ĐẾN", [12, 52, 60, 66])
    title = _block("QUYẾT ĐỊNH", [100, 50, 300, 66])
    footer = _block("13", [290, 780, 310, 795])
    regions = [{"label": "text", "score": 0.77, "bbox": [10, 45, 320, 120]},
               {"label": "text", "score": 0.58, "bbox": [8, 48, 70, 80]}]
    assign_regions([stamp, title, footer], regions)
    assert stamp["layout_region"]["order"] != title["layout_region"]["order"]
    assert footer["layout_region"]["label"] == "unassigned"
    ordered, _ = layout_page([footer, title, stamp], 600, 800)
    assert ordered[-1] is footer


def test_blocks_without_regions_keep_the_y_band_order():
    blocks = [_block("b", [10, 40, 50, 50]), _block("a", [10, 10, 50, 20])]
    ordered, _ = layout_page(blocks, 600, 800)
    assert [b["text"] for b in ordered] == ["a", "b"]


def test_fragment_slightly_off_its_line_stays_at_the_line_start():
    region = {"order": 0, "label": "text", "score": 0.9}
    blocks = [{"text": "Quyết định số 263", "bbox": [164.6, 427.7, 374.5, 451.2], "layout_region": region},
              {"text": "Căn", "bbox": [119.0, 431.0, 146.1, 446.9], "layout_region": region},
              {"text": "tháng 02 năm 2022", "bbox": [90.0, 452.0, 300.0, 474.0], "layout_region": region}]
    ordered, _ = layout_page(blocks, 600, 800)
    assert [b["text"] for b in ordered] == ["Căn", "Quyết định số 263", "tháng 02 năm 2022"]
