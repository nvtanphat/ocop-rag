from types import SimpleNamespace

from PIL import Image

from ai_core.processing.ocop import easy_viet_ocr


def _region(left, top, right, bottom):
    return {
        "bbox_px": [left, top, right, bottom],
        "polygon": [[left, top], [right, top], [right, bottom], [left, bottom]],
    }


def test_low_confidence_short_ascii_fragments_are_candidates_only():
    assert easy_viet_ocr._is_low_confidence_short_fragment(
        "Contractional", 0.50, height=10, median_height=30
    )
    assert easy_viet_ocr._is_low_confidence_short_fragment(
        "2013", 0.30, height=10, median_height=30
    )
    assert not easy_viet_ocr._is_low_confidence_short_fragment(
        "Contractional", 0.80, height=10, median_height=30
    )
    assert not easy_viet_ocr._is_low_confidence_short_fragment(
        "Contractional", 0.50, height=20, median_height=30
    )
    assert not easy_viet_ocr._is_low_confidence_short_fragment(
        "Sử dụng", 0.50, height=10, median_height=30
    )


def test_detected_checkbox_prefix_is_removed_from_recognized_text():
    text, noise = easy_viet_ocr._strip_leading_checkbox_token("ở Có nội dung")
    assert text == "Có nội dung" and noise == "ở"
    assert easy_viet_ocr._strip_leading_checkbox_token("Có nội dung") == ("Có nội dung", None)


def test_checkbox_detection_handles_small_cell_box_below_a_table_rule():
    import cv2
    import numpy as np

    crop=np.full((38,435,3),255,dtype=np.uint8)
    crop[0,:]=0  # the neighboring table rule touches the crop edge
    cv2.rectangle(crop,(3,17),(10,24),(0,0,0),1)

    cleared=np.asarray(easy_viet_ocr._blank_leading_checkbox(Image.fromarray(crop)))

    assert cleared[:,:13].min()==255


def test_ocr_keeps_tiny_low_confidence_noise_out_of_page_text(monkeypatch):
    regions = [
        _region(10, 10, 100, 40),
        _region(10, 50, 100, 80),
        _region(10, 90, 100, 120),
        _region(120, 50, 210, 80),
        _region(120, 10, 210, 20),
    ]
    monkeypatch.setattr(easy_viet_ocr, "_detector", lambda: object())
    monkeypatch.setattr(easy_viet_ocr, "_predictor", lambda: object())
    monkeypatch.setattr(easy_viet_ocr, "_detect_regions", lambda *args, **kwargs: regions)
    monkeypatch.setattr(easy_viet_ocr, "_split_at_table_rows", lambda rows, *args: rows)
    monkeypatch.setattr(easy_viet_ocr, "_merge_line_fragments", lambda rows, *args: rows)
    monkeypatch.setattr(easy_viet_ocr, "_split_long_regions", lambda rows, *args: rows)
    recognized=[]
    def recognize(_predictor, crop):
        index=len(recognized)
        recognized.append(index)
        if index==0:
            return "ở Nội dung",0.90,[]
        if crop.height<20:
            return "Contractional",0.50,[]
        return "Nội dung",0.90,[]
    monkeypatch.setattr(easy_viet_ocr, "_recognize", recognize)
    monkeypatch.setattr(easy_viet_ocr, "detect_regions", lambda _rgb: ([], None))
    monkeypatch.setattr(easy_viet_ocr, "assign_regions", lambda *_args: None)
    monkeypatch.setattr("ocop_ocr.table_parser.raster_tables", lambda *_args, **_kwargs: [])

    image=Image.new("RGB", (300, 150), "white")
    from PIL import ImageDraw
    ImageDraw.Draw(image).rectangle((13,17,25,29),outline="black",width=1)
    result, tables = easy_viet_ocr.run_easy_viet_ocr(
        image,
        SimpleNamespace(rect=SimpleNamespace(width=300, height=150)),
        detect_tables=False,
    )

    assert tables == []
    assert len(result.blocks) == 4
    assert all("Contractional" not in block["text"] for block in result.blocks)
    assert result.blocks[0]["text"] == "Nội dung"
    assert result.blocks[0]["ocr_raw_text"] == "ở Nội dung"
    assert result.blocks[0]["ocr_normalizations"] == [{"kind":"remove_leading_checkbox_token","token":"ở"}]
    assert {candidate["reason"] for candidate in result.noise_candidates} == {
        "short_prefix_recognized_in_leading_checkbox_region",
        "low_confidence_short_ascii_fragment",
    }
    assert all(candidate["candidate_only"] and candidate["review_status"]=="needs_review"
               for candidate in result.noise_candidates)
    assert "ocr_noise_candidates_require_review:2" in result.warnings
