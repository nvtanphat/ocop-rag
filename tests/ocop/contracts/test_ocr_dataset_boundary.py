"""RAG can inspect readiness without importing the optional OCR project."""

import subprocess
import sys
import json
import hashlib

from ocop_contracts.dataset import digest_json
from ocop_contracts.models import SourceDocument
from ocop_contracts.registry import snapshot, sha256_file


def test_rag_status_does_not_import_ocr_or_heavy_ocr_dependencies(tmp_path):
    script = """
import sys
from pathlib import Path
class RejectOCR:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"ocop_ocr", "easyocr", "vietocr", "torch", "cv2"}:
            raise ImportError("RAG imported OCR dependency: " + fullname)
sys.meta_path.insert(0, RejectOCR())
from ai_core.system.pipeline import OcopSystemPipeline
assert OcopSystemPipeline(Path(sys.argv[1])).status()["state"] == "not_ready"
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_actual_rag_build_reads_dataset_without_ocr_dependencies(tmp_path):
    import fitz

    config = tmp_path / "configs"
    config.mkdir()
    pdf = tmp_path / "source.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(pdf)
    source = SourceDocument(source_id="TEST", path="source.pdf", source_kind="cooperative_law")
    locked = snapshot(tmp_path, [source])
    (config / "ocop_sources.json").write_text(
        json.dumps({"schema_version": 1, "sources": [source.model_dump(mode="json")]}), encoding="utf-8"
    )
    (config / "ocop_sources.lock.json").write_text(json.dumps(locked), encoding="utf-8")
    dataset = tmp_path / "dataset"
    (dataset / "pages").mkdir(parents=True)
    page = {
        "source_id": "TEST",
        "source_sha256": sha256_file(pdf),
        "pdf_page": 1,
        "width_pt": 595,
        "height_pt": 842,
        "extracted_text": "Article 1. Cooperative rules.",
        "blocks": [{"block_id": "b1", "text": "Article 1. Cooperative rules.", "bbox": [40, 40, 400, 60]}],
        "tables": [],
        "review_status": "needs_review",
    }
    artifact = dataset / "pages/TEST.jsonl"
    artifact.write_text(json.dumps(page) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "complete": True,
        "ocr_version": "test",
        "da_duyet": 0,
        "input_snapshot_sha256": locked["aggregate_sha256"],
        "counts": {"pages": 1},
        "corrections_sha256": hashlib.sha256(b"").hexdigest(),
        "sources": [
            {
                "source_id": "TEST",
                "source_sha256": sha256_file(pdf),
                "pages": [1],
                "page_count_expected": 1,
                "artifact": "pages/TEST.jsonl",
                "artifact_sha256": sha256_file(artifact),
            }
        ],
    }
    manifest["dataset_digest"] = digest_json(manifest)
    (dataset / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    script = """
import sys
from pathlib import Path
class RejectOCR:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"ocop_ocr", "easyocr", "vietocr", "torch", "cv2"}:
            raise ImportError("RAG imported OCR dependency: " + fullname)
sys.meta_path.insert(0, RejectOCR())
from ai_core.system.pipeline import OcopSystemPipeline, PipelineOptions
root = Path(sys.argv[1])
result = OcopSystemPipeline(root).ensure(PipelineOptions(ocr_dataset=root / "dataset", semantic_extract=False))
assert result["state"] == "ready", result
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
