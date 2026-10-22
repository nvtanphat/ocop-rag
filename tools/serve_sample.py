"""Serve a partial sample corpus for a demo (debug app, allow_partial_debug=True; never the production API).

    python tools/serve_sample.py --root D:/AgentAI/OCOP-RAG/ocop-work-sample [--host 127.0.0.1] [--port 8001]

The sample's manifests stay labelled ``partial_debug_not_production``; the production app refuses such a corpus (HTTP 409),
this one opens it explicitly and says so in /api/ocop/health. Loads ``.env`` (answer LLM settings) before importing the app.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', type=Path, required=True, help='sample corpus root (configs/ + data/)')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8001)
    args = ap.parse_args()
    root = args.root.resolve()
    os.environ['OCOP_ROOT'] = str(root)  # read-only routes (sources, PDF, evidence image) resolve against the sample too
    from ai_core.orchestration.ocop.llm import load_env_file
    load_env_file()
    import uvicorn

    from backend.api.ocop_debug import create_debug_app
    uvicorn.run(create_debug_app(root, allow_partial_debug=True), host=args.host, port=args.port, log_level='info')


if __name__ == '__main__':
    main()
