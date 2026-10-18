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

def test_frontend_icon_components_are_imported():
    # Regression: these JSX icons previously failed TypeScript compile.
    chat = (ROOT / "frontend/src/ocop/Chat.tsx").read_text(encoding="utf-8")
    dashboard = (ROOT / "frontend/src/pages/Dashboard.tsx").read_text(encoding="utf-8")
    assert "ExternalLink, Leaf, RotateCcw" in chat
    assert "GitBranch, Leaf, Menu, RefreshCcw" in dashboard
