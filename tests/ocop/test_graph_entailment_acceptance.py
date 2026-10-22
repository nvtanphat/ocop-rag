"""Graph acceptance and edge entailment contracts using synthetic evidence only."""

import json
from graph_check_helpers import checked_records

import pytest

from ai_core.graph.ocop.builder import build_graph, records
from graph_check_helpers import accepted_graph
from ai_core.knowledge.ocop.extractor import extract_semantics
from ai_core.processing.ocop.business_candidates import candidates


@pytest.mark.parametrize(('statement', 'expected'), [
    ('Bộ Y tế kiểm tra hồ sơ đối với các sản phẩm thực phẩm.', True),
    ('Đối với hồ sơ cần bổ sung, Bộ Y tế kiểm tra hồ sơ.', False),
    ('Nếu hồ sơ cần bổ sung, Bộ Y tế kiểm tra hồ sơ.', False),
    ('Bộ Y tế công nhận đối với các sản phẩm thực phẩm.', False),
    ('UBND cấp xã đề nghị Bộ Y tế kiểm tra hồ sơ đối với sản phẩm.', False),
])
def test_responsibility_object_preposition_is_not_a_conditional_scope(statement, expected):
    from ai_core.graph.ocop.grounding import _entails
    from ai_core.knowledge.ocop.authorities import resolve

    actor = {'properties': resolve('Bộ Y tế')}
    step = {'label': statement, 'properties': {'statement_candidate': statement},
            'evidence_unit_ids': ['unit']}
    assert _entails({'relation_type': 'RESPONSIBLE_FOR'}, actor, step,
                    {'unit': {'text': statement}}) is expected


