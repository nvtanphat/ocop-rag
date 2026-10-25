"""Release-level regression for coherent source state and UI entrypoint imports."""

from pathlib import Path
from fastapi.testclient import TestClient
from backend.api.ocop_main import app
from ai_core.system.pipeline import OcopSystemPipeline

ROOT = Path(__file__).resolve().parents[2]


def test_clean_source_bundle_requires_first_index_build():
    current = OcopSystemPipeline(ROOT).status(validate_sources=True)
    assert current["sources"] == 12
    assert current["source_snapshot_sha256"]
    if current["state"] == "ready":
        assert current["lineage_ok"] is True
        assert current["pdf_parser_current"] is True
    else:
        assert current["state"] in ("not_ready", "updating")
        assert current["lineage_ok"] is False


def test_health_exposes_source_and_parser_state():
    response = TestClient(app).get("/api/ocop/health")
    assert response.status_code == 200
    state = response.json()["pipeline"]
    assert state["sources"] == 12
    assert state["state"] in ("ready", "not_ready", "updating")


