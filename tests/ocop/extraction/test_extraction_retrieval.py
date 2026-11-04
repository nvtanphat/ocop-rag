"""No-network contract tests for evidence extraction and indexing on OCOP core."""

from __future__ import annotations

import json
import pytest

from ai_core.processing.ocop.knowledge_extract import page_units, extract_entities_relations
from ai_core.processing.ocop.business_candidates import candidates
from ai_core.retrieval.ocop.structure_chunker import plan_chunks
from ai_core.retrieval.ocop.index_pipeline import (
    build_chunks,
    BM25Search,
    create_bm25,
    build_index,
)
from ai_core.retrieval.ocop.search import rrf, search


def split_units(unit, **options):
    return [part.text for part in plan_chunks(unit, **options)]


def page(text="Điều 3. Bộ tiêu chí OCOP\n1. Chất lượng 35 điểm", tables=None, status="needs_review"):
    return {
        "source_id": "VN.TEST.QD.2026",
        "pdf_page": 7,
        "width_pt": 595,
        "height_pt": 842,
        "extracted_text": text,
        "blocks": [],
        "tables": tables or [],
        "extraction_method": "ocr",
        "ocr_engine": "easyocr_vietocr",
        "review_status": status,
    }


def test_extract_page_provenance_and_stable_ids():
    a = page_units(page())
    b = page_units(page())
    assert a == b
    assert a[0]["spans"][0]["pdf_page"] == 7
    assert any(u["unit_kind"] == "article" for u in a)
    assert all(u["unit_id"].startswith("ocop:") for u in a)


def test_text_evidence_keeps_ocr_block_bbox_and_source_hash():
    source_hash = "a" * 64
    pg = page("Title line\nEvidence line")
    pg["source_sha256"] = source_hash
    pg["blocks"] = [
        {"block_id": "vl:0", "text": "Title line", "bbox": [10, 20, 100, 40]},
        {"block_id": "vl:1", "text": "Evidence line", "bbox": [10, 45, 140, 65]},
    ]
    unit = page_units(pg)[1]
    assert unit["spans"] == [
        {
            "pdf_page": 7,
            "bbox": [10.0, 20.0, 100.0, 40.0],
            "block_id": "vl:0",
            "table_bbox": None,
            "table_id": None,
            "cell_id": None,
            "printed_page": None,
            "source_sha256": source_hash,
        },
        {
            "pdf_page": 7,
            "bbox": [10.0, 45.0, 140.0, 65.0],
            "block_id": "vl:1",
            "table_bbox": None,
            "table_id": None,
            "cell_id": None,
            "printed_page": None,
            "source_sha256": source_hash,
        },
    ]


def test_table_chunks_keep_source_hash_in_cell_spans():
    source_hash = "b" * 64
    tbl = {
        "table_id": "table:sha",
        "bbox": [20, 40, 500, 400],
        "cells": [
            {"row": 0, "col": 0, "text": "Criterion", "bbox": [20, 40, 300, 80]},
            {"row": 0, "col": 1, "text": "Points", "bbox": [300, 40, 500, 80]},
            {"row": 1, "col": 0, "text": "Quality", "bbox": [20, 80, 300, 120]},
            {"row": 1, "col": 1, "text": "3"},
        ],
    }
    pg = page(tables=[tbl])
    pg["source_sha256"] = source_hash
    unit = next(
        u
        for u in page_units(pg, source_kind="ocop_framework")
        if u["unit_kind"] == "criterion_table_candidate"
    )
    chunks = build_chunks([unit], "source-hash")
    spans = [span for chunk in chunks for span in chunk["spans"]]
    assert spans and all(span["source_sha256"] == source_hash for span in spans)
    assert all(span["table_bbox"] == [20.0, 40.0, 500.0, 400.0] for span in spans)
    missing_cell = next(span for span in spans if span["cell_id"] == "table:sha:r1:c1")
    assert missing_cell["bbox"] is None


def test_table_candidate_keeps_coordinates_and_cells():
    tbl = {
        "table_id": "table:0",
        "bbox": [20, 40, 500, 400],
        "cells": [
            {"row": 0, "col": 0, "text": "Tiêu chí"},
            {"row": 0, "col": 1, "text": "Điểm"},
            {"row": 1, "col": 0, "text": "Nguồn gốc"},
            {"row": 1, "col": 1, "text": "3"},
        ],
    }
    units = page_units(page(tables=[tbl]), source_kind="ocop_framework")
    table = next(u for u in units if u["unit_kind"] == "criterion_table_candidate")
    assert table["spans"][0]["bbox"] == [20.0, 40.0, 500.0, 400.0]
    assert table["structured"]["cells"][3]["text"] == "3"
    c = candidates(units, {"VN.TEST.QD.2026": "ocop_framework"})
    assert len(c["criterion_candidates"]) == 2
    assert c["criterion_candidates"][1]["score_candidate"] == 3
    assert c["criterion_candidates"][1]["review_status"] == "needs_review"


