"""Single OCOP source-to-answer pipeline.

    python tools/cli.py run                  # prepare corpus and serve API
    python tools/cli.py run --query "..."    # prepare corpus and answer once
    python tools/cli.py run --build-only      # prepare corpus without serving
    python tools/cli.py status               # inspect corpus readiness
    python tools/cli.py debug --help         # advanced operator commands
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    cli = argparse.ArgumentParser(description="OCOP GraphRAG — one end-to-end pipeline")
    sub = cli.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="OCR dataset -> evidence -> retrieval/graph -> API or answer")
    run.add_argument("--root", type=Path, default=ROOT)
    run.add_argument("--ocr-dataset", type=Path, help="Complete source-locked OCR dataset directory")
    run.add_argument("--query", help="Answer one question after preparing the corpus")
    run.add_argument("--build-only", action="store_true", help="Prepare corpus without starting the API")
    run.add_argument("--refresh", action="store_true", help="Rebuild all derived artifacts (OCR cache reused)")
    run.add_argument("--dense", action="store_true", help="Build real EmbeddingGemma/Qdrant vectors")
    run.add_argument("--semantic-extract", action=argparse.BooleanOptionalAction, default=True,
                     help="Use the extraction LLM (OCOP_EXTRACT_LLM_PROVIDER) for source-grounded candidate entities, features, relations and rules (enabled by default; --no-semantic-extract disables it)")
    run.add_argument("--semantic-max-units", type=int, default=None,
                     help="Maximum EvidenceUnits sent to the extraction LLM (default: all eligible units)")
    run.add_argument("--full", action="store_true", help="Require Dense, MongoDB, Neo4j and the answer LLM")
    run.add_argument("--require-eval-gate", action="store_true", help="Block serving when verified production evaluation gates fail")
    run.add_argument("--mongo", action="store_true", help="Also materialize structured data in MongoDB")
    run.add_argument("--neo4j", action="store_true", help="Also publish graph into Neo4j")
    run.add_argument("--dpi", type=int, default=300)
    run.add_argument("--embedding-model", default="google/embeddinggemma-300m")
    run.add_argument("--embedding-revision")
    run.add_argument("--qdrant-host", default="localhost")
    run.add_argument("--qdrant-port", type=int, default=6333)
    run.add_argument("--mongo-uri", default="mongodb://127.0.0.1:27017")
    run.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    run.add_argument("--no-llm", action="store_true", help="Use evidence-only answer mode")
    run.add_argument("--retrieval-mode", choices=("auto", "sparse", "dense", "hybrid"), default="auto")
    run.add_argument("--rerank", action="store_true")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8000)
    eval_cmd = sub.add_parser("evaluate", help="Independent retrieval/agent eval; does not OCR PDFs")
    eval_cmd.add_argument('arguments', nargs=argparse.REMAINDER)
    status = sub.add_parser("status", help="Validate current unified corpus readiness")
    status.add_argument("--root", type=Path, default=ROOT)
    review=sub.add_parser('review',help='Export human review queue, record one decision, or show statistics')
    review.add_argument('action',choices=['queue','decide','stats','refresh-index'])
    review.add_argument('--root',type=Path,default=ROOT)
    review.add_argument('--out',type=Path)
    review.add_argument('--render',action='store_true',help='Render source-checked crops when exporting')
    review.add_argument('--target-id')
    review.add_argument('--content-hash')
    review.add_argument('--decision',choices=['approve','reject','correct'])
    review.add_argument('--reviewer')
    review.add_argument('--correction-file',type=Path)
    review.add_argument('--notes',default='')
    debug = sub.add_parser("debug", help="Developer commands for inspecting individual internal components")
    debug.add_argument("arguments", nargs=argparse.REMAINDER)
    if len(sys.argv)>1 and sys.argv[1]=='evaluate':
        completed=subprocess.run([sys.executable,str(ROOT/'tools'/'evaluate_ocop.py'),
                                  *sys.argv[2:]],cwd=ROOT,check=False)
        raise SystemExit(completed.returncode)
    args = cli.parse_args()
    if args.command=='review':
        from ai_core.graph.ocop.review import load_queue,statistics,record_decision,render_queue_crops,rebuild_reviewed_graph
        try:
            if args.action=='decide':
                if not all([args.target_id,args.content_hash,args.decision,args.reviewer]):
                    cli.error('decide requires --target-id, --content-hash, --decision, --reviewer')
                correction=json.loads(args.correction_file.read_text(encoding='utf-8')) if args.correction_file else None
                event=record_decision(args.root,args.target_id,args.content_hash,args.decision,args.reviewer,
                                      correction=correction,notes=args.notes)
                graph=rebuild_reviewed_graph(args.root)
                from ai_core.system.index_refresh import refresh_index_after_graph_change
                result={'decision':event,'graph':graph['counts'],'index':refresh_index_after_graph_change(args.root)}
            elif args.action=='refresh-index':
                from ai_core.system.index_refresh import refresh_index_after_graph_change
                result=refresh_index_after_graph_change(args.root)
            else:
                items=load_queue(args.root)
                result=statistics(items)
                if args.action=='queue':
                    target=args.out or args.root/'data/review/ocop_review_queue.jsonl'
                    target.parent.mkdir(parents=True,exist_ok=True)
                    if args.render:
                        result['unique_crops']=render_queue_crops(args.root,items)
                    target.write_text(''.join(json.dumps(i,ensure_ascii=False)+'\n' for i in items),encoding='utf-8')
                    result['output']=str(target)
            print(json.dumps(result,ensure_ascii=False,indent=2))
        except (ValueError,OSError,RuntimeError) as exc:
            print('OCOP review error: '+str(exc),file=sys.stderr);raise SystemExit(1) from exc
        return
    if args.command == "debug":
        completed = subprocess.run([sys.executable, str(ROOT / "tools" / "debug_cli.py"),
                                    *args.arguments], cwd=ROOT, check=False)
        raise SystemExit(completed.returncode)

    from ai_core.system.pipeline import OcopSystemPipeline, PipelineOptions
    system = OcopSystemPipeline(args.root.resolve())
    if args.command == "status":
        print(json.dumps(system.status(validate_sources=True), indent=2, ensure_ascii=False))
        return

    if args.build_only and args.query:
        cli.error("--build-only and --query are mutually exclusive")
    try:
        if args.full:
            from ai_core.orchestration.ocop.llm import answer_provider
            if answer_provider() == "ollama":
                from ai_core.system.runtime import verify_ollama_model
                verify_ollama_model(os.getenv("OCOP_OLLAMA_URL", "http://127.0.0.1:11434"),
                                    os.getenv("OCOP_LLM_MODEL", "qwen3.5:2b"))
        prepared = system.ensure(PipelineOptions(
            ocr_dataset=args.ocr_dataset,
            refresh=args.refresh, semantic_extract=args.semantic_extract, semantic_max_units=args.semantic_max_units, dense=args.dense or args.full, mongo=args.mongo or args.full, neo4j=args.neo4j or args.full,
            dpi=args.dpi,
            embedding_model=args.embedding_model, embedding_revision=args.embedding_revision,
            qdrant_host=args.qdrant_host, qdrant_port=args.qdrant_port,
            mongo_uri=args.mongo_uri, neo4j_uri=args.neo4j_uri,
        ))
        print(json.dumps({"pipeline": prepared}, indent=2, ensure_ascii=False), flush=True)
        if args.require_eval_gate or os.environ.get('OCOP_ENFORCE_RELEASE_GATE')=='1':
            from ai_core.evaluation.ocop.release import validate_latest
            gate=validate_latest(system.root,corpus_version=prepared.get('corpus_version'))
            if gate['status']!='pass':
                raise RuntimeError('OCOP production release blocked: '+', '.join(gate['failures']))
        if args.build_only:
            return
        if args.query:
            effective_mode = ("hybrid" if prepared["dense_ready"] else "sparse") if args.retrieval_mode == "auto" else args.retrieval_mode
            if effective_mode != "sparse" and not prepared["dense_ready"]:
                raise RuntimeError("Dense vectors missing. Re-run with --dense or use --retrieval-mode sparse")
            from ai_core.orchestration.ocop.workflow import OcopAgent
            from ai_core.orchestration.ocop.llm import make_answer_client
            llm = None if args.no_llm else make_answer_client()
            answer = OcopAgent(system.root, llm=llm, retrieval_mode=effective_mode,
                               rerank=args.rerank).ask(args.query)
            print(answer.model_dump_json(indent=2))
            return
        # API modules resolve their source/index/graph roots on import. Serve
        # exactly the corpus just prepared, even if an older OCOP_ROOT exists.
        os.environ['OCOP_ROOT'] = str(system.root)
        from uvicorn import run as serve
        serve("backend.api.ocop_main:app", host=args.host, port=args.port)
    except (RuntimeError, ValueError, FileNotFoundError, OSError) as exc:
        print(f"OCOP pipeline error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
