"""OCOP-specific read/query API for the existing OCOP artifacts.

Never mounts user dossiers or trusts client-supplied authentication. The
reference library is explicitly allowlisted by configs/ocop_sources.json.
"""

from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ConfigDict

from ai_core.orchestration.ocop.workflow import OcopAgent
from ai_core.orchestration.ocop.llm import answer_provider, make_answer_client
from ai_core.orchestration.ocop.dialogue import understand
from ai_core.orchestration.ocop.sessions import default_store
from ai_core.system.pipeline import OcopSystemPipeline
from ai_core.system.profile import profile_status, rerank_enabled
from backend.api.graph_subgraph import MAX_SEEDS, SubgraphResponse, read_subgraph
from backend.api.reference_data import ReferenceResponse, read_references

ROOT = Path(os.environ.get("OCOP_ROOT", Path(__file__).resolve().parents[2])).resolve()
DATA = ROOT / "data" / "processed" / "ocop"
router = APIRouter(prefix="/api/ocop", tags=["OCOP knowledge"])
LOG = logging.getLogger("ocop.api")


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=128)
    retrieval_mode: Literal["sparse", "dense", "hybrid"] = "sparse"
    use_llm: bool = False


def service_unavailable(code: str, layer: str, exc: Exception) -> HTTPException:
    """503 with a fixed schema {code, layer, error_type, message}; never echoes the exception text (may hold secrets)."""
    # The operator sees which layer failed and with what kind of error; the exception text stays out of every log.
    LOG.warning("unavailable code=%s layer=%s error=%s", code, layer, type(exc).__name__)
    return HTTPException(
        status_code=503,
        detail={
            "code": code,
            "layer": layer,
            "error_type": type(exc).__name__,
            "message": "Dịch vụ OCOP tạm thời chưa sẵn sàng; kiểm tra cấu hình hoặc hạ tầng rồi thử lại.",
        },
    )


def _json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _registry() -> list[dict[str, Any]]:
    return _json(ROOT / "configs" / "ocop_sources.json").get("sources", [])


