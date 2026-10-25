import json
import sys

import pytest

from ocop_ocr import __main__ as cli
from ocop_ocr import pdf_pipeline


def test_failed_run_has_diagnostic_state_and_status_can_read_it(tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise RuntimeError("worker stopped")

    monkeypatch.setattr(pdf_pipeline, "run_pipeline", fail)
    monkeypatch.setattr(sys, "argv", ["ocop_ocr", "run", "--dataset", str(tmp_path), "--page", "source:2"])
    with pytest.raises(RuntimeError, match="worker stopped"):
        cli.main()
    state = json.loads((tmp_path / "run-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "failed"
    assert state["requested_pages"] == ["source:2"]
    assert not (tmp_path / "manifest.json").exists()
    monkeypatch.setattr(sys, "argv", ["ocop_ocr", "status", "--dataset", str(tmp_path)])
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["complete"] is False
    assert result["run"]["error"] == "RuntimeError: worker stopped"


def test_status_reports_abandoned_run_without_publishing(tmp_path, monkeypatch, capsys):
    (tmp_path / "run-state.json").write_text(json.dumps({"status": "running", "pid": 42}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["ocop_ocr", "status", "--dataset", str(tmp_path)])
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["run"]["status"] == "interrupted"
    assert result["complete"] is False
    assert "rerun" in result["action"]
