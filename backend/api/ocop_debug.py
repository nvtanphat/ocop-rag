"""Explicit local debug application. Never mounted by the production application."""
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from backend.api import ocop_routes
from backend.api.ocop_routes import AskRequest, service_unavailable
from ai_core.orchestration.ocop.workflow import OcopAgent
from ai_core.orchestration.ocop.llm import make_answer_client
from ai_core.orchestration.ocop.dialogue import understand
from ai_core.orchestration.ocop.sessions import SessionStore


def create_debug_app(root: Path, *, allow_partial_debug: bool = False) -> FastAPI:
    if allow_partial_debug is not True:
        raise ValueError('Local debug application requires explicit allow_partial_debug=True')
    @asynccontextmanager
    async def lifespan(_app):
        # Load the embedding model / Qdrant connection before the first visitor asks, so request one is not a 40 s cold start.
        def run():
            try:
                OcopAgent(root, llm=None, allow_partial_debug=True, retrieval_mode='hybrid').ask('OCOP là gì?')
            except Exception:  # noqa: BLE001 - warm-up is best effort; real requests report their own errors
                pass
        threading.Thread(target=run, daemon=True).start()
        yield

    app = FastAPI(title='OCOP local partial corpus debug', lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'Authorization'])
    sessions = SessionStore()  # same store type and masking as the public API
    # The read-only routes (health, sources, PDF, evidence image, knowledge views) read OCOP_ROOT at import time, so they are
    # mounted only when it names this same corpus (tools/serve_sample.py sets it): a citation from /query then opens in the UI.
    # /query stays the debug one below; module state is never rewritten here.
    if ocop_routes.ROOT == root.resolve():
        for route in ocop_routes.router.routes:
            if getattr(route, 'path', None) != '/api/ocop/query':
                app.router.routes.append(route)

    @app.post('/api/ocop/query')
    async def query(request: AskRequest):
        try:
            use_llm = request.use_llm and understand(request.query)[0].action != 'respond'
            agent = OcopAgent(root, llm=make_answer_client() if use_llm else None,
                              allow_partial_debug=True, retrieval_mode=request.retrieval_mode)
        except (RuntimeError, ValueError, OSError) as exc:
            raise service_unavailable('llm_unavailable' if request.use_llm else 'agent_unavailable', 'configuration', exc) from exc
        try:
            answer = await run_in_threadpool(agent.ask, request.query, session=sessions.get(request.session_id))
        except (RuntimeError, ValueError, OSError) as exc:
            raise service_unavailable('query_failed', 'retrieval', exc) from exc
        sessions.save(request.session_id, request.query, answer)
        return answer.model_dump(mode='json')

    return app
