"""graph CLI: build source-backed graph and optionally upload to Neo4j."""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from ai_core.graph.ocop.builder import build_graph
from ai_core.graph.ocop.store import publish_neo4j

ROOT = Path(__file__).resolve().parents[3]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--knowledge", type=Path, default=Path("data/processed/ocop/knowledge"))
    p.add_argument("--output", type=Path, default=Path("data/processed/ocop/graph"))
    p.add_argument("--neo4j", action="store_true")
    p.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    p.add_argument("--neo4j-user", default="neo4j")
    p.add_argument("--verified-only", action="store_true")
    a = p.parse_args()
    knowledge = a.knowledge if a.knowledge.is_absolute() else ROOT / a.knowledge
    output = a.output if a.output.is_absolute() else ROOT / a.output
    result = build_graph(knowledge, output)
    if a.neo4j:
        password = os.getenv("NEO4J_PASSWORD")
        if not password:
            raise RuntimeError("NEO4J_PASSWORD required")
        result["neo4j"] = publish_neo4j(
            output, uri=a.neo4j_uri, user=a.neo4j_user, password=password, verified_only=a.verified_only
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
