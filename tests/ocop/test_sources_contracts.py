"""Source-contract tests: business contracts, hashes, page profiling, source isolation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ocop_contracts.models import EvidenceUnit, SourceDocument, SourceSpan
from ocop_ocr.profiler import profile_pdf
from ocop_contracts.registry import compare_lock, load_registry, snapshot


@pytest.fixture
def pdf_root(tmp_path: Path) -> Path:
    fitz = pytest.importorskip("fitz")
    (tmp_path / "data/raw/ocop").mkdir(parents=True)
    p = tmp_path / "data/raw/ocop/sample.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        for i in range(15):
            page.insert_text((60, 80 + i * 20), "Van ban thu nghiem de kiem tra PDF native text")
        doc.save(p)
    return tmp_path


def source_record(path="data/raw/ocop/sample.pdf", sid="VN.TEST.SAMPLE") -> dict:
    return {"source_id": sid, "path": path, "source_kind": "ocop_framework"}


def test_registry_snapshot_roundtrip_and_hash(pdf_root: Path):
    path = pdf_root / "registry.json"
    path.write_text(json.dumps({"schema_version": 1, "sources": [source_record()]}), encoding="utf8")
    records = load_registry(path)
    s1 = snapshot(pdf_root, records)
    s2 = snapshot(pdf_root, records)
    assert s1 == s2
    assert len(s1["aggregate_sha256"]) == 64
    assert len(s1["sources"]) == 1
    compare_lock(s1, s2)


def test_snapshot_detects_modified_content(pdf_root: Path):
    src = [SourceDocument.model_validate(source_record())]
    original = snapshot(pdf_root, src)
    (pdf_root / src[0].path).write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="differs"):
        compare_lock(snapshot(pdf_root, src), original)


def test_missing_file_blocks_ingestion(pdf_root: Path):
    (pdf_root / "data/raw/ocop/sample.pdf").unlink()
    with pytest.raises(FileNotFoundError):
        snapshot(pdf_root, [SourceDocument.model_validate(source_record())])


def test_duplicate_source_id_rejected(tmp_path: Path):
    records = [source_record(), source_record(sid="VN.TEST.SAMPLE", path="a.pdf")]
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"schema_version": 1, "sources": records}), encoding="utf8")
    with pytest.raises(ValueError, match="duplicate"):
        load_registry(p)


@pytest.mark.parametrize("bad", ["../escape.pdf", "/etc/passwd.pdf", "a\\b.pdf", "foo.txt"])
def test_unsafe_path_rejected(bad):
    with pytest.raises(ValidationError):
        SourceDocument.model_validate(source_record(path=bad))


def test_date_conflict_rejected():
    with pytest.raises(ValidationError):
        SourceDocument.model_validate({**source_record(), "effective_from": "2027-01-01", "effective_to": "2026-01-01"})


def test_source_span_bbox_rejected():
    with pytest.raises(ValidationError):
        SourceSpan(pdf_page=1, bbox=(20, 30, 19, 40))


def test_evidence_unit_requires_pdf_provenance():
    with pytest.raises(ValidationError):
        EvidenceUnit(unit_id="e1", source_id="s", unit_kind="criterion", text="abc", spans=[], extractor_version="p1")


def test_native_pdf_profiler(pdf_root: Path):
    records = profile_pdf(pdf_root / "data/raw/ocop/sample.pdf", "VN.TEST.SAMPLE")
    assert len(records) == 1
    assert records[0]["pdf_page"] == 1
    assert records[0]["page_class"] == "native_text"
    assert not records[0]["needs_ocr_review"]


def test_image_only_page_needs_ocr(pdf_root: Path):
    fitz = pytest.importorskip("fitz")
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), 0)
    p = pdf_root / "data/raw/ocop/image.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=300)
        page.insert_image(page.rect, pixmap=image)
        doc.save(p)
    records = profile_pdf(p, "VN.TEST.IMAGE")
    assert records[0]["needs_ocr_review"]
    assert records[0]["largest_image_area_ratio"] >= 0.99


def test_ocop_schema_is_independent_of_other_domains():
    from ocop_contracts.models import EvidenceUnit, SourceDocument

    assert EvidenceUnit.model_fields["unit_id"].is_required()
    assert SourceDocument.model_fields["source_kind"].is_required()


def test_stable_ids_are_reproducible_and_domain_scoped():
    from ocop_contracts.ids import stable_id

    uid = stable_id("criterion", "VN.OCOP.QD26.2026", ["PLII", "sheet-01", "1.1"])
    assert uid == stable_id("criterion", "VN.OCOP.QD26.2026", ["PLII", "sheet-01", "1.1"])
    assert uid != stable_id("criterion", "VN.OCOP.QD148.2023", ["PLII", "sheet-01", "1.1"])
    assert uid != stable_id("option", "VN.OCOP.QD26.2026", ["PLII", "sheet-01", "1.1"])
    assert uid != stable_id("criterion", "VN.OCOP.QD26.2026", ["PLII", "sheet-01", "1.1"], revision="r2")


def test_stable_ids_reject_missing_hierarchy():
    from ocop_contracts.ids import stable_id

    with pytest.raises(ValueError):
        stable_id("criterion", "VN.OCOP.QD26.2026", [])
    with pytest.raises(ValueError):
        stable_id("criterion", "VN.OCOP.QD26.2026", [""])


def test_content_fingerprint_separate_from_unit_identity():
    from ocop_contracts.ids import content_sha256, stable_id

    a = stable_id("criterion", "VN.OCOP.QD26.2026", ["1.1"])
    assert a == stable_id("criterion", "VN.OCOP.QD26.2026", ["1.1"])
    assert content_sha256("Nội dung A") != content_sha256("Nội dung B")
    assert len(content_sha256("Nội dung A")) == 64


def test_unregistered_pdf_rejected_by_snapshot(pdf_root: Path):
    fitz = pytest.importorskip("fitz")
    unlisted = pdf_root / "data/raw/ocop/unlisted.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(unlisted)
    with pytest.raises(ValueError, match="unregistered"):
        snapshot(pdf_root, [SourceDocument.model_validate(source_record())])


def test_registry_rejects_case_insensitive_path_collision(tmp_path: Path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"schema_version": 1, "sources": [
        source_record(path="data/raw/ocop/FILE.pdf", sid="VN.TEST.A"),
        source_record(path="data/raw/ocop/file.pdf", sid="VN.TEST.B"),
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_registry(path)
