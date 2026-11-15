"""A served graph for tests: nodes, edges and the manifest the runtime validates (status, checks, file hashes)."""

import json
from pathlib import Path

from ocop_contracts.ids import content_sha256
from ai_core.graph.ocop.builder import SCHEMA_REVISION


def write_checked_graph(path: Path, nodes: list[dict], edges: list[dict]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    digests = {}
    for name, rows in (("nodes.jsonl", nodes), ("edges.jsonl", edges)):
        data = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
        (path / name).write_bytes(data)
        digests[name] = content_sha256(data)
    manifest = {"status": "local_ready", "graph_version": "test", "schema_revision": SCHEMA_REVISION,
                "checks": {"fixture_only": True}, "file_sha256": digests}
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return path
