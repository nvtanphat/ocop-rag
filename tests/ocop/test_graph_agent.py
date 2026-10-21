"""Unit/contract tests for graph/agent. No model, Neo4j or network required."""
from __future__ import annotations
import json
import pytest
from ai_core.graph.ocop.builder import build_graph
from ai_core.graph.ocop.ontology import validate_edge
from ai_core.graph.ocop.retriever import traverse
from ai_core.graph.ocop.temporal import applicable
from ai_core.assessment.ocop.rules import checklist,estimate_score
from ai_core.assessment.ocop.dossiers import DossierStore
from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.contracts import Intent
from ai_core.orchestration.ocop.workflow import OcopAgent
from datetime import date


def _jsonl(path,rows):
    if path.name=='structured.jsonl':
        from tests.ocop.lookup_graph_fixture import write_lookup_graph
        write_lookup_graph(path.parent,rows)
        return
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf-8')


def _fixture(tmp_path):
    knowledge=tmp_path/'knowledge';knowledge.mkdir()
    (knowledge/'manifest.json').write_text(json.dumps({'complete':True,'corpus_version':'graph-agent-fixture'}))
    evid={'unit_id':'unit-1','source_id':'DOC1','unit_kind':'article','review_status':'verified',
          'text':'Điều 1. Sản phẩm OCOP','spans':[{'pdf_page':1,'bbox':[0,0,100,20],
                                                    'block_id':'native:0:0','source_sha256':'a'*64}]}
    _jsonl(knowledge/'evidence_units.jsonl',[evid]);_jsonl(knowledge/'entities.jsonl',[
        {'entity_id':'doc','entity_type':'source_document','source_id':'DOC1','name':'Quyết định', 'evidence_unit_ids':['unit-1'],'review_status':'verified'},
        {'entity_id':'paragraph','entity_type':'evidence_unit','source_id':'DOC1','name':'Điều 1','evidence_unit_ids':['unit-1'],'review_status':'verified'},
    ])
    _jsonl(knowledge/'relations.jsonl',[
        {'relation_type':'CONTAINS','source_entity_id':'doc','target_entity_id':'paragraph',
         'evidence_unit_id':'unit-1','source_id':'DOC1','review_status':'verified'}])
    _jsonl(knowledge/'criterion_candidates.jsonl',[
        {'candidate_id':'c1','source_id':'DOC1','evidence_unit_id':'unit-1','label_candidate':'Tiêu chí A','review_status':'needs_review'}])
    return knowledge

def test_graph_build_and_repeat(tmp_path):
    knowledge=_fixture(tmp_path);out=tmp_path/'graph'
    a=build_graph(knowledge,out);first=(out/'edges.jsonl').read_bytes()
    b=build_graph(knowledge,out)
    assert a==b and first==(out/'edges.jsonl').read_bytes()
    assert a['counts']['edges']>=3
    graph=traverse(out,['doc'],hops=2)
    assert any(n['node_id']=='paragraph' for n in graph['nodes'])
    assert all(e['check']=='passed' for e in graph['edges'])
    assert not traverse(out,['doc'],verified_only=True)['nodes']
    assert validate_edge('AMENDS','SourceDocument','SourceDocument').ok
    assert not validate_edge('ARBITRARY','SourceDocument','SourceDocument').ok
    with pytest.raises(ValueError):traverse(out,['doc'],hops=4)

def test_graph_reject_orphans(tmp_path):
    p=_fixture(tmp_path)
    _jsonl(p/'relations.jsonl',[{'relation_type':'MENTIONS','source_entity_id':'doc','target_entity_id':'unknown',
                               'evidence_unit_id':'unit-1','source_id':'DOC1'}])
    r=build_graph(p,tmp_path/'graph')
    assert r['counts']['rejected']==1

def test_temporal_unknown_not_hallucinated():
    assert applicable({'review_status':'needs_review','effective_from':'2026-05-22'},as_of_date=date(2026,10,17))['status']=='unknown'
    assert applicable({'review_status':'verified','effective_from':'2026-05-22'},as_of_date=date(2026,10,17))['status']=='applicable'
    assert applicable({'review_status':'verified','effective_from':'2026-05-22','transition_window':'60d'},as_of_date=date(2026,10,17))['status']=='unknown'

def test_rule_engine_only_verified():
    req=[{'requirement_id':'a','evidence_type':'X','review_status':'verified','applicable':True},
         {'requirement_id':'b','evidence_type':'Y','review_status':'needs_review','applicable':True}]
    result=checklist(req,[{'evidence_type':'X','verified':True}])
    assert [r['status'] for r in result]==['satisfied','needs_human_review']
    criterion={'criterion_id':'c','review_status':'verified','scoring_mode':'choose_one','max_points':3,
               'score_options':[{'option_id':'o','points':2,'review_status':'verified'}]}
    score=estimate_score([criterion],{'c':'o'})
    assert score['minimum_points']=='2' and score['official_star_rating'] is None
    criterion['review_status']='needs_review'
    score=estimate_score([criterion],{'c':'o'})
    assert score['minimum_points']=='0' and score['maximum_points']=='3'

def test_dossier_authorization_and_isolation(tmp_path):
    store=DossierStore(tmp_path)
    with pytest.raises(PermissionError):store.put('tenantA','doc1',[])
    store.put('tenantA','doc1',[{'evidence_type':'X'}],authorization_checked=True)
    assert store.get('tenantB','doc1',authorization_checked=True) is None
    assert store.get('tenantA','doc1',authorization_checked=True)['documents'][0]['evidence_type']=='X'
    with pytest.raises(ValueError):store.get('../etc','doc1',authorization_checked=True)

