"""Public import boundaries for the independent OCR distribution."""
import importlib
import subprocess
import sys


def test_shared_page_contract_preserves_existing_serialization():
    from ocop_contracts.models import PageArtifact

    page = PageArtifact(source_id="sample", pdf_page=1, width_pt=595, height_pt=842)
    assert page.model_dump(mode="json") == {
        "source_id": "sample", "source_sha256": None, "pdf_page": 1,
        "width_pt": 595.0, "height_pt": 842.0, "extracted_text": "",
        "blocks": [], "extraction_method": "unprocessed", "review_status": "pending",
    }


def test_ocr_has_no_dependency_on_parent_application():
    script = '''
import sys
class RejectParent:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "ai_core" or fullname.startswith("ai_core."):
            raise ImportError("OCR must not import ai_core")
sys.meta_path.insert(0, RejectParent())
import ocop_ocr.pdf_pipeline
import ocop_ocr.legend_proposals
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_legacy_import_is_same_module_for_existing_callers():
    assert importlib.import_module("ai_core.processing.ocop.pdf_pipeline") is importlib.import_module(
        "ocop_ocr.pdf_pipeline"
    )
