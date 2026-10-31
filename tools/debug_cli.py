"""OCOP GraphRAG CLI: PDF audit, extraction, indexing, graph building and querying.

Usage: python tools/cli.py <command> [-- arguments]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Vietnamese command descriptions require UTF-8 on Windows; replacement keeps
# terminals that cannot render a glyph from turning output into a crash.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).parents[1]

# command name -> (importable "module.path", one-line description)
_MODULE_COMMANDS: dict[str, tuple[str, str]] = {
    "build-ocop-graph": (
        "ai_core.graph.ocop.cli",
        "OCOP graph: validate and materialize local graph, optionally publish Neo4j",
    ),
    "ask-ocop": (
        "ai_core.orchestration.ocop.cli",
        "OCOP agent: routed GraphRAG answer with an OpenAI-compatible LLM",
    ),
    "extract-ocop": (
        "ai_core.processing.ocop.knowledge_extract",
        "OCOP evidence: extract evidence units, facts, entities and relations",
    ),
    "index-ocop": (
        "ai_core.retrieval.ocop.index_pipeline",
        "OCOP retrieval: chunks, BM25 and optional real EmbeddingGemma/Qdrant index",
    ),
    "lookup-ocop": (
        "ai_core.retrieval.ocop.lookup",
        "OCOP retrieval: exact evidence/candidate lookup by document, page and ID",
    ),
    "search-ocop": (
        "ai_core.retrieval.ocop.search",
        "OCOP retrieval: query evidence by BM25, dense or RRF hybrid",
    ),
    "process-ocop-pdf": (
        "ocop_ocr.pdf_pipeline",
        "OCOP PDF: source-locked native text/OCR/layout/table extraction",
    ),
    "smoke-ocop": (
        "ai_core.system.smoke",
        "OCOP debug smoke: selected pages through OCR, evidence, index, graph and agent",
    ),
    "audit-ocop": (
        "ai_core.processing.ocop_audit",
        "Read-only full OCOP PDF inventory and per-page OCR classification",
    ),
    "lock-ocop": (
        "ai_core.processing.ocop_audit",
        "Lock approved OCOP PDF hashes (explicit source change only)",
    ),
}

def _list_commands() -> str:
    lines = ["Available commands:", ""]
    width = max(len(name) for name in _MODULE_COMMANDS)
    for name, (_, desc) in sorted(_MODULE_COMMANDS.items()):
        lines.append(f"  {name:<{width}}  {desc}")
    return "\n".join(lines)


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print()
        print(_list_commands())
        sys.exit(0 if argv else 1)

    command, *rest = argv
    if rest[:1] == ["--"]:
        rest = rest[1:]

    if command in _MODULE_COMMANDS:
        module, _ = _MODULE_COMMANDS[command]
        cmd = [sys.executable, "-m", module, *rest]
        if command == "lock-ocop":
            cmd.append("--write-lock")
    else:
        print(f"Unknown command: {command!r}\n", file=sys.stderr)
        print(_list_commands(), file=sys.stderr)
        sys.exit(2)

    result = subprocess.run(cmd, cwd=str(_ROOT), check=False)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