def test_grounded_relations_no_foreign_ids():
    us = page_units(page("Căn cứ 26/2026/QĐ-TTg: sản phẩm OCOP"))
    entities, relations = extract_entities_relations(
        us, {"VN.TEST.QD.2026": {"document_number": "26/2026/QĐ-TTg"}}
    )
    ids = {e["entity_id"] for e in entities}
    assert relations
    assert all(r["source_entity_id"] in ids and r["target_entity_id"] in ids for r in relations)
    assert any(r["relation_type"] == "REFERENCES" for r in relations)


def test_chunk_contains_tail_and_parent_citations():
    words = [f"item{i}" for i in range(600)]
    unit = page_units(page(" ".join(words)))[1]
    parts = split_units(unit, max_words=100, overlap=10)
    assert len(parts) > 1
    assert words[0] in parts[0] and words[-1] in parts[-1]
    chunks = build_chunks([unit], "version1", max_words=100, overlap=10)
    assert len(chunks) == len(parts)
    assert all(c["evidence_unit_id"] == unit["unit_id"] and c["spans"][0]["pdf_page"] == 7 for c in chunks)


def test_empty_table_placeholder_not_searchable():
    unit = page_units(page(tables=[{"table_id": "tbl", "cells": []}]), source_kind="ocop_framework")[-1]
    assert not split_units(unit)


def test_bm25_query_and_exact_document_provenance(tmp_path):
    units = page_units(page("Điều 3. Tiêu chí về chất lượng sản phẩm OCOP: 35 điểm"))
    chunks = build_chunks(units[1:], "v4")
    path = tmp_path / "bm25.json.gz"
    info = create_bm25(chunks, path)
    assert info["documents"] == len(chunks)
    results = BM25Search(path).search("chất lượng sản phẩm", top_k=5)
    assert results and results[0][0] < len(chunks)


def test_rrf_deterministic():
    result = rrf([["A", "B"], ["B", "A"]])
    assert result["A"] == pytest.approx(result["B"])
    assert rrf([["A"], ["A"]])["A"] > rrf([["A"]])["A"]


def test_index_and_search_fixture_integration(tmp_path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    unit = page_units(page("Điều 1. Chất lượng sản phẩm OCOP đạt 35 điểm"))[1]
    (knowledge / "evidence_units.jsonl").write_text(
        json.dumps(unit, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (knowledge / "manifest.json").write_text(
        json.dumps({"complete": True, "corpus_version": "testver", "counts": {"pages": 1}}), encoding="utf-8"
    )
    index_dir = tmp_path / "index"
    result = build_index(knowledge=knowledge, index_dir=index_dir)
    assert result["status"] == "sparse_ready"
    rows = search(index_dir, "chất lượng sản phẩm", mode="sparse")
    assert rows and rows[0]["pdf_page"] == 7
    fallback = search(index_dir, "chất lượng sản phẩm", mode="hybrid")
    assert fallback and fallback[0]["retrieval_mode"] == "sparse"
    assert fallback[0]["retrieval_fallback_reason"] == "dense_not_built"
    assert not search(index_dir, "chất lượng sản phẩm", source_id="VN.NO.SOURCE")


def test_index_stable_on_repeated_build(tmp_path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    unit = page_units(page("Mẫu số 01. Phiếu đăng ký"))[1]
    (knowledge / "evidence_units.jsonl").write_text(
        json.dumps(unit, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (knowledge / "manifest.json").write_text(
        json.dumps({"complete": True, "corpus_version": "stable", "counts": {"pages": 1}}), encoding="utf-8"
    )
    one = build_index(knowledge=knowledge, index_dir=tmp_path / "index")
    two = build_index(knowledge=knowledge, index_dir=tmp_path / "index")
    assert one == two


def test_bm25_compressed_bytes_are_reproducible(tmp_path):
    """Two builds of identical chunks must have the same full gzip SHA-256."""
    import hashlib

    unit = page_units(page("Điều 1. Quy định về OCOP"))[1]
    chunks = build_chunks([unit], "deterministic")
    target = tmp_path / "bm25.json.gz"
    create_bm25(chunks, target)
    digest_first = hashlib.sha256(target.read_bytes()).hexdigest()
    create_bm25(chunks, target)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest_first
