"""Assertions about the usable projection of the single checked graph."""
from ai_core.graph.ocop.builder import records
from ai_core.graph.ocop.grounding import check_graph, usable


def checked_records(path):
    return (row for row in records(path) if usable(row))


def accepted_graph(*args, **kwargs):
    args = ([r.get("machine_candidate", r) | {k: v for k, v in r.items() if k in {"review_status"}}
             for r in args[0]],
            [r.get("machine_candidate", r) | {k: v for k, v in r.items() if k in {"review_status"}}
             for r in args[1]], *args[2:])
    nodes, edges, summary = check_graph(*args, **kwargs)
    exclusions = [{"record_type": kind, "record_id": row[key], "reason": row["check_reason"]}
                  for kind, rows, key in (("node", nodes, "node_id"), ("edge", edges, "edge_id"))
                  for row in rows if not usable(row)]
    return [n for n in nodes if usable(n)], [e for e in edges if usable(e)], exclusions, summary
