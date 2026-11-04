"""The role view: a closed vocabulary over the stored graph, with folded properties and lifted citations."""

from __future__ import annotations

from ai_core.graph.ocop.roles import _config, edge_roles, node_roles, project


def node(identity, kind, label="", evidence=("u1",), **properties):
    return {
        "node_id": identity,
        "node_type": kind,
        "label": label or identity,
        "check": "passed",
        "evidence_unit_ids": list(evidence),
        "citations": [{"source_id": "S", "evidence_unit_id": evidence[0], "pdf_page": 1, "bbox": [0, 0, 1, 1],
                       "source_sha256": "a" * 64, "quote": "q"}],
        "properties": properties,
    }


def edge(identity, relation, start, end):
    return {"edge_id": identity, "relation_type": relation, "source_entity_id": start, "target_entity_id": end,
            "check": "passed", "citations": [], "evidence_unit_ids": ["u1"]}


def test_every_mapped_type_has_one_role_and_roles_are_the_declared_vocabulary():
    nodes, edges = frozenset(_config()["nodes"]), frozenset(_config()["edges"])
    assert set(node_roles().values()) == nodes and set(edge_roles().values()) == edges
    assert len(nodes) == 14


def test_a_score_option_is_a_property_of_its_criterion_not_a_node():
    rows = [node("c", "Criterion"), node("o", "ScoreOption", "Có công bố", points_candidate=3)]
    out_nodes, _ = project(rows, [edge("e", "HAS_OPTION", "c", "o")])
    assert [n["node_id"] for n in out_nodes] == ["c"]
    option = out_nodes[0]["properties"]["options"][0]
    assert option["label"] == "Có công bố" and option["points_candidate"] == 3
    assert option["pdf_page"] == 1 and option["bbox"] == [0, 0, 1, 1] and option["source_sha256"] == "a" * 64


def test_a_norm_keeps_only_its_nearest_provision():
    rows = [node("a", "Article"), node("k", "Clause"), node("p", "Point"), node("n", "Obligation")]
    links = [edge(f"e{i}", "HAS_NORM", s, "n") for i, s in enumerate("akp")]
    _, out_edges = project(rows, links)
    assert [(e["source_entity_id"], e["relation_type"]) for e in out_edges] == [("p", "EXPRESSES")]


def test_an_edge_ending_at_an_evidence_unit_is_lifted_to_the_deepest_provision_that_quotes_it():
    rows = [node("a", "Article", evidence=("u1",)), node("k", "Clause", evidence=("u1",)),
            node("u", "EvidenceUnit", evidence=("u1",)), node("d", "Article", evidence=("u2",))]
    _, out_edges = project(rows, [edge("e", "CITES", "d", "u")])
    assert [(e["source_entity_id"], e["target_entity_id"], e["relation_type"]) for e in out_edges] == [
        ("d", "k", "REFERENCES")]


def test_types_without_a_role_stay_out_and_provenance_is_flat():
    rows = [node("m", "Mention"), node("c", "Criterion")]
    out_nodes, out_edges = project(rows, [edge("e", "MENTIONS", "m", "c")])
    assert [n["node_id"] for n in out_nodes] == ["c"] and out_edges == []
    assert {k: out_nodes[0][k] for k in ("source_id", "pdf_page", "bbox", "source_sha256", "evidence_unit_ids")} == {
        "source_id": "S", "pdf_page": 1, "bbox": [0, 0, 1, 1], "source_sha256": "a" * 64, "evidence_unit_ids": ["u1"]}


def test_every_stored_type_is_a_role_a_folded_property_or_declared_outside_the_answer_view():
    from ai_core.graph.ocop.ontology import EDGE_ENDPOINTS, NODE_TYPES
    from ai_core.graph.ocop.roles import _config

    config = _config()
    folded_nodes = {spec["child"] for spec in config["properties"].values()}
    folded_edges = {spec["relation"] for spec in config["properties"].values()}
    outside = config["not_answer"]
    assert not NODE_TYPES - node_roles().keys() - folded_nodes - set(outside["nodes"])
    assert not EDGE_ENDPOINTS.keys() - edge_roles().keys() - folded_edges - set(outside["edges"])
    assert not (node_roles().keys() | edge_roles().keys()) & set(outside["nodes"] + outside["edges"])