def sheet_graph(tmp_path):
    from tests.ocop.test_criterion_sheets import fixture
    from tests.ocop.test_legal_structure import extract, REGISTRY

    units = fixture()
    knowledge = tmp_path / 'knowledge'
    knowledge.mkdir()
    (knowledge / 'manifest.json').write_text(json.dumps({
        'complete': True, 'corpus_version': 'synthetic', 'document_registry': REGISTRY,
    }), encoding='utf-8')
    for name, rows in {'evidence_units': units, **extract(units)}.items():
        (knowledge / f'{name}.jsonl').write_text(
            ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    graph = tmp_path / 'graph'
    build_graph(knowledge, graph)
    return list(records(graph / 'nodes.jsonl')), list(records(graph / 'edges.jsonl')), units


def test_numbered_criterion_accepts_printed_comma_and_no_space(tmp_path):
    nodes, _, _ = sheet_graph(tmp_path)
    for label in ('1.1, Tiêu chí', '3.1.Tiêu chí'):
        assert next(n for n in nodes if n['label'] == label)['check'] == 'passed'


def test_cross_page_option_requires_explicit_continuity_and_unbroken_scope(tmp_path):
    from copy import deepcopy
    from ai_core.graph.ocop.grounding import _entails

    nodes, edges, units = sheet_graph(tmp_path)
    by_id = {n['node_id']: n for n in nodes}
    option = next(n for n in nodes if n['label'] == 'Phương án cao')
    edge = next(e for e in edges if e['relation_type'] == 'HAS_OPTION'
                and e['target_entity_id'] == option['node_id'])
    assert edge['check'] == 'passed'
    source = by_id[edge['source_entity_id']]
    target = option.get('machine_candidate', option)
    source = source.get('machine_candidate', source)
    units = {u['unit_id']: u for u in units}
    assert _entails(edge, source, target, units)
    without_hint = deepcopy(units)
    for u in without_hint.values():
        u['structured'].pop('table_continuity', None)
    assert not _entails(edge, source, target, without_hint)
    other_sheet = deepcopy(target)
    other_sheet['properties']['sheet_number_candidate'] = '99'
    assert not _entails(edge, source, other_sheet, units)
    intervening = deepcopy(units)
    previous = next(u for u in intervening.values()
                    if u['structured'].get('table_id') == 'table:3')
    previous['structured']['cells'].append({'row': 6, 'col': 0, 'text': '1.2. Autre'})
    assert not _entails(edge, source, target, intervening)


def recognition_graph(tmp_path):
    from test_business_entity_extraction import _recognition_fixture

    table = _recognition_fixture()
    table["spans"][0]["source_sha256"] = "a" * 64
    table["review_status"] = "needs_review"
    sid = table["source_id"]
    header = {
        "unit_id": "heading",
        "source_id": sid,
        "unit_kind": "paragraph",
        "text": "Quyết định công nhận sản phẩm OCOP",
        "structured": {},
        "spans": [{"pdf_page": 1, "bbox": [0, 0, 400, 30], "source_sha256": "a" * 64}],
    }
    units = [table, header]
    semantics = extract_semantics(
        units, {sid: "recognition_decision"}, candidates(units, {sid: "recognition_decision"})
    )
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "manifest.json").write_text(
        json.dumps(
            {
                "complete": True,
                "corpus_version": "synthetic",
                "document_registry": {
                    sid: {"source_kind": "recognition_decision", "document_number": "1/QĐ-UBND"}
                },
            }
        ),
        encoding="utf-8",
    )
    for name, rows in {"evidence_units": units, **semantics}.items():
        (knowledge / f"{name}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
    graph = tmp_path / "graph"
    build_graph(knowledge, graph)
    return (
        list(records(graph / "nodes.jsonl")),
        list(records(graph / "edges.jsonl")),
        {u["unit_id"]: u for u in units},
    )


def test_ownership_accepts_checked_same_record_with_explicit_rowspan(tmp_path):
    nodes, edges, units = recognition_graph(tmp_path)
    accepted, relations, _, _ = accepted_graph(
        nodes, edges, units, registry={nodes[0]["source_id"]: {"source_kind": "recognition_decision"}}
    )
    assert len([e for e in relations if e["relation_type"] == "OWNED_BY"]) == 2
    assert all(e["review_status"] != "verified" for e in relations)
    assert any(n["node_type"] == "RecognitionRecord" for n in accepted)


def test_ownership_cannot_borrow_another_record_or_unchecked_link(tmp_path):
    nodes, edges, units = recognition_graph(tmp_path)
    registry = {
        next(n["source_id"] for n in nodes if n["node_type"] == "RecognitionRecord"): {
            "source_kind": "recognition_decision"
        }
    }
    # Leave each required edge somewhere in the table, but never on the same record.
    products = sorted(
        [e for e in edges if e["relation_type"] == "RECOGNIZES"], key=lambda e: e["source_entity_id"]
    )
    owners = sorted(
        [e for e in edges if e["relation_type"] == "DECLARED_BY"], key=lambda e: e["source_entity_id"]
    )
    edges = [e for e in edges if e["relation_type"] not in {"RECOGNIZES", "DECLARED_BY"}] + [
        products[0],
        owners[1],
    ]
    _, accepted, _, _ = accepted_graph(nodes, edges, units, registry=registry)
    assert not any(e["relation_type"] == "OWNED_BY" for e in accepted)
    owners[1]["review_status"] = "rejected"
    edges.append(owners[0] | {"review_status": "rejected"})
    _, accepted, _, _ = accepted_graph(nodes, edges, units, registry=registry)
    assert not any(e["relation_type"] == "OWNED_BY" for e in accepted)


def test_ownership_support_must_survive_graph_shape_checks(tmp_path):
    nodes, edges, units = recognition_graph(tmp_path)
    registry = {
        next(n["source_id"] for n in nodes if n["node_type"] == "RecognitionRecord"): {
            "source_kind": "recognition_decision"
        }
    }
    edges = [e for e in edges if e["relation_type"] != "HAS_RECORD"]
    _, accepted, _, _ = accepted_graph(nodes, edges, units, registry=registry)
    assert not any(e["relation_type"] == "OWNED_BY" for e in accepted)


@pytest.mark.parametrize("prefix", ["Không", "Nếu", "Trường hợp"])
def test_textual_ownership_rejects_negation_and_conditions(prefix):
    text = f"{prefix} sản phẩm: Mật ong thuộc sở hữu của HTX Hoa Sen."
    ref = {
        "source_id": "CURRENT",
        "evidence_unit_id": "unit",
        "pdf_page": 1,
        "bbox": [0, 0, 400, 100],
        "source_sha256": "a" * 64,
        "quote": text,
    }
    nodes = [
        {
            "node_id": identity,
            "node_type": kind,
            "label": label,
            "source_id": "CURRENT",
            "citations": [ref],
            "evidence_unit_ids": ["unit"],
            "review_status": "candidate",
        }
        for identity, kind, label in [
            ("product", "Product", "Mật ong"),
            ("owner", "Organization", "HTX Hoa Sen"),
        ]
    ]
    edge = {
        "edge_id": "ownership",
        "relation_type": "OWNED_BY",
        "source_id": "CURRENT",
        "source_entity_id": "product",
        "target_entity_id": "owner",
        "citations": [ref],
        "evidence_unit_ids": ["unit"],
        "review_status": "candidate",
    }
    _, edges, _, _ = accepted_graph(nodes, [edge], {"unit": {"text": text}})
    assert not edges


def legal_graph(text, relation, *, method=None):
    ref = {
        "source_id": "CURRENT",
        "evidence_unit_id": "clause",
        "pdf_page": 1,
        "bbox": [0, 0, 400, 100],
        "source_sha256": "a" * 64,
        "quote": text,
    }
    units = {
        uid: {
            "source_id": sid,
            "unit_id": uid,
            "text": body,
            "spans": [{"pdf_page": 1, "bbox": [0, 0, 400, 100], "source_sha256": "a" * 64}],
        }
        for uid, sid, body in [("clause", "CURRENT", text), ("target", "OLD", "Văn bản gốc")]
    }
    properties = (
        {"extraction_method": method, "llm_enriched_attributes": "issuer_candidate"} if method else {}
    )
    nodes = [
        {
            "node_id": identity,
            "node_type": "SourceDocument",
            "source_id": sid,
            "label": sid,
            "citations": [ref],
            "evidence_unit_ids": ["clause"],
            "review_status": "candidate",
            "properties": properties,
        }
        for identity, sid in [("current", "CURRENT"), ("old", "OLD")]
    ]
    edge = {
        "edge_id": "legal",
        "relation_type": relation,
        "source_entity_id": "current",
        "target_entity_id": "old",
        "source_id": "CURRENT",
        "citations": [ref],
        "evidence_unit_ids": ["clause"],
        "review_status": "candidate",
        "properties": properties,
    }
    return accepted_graph(
        nodes,
        [edge],
        units,
        registry={"CURRENT": {"document_number": "26/QĐ-TTg"}, "OLD": {"document_number": "148/QĐ-TTg"}},
    )


@pytest.mark.parametrize(
    ("relation", "cue"),
    [
        ("REPLACES", "thay thế"),
        ("REPLACES", "hết hiệu lực"),
        ("AMENDS", "sửa đổi"),
        ("AMENDS", "bổ sung"),
        ("BASED_ON", "Căn cứ"),
    ],
)
def test_document_relation_uses_registered_number_in_its_own_clause(relation, cue):
    _, edges, _, _ = legal_graph(f"Điều 1. {cue} Quyết định số 148/QĐ-TTg ngày 24 tháng 2.", relation)
    assert [e["relation_type"] for e in edges] == [relation]


@pytest.mark.parametrize(
    "text",
    [
        "1. Thay thế văn bản trước đây.\n2. Quyết định số 148/QĐ-TTg được nhắc đến.",
        "Điều 1. Thay thế văn bản trước đây.\nĐiều 2. Quyết định số 148/QĐ-TTg.",
        "Không thay thế Quyết định số 148/QĐ-TTg.",
        "Nếu thay thế Quyết định số 148/QĐ-TTg thì thông báo.",
        "Trường hợp thay thế Quyết định số 148/QĐ-TTg thì thông báo.",
        "Thay thế Quyết định số 1148/QĐ-TTg.",
        "Thay thế Quyết định số 148/QĐ-TTg-OTHER.",
    ],
)
@pytest.mark.parametrize("relation", ["REPLACES", "AMENDS", "BASED_ON"])
def test_document_relation_rejects_wrong_clause_negation_condition_or_number(text, relation):
    cue = {"REPLACES": "thay thế", "AMENDS": "sửa đổi", "BASED_ON": "căn cứ"}[relation]
    text = text.replace("Thay thế", cue).replace("thay thế", cue)
    _, edges, _, _ = legal_graph(text, relation)
    assert not edges


def test_agent_graph_preserves_llm_origin_without_verification():
    nodes, edges, _, _ = legal_graph(
        "Thay thế Quyết định số 148/QĐ-TTg.", "REPLACES", method="llm_candidate:synthetic-model"
    )
    for row in nodes + edges:
        assert row["properties"]["extraction_method"] == "llm_candidate:synthetic-model"
        assert row["properties"]["llm_enriched_attributes"] == "issuer_candidate"
        assert row["review_status"] != "verified"


def test_builder_keeps_llm_origin_on_generated_evidence_edges(tmp_path):
    from test_extraction_graph_contracts import Client
    from test_operational_graph import build, write
    from ai_core.knowledge.ocop.llm_proposals import propose

    graph, _ = build(tmp_path, "Điều 1. Sản phẩm: Mật ong đóng chai thủy tinh")
    knowledge = graph.parent / "knowledge"
    unit = next(records(knowledge / "evidence_units.jsonl"))
    output = propose([unit], Client({"entities": [{"kind": "Product", "anchor": "Mật ong"}]}))
    write(
        knowledge / "business_entities.jsonl",
        list(records(knowledge / "business_entities.jsonl")) + output["entities"],
    )
    build_graph(knowledge, graph)
    product = next(n for n in checked_records(graph / "nodes.jsonl") if n["node_type"] == "Product")
    links = [e for e in checked_records(graph / "edges.jsonl") if e["source_entity_id"] == product["node_id"]]
    assert links
    assert all(e["properties"]["extraction_method"] == "llm_candidate:offline" for e in links)
    assert all(e["review_status"] != "verified" for e in links)


def test_explicit_registered_suspension_has_a_checked_predicate():
    _, edges, _, _ = legal_graph('Điều 1. Tạm đình chỉ hiệu lực Quyết định số 148/QĐ-TTg.', 'SUSPENDS')
    assert [e['relation_type'] for e in edges] == ['SUSPENDS']


@pytest.mark.parametrize('text', [
    'Không tạm đình chỉ hiệu lực Quyết định số 148/QĐ-TTg.',
    'Nếu tạm đình chỉ hiệu lực Quyết định số 148/QĐ-TTg thì thông báo.',
    '1. Tạm đình chỉ hiệu lực văn bản trước đây.\n2. Quyết định số 148/QĐ-TTg được nhắc đến.',
])
def test_suspension_cannot_borrow_a_number_or_ignore_modality(text):
    _, edges, _, _ = legal_graph(text, 'SUSPENDS')
    assert edges == []


def test_list_item_inherits_its_list_header_but_not_a_sibling_items_condition():
    from ai_core.graph.ocop.grounding import _inherited_condition
    sibling = '2. Chủ tịch UBND cấp tỉnh thực hiện:\na) Trong trường hợp cần thiết, thông báo hướng dẫn hồ sơ\n'
    assert _inherited_condition(sibling, 'b) Chủ tịch UBND cấp tỉnh thành lập Hội đồng') == '2. Chủ tịch UBND cấp tỉnh thực hiện:'
    conditional_header = '2. Nếu sản phẩm đạt 1 sao:\na) lập biên bản\n'
    assert 'Nếu' in _inherited_condition(conditional_header, 'b) UBND cấp tỉnh thông báo')
    assert 'Trường hợp' in _inherited_condition('Nội dung A. Trường hợp X, ', 'UBND tổ chức họp')
