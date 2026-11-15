"""The built graph keeps the structure answers rely on.

Structural bugs of the score-sheet tree (a merged sheet, a part lost to an OCR-cut heading, a group whose heading was not
read) passed every unit test and only showed when a user asked the wrong question. These checks read the graph that is
actually served, with checked edges only, so a rebuild that breaks the tree fails here.
"""

import json
from collections import defaultdict
from pathlib import Path

import pytest

GRAPH = Path(__file__).resolve().parents[3] / "data/processed/ocop/graph"


def _records(name):
    with (GRAPH / name).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


@pytest.fixture(scope="module")
def graph():
    if not (GRAPH / "nodes.jsonl").is_file():
        pytest.skip("graph not built")
    nodes = {n["node_id"]: n for n in _records("nodes.jsonl")}
    edges = [e for e in _records("edges.jsonl") if e.get("check") == "passed"]
    children = defaultdict(list)
    for edge in edges:
        if edge["relation_type"] in ("HAS_CRITERION", "HAS_SUBCRITERION"):
            children[edge["source_entity_id"]].append(edge["target_entity_id"])
    documents = {n["node_id"]: n["source_id"] for n in nodes.values() if n["node_type"] == "SourceDocument"}
    replaced = {documents[e["target_entity_id"]] for e in edges
                if e["relation_type"] == "REPLACES" and e["target_entity_id"] in documents}
    return nodes, children, replaced


def _points(node):
    value = (node.get("properties") or {}).get("max_points")
    return float(value) if value is not None else None


def test_every_sheet_of_the_framework_in_force_has_parts_worth_100_points(graph):
    nodes, children, replaced = graph
    sheets = [n for n in nodes.values() if n["node_type"] == "CriterionSheet" and n["source_id"] not in replaced]
    assert sheets
    wrong = {}
    for sheet in sheets:
        parts = [nodes[c] for c in children[sheet["node_id"]] if (nodes[c].get("properties") or {}).get("part_letter")]
        total = sum(_points(p) or 0 for p in parts)
        if sorted(p["properties"]["part_letter"] for p in parts) != ["A", "B", "C"] or total != 100:
            wrong[sheet["label"]] = (sorted(p["properties"]["part_letter"] for p in parts), total)
    assert not wrong, wrong


def test_the_groups_of_each_part_add_up_to_the_part(graph):
    nodes, children, replaced = graph
    wrong = {}
    for sheet in (n for n in nodes.values() if n["node_type"] == "CriterionSheet" and n["source_id"] not in replaced):
        for part_id in children[sheet["node_id"]]:
            part = nodes[part_id]
            groups = [nodes[c] for c in children[part_id]]
            stated = [_points(g) for g in groups]
            if _points(part) is not None and (None in stated or sum(stated) != _points(part)):
                wrong[f"{sheet['label']} / {part['label']}"] = (stated, _points(part))
    assert not wrong, wrong


def test_sheets_star_levels_and_recognition_records_all_pass_their_checks(graph):
    nodes, _, _ = graph
    failed = [(n["node_type"], n["label"]) for n in nodes.values()
              if n["node_type"] in ("CriterionSheet", "StarLevel", "RecognitionRecord") and n.get("check") != "passed"]
    assert not failed, failed
