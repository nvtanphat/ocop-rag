"""Explicit local debug application. Never mounted by the production application."""
from pathlib import Path
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from backend.api.ocop_routes import AskRequest, service_unavailable
from ai_core.orchestration.ocop.workflow import OcopAgent
from ai_core.orchestration.ocop.llm import make_answer_client
from ai_core.orchestration.ocop.sessions import SessionStore


def create_debug_app(root: Path, *, allow_partial_debug: bool = False) -> FastAPI:
    if allow_partial_debug is not True:
        raise ValueError('Local debug application requires explicit allow_partial_debug=True')
    app = FastAPI(title='OCOP local partial corpus debug')
    sessions = SessionStore()  # same store type and masking as the public API

    @app.post('/api/ocop/query')
    async def query(request: AskRequest):
        try:
            agent = OcopAgent(root, llm=make_answer_client() if request.use_llm else None,
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
