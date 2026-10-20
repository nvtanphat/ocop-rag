"""Automatic graph acceptance and real downstream wiring, without human decisions."""
import json

from ai_core.knowledge.ocop.extractor import extract_semantics
from ai_core.graph.ocop.builder import build_graph, records
from ai_core.graph.ocop.retriever import traverse
from ai_core.orchestration.ocop.tools import ToolRegistry


def write(path, rows):
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')


def build(tmp_path, text='Điều 1. Trách nhiệm\n1. UBND cấp xã tiếp nhận hồ sơ.\na) Kiểm tra hồ sơ.'):
    base = tmp_path / 'data/processed/ocop'
    knowledge = base / 'knowledge'
    knowledge.mkdir(parents=True)
    unit = {'source_id': 'SOURCE.TEST', 'unit_id': 'unit:article', 'unit_kind': 'article',
            'text': text, 'structured': {}, 'review_status': 'machine_extracted',
            'spans': [{'pdf_page': 1, 'bbox': [0, 0, 200, 300], 'source_sha256': 'a' * 64}]}
    semantics = extract_semantics([unit], {'SOURCE.TEST': 'ocop_framework'}, {},
                                 source_registry={'SOURCE.TEST': {'document_number': '26/QĐ-TTg'}})
    (knowledge / 'manifest.json').write_text(json.dumps({'complete': True, 'corpus_version': 'contract-test'}))
    write(knowledge / 'evidence_units.jsonl', [unit])
    for name, rows in semantics.items():
        write(knowledge / (name + '.jsonl'), rows)
    graph = base / 'graph'
    manifest = build_graph(knowledge, graph)
    index = base / 'index'
    index.mkdir()
    (index / 'manifest.json').write_text(json.dumps({'corpus_version': 'contract-test',
                                                   'source_knowledge_version': 'contract-test'}))
    write(index / 'evidence_units.jsonl', [unit])
    write(index / 'structured.jsonl', [])
    return graph, manifest


def test_machine_extraction_reaches_agent_without_human_verification(tmp_path):
    graph, manifest = build(tmp_path)
    assert manifest['grounding']['edges'] > 0
    result = ToolRegistry(tmp_path).dispatch('search_graph', query='Điều 1 liên quan khoản nào', slots={},
        context={'retrieved_evidence_ids': ['unit:article']})
    assert result['grounded_only'] is True
    assert any(e['relation_type'] == 'HAS_CLAUSE' for e in result['edges'])
    assert result['results']
    assert all(r['source_spans'][0]['source_sha256'] == 'a' * 64 for r in result['results'])
    assert all(r['review_status'] != 'verified' for r in result['results'])
    assert result['paths']


def test_checked_traversal_has_path_evidence_and_no_score_promotion(tmp_path):
    graph, _ = build(tmp_path)
    article = next(n for n in records(graph / 'agent_nodes.jsonl') if n['node_type'] == 'Article')
    result = traverse(graph, [article['node_id']], hops=2, grounded_only=True)
    assert any(n['node_type'] == 'Point' for n in result['nodes'])
    assert any(len(path['edge_ids']) == 2 for path in result['paths'])
    assert all(e['citations'] and e['validation']['legal_verified'] is False for e in result['edges'])


def test_cooccurrence_and_negated_ownership_are_excluded(tmp_path):
    from ai_core.graph.ocop.grounding import materialize_grounded_graph
    for quote in ['Sản phẩm: Mật ong và HTX Hoa Sen cùng dự hội chợ',
                  'Sản phẩm: Mật ong không thuộc sở hữu của HTX Hoa Sen',
                  'Sản phẩm: Mật ong do HTX Hoa Sen sản xuất']:
        ref = {'source_id': 'SOURCE.TEST', 'evidence_unit_id': 'unit:1', 'pdf_page': 1,
               'bbox': [0, 0, 100, 10], 'source_sha256': 'a' * 64, 'quote': quote}
        nodes = [{'node_id': identity, 'node_type': kind, 'source_id': 'SOURCE.TEST', 'label': label,
                  'citations': [ref], 'evidence_unit_ids': ['unit:1'], 'review_status': 'needs_review'}
                 for identity, kind, label in [('p', 'Product', 'Mật ong'), ('o', 'Organization', 'HTX Hoa Sen')]]
        edge = {'edge_id': 'edge:1', 'source_entity_id': 'p', 'target_entity_id': 'o',
                'source_id': 'SOURCE.TEST', 'relation_type': 'OWNED_BY', 'citations': [ref],
                'evidence_unit_ids': ['unit:1'], 'review_status': 'needs_review'}
        _, edges, excluded, _ = materialize_grounded_graph(nodes, [edge], {'unit:1': {'text': quote}})
        assert edges == []
        assert excluded[-1]['reason'] == 'predicate_not_entailed_by_supported_verifier'