def _source_entry(source_id: str) -> dict[str, Any]:
    item = next((s for s in _registry() if s["source_id"] == source_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy nguồn trong danh mục OCOP")
    return item


def _file_for(item: dict[str, Any]) -> Path:
    base = (ROOT / "data" / "raw" / "ocop").resolve()
    file = (ROOT / item["path"]).resolve()
    if file.suffix.lower() != ".pdf" or not file.is_relative_to(base):
        raise HTTPException(status_code=403, detail="Đường dẫn nguồn không được phép")
    if not file.is_file():
        raise HTTPException(status_code=404, detail="Chưa có PDF gốc trong thư mục dữ liệu")
    return file


def query_summary(payload: dict, total_ms: float, use_llm: bool, retrieval_mode: str) -> dict:
    """One low-cardinality line per answered question: where it went and where the time was spent.

    Never holds the question, the session, the answer text or any evidence text."""
    trace = payload.get("tool_trace") or []
    tool_ms = sum(float(step.get("latency_ms") or 0) for step in trace if step.get("step") == "tool")
    diagnostics = payload.get("generation_diagnostics") or {}
    rejected = diagnostics.get("rejected")
    accepted = diagnostics.get("accepted")
    return {
        "status": payload.get("status"),
        "intent": payload.get("intent"),
        "path": (payload.get("route") or {}).get("retrieval_path"),
        "tools": payload.get("tools_used") or [],
        "mode": retrieval_mode,
        "llm": bool(use_llm),
        "citations": len(payload.get("citations") or []),
        "claims_accepted": accepted if isinstance(accepted, int) else len(accepted or []),
        "claims_rejected": len(rejected or []) if not isinstance(rejected, int) else rejected,
        "total_ms": round(total_ms),
        "tools_ms": round(tool_ms),
        "generation_ms": round(max(total_ms - tool_ms, 0)),
    }


def _answer_llm_ready() -> bool:
    """A hosted answer model is configured, so generation can be on by default. A local one may simply be off."""
    try:
        return answer_provider() == "openai" and make_answer_client() is not None
    except (RuntimeError, ValueError, OSError):
        return False


@router.get("/health")
def health():
    index = _json(DATA / "index" / "manifest.json")
    pages = _json(DATA / "pages" / "manifest.json")
    graph = _json(DATA / "graph" / "manifest.json")
    system = OcopSystemPipeline(ROOT).status(validate_sources=True, reuse_unchanged=True)
    try:
        profile = profile_status(ROOT)
    except ValueError:
        profile = {"profile": "invalid", "ready": False, "missing": ["invalid_profile"]}
    return {
        "status": system["state"] if profile["ready"] else "not_ready",
        "pipeline": system,
        "retrieval_profile": profile,
        "answer_llm": _answer_llm_ready(),
        "sources_registered": len(_registry()),
        "pages": pages.get("counts", {}).get("pages", 0),
        "index_status": index.get("status", "missing"),
        "dense_ready": bool(index.get("dense", {}).get("enabled")),
        "graph_status": graph.get("status", "missing"),
        "corpus_version": index.get("corpus_version"),
    }


@lru_cache(maxsize=32)
def _ocr_page_count(artifact: str, sha256: str) -> int:
    """Pages of one source artifact read by OCR (cached per artifact hash; a rebuilt artifact has a new hash)."""
    count = 0
    try:
        with (DATA / "pages" / artifact).open(encoding="utf-8") as lines:
            for line in lines:
                count += bool(json.loads(line).get("ocr_engine")) if line.strip() else 0
    except (OSError, ValueError):
        return 0
    return count


def _source_pages(entry: dict) -> tuple[int, int]:
    """(pages, OCR pages) of a source from the page manifest."""
    pages = len(entry.get("pages") or []) or int(entry.get("page_count_expected") or 0)
    artifact = entry.get("artifact")
    ocr = _ocr_page_count(artifact, entry.get("artifact_sha256", "")) if artifact else 0
    return pages, ocr


@router.get("/sources")
def sources():
    pages = _json(DATA / "pages" / "manifest.json")
    by_id = {s["source_id"]: s for s in pages.get("sources", [])}
    return [
        {
            "source_id": s["source_id"],
            "document_number": s.get("document_number"),
            "source_kind": s.get("source_kind"),
            "jurisdiction": s.get("jurisdiction"),
            "source_verification": s.get("source_verification"),
            "page_count": _source_pages(by_id.get(s["source_id"], {}))[0],
            "ocr_pages": _source_pages(by_id.get(s["source_id"], {}))[1],
            "filename": Path(s["path"]).name,
        }
        for s in _registry()
    ]


def references(kind: Literal["criteria", "products"]) -> ReferenceResponse:
    try:
        ready = OcopSystemPipeline(ROOT).status(validate_sources=True, reuse_unchanged=True)["state"] == "ready"
        return read_references(ROOT, kind, ready=ready)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        raise service_unavailable("reference_unavailable", "reference", exc) from exc


@router.get("/criteria", response_model=ReferenceResponse)
def criteria():
    return references("criteria")


@router.get("/products", response_model=ReferenceResponse)
def products():
    return references("products")


@router.get("/graph/subgraph", response_model=SubgraphResponse)
def graph_subgraph(
    node_id: list[str] = Query(default=[], max_length=MAX_SEEDS),
    evidence_unit_id: str | None = Query(default=None, max_length=128),
    hops: int = Query(default=1, ge=0, le=2),
    limit: int = Query(default=60, ge=1, le=150),
):
    """Checked neighbourhood of nodes or of the entities an evidence unit supports; public records only."""
    if not node_id and not evidence_unit_id:
        raise HTTPException(status_code=422, detail="Cần node_id hoặc evidence_unit_id.")
    if any(len(item) > 128 for item in node_id):
        raise HTTPException(status_code=422, detail="node_id không hợp lệ.")
    try:
        return read_subgraph(ROOT, node_ids=node_id, evidence_unit_id=evidence_unit_id, hops=hops, limit=limit)
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        raise service_unavailable("graph_unavailable", "graph", exc) from exc


@router.get("/sources/{source_id}/pdf")
def source_pdf(source_id: str):
    item = _source_entry(source_id)
    file = _file_for(item)
    return FileResponse(
        file, media_type="application/pdf", content_disposition_type="inline", filename=file.name
    )


@router.get("/sources/{source_id}/pages/{page}/evidence.png")
def source_page_evidence(
    source_id: str,
    page: int,
    box: list[str] = Query(default=[]),
    context: list[str] = Query(default=[]),
    sha: str | None = Query(default=None, pattern=r"^[0-9a-f]{64}$"),
    dpi: int = Query(default=110),
    crop: bool = False,
):
    """PDF page (or the evidence region) with cited boxes highlighted; see backend/api/evidence_image.py."""
    from fastapi.responses import Response
    from backend.api.evidence_image import EvidenceImageError, parse_boxes, render_evidence_png

    file = _file_for(_source_entry(source_id))
    try:
        png = render_evidence_png(
            ROOT,
            file,
            source_id,
            page,
            evidence=parse_boxes(box),
            context=parse_boxes(context),
            expected_sha=sha,
            dpi=dpi,
            crop=crop,
        )
    except EvidenceImageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise service_unavailable("render_failed", "pdf", exc) from exc
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


# Session state contains only conversational slots, never identity/tenant permissions.
@lru_cache(maxsize=128)
def _agent(
    with_llm: bool,
    retrieval_mode: str,
    corpus_version: str = "",
    allow_partial_debug: bool = False,
    rerank: bool = False,
):
    # Never reuse an agent holding an obsolete index/graph after rebuild.
    return OcopAgent(
        ROOT,
        llm=make_answer_client() if with_llm else None,
        retrieval_mode=retrieval_mode,
        rerank=rerank,
        allow_partial_debug=allow_partial_debug,
    )


@router.post("/query")
async def ask(request: AskRequest):
    # Whether this deployment can serve the requested mode does not depend on the corpus, so it is decided first.
    try:
        profile = profile_status(ROOT)
    except ValueError as exc:
        raise service_unavailable("profile_invalid", "configuration", exc) from exc
    if request.retrieval_mode != "sparse" and profile["profile"] == "sparse":
        raise HTTPException(
            status_code=422,
            detail="Bản triển khai này chỉ phục vụ truy xuất sparse; cấu hình OCOP_RETRIEVAL_PROFILE=hybrid để dùng dense/hybrid.",
        )
    if not profile["ready"]:
        raise service_unavailable("retrieval_profile_unready", "retrieval", RuntimeError(",".join(profile["missing"])))
    manifest = _json(DATA / "index" / "manifest.json")
    if (DATA / ".promoting").exists():
        raise HTTPException(status_code=503, detail="Kho OCOP đang cập nhật, thử lại sau.")
    if not manifest:
        raise HTTPException(
            status_code=503, detail="Chưa chuẩn bị corpus OCOP. Chạy python tools/cli.py run."
        )
    readiness = OcopSystemPipeline(ROOT).status(validate_sources=True, reuse_unchanged=True)
    allow_partial = readiness["state"] != "ready" and bool(manifest.get("corpus_version"))
    if not allow_partial and readiness["state"] != "ready":
        raise HTTPException(
            status_code=503,
            detail=("Corpus OCOP chưa đồng bộ/đúng phiên bản. Chạy python tools/cli.py run --build-only."),
        )
    # Public search only. No client-provided tenant_id or dossier privileges.
    try:
        use_llm = request.use_llm and understand(request.query)[0].action != "respond"
        agent = _agent(
            use_llm,
            request.retrieval_mode,
            manifest.get("corpus_version", ""),
            allow_partial,
            rerank=rerank_enabled() and request.retrieval_mode != "sparse",
        )
    except (RuntimeError, ValueError, OSError) as exc:
        raise service_unavailable(
            "llm_unavailable" if request.use_llm else "agent_unavailable", "configuration", exc
        ) from exc
    started = time.monotonic()
    try:
        answer = await run_in_threadpool(
            agent.ask, request.query, session=default_store.get(request.session_id)
        )
        default_store.save(request.session_id, request.query, answer)
        payload = answer.model_dump(mode="json")
        LOG.info(
            "query %s",
            json.dumps(
                query_summary(payload, (time.monotonic() - started) * 1000, use_llm, request.retrieval_mode),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        return payload
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        raise service_unavailable("query_failed", "retrieval", exc) from exc
