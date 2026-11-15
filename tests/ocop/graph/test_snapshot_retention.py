import json

from ai_core.graph.ocop.builder import build_graph
from tests.ocop.graph.test_graph_integrity import make_knowledge


def test_keep_the_three_most_recent_snapshots(tmp_path):
    knowledge = make_knowledge(tmp_path)
    output = tmp_path / "graph"
    versions = []
    for number in range(6):
        manifest_file = knowledge / "manifest.json"
        manifest = json.loads(manifest_file.read_text())
        manifest["corpus_version"] = f"fixture-{number}"
        manifest_file.write_text(json.dumps(manifest))
        versions.append(build_graph(knowledge, output)["graph_version"])
    assert {p.name for p in (output / "snapshots").iterdir() if p.is_dir()} == set(versions[-3:])
