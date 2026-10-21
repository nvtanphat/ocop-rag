"""OCOP-specific read/query API for the existing OCOP artifacts.

Never mounts user dossiers or trusts client-supplied authentication. The
reference library is explicitly allowlisted by configs/ocop_sources.json.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ConfigDict

from ai_core.orchestration.ocop.workflow import OcopAgent
from ai_core.orchestration.ocop.llm import make_answer_client
from ai_core.orchestration.ocop.sessions import default_store
from ai_core.system.pipeline import OcopSystemPipeline

ROOT = Path(os.environ.get('OCOP_ROOT',Path(__file__).resolve().parents[2])).resolve()
DATA = ROOT / "data" / "processed" / "ocop"
router = APIRouter(prefix="/api/ocop", tags=["OCOP knowledge"])


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=128)
    retrieval_mode: Literal["sparse", "dense", "hybrid"] = "sparse"
    use_llm: bool = False


def service_unavailable(code: str, layer: str, exc: Exception) -> HTTPException:
    """503 with a fixed schema {code, layer, error_type, message}; never echoes the exception text (may hold secrets)."""
    return HTTPException(status_code=503, detail={
        'code': code, 'layer': layer, 'error_type': type(exc).__name__,
        'message': 'Dịch vụ OCOP tạm thời chưa sẵn sàng; kiểm tra cấu hình hoặc hạ tầng rồi thử lại.'})


def _json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _jsonl(path: Path):
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


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


@router.get("/health")
def health():
    index = _json(DATA / "index" / "manifest.json")
    pages = _json(DATA / "pages" / "manifest.json")
    graph = _json(DATA / "graph" / "manifest.json")
    system = OcopSystemPipeline(ROOT).status(validate_sources=True)
    return {
        "status": system["state"],
        "pipeline": system,
        "sources_registered": len(_registry()),
        "pages": pages.get("counts", {}).get("pages", 0),
        "index_status": index.get("status", "missing"),
        "dense_ready": bool(index.get("dense", {}).get("enabled")),
        "graph_status": graph.get("status", "missing"),
        "corpus_version": index.get("corpus_version"),
    }


@router.get("/overview")
def overview():
    return {
        "sources": len(_registry()),
        "pages": _json(DATA / "pages" / "manifest.json").get("counts", {}),
        "knowledge": _json(DATA / "knowledge" / "manifest.json").get("counts", {}),
        "index": _json(DATA / "index" / "manifest.json"),
        "graph": _json(DATA / "graph" / "manifest.json"),
        "verification": "machine_extracted_not_verified",
    }


@router.get("/sources")
def sources():
    pages = _json(DATA / "pages" / "manifest.json")
    by_id = {s["source_id"]: s for s in pages.get("sources", [])}
    return [{
        "source_id": s["source_id"],
        "document_number": s.get("document_number"),
        "source_kind": s.get("source_kind"),
        "jurisdiction": s.get("jurisdiction"),
        "source_verification": s.get("source_verification"),
        "page_count": by_id.get(s["source_id"], {}).get("pages_processed", 0),
        "ocr_pages": by_id.get(s["source_id"], {}).get("counts", {}).get("ocr_executed", 0),
        "filename": Path(s["path"]).name,
    } for s in _registry()]


@router.get("/sources/{source_id}/pdf")
def source_pdf(source_id: str):
    item = _source_entry(source_id)
    file = _file_for(item)
    return FileResponse(file, media_type="application/pdf", content_disposition_type="inline", filename=file.name)


@router.get("/criteria")
def criteria(q: str = Query(default="", max_length=160), source_id: str = "", offset: int = Query(default=0, ge=0), limit: int = Query(default=25, ge=1, le=100)):
    filtered = []
    for row in _catalog('Criterion'):
        if source_id and row.get("source_id") != source_id:
            continue
        if q and q.casefold() not in row['label'].casefold():
            continue
        filtered.append(row)
    return {"items": filtered[offset:offset + limit], "total": len(filtered), "kind": "checked_graph"}


@router.get("/forms")
def forms():
    return {"items": _catalog('FormTemplate'), "kind": "checked_graph"}


@router.get("/recognitions")
def recognitions(q: str = Query(default="", max_length=160), offset: int = Query(default=0, ge=0), limit: int = Query(default=25, ge=1, le=100)):
    filtered = [row for row in _catalog('RecognitionRecord')
                if not q or q.casefold() in ' '.join([row['label'], *row['linked_labels']]).casefold()]
    return {"items": filtered[offset:offset + limit], "total": len(filtered), "kind": "checked_graph"}


def _catalog(kind):
    if not (DATA / 'graph' / 'manifest.json').is_file():
        return []
    _, nodes, edges = _checked_snapshot()
    by_id = {n['node_id']: n for n in nodes}
    linked = {}
    predicates = {'FormTemplate': {'HAS_FIELD'}, 'RecognitionRecord': {'RECOGNIZES', 'DECLARED_BY'}}
    for edge in edges:
        if edge['relation_type'] in predicates.get(kind, set()):
            linked.setdefault(edge['source_entity_id'], []).append(by_id[edge['target_entity_id']]['label'])
    return [{**node, 'linked_labels': sorted(set(linked.get(node['node_id'], [])))}
            for node in nodes if node['node_type'] == kind]


@lru_cache(maxsize=1)
def _graph_data(graph_version: str = ""):
    # Version-keyed cache invalidates automatically after a corpus swap.
    from ai_core.graph.ocop.integrity import validate_graph_snapshot
    path = DATA / 'graph' / 'snapshots' / graph_version
    validate_graph_snapshot(path)
    from ai_core.graph.ocop.grounding import usable, public_record
    nodes = [public_record(n) for n in _jsonl(path / "nodes.jsonl") if usable(n)]
    ids = {n['node_id'] for n in nodes}
    edges = [public_record(e) for e in _jsonl(path / "edges.jsonl") if usable(e)
             and e['source_entity_id'] in ids and e['target_entity_id'] in ids]
    return nodes, edges


@router.get("/graph")
def graph(q: str = Query(default="", max_length=160), node_type: str = "", limit: int = Query(default=60, ge=1, le=200)):
    if not (DATA / 'graph' / 'manifest.json').is_file():
        return {'nodes': [], 'edges': [], 'total_matches': 0,
                'kind': 'source_grounded_graph', 'status': 'graph_not_built'}
    manifest, nodes, edges = _checked_snapshot()
    if q:
        matches = [n for n in nodes if q.casefold() in str(n.get("label", "")).casefold()]
    elif node_type:
        matches = [n for n in nodes if n.get("node_type") == node_type]
    else:
        matches = [n for n in nodes if n.get("node_type") == "SourceDocument"]
        matches += [n for n in nodes if n.get("node_type") in ("Product", "Organization", "RecognitionDecision", "ProductGroup", "FormTemplate")]
    selected = matches[:limit]
    ids = {n["node_id"] for n in selected}
    connected = [e for e in edges if e.get("source_entity_id", e.get("source_id")) in ids and e.get("target_entity_id", e.get("target_id")) in ids]
    return {"nodes": selected, "edges": connected[:600], "total_matches": len(matches),
            "kind": "source_grounded_graph", 'validation': manifest['checks']}


def _checked_snapshot():
    from ai_core.graph.ocop.integrity import validate_graph_snapshot
    from ai_core.graph.ocop.builder import SCHEMA_REVISION
    try:
        manifest = validate_graph_snapshot(DATA / 'graph')
        if not manifest.get('checks') or manifest.get('schema_revision') != SCHEMA_REVISION:
            raise ValueError('graph check policy changed; rebuild corpus')
        nodes, edges = _graph_data(manifest['graph_version'])
        return manifest, nodes, edges
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(status_code=409, detail='Graph chưa có snapshot đã kiểm tra hợp lệ; cần build lại corpus.') from exc


# Session state contains only conversational slots, never identity/tenant permissions.
@lru_cache(maxsize=128)
def _agent(with_llm: bool, retrieval_mode: str, corpus_version: str = ""):
    # Never reuse an agent holding an obsolete index/graph after rebuild.
    return OcopAgent(ROOT, llm=make_answer_client() if with_llm else None, retrieval_mode=retrieval_mode)


@router.post("/query")
async def ask(request: AskRequest):
    manifest = _json(DATA / "index" / "manifest.json")
    if (DATA / ".promoting").exists():
        raise HTTPException(status_code=503, detail="Kho OCOP đang cập nhật, thử lại sau.")
    if not manifest:
        raise HTTPException(status_code=503, detail="Chưa chuẩn bị corpus OCOP. Chạy python tools/cli.py run.")
    # Fail closed: only a complete source-locked, parser-versioned corpus may be queried.
    readiness = OcopSystemPipeline(ROOT).status(validate_sources=True)
    if readiness["state"] != "ready":
        raise HTTPException(status_code=503, detail=(
            "Corpus OCOP chưa đồng bộ/đúng phiên bản. "
            "Chạy python tools/cli.py run --build-only."
        ))
    # Public search only. No client-provided tenant_id or dossier privileges.
    try:
        agent = _agent(request.use_llm, request.retrieval_mode, manifest.get("corpus_version", ""))
    except (RuntimeError, ValueError, OSError) as exc:
        raise service_unavailable('llm_unavailable' if request.use_llm else 'agent_unavailable', 'configuration', exc) from exc
    try:
        answer = await run_in_threadpool(agent.ask, request.query, session=default_store.get(request.session_id))
        default_store.save(request.session_id, request.query, answer)
        return answer.model_dump(mode="json")
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        raise service_unavailable('query_failed', 'retrieval', exc) from exc
