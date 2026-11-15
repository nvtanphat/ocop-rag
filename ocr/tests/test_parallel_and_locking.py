"""Actual subprocesses exercise process isolation and hard-stop recovery."""

import json
import subprocess
import sys

import fitz
import pytest

from ocop_contracts.locking import process_lock
from ocop_contracts.models import SourceDocument
from ocop_contracts.registry import snapshot
from ocop_ocr.pdf_pipeline import run_pipeline


def test_five_pages_parallel_match_serial(tmp_path):
    pdf = tmp_path / "sample.pdf"
    with fitz.open() as document:
        for number in range(5):
            page = document.new_page()
            page.insert_text((40, 60), f"Article {number + 1}. A native source paragraph.")
        document.save(pdf)
    source = SourceDocument(source_id="TEST", path="sample.pdf", source_kind="ocop_framework")
    registry, lock = tmp_path / "registry.json", tmp_path / "lock.json"
    registry.write_text(
        json.dumps({"schema_version": 1, "sources": [source.model_dump(mode="json")]}), encoding="utf-8"
    )
    lock.write_text(json.dumps(snapshot(tmp_path, [source])), encoding="utf-8")
    results = []
    for workers in (1, 3):
        output = tmp_path / f"out-{workers}"
        manifest = run_pipeline(
            tmp_path,
            registry=registry,
            lock=lock,
            output=output,
            cache_dir=tmp_path / f"cache-{workers}",
            ocr=False,
            workers=workers,
        )
        artifact = output / manifest["sources"][0]["artifact"]
        results.append(artifact.read_bytes())
    assert results[0] == results[1]


def test_hard_stop_releases_lock_without_manual_removal(tmp_path):
    path = tmp_path / "lock"
    ready = tmp_path / "ready"
    script = """
from pathlib import Path
import sys, time
from ocop_contracts.locking import process_lock
with process_lock(Path(sys.argv[1])):
    Path(sys.argv[2]).write_text("ready")
    while True:
        time.sleep(.05)
"""
    child = subprocess.Popen([sys.executable, "-c", script, str(path), str(ready)])
    try:
        import time

        deadline = time.monotonic() + 10
        while not ready.exists():
            assert time.monotonic() < deadline, "child did not acquire lock"
            time.sleep(0.02)
        with pytest.raises(RuntimeError, match="owns lock"):
            with process_lock(path):
                pytest.fail("two processes acquired the same lock")
        child.kill()
        child.wait(timeout=5)
        with process_lock(path):
            pass
        assert json.loads(path.read_text())["pid"] > 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
