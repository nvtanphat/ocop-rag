"""OCOP GraphRAG web API."""

import logging
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from backend.api.ocop_routes import router

ROOT = Path(__file__).resolve().parents[2]
INDEX_FILE = ROOT / "frontend" / "dist" / "index.html"


def _configure_logging() -> None:
    """The application's own log ("ocop.*"), beside uvicorn's access lines; OCOP_LOG_LEVEL changes its level."""
    log = logging.getLogger("ocop")
    if log.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(os.environ.get("OCOP_LOG_LEVEL", "INFO").upper())
    log.propagate = False


_configure_logging()

app = FastAPI(title="OCOP GraphRAG API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(router)

ASSETS_DIR = ROOT / "frontend" / "dist" / "assets"
if ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.get("/", include_in_schema=False)
def index():
    if INDEX_FILE.is_file():
        return FileResponse(INDEX_FILE, media_type="text/html")
    return {"status": "ok", "app": "OCOP GraphRAG API"}
