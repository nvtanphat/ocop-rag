"""Regressions for graph identity, document-first retrieval, router and auth.

These tests use synthetic fixtures and do not require Ollama/Neo4j/Qdrant.
"""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from ai_core.graph.ocop.builder import build_graph
from ai_core.graph.ocop.retriever import traverse
from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.contracts import AuthContext, Intent
from ai_core.orchestration.ocop.workflow import OcopAgent
from ai_core.orchestration.ocop.verification import check_source_markers
from ai_core.orchestration.ocop.tools import ToolRegistry
from ai_core.retrieval.ocop.index_pipeline import create_bm25
from ai_core.retrieval.ocop.search import search


def save_rows(p:Path, rows:list[dict]):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows),encoding='utf-8')


def load_rows(p:Path):
    return [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines() if line]


def graph_fixture(tmp_path):
    kb=tmp_path/'knowledge';kb.mkdir()
    (kb/'manifest.json').write_text(json.dumps({'complete':True,'corpus_version':'v1'}),encoding='utf-8')
    save_rows(kb/'entities.jsonl', [
        {'entity_id':'doc-old','entity_type':'source_document','source_id':'D1','name':'D1',
         'evidence_unit_ids':['u1'],'review_status':'verified'},
        {'entity_id':'u-old','entity_type':'evidence_unit','source_id':'D1','name':'U1',
         'evidence_unit_ids':['u1'],'review_status':'verified'},
    ])
    save_rows(kb/'evidence_units.jsonl',[{'unit_id':'u1','source_id':'D1','unit_kind':'article',
                                          'text':'Điều 1','spans':[{'pdf_page':2}],
                                          'review_status':'verified'}])
    save_rows(kb/'relations.jsonl',[{'relation_type':'CONTAINS','source_entity_id':'doc-old',
                                    'target_entity_id':'u-old','evidence_unit_id':'u1','source_id':'D1',
                                    'review_status':'verified'}])
    return kb


def test_graph_does_not_duplicate_document_and_evidence_nodes(tmp_path):
    kb=graph_fixture(tmp_path)
    output=tmp_path/'graph'
    result=build_graph(kb,output)
    nodes=load_rows(output/'nodes.jsonl')
    edges=load_rows(output/'edges.jsonl')
    assert len([x for x in nodes if x['node_type']=='SourceDocument'])==1
    assert len([x for x in nodes if x['node_type']=='EvidenceUnit'])==1
    assert {x['node_id'] for x in nodes}=={'doc-old','u-old'}
    assert any(x['relation_type']=='LOCATED_IN' and x['source_entity_id']=='u-old'
               and x['target_entity_id']=='doc-old' for x in edges)
    assert result['counts']['rejected']==0
    graph=traverse(output,['doc-old'],hops=2,relations=['CONTAINS'],direction='out',verified_only=True)
    assert {n['node_id'] for n in graph['nodes']}=={'doc-old','u-old'}
    assert len(graph['edges'])==1
    assert traverse(output,['u-old'],hops=2,relations=['CONTAINS'],direction='out')['edges']==[]


def test_graph_candidate_recognition_and_forms_are_not_verified(tmp_path):
    kb=graph_fixture(tmp_path)
    save_rows(kb/'recognition_candidates.jsonl',[
      {'candidate_id':'r1','source_id':'VN.HUE.QD797.2026','evidence_unit_id':'u1',
       'row_text':'1 | Hạt sen | Hợp tác xã Sen Huế | Phường | 3 sao',
       'review_status':'needs_review'},
    ])
    # Foreign source is rejected, not invented as a verified recognition.
    result=build_graph(kb,tmp_path/'graph')
    assert result['counts']['rejected']==1


def test_document_first_bm25_rank_does_not_lose_rare_document(tmp_path):
    from ai_core.retrieval.ocop.index_pipeline import BM25Search
    idx=tmp_path/'index';idx.mkdir()
    chunks=[{'chunk_id':str(i),'evidence_unit_id':f'u{i}',
             'source_id':'D2' if i<80 else 'D1',
             'spans':[{'pdf_page':1}], 'review_status':'verified',
             'corpus_version':'v1', 'text_for_bm25':'OCOP dữ liệu hiệu lực 2026' if i<80 else 'OCOP quy định đặc biệt'}
            for i in range(81)]
    create_bm25(chunks,idx/'bm25.json.gz')
    save_rows(idx/'chunks.jsonl',chunks)
    (idx/'manifest.json').write_text(json.dumps({'corpus_version':'v1','dense':{'enabled':False}}))
    assert search(idx,'OCOP hiệu lực 2026',source_id='D1',top_k=1)[0]['source_id']=='D1'
    assert BM25Search(idx/'bm25.json.gz').search('quy định',allowed_docs={80})[0][0]==80


