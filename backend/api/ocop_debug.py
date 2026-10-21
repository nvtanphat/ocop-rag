"""Explicit local debug application. Never mounted by the production application."""
from pathlib import Path
from fastapi import FastAPI, HTTPException
from starlette.concurrency import run_in_threadpool
from backend.api.ocop_routes import AskRequest
from ai_core.orchestration.ocop.workflow import OcopAgent
from ai_core.orchestration.ocop.llm import OllamaClient


def create_debug_app(root: Path, *, allow_partial_debug: bool = False) -> FastAPI:
    if allow_partial_debug is not True:
        raise ValueError('Local debug application requires explicit allow_partial_debug=True')
    app = FastAPI(title='OCOP local partial corpus debug')

    @app.post('/api/ocop/query')
    async def query(request: AskRequest):
        agent = OcopAgent(root, llm=OllamaClient() if request.use_llm else None,
                          allow_partial_debug=True,retrieval_mode=request.retrieval_mode)
        try:
            answer = await run_in_threadpool(agent.ask, request.query)
            return answer.model_dump(mode='json')
        except (RuntimeError, ValueError, OSError) as exc:
            raise HTTPException(503, 'Local debug query unavailable: '+type(exc).__name__) from exc

    return app
