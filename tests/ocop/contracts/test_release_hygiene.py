"""Verify distribution names remain descriptive and derived outputs stay out of source."""

from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_no_legacy_scripts_or_historical_docs():
    assert not (ROOT / "tools/smoke_e2e.py").exists()
    assert not (ROOT / "docs/archive").exists()
    assert not (ROOT / "tools/run_full_eval.ps1").exists()


def test_no_generated_output_or_release_label_in_distributed_names():
    source_paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    for name in ("reports", "outputs", "data/processed", "data/runtime", "data/review", "data/private"):
        assert not any(path == name or path.startswith(name + "/") for path in source_paths)
    assert not [path for path in source_paths if re.search(r"(?i)(?:^|[/_-])v\d+(?=[./_-]|$)", path)]


def test_manual_benchmark_does_not_reference_a_historical_release():
    import json

    cases = ROOT / "data/evaluations/ocop/manual_pdf_benchmark.jsonl"
    sources_file = ROOT / "data/evaluations/ocop/manual_pdf_sources.json"
    if not (cases.is_file() and sources_file.is_file()):
        pytest.skip("no manual PDF benchmark has been provided")
    ids = [json.loads(line)["id"] for line in cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert ids and len(ids) == len(set(ids))
    assert all(case.startswith("OCOP-QA-") for case in ids)
    sources = json.loads(sources_file.read_text(encoding="utf-8"))
    assert sources
    assert all("source_zip" not in item and "path_in_zip" not in item for item in sources.values())
