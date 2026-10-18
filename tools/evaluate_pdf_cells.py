"""Evaluate independent, source-locked cell transcriptions against page artifacts.

This measures cell text at annotated PDF coordinates. Table detection counts or
alternative candidate readings alone cannot satisfy the critical-cell gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_core.processing.ocop.pdf_loader import checked_sources  # noqa: E402 - standalone CLI bootstrap


def _validate_provenance(artifact: dict, annotation: dict) -> None:
    if (
        artifact.get("source_id") != annotation["source_id"]
        or artifact.get("source_sha256") != annotation["source_sha256"]
        or artifact.get("pdf_page") != annotation["pdf_page"]
    ):
        raise ValueError("cell_evaluation_provenance_mismatch")


def evaluate_text_page(artifact: dict, annotation: dict) -> dict:
    _validate_provenance(artifact, annotation)

    def normalized(value):
        return " ".join(unicodedata.normalize("NFC", value).casefold().split())

    text = normalized(artifact.get("extracted_text", ""))
    anchors = [
        {"expected": anchor, "present": normalized(anchor) in text} for anchor in annotation["anchors"]
    ]
    return {
        "source_id": annotation["source_id"],
        "pdf_page": annotation["pdf_page"],
        "anchors": anchors,
        "exact_anchors": sum(a["present"] for a in anchors),
        "critical_anchors_pass": bool(anchors) and all(a["present"] for a in anchors),
    }


def evaluate_page(artifact: dict, annotation: dict) -> dict:
    _validate_provenance(artifact, annotation)
    results = []
    for label in annotation["cells"]:
        x, y = annotation["score_column_x_pt"], label["y_pt"]
        matches = [
            c
            for table in artifact.get("tables", [])
            for c in table.get("cells", [])
            if c.get("bbox") is not None
            and c["bbox"][0] < x < c["bbox"][2]
            and c["bbox"][1] < y < c["bbox"][3]
        ]
        # Multiple overlapping candidates are ambiguous, even if one happens to
        # contain the expected value. Never select a prediction using the gold.
        cell = matches[0] if len(matches) == 1 else None
        actual = " ".join(str(cell.get("text", "")).split()) if cell is not None else None
        alternatives = sorted({str(c["text"]) for c in cell.get("score_ocr_candidates", [])}) if cell else []
        results.append(
            {
                "y_pt": y,
                "expected": label["expected"],
                "actual": actual,
                "matching_regions": len(matches),
                "exact": actual == label["expected"],
                "candidate_contains_expected": bool(label["expected"]) and label["expected"] in alternatives,
                "candidates": alternatives,
            }
        )
    numeric = [r for r in results if r["expected"]]
    return {
        "source_id": annotation["source_id"],
        "pdf_page": annotation["pdf_page"],
        "cells": results,
        "annotated_cells": len(results),
        "exact_cells": sum(r["exact"] for r in results),
        "numeric_cells": len(numeric),
        "exact_numeric_cells": sum(r["exact"] for r in numeric),
        "candidate_numeric_hits": sum(r["candidate_contains_expected"] for r in numeric),
        "critical_cells_pass": bool(numeric) and all(r["exact"] for r in results),
    }


def evaluate_marker_page(artifact: dict, annotation: dict) -> dict:
    """Markers must occur in their own source cell, not merely somewhere on a page."""
    _validate_provenance(artifact, annotation)
    rows = []
    matched_ids = set()
    for label in annotation["cells"]:
        x, y = label["x_pt"], label["y_pt"]
        matches = [
            cell
            for table in artifact.get("tables", [])
            for cell in table.get("cells", [])
            if cell.get("bbox")
            and cell["bbox"][0] < x < cell["bbox"][2]
            and cell["bbox"][1] < y < cell["bbox"][3]
        ]
        actual = re.findall(r"\*+", str(matches[0].get("text", ""))) if len(matches) == 1 else None
        if len(matches) == 1:
            matched_ids.add(id(matches[0]))
        rows.append(
            {
                "expected": label["markers"],
                "actual": actual,
                "x_pt": x,
                "y_pt": y,
                "matching_regions": len(matches),
                "exact": actual == label["markers"],
            }
        )
    unexpected = 0
    if annotation.get("exhaustive_table_markers"):
        unexpected = sum(
            bool(re.findall(r"\*+", str(cell.get("text", ""))))
            for table in artifact.get("tables", [])
            for cell in table.get("cells", [])
            if id(cell) not in matched_ids
        )
    return {
        "source_id": annotation["source_id"],
        "pdf_page": annotation["pdf_page"],
        "cells": rows,
        "exact_cells": sum(row["exact"] for row in rows),
        "annotated_cells": len(rows),
        "unexpected_marker_cells": unexpected,
        "critical_markers_pass": bool(rows) and all(r["exact"] for r in rows) and unexpected == 0,
    }


def evaluate(
    artifacts: Path,
    gold: Path,
    *,
    root: Path = ROOT,
    split: str = "dev",
    text_gold: Path | None = None,
    marker_gold: Path | None = None,
) -> dict:
    _, snapshot = checked_sources(
        root, root / "configs/ocop_sources.json", root / "configs/ocop_sources.lock.json"
    )
    digests = {s["source_id"]: s["sha256"] for s in snapshot["sources"]}
    annotations = json.loads(gold.read_text(encoding="utf-8"))
    if annotations.get("schema_version") != 1 or not annotations.get("pages"):
        raise ValueError("missing_cell_annotations")
    manifest = json.loads((artifacts / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("input_snapshot_sha256") != snapshot["aggregate_sha256"]:
        raise ValueError("artifact_snapshot_mismatch")
    records = {}
    for source in manifest["sources"]:
        path = (artifacts / source["artifact"]).resolve()
        if not path.is_relative_to(artifacts.resolve()):
            raise ValueError("artifact_path_outside_directory")
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = (row["source_id"], row["pdf_page"])
            if key in records:
                raise ValueError("duplicate_page_artifact")
            records[key] = row
    pages = []
    for annotation in annotations["pages"]:
        if split != "all" and annotation["split"] != split:
            continue
        if annotation["source_sha256"] != digests.get(annotation["source_id"]):
            raise ValueError("annotation_source_hash_mismatch")
        key = (annotation["source_id"], annotation["pdf_page"])
        if key not in records:
            raise ValueError(f"missing_annotated_page:{key}")
        pages.append(evaluate_page(records[key], annotation))
    if not pages:
        raise ValueError("no_annotations_in_selected_split")
    result = {
        "split": split,
        "annotation_review_status": annotations["review_status"],
        "critical_cells_pass": all(p["critical_cells_pass"] for p in pages),
        "numeric_cells": sum(p["numeric_cells"] for p in pages),
        "exact_numeric_cells": sum(p["exact_numeric_cells"] for p in pages),
        "candidate_numeric_hits": sum(p["candidate_numeric_hits"] for p in pages),
        "limitations": annotations["limitations"],
        "pages": pages,
    }
    if text_gold is not None:
        text_labels = json.loads(text_gold.read_text(encoding="utf-8"))
        if text_labels.get("schema_version") != 1 or not text_labels.get("pages"):
            raise ValueError("missing_text_annotations")
        text_pages = []
        for annotation in text_labels["pages"]:
            if annotation["source_sha256"] != digests.get(annotation["source_id"]):
                raise ValueError("text_annotation_source_hash_mismatch")
            key = (annotation["source_id"], annotation["pdf_page"])
            if key not in records:
                raise ValueError(f"missing_text_annotated_page:{key}")
            text_pages.append(evaluate_text_page(records[key], annotation))
        result["text_evaluation"] = {
            "annotation_review_status": text_labels["review_status"],
            "pages": text_pages,
            "annotated_pages": len(text_pages),
            "exact_anchors": sum(p["exact_anchors"] for p in text_pages),
            "total_anchors": sum(len(p["anchors"]) for p in text_pages),
            "critical_anchors_pass": all(p["critical_anchors_pass"] for p in text_pages),
            "limitations": text_labels["limitations"],
        }
    if marker_gold is not None:
        marker_labels = json.loads(marker_gold.read_text(encoding="utf-8"))
        if marker_labels.get("schema_version") != 1 or not marker_labels.get("pages"):
            raise ValueError("missing_marker_annotations")
        marker_pages = []
        for annotation in marker_labels["pages"]:
            if annotation["source_sha256"] != digests.get(annotation["source_id"]):
                raise ValueError("marker_annotation_source_hash_mismatch")
            key = (annotation["source_id"], annotation["pdf_page"])
            if key not in records:
                raise ValueError(f"missing_marker_annotated_page:{key}")
            marker_pages.append(evaluate_marker_page(records[key], annotation))
        result["marker_evaluation"] = {
            "pages": marker_pages,
            "annotated_cells": sum(p["annotated_cells"] for p in marker_pages),
            "exact_cells": sum(p["exact_cells"] for p in marker_pages),
            "critical_markers_pass": all(p["critical_markers_pass"] for p in marker_pages),
            "annotation_review_status": marker_labels["review_status"],
            "limitations": marker_labels["limitations"],
        }
    return result


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--artifacts", type=Path, required=True)
    cli.add_argument("--gold", type=Path, default=ROOT / "tests/fixtures/ocop_pdf_score_cells.json")
    cli.add_argument("--output", type=Path)
    cli.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    cli.add_argument("--text-gold", type=Path, help="Optional independent legal-text anchor fixture")
    cli.add_argument("--marker-gold", type=Path, help="Independent per-cell footnote-marker fixture")
    args = cli.parse_args()
    result = evaluate(
        args.artifacts, args.gold, split=args.split, text_gold=args.text_gold, marker_gold=args.marker_gold
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {k: v for k, v in result.items() if k not in ("pages", "text_evaluation", "marker_evaluation")}
    if "text_evaluation" in result:
        summary["text_evaluation"] = {k: v for k, v in result["text_evaluation"].items() if k != "pages"}
    if "marker_evaluation" in result:
        summary["marker_evaluation"] = {k: v for k, v in result["marker_evaluation"].items() if k != "pages"}
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    passed = (
        result["critical_cells_pass"]
        and result.get("text_evaluation", {}).get("critical_anchors_pass", True)
        and result.get("marker_evaluation", {}).get("critical_markers_pass", True)
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
