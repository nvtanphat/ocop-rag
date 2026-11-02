"""Runtime data may ship; private data, rebuild caches and local state may not."""

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
    for name in (
        "reports", "outputs", "data/runtime", "data/review", "data/private", "data/models", "data/stores",
        "data/processed/ocop/cache", "data/processed/ocop/semantic_cache", "data/ocr-dataset/_raw",
    ):
        assert not any(path == name or path.startswith(name + "/") for path in source_paths)
    runtime = [path for path in source_paths if path.startswith("data/processed/")]
    allowed = ("data/processed/ocop/" + name + "/" for name in ("graph", "index", "knowledge", "pages"))
    allowed = tuple(allowed)
    assert all(path == "data/processed/ocop/system_manifest.json" or path.startswith(allowed) for path in runtime)
    assert not [path for path in runtime if Path(path).suffix in {".log", ".lock", ".sqlite", ".sqlite3", ".db"}]
    if runtime:
        import json

        version = json.loads((ROOT / "data/processed/ocop/graph/manifest.json").read_text(encoding="utf-8"))["graph_version"]
        snapshots = [path for path in runtime if "/snapshots/" in path]
        assert all(path.startswith(f"data/processed/ocop/graph/snapshots/{version}/") for path in snapshots)
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
