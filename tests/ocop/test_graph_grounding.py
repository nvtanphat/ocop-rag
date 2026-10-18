"""Independent RED tests for OCOP Graph Construction/Traversal .

Fixtures are intentionally synthetic. Do not change expectations to make tests pass.
"""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from ai_core.graph.ocop.builder import build_graph
from ai_core.graph.ocop.retriever import traverse


def put(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')


def root(tmp_path):
    k=tmp_path/'kb'
    k.mkdir()
    (k/'manifest.json').write_text(json.dumps({'complete': True, 'corpus_version': 'same-corpus'}))
    put(k/'evidence_units.jsonl', [
        {'unit_id':'unit-s1','source_id':'SOURCE-A','review_status':'verified','unit_kind':'paragraph','text':'Sản phẩm mật ong được công nhận','spans':[{'pdf_page':1}]},
        {'unit_id':'unit-s2','source_id':'SOURCE-B','review_status':'verified','unit_kind':'paragraph','text':'Hướng dẫn sản phẩm cà phê','spans':[{'pdf_page':2}]},
    ])
    put(k/'entities.jsonl', [
        {'entity_id':'doc-a','entity_type':'source_document','source_id':'SOURCE-A','name':'Văn bản A', 'review_status':'verified','evidence_unit_ids':['unit-s1']},
        {'entity_id':'doc-b','entity_type':'source_document','source_id':'SOURCE-B','name':'Văn bản B', 'review_status':'verified','evidence_unit_ids':['unit-s2']},
    ])
    put(k/'relations.jsonl', [])
    return k


def be(entity_id, kind, source='SOURCE-A', evid='unit-s1', label=None, status='verified'):
    return {'entity_id':entity_id, 'kind':kind, 'source_id':source, 'label': label or entity_id, 'status':status,
            'evidence':[{'source_id':source,'evidence_unit_id':evid,'pdf_page':1,'quote':'Sản phẩm mật ong'}],
            'attributes':{}}


def ref(source='SOURCE-A', uid='unit-s1'):
    return {'source_id':source,'evidence_unit_id':uid,'pdf_page':1,'quote':'Sản phẩm mật ong'}


def test_control_verified_graph_traversal_works(tmp_path):
    k=root(tmp_path); g=tmp_path/'g'; build_graph(k,g)
    got=traverse(g,['doc-a'],hops=1,verified_only=True)
    assert any(x['node_id']=='doc-a' for x in got['nodes'])
    assert all(x['review_status']=='verified' for x in got['nodes'])


def test_verified_only_must_not_return_unverified_seed(tmp_path):
    k=root(tmp_path); entities=[json.loads(s) for s in (k/'entities.jsonl').read_text().splitlines()]
    entities[0]['review_status']='needs_review'
    put(k/'entities.jsonl',entities);g=tmp_path/'g';build_graph(k,g)
    got=traverse(g,['doc-a'],hops=0,verified_only=True)
    assert got['nodes']==[], 'verified_only must filter seed nodes themselves'


def test_graph_version_changes_when_evidence_label_changes(tmp_path):
    k=root(tmp_path);g=tmp_path/'g';first=build_graph(k,g)
    entities=[json.loads(s) for s in (k/'entities.jsonl').read_text().splitlines()]
    entities[0]['name']='Văn bản A (đã hiệu đính)'
    put(k/'entities.jsonl',entities)
    second=build_graph(k,g)
    assert first['graph_version']!=second['graph_version'], 'content edits with stable IDs must invalidate graph snapshot version'


def test_graph_rejects_business_relation_with_unknown_evidence(tmp_path):
    k=root(tmp_path);g=tmp_path/'g'
    put(k/'business_entities.jsonl', [be('decision-1','RecognitionDecision'),be('record-1','RecognitionRecord')])
    put(k/'business_relations.jsonl', [
        {'relation_id':'rel-1','relation_type':'HAS_RECORD','source_entity_id':'decision-1','target_entity_id':'record-1',
         'status':'verified','evidence':[ref(uid='not-a-real-unit')]}
    ])
    build_graph(k,g)
    edges=[json.loads(x) for x in (g/'edges.jsonl').read_text().splitlines()]
    assert not any(e['relation_type']=='HAS_RECORD' for e in edges), 'orphan proof must not become verified edge'


def test_graph_rejects_business_relation_cross_source_evidence(tmp_path):
    k=root(tmp_path);g=tmp_path/'g'
    put(k/'business_entities.jsonl', [be('decision-1','RecognitionDecision'),be('record-1','RecognitionRecord')])
    put(k/'business_relations.jsonl', [
        {'relation_id':'rel-1','relation_type':'HAS_RECORD','source_entity_id':'decision-1','target_entity_id':'record-1',
         'status':'verified','evidence':[ref(source='SOURCE-B',uid='unit-s2')]}
    ])
    build_graph(k,g)
    edges=[json.loads(x) for x in (g/'edges.jsonl').read_text().splitlines()]
    assert not any(e['relation_type']=='HAS_RECORD' for e in edges), 'unrelated document proof must not justify relation'


def test_graph_rejects_duplicate_entity_id_conflicting_claims(tmp_path):
    k=root(tmp_path);g=tmp_path/'g'
    put(k/'business_entities.jsonl', [be('product-1','Product',label='Mật ong',status='verified'),
                                      be('product-1','Product',label='Cà phê',status='needs_review')])
    with pytest.raises(ValueError, match='duplicate|collision|conflict'):
        build_graph(k,g)
