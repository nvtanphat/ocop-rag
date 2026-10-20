"""One checked graph contract, exercised through the builder and consumers."""
import json


def test_splitting_actors_does_not_drop_a_leading_condition(tmp_path):
    from test_operational_graph import build
    graph, _ = build(tmp_path, 'Điều 7. Trình tự\n1. Đối với sản phẩm đăng ký lại, '
                     'Chủ tịch UBND cấp tỉnh xem xét hồ sơ, UBND cấp tỉnh có văn bản và gửi hồ sơ.')
    edges = list(records(graph / 'edges.jsonl'))
    assert any(e['relation_type'] == 'RESPONSIBLE_FOR' for e in edges)
    assert not any(e['relation_type'] == 'RESPONSIBLE_FOR' and e['check'] == 'passed' for e in edges)

from ai_core.graph.ocop.builder import build_graph, records
from ai_core.graph.ocop.retriever import traverse


def test_builder_writes_one_graph_with_checks_and_preserves_failed_rows(tmp_path):
    from test_operational_graph import build, write

    graph, _ = build(tmp_path, 'Điều 1. Sản phẩm: Mật ong không thuộc sở hữu của HTX Hoa Sen.')
    knowledge = graph.parent / 'knowledge'
    from ai_core.knowledge.ocop.llm_proposals import propose
    from test_extraction_graph_contracts import Client

    unit = next(records(knowledge / 'evidence_units.jsonl'))
    result = propose([unit], Client({'entities': [
        {'kind': 'Product', 'anchor': 'Mật ong'}, {'kind': 'Organization', 'anchor': 'HTX Hoa Sen'}],
        'relations': [{'type': 'OWNED_BY', 'source': 0, 'target': 1}]}))
    write(knowledge / 'business_entities.jsonl', list(records(knowledge / 'business_entities.jsonl')) + result['entities'])
    write(knowledge / 'business_relations.jsonl', list(records(knowledge / 'business_relations.jsonl')) + result['relations'])
    manifest = build_graph(knowledge, graph)
    assert {p.name for p in graph.iterdir() if p.is_file()} == {'nodes.jsonl', 'edges.jsonl', 'manifest.json'}
    assert set(manifest['file_sha256']) == {'nodes.jsonl', 'edges.jsonl'}
    nodes, edges = list(records(graph / 'nodes.jsonl')), list(records(graph / 'edges.jsonl'))
    assert nodes and edges
    for row in nodes + edges:
        assert row['check'] in {'passed', 'failed', 'human_verified'}
        assert ('check_reason' in row) == (row['check'] == 'failed')
        assert row['origin'] == 'deterministic' or row['origin'].startswith('llm:')
        assert row['check'] != 'human_verified'
    product = next(n for n in nodes if n['node_type'] == 'Product')
    assert product['origin'] == 'llm:offline'
    ownership = next(e for e in edges if e['relation_type'] == 'OWNED_BY')
    assert ownership['check'] == 'failed'
    result = traverse(graph, [product['node_id']], hops=1)
    assert not any(e['relation_type'] == 'OWNED_BY' for e in result['edges'])


def test_verified_input_is_not_a_human_ledger_decision(tmp_path):
    from test_operational_graph import build

    graph, _ = build(tmp_path)
    knowledge = graph.parent / 'knowledge'
    path = knowledge / 'entities.jsonl'
    rows = list(records(path))
    for row in rows:
        row['review_status'] = 'verified'
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    units = list(records(knowledge / 'evidence_units.jsonl'))
    for unit in units:
        unit['review_status'] = 'verified'
    (knowledge / 'evidence_units.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in units), encoding='utf-8')
    build_graph(knowledge, graph)
    assert all(n['check'] != 'human_verified' for n in records(graph / 'nodes.jsonl'))


def test_invalid_construction_is_retained_but_never_traversed(tmp_path):
    from test_operational_graph import build, write
    from ai_core.graph.ocop.review import load_queue

    graph, _ = build(tmp_path)
    knowledge = graph.parent / 'knowledge'
    write(knowledge / 'business_entities.jsonl', [{
        'entity_id': 'bad-product', 'source_id': 'SOURCE.TEST', 'kind': 'Product',
        'label': 'Unsupported product', 'status': 'candidate', 'attributes': {},
        'evidence': [{'source_id': 'SOURCE.TEST', 'evidence_unit_id': 'missing',
                      'pdf_page': 1, 'bbox': [0, 0, 10, 10], 'quote': 'Unsupported product'}]}])
    build_graph(knowledge, graph)
    bad = next(n for n in records(graph / 'nodes.jsonl') if n['node_id'] == 'bad-product')
    assert bad['check'] == 'failed'
    assert bad['check_reason'] == 'business_entity_missing_evidence'
    assert not traverse(graph, ['bad-product'])['nodes']
    assert next(i for i in load_queue(tmp_path) if i['target_id'] == 'bad-product')['check'] == 'failed'


def test_public_catalogs_cannot_bypass_graph_checks(tmp_path, monkeypatch):
    from test_operational_graph import build, write
    from backend.api import ocop_routes as routes
    from backend.api.ocop_main import app
    from fastapi.testclient import TestClient

    graph, _ = build(tmp_path)
    for kind in ('criterion', 'form', 'recognition'):
        write(graph.parent / 'knowledge' / f'{kind}_candidates.jsonl', [{
            'candidate_id': 'UNSAFE', 'label_candidate': 'UNSAFE', 'row_text': 'UNSAFE'}])
    monkeypatch.setattr(routes, 'DATA', graph.parent)
    routes._graph_data.cache_clear()
    client = TestClient(app)
    for endpoint in ('criteria', 'forms', 'recognitions'):
        response = client.get('/api/ocop/' + endpoint)
        assert response.status_code == 200
        assert response.json()['kind'] == 'checked_graph'
        assert 'UNSAFE' not in response.text
    routes._graph_data.cache_clear()


def test_negated_submission_is_not_a_checked_evidence_requirement(tmp_path):
    from test_operational_graph import build
    graph, _ = build(tmp_path, 'Điều 6. Hồ sơ\n1. UBND cấp xã chuẩn bị hồ sơ, không nộp phiếu kiểm nghiệm.')
    edges = list(records(graph / 'edges.jsonl'))
    assert not any(e['relation_type']=='REQUIRES_EVIDENCE' and e['check']=='passed' for e in edges)
    assert not any(r['relation_type']=='REQUIRES_EVIDENCE'
                   for r in records(graph.parent / 'knowledge/business_relations.jsonl'))


def test_checked_actor_can_inherit_an_explicit_collective_header(tmp_path):
    from test_operational_graph import build
    graph, _ = build(tmp_path, 'Điều 4. Trách nhiệm\n1. Các Bộ: Y tế, Công Thương, Nông nghiệp và Môi trường\na) Chủ động rà soát hồ sơ.')
    nodes={r['node_id']:r for r in records(graph / 'nodes.jsonl')}
    actors={nodes[e['source_entity_id']]['label'] for e in records(graph / 'edges.jsonl')
            if e['relation_type']=='RESPONSIBLE_FOR' and e['check']=='passed'}
    assert actors == {'Bộ Y tế','Bộ Công Thương','Bộ Nông nghiệp và Môi trường'}