def test_router_14_intents_recognizable():
    samples=[('OCOP là gì',Intent.OCOP_OVERVIEW),('Điều 6 QĐ26/2026 quy định gì',Intent.EXACT_LOOKUP),
             ('mật ong thuộc nhóm nào',Intent.PRODUCT_CLASSIFICATION),('tiêu chí bao nhiêu điểm',Intent.CRITERIA_LOOKUP),
             ('mẫu 02 cần điền gì',Intent.PROCEDURE_FORM),('so sánh năm 2025 2026',Intent.TEMPORAL_COMPARE),
             ('Huế công nhận sản phẩm nào',Intent.RECOGNITION_LOOKUP),('miễn giấy an toàn thực phẩm?',Intent.SECTOR_COMPLIANCE),
             ('tiêu chí X liên quan đến mẫu nào',Intent.MULTIHOP_REASONING)]
    for question,expect in samples:assert route_query(question).intent==expect,(question,route_query(question))
    assert route_query('hồ sơ tôi thiếu gì').intent==Intent.CLARIFY
    assert route_query('tính điểm',session={'tenant_id':'t','dossier_id':'d'}).intent==Intent.SCORE_ESTIMATE
    assert route_query('thế 4 sao?',session={'last_query':'OCOP mấy sao','slots':{}}).intent==Intent.FOLLOWUP

def test_fallback_answer_source_citations(tmp_path):
    from ai_core.retrieval.ocop.index_pipeline import create_bm25
    index=tmp_path/'data/processed/ocop/index';index.mkdir(parents=True)
    item={'chunk_id':'x','evidence_unit_id':'u','source_id':'VN.QD26','text_for_bm25':'Thông tin OCOP tiêu chí sản phẩm',
          'review_status':'needs_review','corpus_version':'fixture','spans':[{'pdf_page':7,'bbox':[1,2,3,4]}]}
    _jsonl(index/'chunks.jsonl',[item]);create_bm25([item],index/'bm25.json.gz')
    (index/'manifest.json').write_text(json.dumps({'corpus_version':'fixture','dense':{'enabled':False}}),encoding='utf-8')
    agent=OcopAgent(tmp_path)
    answer=agent.ask('OCOP là gì')
    assert answer.status=='retrieval_only'
    assert answer.citations[0]['pdf_page']==7
    assert answer.workflow_engine in ('langgraph','deterministic_fallback')
    assert answer.citations[0]['source_id']=='VN.QD26'

def test_pdf_upload_quarantine(tmp_path):
    st=DossierStore(tmp_path)
    with pytest.raises(PermissionError):st.upload_pdf('tenantA','d1',b'%PDF-1.7')
    with pytest.raises(ValueError):st.upload_pdf('tenantA','d1',b'not a pdf',authorization_checked=True)
    uploaded=st.upload_pdf('tenantA','d1',b'%PDF-1.7\n%%EOF',authorization_checked=True)
    assert uploaded['status']=='quarantined_unscanned'
    assert st.get('tenantB','d1',authorization_checked=True) is None

def test_citation_verification_rejects_hallucinated_reference():
    from ai_core.orchestration.ocop.verification import check_source_markers
    cite=[{'source_id':'D','pdf_page':1,'review_status':'needs_review'}]
    assert check_source_markers('theo [S2]',cite)['invalid_markers']==[2]
    assert check_source_markers('theo [S1]',cite)['unverified_source'] is True

def test_agent_exact_forms_and_criteria(tmp_path):
    from ai_core.orchestration.ocop.tools import ToolRegistry
    idx=tmp_path/'data/processed/ocop/index';idx.mkdir(parents=True)
    (idx/'manifest.json').write_text(json.dumps({'corpus_version':'x'}),encoding='utf-8')
    _jsonl(idx/'evidence_units.jsonl',[])
    _jsonl(idx/'structured.jsonl',[
        {'candidate_id':'c','record_kind':'criterion_candidates','evidence_unit_id':'e','source_id':'VN.OCOP.QD26.2026',
         'source_spans':[{'pdf_page':18}],'label_candidate':'Tiêu chí 1','review_status':'needs_review'},
        {'candidate_id':'f1','record_kind':'form_candidates','evidence_unit_id':'e1','source_id':'VN.OCOP.QD26.2026',
         'source_spans':[{'pdf_page':148}],'form_number':1,'title':'Mẫu 01'},
        {'candidate_id':'f3','record_kind':'form_candidates','evidence_unit_id':'e3','source_id':'VN.OCOP.QD26.2026',
         'source_spans':[{'pdf_page':147}],'form_number':3,'title':'Mẫu 03'},
    ])
    reg=ToolRegistry(tmp_path)
    forms=reg.dispatch('lookup_form',query='Mẫu 01',slots={'form_id':'1'})
    assert [x['candidate_id'] for x in forms['results']]==['f1']
    criteria=reg.dispatch('lookup_criterion',query='Tiêu chí QĐ26/2026',slots={'document_code':'26/2026'})
    assert [x['candidate_id'] for x in criteria['results']]==['c']

def test_router_out_of_scope(tmp_path):
    assert route_query('Giá bitcoin hôm nay?').intent == Intent.OUT_OF_SCOPE
    answer=OcopAgent(tmp_path).ask('Xem tarot cho tôi')
    assert answer.status=='out_of_scope' and not answer.citations
