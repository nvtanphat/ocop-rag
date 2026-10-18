"""A score at the wrong row/source or among alternatives cannot pass OCR QA."""

from copy import deepcopy

import pytest

from tools.evaluate_pdf_cells import evaluate_page, evaluate_text_page, evaluate_marker_page


def fixture():
    provenance = {"source_id": "VN.TEST", "source_sha256": "a" * 64, "pdf_page": 1}
    annotation = {
        **provenance,
        "score_column_x_pt": 90,
        "cells": [{"y_pt": 20, "expected": "1"}, {"y_pt": 40, "expected": "3"}],
    }
    page = {
        **provenance,
        "tables": [
            {"cells": [{"bbox": [80, 10, 100, 30], "text": "1"}, {"bbox": [80, 30, 100, 50], "text": "3"}]}
        ],
    }
    return page, annotation


def test_footnotes_cannot_move_to_another_criterion_or_pass_as_candidates():
    page, _ = fixture()
    annotation = {k: page[k] for k in ("source_id", "source_sha256", "pdf_page")}
    annotation["cells"] = [
        {"x_pt": 90, "y_pt": 20, "markers": ["*****"]},
        {"x_pt": 90, "y_pt": 40, "markers": ["****"]},
    ]
    cells = page["tables"][0]["cells"]
    cells[0]["text"], cells[1]["text"] = "Criterion*****", "Criterion****"
    assert evaluate_marker_page(page, annotation)["critical_markers_pass"]
    cells[0]["text"], cells[1]["text"] = cells[1]["text"], cells[0]["text"]
    assert evaluate_marker_page(page, annotation)["exact_cells"] == 0
    cells[0]["marker_candidates"] = [{"text": "*****"}]
    assert not evaluate_marker_page(page, annotation)["critical_markers_pass"]


def test_footnote_provenance_and_empty_labels_fail_closed():
    page, _ = fixture()
    annotation = {k: page[k] for k in ("source_id", "source_sha256", "pdf_page")}
    annotation["cells"] = []
    assert not evaluate_marker_page(page, annotation)["critical_markers_pass"]
    annotation["source_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="provenance_mismatch"):
        evaluate_marker_page(page, annotation)


def test_extra_footnotes_cannot_pass_exhaustive_marker_labels():
    page, _ = fixture()
    annotation = {k: page[k] for k in ("source_id", "source_sha256", "pdf_page")}
    annotation.update(cells=[{"x_pt": 90, "y_pt": 20, "markers": ["*****"]}], exhaustive_table_markers=True)
    page["tables"][0]["cells"][0]["text"] = "*****"
    assert evaluate_marker_page(page, annotation)["critical_markers_pass"]
    page["tables"][0]["cells"][1]["text"] = "****"
    result = evaluate_marker_page(page, annotation)
    assert result["unexpected_marker_cells"] == 1
    assert not result["critical_markers_pass"]


def test_correct_scores_in_wrong_rows_fail():
    page, annotation = fixture()
    assert evaluate_page(page, annotation)["critical_cells_pass"]
    cells = page["tables"][0]["cells"]
    cells[0]["text"], cells[1]["text"] = cells[1]["text"], cells[0]["text"]
    result = evaluate_page(page, annotation)
    assert result["exact_numeric_cells"] == 0 and not result["critical_cells_pass"]


def test_ambiguous_regions_cannot_be_resolved_using_expected_score():
    page, annotation = fixture()
    extra = deepcopy(page["tables"][0])
    extra["cells"][0]["text"] = "9"
    page["tables"].append(extra)
    result = evaluate_page(page, annotation)
    assert not result["critical_cells_pass"]
    assert result["exact_numeric_cells"] == 0


@pytest.mark.parametrize(
    "field,value", [("source_id", "OTHER"), ("source_sha256", "b" * 64), ("pdf_page", 2)]
)
def test_wrong_provenance_rejected(field, value):
    page, annotation = fixture()
    page[field] = value
    with pytest.raises(ValueError, match="provenance"):
        evaluate_page(page, annotation)


def test_alternative_candidate_is_reported_separately_from_exact_extraction():
    page, annotation = fixture()
    cell = page["tables"][0]["cells"][0]
    cell["text"] = ""
    cell["score_ocr_candidates"] = [{"text": "1", "review_status": "needs_review"}]
    result = evaluate_page(page, annotation)
    assert result["candidate_numeric_hits"] == 1
    assert not result["critical_cells_pass"]


def test_missing_region_does_not_count_as_intentional_blank():
    page, annotation = fixture()
    annotation["cells"][0]["expected"] = ""
    page["tables"] = []
    result = evaluate_page(page, annotation)
    assert result["exact_cells"] == 0


def test_text_evaluation_retains_vietnamese_accents_and_legal_numbers():
    page, annotation = fixture()
    annotation["anchors"] = ["từ 50% đến dưới 75%"]
    page["extracted_text"] = "TỪ 50%\n ĐẾN DƯỚI 75%"
    assert evaluate_text_page(page, annotation)["critical_anchors_pass"]
    page["extracted_text"] = "TỪ 30% ĐẾN DƯỚI 75%"
    assert not evaluate_text_page(page, annotation)["critical_anchors_pass"]
    page["extracted_text"] = "tu 50% den duoi 75%"
    assert not evaluate_text_page(page, annotation)["critical_anchors_pass"]


def test_text_evaluation_rejects_right_quote_from_wrong_source():
    page, annotation = fixture()
    annotation["anchors"] = ["legal evidence"]
    page["extracted_text"] = "legal evidence"
    page["source_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="provenance"):
        evaluate_text_page(page, annotation)


def test_empty_text_annotation_cannot_pass():
    page, annotation = fixture()
    annotation["anchors"] = []
    assert not evaluate_text_page(page, annotation)["critical_anchors_pass"]
