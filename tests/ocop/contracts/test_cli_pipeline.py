"""Real native dataset -> public CLI -> public API, with no model or remote service."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient

from backend.api import ocop_routes
from backend.api.ocop_main import app
from tests.fixtures.corpus import create_native_corpus

ROOT = Path(__file__).resolve().parents[3]


def run(*arguments):
    result = subprocess.run(
        [sys.executable, *arguments],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_complete_dataset_builds_and_serves_source_bound_answers(tmp_path, monkeypatch):
    pdf = create_native_corpus(tmp_path)
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    dataset = tmp_path / "data/ocr-dataset"
    # A real producer run over native text. --without-ocr guarantees no model call.
    producer = subprocess.run(
        [
            sys.executable,
            "-m",
            "ocop_ocr",
            "run",
            "--root",
            str(tmp_path),
            "--dataset",
            str(dataset),
            "--workers",
            "1",
            "--without-ocr",
        ],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
    )
    assert producer.returncode == 0, producer.stdout + producer.stderr
    assert json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))["complete"] is True
    built = run("tools/cli.py", "run", "--root", str(tmp_path), "--no-semantic-extract", "--build-only")
    assert built["pipeline"]["state"] == "ready"
    assert run("tools/cli.py", "status", "--root", str(tmp_path))["state"] == "ready"

    monkeypatch.setattr(ocop_routes, "ROOT", tmp_path)
    monkeypatch.setattr(ocop_routes, "DATA", tmp_path / "data/processed/ocop")
    ocop_routes._agent.cache_clear()
    try:
        with TestClient(app) as client:
            assert client.get("/api/ocop/health").json()["status"] == "ready"
            response = client.post(
                "/api/ocop/query", json={"query": "OCOP program registration", "use_llm": False}
            )
            assert response.status_code == 200
            citations = response.json()["citations"]
            assert citations
            for citation in citations:
                assert citation["source_id"] == "SYNTHETIC.OCOP.REFERENCE"
                assert citation["source_sha256"] == sha
                assert citation["pdf_page"] == 1
                assert citation["bbox"] and citation["evidence_unit_id"]
                assert citation["review_status"] != "verified"
    finally:
        ocop_routes._agent.cache_clear()
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == sha