def test_graph_attribute_proof_is_not_lost_and_invalid_proof_is_rejected(tmp_path):
    from ai_core.knowledge.ocop.llm_proposals import propose
    from test_extraction_graph_contracts import Client
    graph, _ = build(tmp_path, 'Điều 1. Mật ong đóng chai thủy tinh')
    knowledge = graph.parent / 'knowledge'
    source = json.loads((knowledge / 'evidence_units.jsonl').read_text(encoding='utf-8'))
    result = propose([source], Client({'entities': [
        {'kind': 'Product', 'anchor': 'Mật ong', 'attributes': {'packaging': 'chai thủy tinh'}}]}))
    entities = list(records(knowledge / 'business_entities.jsonl')) + result['entities']
    write(knowledge / 'business_entities.jsonl', entities)
    build_graph(knowledge, graph)
    product = next(n for n in records(graph / 'agent_nodes.jsonl') if n['node_type'] == 'Product')
    assert product['properties']['packaging'] == 'chai thủy tinh'
    assert product['attribute_claims'][0]['status'] == 'source_grounded'
    assert product['attribute_claims'][0]['evidence'][0]['quote'] in source['text']
    result['entities'][0]['attribute_claims'][0]['evidence'][0]['source_sha256'] = 'b' * 64
    write(knowledge / 'business_entities.jsonl', entities)
    build_graph(knowledge, graph)
    assert not any(n['node_type'] == 'Product' for n in records(graph / 'agent_nodes.jsonl'))
    assert any(r['reason'] == 'business_attribute_missing_evidence' for r in records(graph / 'rejected.jsonl'))


def test_agent_executes_text_to_checked_multihop_graph_with_machine_sources(tmp_path):
    from ai_core.orchestration.ocop.workflow import OcopAgent
    from ai_core.orchestration.ocop.contracts import Route, Intent
    from ai_core.orchestration.ocop.planner import build_plan
    from ai_core.retrieval.ocop.index_pipeline import create_bm25
    graph, _ = build(tmp_path)
    index = graph.parent / 'index'
    source = next(records(index / 'evidence_units.jsonl'))
    chunk = {**source, 'chunk_id': 'chunk:source', 'evidence_unit_id': source['unit_id'],
             'corpus_version': 'contract-test', 'text_for_bm25': source['text']}
    write(index / 'chunks.jsonl', [chunk])
    create_bm25([chunk], index / 'bm25.json.gz')
    route = Route(intent=Intent.MULTIHOP_REASONING, strategy='graph_hybrid',
                  required_tools=['search_regulations', 'search_graph'])
    state = {'query': 'UBND cấp xã tiếp nhận hồ sơ liên quan Điều 1',
             'route': route.model_dump(mode='json'), 'plan': build_plan(route)}
    agent = OcopAgent(tmp_path)
    executed = agent.execute(state)
    result = next(r['output'] for r in executed['results'] if r['tool'] == 'search_graph')
    assert result['status'] == 'checked_source_graph'
    assert any(e['relation_type'] == 'HAS_CLAUSE' for e in result['edges'])
    assert result['results'] and result['paths']
    from ai_core.orchestration.ocop.answer import assemble
    answer = assemble(state['query'], executed['results'])
    assert answer['citations'] and answer['status'] == 'retrieval_only'
    assert any(r['source_sha256'] == 'a' * 64 for r in answer['citations'])
    assert OcopAgent._verified_slots(executed['results']) == {}


def test_public_graph_uses_checked_snapshot_and_detects_tampering(tmp_path, monkeypatch):
    from backend.api import ocop_routes as routes
    from backend.api.ocop_main import app
    from fastapi.testclient import TestClient
    graph, _ = build(tmp_path)
    monkeypatch.setattr(routes, 'DATA', graph.parent)
    routes._graph_data.cache_clear()
    client = TestClient(app)
    response = client.get('/api/ocop/graph?node_type=Article')
    assert response.status_code == 200
    assert response.json()['kind'] == 'source_grounded_graph'
    assert response.json()['nodes']
    (graph / 'agent_edges.jsonl').write_text('tampered', encoding='utf-8')
    assert client.get('/api/ocop/graph').status_code == 409
    routes._graph_data.cache_clear()


def test_recognition_table_links_are_checked_but_scores_stay_out(tmp_path):
    from test_business_knowledge_upgrade import _recognition_fixture
    from ai_core.processing.ocop.business_candidates import candidates
    graph, _ = build(tmp_path)
    knowledge = graph.parent / 'knowledge'
    table = _recognition_fixture()
    table['spans'][0]['source_sha256'] = 'b' * 64
    table['review_status'] = 'needs_review'
    sid = table['source_id']
    semantics = extract_semantics([table], {sid: 'recognition_decision'},
                                 candidates([table], {sid: 'recognition_decision'}))
    header = {'unit_id':'unit:heading', 'source_id':sid, 'text':'Quyết định công nhận sản phẩm OCOP',
              'unit_kind':'paragraph', 'review_status':'machine_extracted', 'structured':{},
              'spans':[{'pdf_page':1,'bbox':[0,0,200,30],'source_sha256':'b'*64}]}
    write(knowledge / 'evidence_units.jsonl', [table, header])
    for name, rows in semantics.items():
        write(knowledge / (name + '.jsonl'), rows)
    (knowledge / 'manifest.json').write_text(json.dumps({'complete':True,'corpus_version':'contract-test',
        'document_registry':{sid:{'source_kind':'recognition_decision','document_number':'1/QĐ-UBND'}}}))
    build_graph(knowledge, graph)
    nodes = list(records(graph / 'agent_nodes.jsonl'))
    edges = list(records(graph / 'agent_edges.jsonl'))
    assert sum(n['node_type']=='RecognitionRecord' for n in nodes) == 2
    assert sum(e['relation_type']=='RECOGNIZES' for e in edges) == 2
    assert sum(e['relation_type']=='DECLARED_BY' for e in edges) == 2
    assert not any(e['relation_type']=='OWNED_BY' for e in edges)
    assert all('star_rating_candidate' not in n['properties'] and 'score_candidate' not in n['properties'] for n in nodes)
    assert all('sao' not in n['label'] for n in nodes if n['node_type']=='RecognitionRecord')


