"""The one file the owner edits after extraction (like the reviewed OCR text): export it, edit it, build again.

``data/extraction/entities-relations.md`` lists the answer-grade entities and relations page by page::

    ## VN.LAW.17.2023 — trang 5
    [Norm] 001b1c6ac3d9e17f02a81d67 | Tổng số thành viên chính thức là tổ chức kinh tế ...
    [GOVERNS] 7c1e0d3a... 001b1c6a... -> 05bb9fa7...

Edit the text after ``|`` to fix a label; delete a whole line to drop that entity (with its relations) or that relation.
The next build applies the file: it never changes the quote, page, bbox or SHA of a row, keeps the extracted label in
``properties.extracted_label`` and logs every change in ``corrections.jsonl``. There is no approval step.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ocop_contracts.ids import content_sha256

FILE_NAME = "entities-relations.md"
EXPORTED_NAME = "exported.json"
LOG_NAME = "corrections.jsonl"
_HEADING = re.compile(r"^##\s+(?P<source>\S+)\s+—\s+(?P<page>.+?)\s*$")
_NODE = re.compile(r"^\[(?P<role>[A-Za-z]+)\]\s+(?P<id>[0-9a-f]{8,})\s*\|\s?(?P<label>.*)$")
_EDGE = re.compile(r"^\[(?P<role>[A-Z_]+)\]\s+(?P<id>[0-9a-f]{8,})\s+(?P<source>[0-9a-f]{8,})\s+->\s+(?P<target>[0-9a-f]{8,})\s*$")


def short(identity: str) -> str:
    """The hash part of an ID: what the file shows and what a line is matched by."""
    return identity.rsplit(":", 1)[-1]


def export_file(graph_dir: Path, directory: Path) -> dict:
    """Write the editable file from the published graph, and remember which rows it lists."""
    from ai_core.graph.ocop.builder import records
    from ai_core.graph.ocop.grounding import public_record, relation_usable, usable
    from ai_core.graph.ocop.roles import project

    graph_dir, directory = Path(graph_dir), Path(directory)
    nodes = [public_record(n) for n in records(graph_dir / "nodes.jsonl") if usable(n)]
    known = {n["node_id"]: n for n in nodes}
    edges = [
        public_record(e)
        for e in records(graph_dir / "edges.jsonl")
        if usable(e) and e["source_entity_id"] in known and e["target_entity_id"] in known
        and relation_usable(e, known)
    ]
    role_nodes, role_edges = project(nodes, edges)
    pages = defaultdict(lambda: defaultdict(list))
    for node in role_nodes:
        pages[(node.get("source_id") or "", node.get("pdf_page") or 0)]["nodes"].append(node)
    by_id = {n["node_id"]: n for n in role_nodes}
    for edge in role_edges:
        owner = by_id[edge["source_entity_id"]]
        key = (edge.get("source_id") or owner.get("source_id") or "", edge.get("pdf_page") or owner.get("pdf_page") or 0)
        pages[key]["edges"].append(edge)
    lines = [
        "<!-- Sửa chữ sau dấu | để sửa nhãn; xóa cả dòng để bỏ thực thể hoặc quan hệ. Không có bước duyệt. -->",
        "",
    ]
    for (source, page), group in sorted(pages.items()):
        lines.append(f"## {source} — {'trang ' + str(page) if page else 'không rõ trang'}")
        for node in sorted(group["nodes"], key=lambda n: n["node_id"]):
            label = " ".join(str(node.get("label") or "").split())
            lines.append(f"[{node['role']}] {short(node['node_id'])} | {label}")
        for edge in sorted(group["edges"], key=lambda e: e["edge_id"]):
            lines.append(
                f"[{edge['relation_type']}] {short(edge['edge_id'])} "
                f"{short(edge['source_entity_id'])} -> {short(edge['target_entity_id'])}"
            )
        lines.append("")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / FILE_NAME).write_text("\n".join(lines), encoding="utf-8", newline="\n")
    exported = {
        "nodes": {short(n["node_id"]): " ".join(str(n.get("label") or "").split()) for n in role_nodes},
        "edges": sorted(short(e["edge_id"]) for e in role_edges),
    }
    (directory / EXPORTED_NAME).write_text(json.dumps(exported, ensure_ascii=False), encoding="utf-8")
    return {"nodes": len(role_nodes), "edges": len(role_edges), "file": str(directory / FILE_NAME)}


def read_edits(directory: Path) -> dict:
    """What the owner changed since the last export: relabelled nodes and dropped nodes and edges (by hash)."""
    directory = Path(directory)
    path, exported_path = directory / FILE_NAME, directory / EXPORTED_NAME
    if not path.is_file() or not exported_path.is_file():
        return {"labels": {}, "drop_nodes": set(), "drop_edges": set(), "sha256": None}
    exported = json.loads(exported_path.read_text(encoding="utf-8"))
    present_nodes, present_edges, labels = set(), set(), {}
    for line in path.read_text(encoding="utf-8").splitlines():
        node, edge = _NODE.match(line), _EDGE.match(line)
        if node:
            present_nodes.add(node["id"])
            label = " ".join(node["label"].split())
            if node["id"] in exported["nodes"] and label and label != exported["nodes"][node["id"]]:
                labels[node["id"]] = label
        elif edge:
            present_edges.add(edge["id"])
    return {
        "labels": labels,
        "drop_nodes": set(exported["nodes"]) - present_nodes,
        "drop_edges": set(exported["edges"]) - present_edges,
        "sha256": content_sha256(path.read_bytes()),
    }


def apply_edits(nodes: list[dict], edges: list[dict], directory: Path) -> tuple[list[dict], list[dict], dict]:
    """Apply the owner's edits to built rows; return the rows and a summary (also appended to the corrections log)."""
    edits = read_edits(directory)
    dropped = edits["drop_nodes"]
    if not (edits["labels"] or dropped or edits["drop_edges"]):
        return nodes, edges, {"sha256": edits["sha256"], "relabelled": 0, "dropped_nodes": 0, "dropped_edges": 0}
    kept_nodes, relabelled, log = [], 0, []
    gone = {n["node_id"] for n in nodes if short(n["node_id"]) in dropped}
    for node in nodes:
        key = short(node["node_id"])
        if node["node_id"] in gone:
            log.append({"kind": "drop_node", "id": node["node_id"], "label": node.get("label")})
            continue
        if key in edits["labels"] and node.get("label") != edits["labels"][key]:
            properties = {**node.get("properties", {}), "extracted_label": node.get("label")}
            log.append({"kind": "label", "id": node["node_id"], "from": node.get("label"), "to": edits["labels"][key]})
            node = {**node, "label": edits["labels"][key], "properties": properties}
            relabelled += 1
        kept_nodes.append(node)
    kept_edges, dropped_edges = [], 0
    for edge in edges:
        if (
            short(edge["edge_id"]) in edits["drop_edges"]
            or edge["source_entity_id"] in gone
            or edge["target_entity_id"] in gone
        ):
            dropped_edges += 1
            log.append({"kind": "drop_edge", "id": edge["edge_id"], "relation": edge["relation_type"]})
            continue
        kept_edges.append(edge)
    if log:
        stamp = datetime.now(timezone.utc).isoformat()
        with (Path(directory) / LOG_NAME).open("a", encoding="utf-8", newline="\n") as stream:
            for row in log:
                stream.write(json.dumps({**row, "timestamp": stamp}, ensure_ascii=False) + "\n")
    summary = {
        "sha256": edits["sha256"],
        "relabelled": relabelled,
        "dropped_nodes": len(gone),
        "dropped_edges": dropped_edges,
    }
    return kept_nodes, kept_edges, summary
