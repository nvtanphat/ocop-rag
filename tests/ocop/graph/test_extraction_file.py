"""The editable extraction file: export, edit a label, drop a row, build again."""

from __future__ import annotations

import json

from ai_core.graph.ocop.extraction_file import FILE_NAME, LOG_NAME, apply_edits, export_file, read_edits, short


def _citation(page):
    return {"source_id": "S", "evidence_unit_id": "u", "pdf_page": page, "bbox": [0, 0, 1, 1],
            "source_sha256": "a" * 64, "quote": "q"}


def _graph(tmp_path):
    nodes = [
        {"node_id": f"ocop:x:{'a' * 23}1", "node_type": "Obligation", "label": "Phai nop ho so", "check": "passed",
         "source_id": "S", "evidence_unit_ids": ["u"], "citations": [_citation(3)], "properties": {}},
        {"node_id": f"ocop:x:{'b' * 23}2", "node_type": "Concept", "label": "Ho so", "check": "passed",
         "source_id": "S", "evidence_unit_ids": ["u"], "citations": [_citation(3)], "properties": {}},
    ]
    edges = [{"edge_id": f"ocop:e:{'c' * 23}3", "relation_type": "HAS_OBJECT", "source_entity_id": nodes[0]["node_id"],
              "target_entity_id": nodes[1]["node_id"], "check": "passed", "source_id": "S",
              "evidence_unit_ids": ["u"], "citations": [_citation(3)]}]
    graph = tmp_path / "graph"
    graph.mkdir()
    for name, rows in (("nodes.jsonl", nodes), ("edges.jsonl", edges)):
        (graph / name).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return graph, nodes, edges


def test_the_exported_file_lists_nodes_and_edges_by_page(tmp_path):
    graph, nodes, _ = _graph(tmp_path)
    export_file(graph, tmp_path / "x")
    text = (tmp_path / "x" / FILE_NAME).read_text(encoding="utf-8")
    assert "## S — trang 3" in text
    assert f"[Norm] {short(nodes[0]['node_id'])} | Phai nop ho so" in text
    assert "[GOVERNS]" in text


def test_a_changed_label_and_a_deleted_line_are_applied_and_logged(tmp_path):
    graph, nodes, edges = _graph(tmp_path)
    directory = tmp_path / "x"
    export_file(graph, directory)
    path = directory / FILE_NAME
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("[Concept]")]
    path.write_text("\n".join(lines).replace("Phai nop ho so", "Phải nộp hồ sơ"), encoding="utf-8")
    kept_nodes, kept_edges, summary = apply_edits(nodes, edges, directory)
    assert [n["label"] for n in kept_nodes] == ["Phải nộp hồ sơ"]
    assert kept_nodes[0]["properties"]["extracted_label"] == "Phai nop ho so"
    assert kept_edges == [] and summary["dropped_nodes"] == 1 and summary["relabelled"] == 1
    assert {json.loads(line)["kind"] for line in (directory / LOG_NAME).read_text(encoding="utf-8").splitlines()} == {
        "label", "drop_node", "drop_edge"}


def test_a_row_that_was_never_exported_is_not_treated_as_deleted(tmp_path):
    graph, nodes, edges = _graph(tmp_path)
    export_file(graph, tmp_path / "x")
    extra = {**nodes[0], "node_id": f"ocop:x:{'d' * 23}4", "label": "Moi"}
    kept_nodes, _, _ = apply_edits([*nodes, extra], edges, tmp_path / "x")
    assert extra["node_id"] in {n["node_id"] for n in kept_nodes}


def test_without_a_file_nothing_changes(tmp_path):
    _, nodes, edges = _graph(tmp_path)
    assert read_edits(tmp_path / "none")["labels"] == {}
    assert apply_edits(nodes, edges, tmp_path / "none")[:2] == (nodes, edges)
