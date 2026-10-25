import json

from ai_core.graph.ocop.builder import build_graph
from tests.ocop.test_graph_integrity import make_knowledge


def test_keep_three_recent_and_ledger_referenced_snapshots(tmp_path):
    knowledge = make_knowledge(tmp_path)
    output = tmp_path / "graph"
    ledger = tmp_path / "ledger.jsonl"
    versions = []
    for number in range(6):
        manifest_file = knowledge / "manifest.json"
        manifest = json.loads(manifest_file.read_text())
        manifest["corpus_version"] = f"fixture-{number}"
        manifest_file.write_text(json.dumps(manifest))
        result = build_graph(knowledge, output, review_decisions=ledger)
        versions.append(result["graph_version"])
        if number == 0:
            ledger.write_text(
                json.dumps(
                    {
                        "graph_version": versions[0],
                        "target_id": "absent",
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "content_hash": "test",
                        "decision": "reject",
                    }
                )
                + "\n"
            )
    assert {p.name for p in (output / "snapshots").iterdir() if p.is_dir()} == set(
        versions[-3:] + versions[:1]
    )