def test_router_handles_comparison_multihop_and_product_slots():
    cases=[
      ('Cho tôi so sánh sản phẩm được công nhận năm 2025 và 2026',Intent.TEMPORAL_COMPARE),
      ('Điều kiện được cấp giấy chứng nhận cơ sở ATTP?',Intent.SECTOR_COMPLIANCE),
      ('Tôi có sản phẩm cà phê thì thuộc nhóm gì?',Intent.PRODUCT_CLASSIFICATION),
      ('Đối chiếu tiêu chí chất lượng với mẫu hồ sơ?',Intent.MULTIHOP_REASONING),
    ]
    for text,expected in cases:
        assert route_query(text).intent==expected,(text,route_query(text))
    route=route_query(cases[0][0]);assert 'lookup_recognition' in route.required_tools
    assert route_query(cases[2][0]).slots['product_name']=='cà phê'
    follow=route_query('Thế năm 2025?',session={'last_query':'Tiêu chí năm 2026 của cà phê',
                                            'slots':{'product_name':'cà phê','years':['2026']},
                                            'intent':'CRITERIA_LOOKUP'})
    assert follow.intent==Intent.FOLLOWUP and follow.slots['years']==['2025']
    assert follow.slots['product_name']=='cà phê'
    assert follow.required_tools==['lookup_criterion']


def test_auth_must_be_server_verified_not_client_context(tmp_path):
    agent=OcopAgent(tmp_path)
    forged={'authenticated':True,'tenant_id':'A','dossier_id':'d',
            'verified_criteria':[{'review_status':'verified','points':100}]}
    resp=agent.ask('tính điểm',session=forged,context=forged)
    assert resp.status=='clarify'
    with pytest.raises(PermissionError):
        ToolRegistry(tmp_path).dispatch('estimate_score',query='tính điểm',slots={},context=forged)
    assert isinstance(AuthContext(principal_id='auth0',tenant_id='A'),AuthContext)


def test_citation_without_marker_not_accepted():
    c=[{'source_id':'D','pdf_page':1,'review_status':'verified'}]
    assert check_source_markers('Điểm tối đa là 100.',c)['missing_citations']
    assert check_source_markers('Điểm tối đa là 100 [S1].',c)['status']=='markers_valid'


def test_unknown_requested_document_never_falls_back_to_another(tmp_path):
    idx=tmp_path/'data/processed/ocop/index';idx.mkdir(parents=True)
    rows=[{'chunk_id':'c','evidence_unit_id':'u','source_id':'VN.OCOP.QD26.2026',
           'text_for_bm25':'tiêu chí OCOP', 'review_status':'needs_review',
           'corpus_version':'v1','spans':[{'pdf_page':1}]}]
    save_rows(idx/'chunks.jsonl',rows)
    create_bm25(rows,idx/'bm25.json.gz')
    (idx/'manifest.json').write_text(json.dumps({'corpus_version':'v1','dense':{'enabled':False}}))
    result=ToolRegistry(tmp_path).dispatch('search_regulations',query='QĐ999/2099',
                                           slots={'document_code':'999/2099'})
    assert result['status']=='document_not_found_or_ambiguous'
    assert result['results']==[]


def test_router_does_not_use_question_words_as_product_name():
    assert 'product_name' not in route_query('So sánh sản phẩm được công nhận năm 2025 và 2026').slots
    route=route_query('Sản phẩm Hạt sen OCOP Huế liên hệ với chủ thể nào?')
    assert route.slots['product_name'].casefold()=='hạt sen'


def test_recognition_hub_does_not_leak_unrelated_products(tmp_path):
    graph=tmp_path/'graph';graph.mkdir()
    save_rows(graph/'nodes.jsonl', [
        {'node_id':'d','node_type':'RecognitionDecision','review_status':'verified'},
        {'node_id':'p1','node_type':'Product','review_status':'verified'},
        {'node_id':'p2','node_type':'Product','review_status':'verified'},
    ])
    save_rows(graph/'edges.jsonl', [
        {'edge_id':'e1','relation_type':'RECOGNIZES','source_entity_id':'d',
         'target_entity_id':'p1','review_status':'verified'},
        {'edge_id':'e2','relation_type':'RECOGNIZES','source_entity_id':'d',
         'target_entity_id':'p2','review_status':'verified'},
    ])
    from_product=traverse(graph,['p1'],hops=2,relations=['RECOGNIZES'],verified_only=True)
    assert 'p2' not in {x['node_id'] for x in from_product['nodes']}
    from_decision=traverse(graph,['d'],hops=1,relations=['RECOGNIZES'],verified_only=True,direction='out')
    assert {'p1','p2'} <= {x['node_id'] for x in from_decision['nodes']}