def test_negated_feature_does_not_enter_agent_properties(tmp_path):
    from ai_core.knowledge.ocop.llm_proposals import propose
    from test_extraction_graph_contracts import Client
    graph, _ = build(tmp_path, 'Điều 1. Sản phẩm: Mật ong không đóng chai thủy tinh')
    knowledge = graph.parent / 'knowledge'
    source = next(records(knowledge / 'evidence_units.jsonl'))
    output = propose([source], Client({'entities': [
        {'kind':'Product','anchor':'Mật ong','attributes':{'packaging':'chai thủy tinh'}}]}))
    write(knowledge / 'business_entities.jsonl', list(records(knowledge / 'business_entities.jsonl')) + output['entities'])
    build_graph(knowledge, graph)
    product = next(n for n in records(graph / 'agent_nodes.jsonl') if n['node_type']=='Product')
    assert 'packaging' not in product['properties']
    assert any(e['reason']=='attribute_association_not_proven_or_conflicting' for e in records(graph / 'excluded_assertions.jsonl'))


def test_entity_cannot_borrow_a_different_documents_evidence(tmp_path):
    from ai_core.knowledge.ocop.llm_proposals import propose
    from test_extraction_graph_contracts import Client
    graph, _ = build(tmp_path, 'Điều 1. Sản phẩm: Mật ong đóng chai thủy tinh')
    knowledge = graph.parent / 'knowledge'
    source = next(records(knowledge / 'evidence_units.jsonl'))
    output = propose([source], Client({'entities':[{'kind':'Product','anchor':'Mật ong'}]}))
    output['entities'][0]['source_id'] = 'OTHER.SOURCE'
    write(knowledge / 'business_entities.jsonl', list(records(knowledge / 'business_entities.jsonl')) + output['entities'])
    build_graph(knowledge, graph)
    assert not any(n['node_type']=='Product' for n in records(graph / 'agent_nodes.jsonl'))
    assert any(r['reason']=='business_entity_source_mismatch' for r in records(graph / 'rejected.jsonl'))


def test_competing_parent_links_are_excluded_as_a_whole():
    from ai_core.graph.ocop.grounding import materialize_grounded_graph
    ref = {'source_id':'SOURCE.TEST','evidence_unit_id':'unit:forms','pdf_page':1,
           'bbox':[0,0,100,100],'source_sha256':'a'*64,'quote':'Mẫu 01, Mẫu 02: Tên sản phẩm'}
    nodes = [{'node_id':identity,'node_type':kind,'label':label,'source_id':'SOURCE.TEST',
              'review_status':'needs_review','properties':{},'citations':[ref],'evidence_unit_ids':['unit:forms']}
             for identity, kind, label in [('f1','FormTemplate','Mẫu 01'),('f2','FormTemplate','Mẫu 02'),
                                           ('field','FormField','Tên sản phẩm')]]
    edges = [{'edge_id':'edge:'+parent,'relation_type':'HAS_FIELD','source_entity_id':parent,
              'target_entity_id':'field','source_id':'SOURCE.TEST','review_status':'needs_review',
              'citations':[ref],'evidence_unit_ids':['unit:forms']} for parent in ['f1','f2']]
    accepted, relationships, exclusions, _ = materialize_grounded_graph(nodes, edges,
        {'unit:forms':{'text':ref['quote']}})
    assert not any(n['node_id']=='field' for n in accepted)
    assert not relationships
    assert any(e['reason']=='ambiguous_parentage' for e in exclusions)


def test_cli_serves_the_same_root_it_built(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    code = """
import os, sys, types, runpy
from ai_core.system.pipeline import OcopSystemPipeline
OcopSystemPipeline.ensure = lambda self, options: {'state':'ready','dense_ready':False}
sys.modules['uvicorn'] = types.SimpleNamespace(run=lambda *a, **k: print('served_root=' + os.environ.get('OCOP_ROOT','')))
sys.argv = ['tools/cli.py','run','--root',sys.argv[1],'--no-llm']
runpy.run_path('tools/cli.py',run_name='__main__')
"""
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8',
        env={**os.environ,'OCOP_ROOT':'different-root','OCOP_ENFORCE_RELEASE_GATE':'0'}, timeout=20)
    assert result.returncode == 0, result.stderr
    assert 'served_root=' + str(tmp_path.resolve()) in result.stdout
