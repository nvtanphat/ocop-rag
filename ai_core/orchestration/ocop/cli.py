"""agent: query OCOP graph/retrieval agent. Requires no API server."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from ai_core.orchestration.ocop.workflow import OcopAgent
from ai_core.orchestration.ocop.llm import OllamaClient
ROOT=Path(__file__).resolve().parents[3]
def main():
    p=argparse.ArgumentParser(description="OCOP rule-first LangGraph/LLM query")
    p.add_argument("query")
    p.add_argument("--root",type=Path,default=ROOT)
    p.add_argument("--with-llm",action="store_true",help="Use real Ollama Qwen3.5 2B")
    p.add_argument("--require-langgraph",action="store_true")
    p.add_argument("--retrieval-mode",choices=("sparse","dense","hybrid"),default="sparse")
    p.add_argument("--rerank",action="store_true")
    p.add_argument("--debug-candidates",action="store_true")
    p.add_argument("--session-json",type=Path,default=None,help="Authenticated session from trusted app, not untrusted PDF")
    a=p.parse_args()
    session=json.loads(a.session_json.read_text(encoding="utf-8")) if a.session_json else {}
    agent=OcopAgent(a.root.resolve(),llm=OllamaClient() if a.with_llm else None,
                    retrieval_mode=a.retrieval_mode,rerank=a.rerank)
    result=agent.ask(a.query,session=session,context={"debug_candidates":a.debug_candidates},
                     require_langgraph=a.require_langgraph)
    print(result.model_dump_json(indent=2))
if __name__=="__main__":main()
