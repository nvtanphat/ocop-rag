"""Independent negative and boundary safety tests (synthetic fixtures only)."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from ai_core.orchestration.ocop.tools import ToolRegistry
from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.workflow import OcopAgent
from ai_core.orchestration.ocop.planner import build_plan, needs_recovery


def jsonl(path: Path, rows: list[dict]):
    if path.name=='structured.jsonl':
        from tests.ocop.lookup_graph_fixture import write_lookup_graph
        write_lookup_graph(path.parent,rows)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows), encoding='utf-8')


@pytest.fixture
def fixture_index(tmp_path):
    idx=tmp_path/'data/processed/ocop/index'
    idx.mkdir(parents=True)
    (idx/'manifest.json').write_text('{"corpus_version":"v-test"}',encoding='utf-8')
    jsonl(idx/'chunks.jsonl',[])
    return tmp_path


def test_form_request_fails_closed_on_partial_match(fixture_index):
    jsonl(fixture_index/'data/processed/ocop/index/structured.jsonl',[
        {'record_kind':'form_candidates','form_number':2,'title':'Mẫu 02','source_id':'VN.OCOP.QD26.2026',
         'source_spans':[{'pdf_page':2}],'review_status':'verified'}])
    query='So sánh mẫu 02 và 03'
    route=route_query(query)
    result=ToolRegistry(fixture_index).dispatch('lookup_form',query=query,slots=route.slots)
    assert result['status']=='incomplete_form_ids'
    assert result['missing_form_ids']==['3']
    output=OcopAgent(fixture_index).answer({'query':query,'route':route.model_dump(mode='json'),
        'results':[{'tool':'lookup_form','output':result}]})['answer']
    assert output['status']=='insufficient_form_scope'
    assert not needs_recovery(route,[{'tool':'lookup_form','output':result}],build_plan(route))


def test_form_number_with_leading_zero_matches(fixture_index):
    jsonl(fixture_index/'data/processed/ocop/index/structured.jsonl',[
        {'record_kind':'form_candidates','form_number':'02','title':'Mẫu 02','source_id':'doc',
         'source_spans':[{'pdf_page':2}],'review_status':'verified'}])
    result=ToolRegistry(fixture_index).dispatch('lookup_form',query='Mẫu 02',slots={'form_id':'2'})
    assert len(result['results'])==1


@pytest.mark.parametrize('question',[
    'Hạn nộp hồ sơ OCOP ở Gia Lai',
    'Han nop ho so OCOP o Gia Lai',
    'Hạn cuối đăng ký OCOP ở Gia Lai',
])
def test_local_deadline_multi_guidance_does_not_search_national_sources(fixture_index,monkeypatch,question):
    configs=fixture_index/'configs/ocop_sources.json';configs.parent.mkdir(parents=True)
    configs.write_text(json.dumps({'sources':[
        {'source_id':'LOCAL-1','source_kind':'local_guidance','jurisdiction':'Gia Lai'},
        {'source_id':'LOCAL-2','source_kind':'local_guidance','jurisdiction':'Gia Lai'},
        {'source_id':'NATIONAL','source_kind':'national','jurisdiction':'nationwide'},
    ]}),encoding='utf-8')
    calls=[]
    def fake_search(_index,_query,**kwargs):
        calls.append(kwargs.get('source_id'))
        return [{'source_id':kwargs.get('source_id'),'evidence_unit_id':'unit',
                 'source_spans':[{'pdf_page':1}]}]
    monkeypatch.setattr('ai_core.orchestration.ocop.tools.search', fake_search)
    output=ToolRegistry(fixture_index).dispatch('search_regulations',query=question,
         slots={'region':'Gia Lai'},context={'retrieval_mode':'sparse'})
    assert calls and set(calls)=={'LOCAL-1','LOCAL-2'}
    assert all(row['source_id'] in {'LOCAL-1','LOCAL-2'} for row in output['results'])


def test_local_deadline_without_guidance_never_searches_broad_corpus(fixture_index,monkeypatch):
    invoked=[]
    monkeypatch.setattr('ai_core.orchestration.ocop.tools.search',lambda *a,**k:invoked.append(1))
    result=ToolRegistry(fixture_index).dispatch('search_regulations',
        query='Han nop ho so OCOP o Gia Lai',slots={'region':'Gia Lai'})
    assert result['status']=='local_guidance_not_in_corpus'
    assert invoked==[]


def test_graph_requires_edge_store_at_planning_time(tmp_path):
    graph=tmp_path/'data/processed/ocop/graph'
    jsonl(graph/'nodes.jsonl',[])
    (graph/'manifest.json').write_text('{}',encoding='utf-8')
    q='Liên hệ giữa các nhóm sản phẩm OCOP'
    route=route_query(q)
    planned=OcopAgent(tmp_path).plan({'query':q,'route':route.model_dump(mode='json')})
    assert 'search_graph' not in planned['plan'].names
    assert 'graph_index_unavailable_text_fallback' in planned['trace'][-1]['reason']


def test_dispatch_graph_without_files_returns_unavailable_not_crash(fixture_index):
    result=ToolRegistry(fixture_index).dispatch('search_graph',query='OCOP',slots={},
             context={'retrieved_evidence_ids':['ev-1']})
    assert result['results']==[] and result['note']=='graph_not_built'


def test_tampered_graph_seed_context_ignored(tmp_path):
    # Context passed through an HTTP request must not be trusted as a graph node ID.
    trusted=OcopAgent(tmp_path)._trusted_context({'query':'OCOP', 'context':{
        'graph_seed_ids':['attacker-node'], 'retrieved_evidence_ids':['fake']},
        'route':route_query('OCOP').model_dump(mode='json')})
    assert 'graph_seed_ids' not in trusted and 'retrieved_evidence_ids' not in trusted


def test_form_ids_cannot_use_unverified_rows_as_full_evidence(fixture_index):
    jsonl(fixture_index/'data/processed/ocop/index/structured.jsonl',[
        {'record_kind':'form_candidates','form_number':2,'title':'Mẫu 02','source_id':'doc',
         'source_spans':[{'pdf_page':2}],'review_status':'verified'},
        {'record_kind':'form_candidates','form_number':3,'title':'Mẫu 03','source_id':'doc',
         'source_spans':[{'pdf_page':3}],'review_status':'needs_review'}])
    result=ToolRegistry(fixture_index).dispatch('lookup_form',query='Mẫu 02 và 03',
         slots={'form_ids':['2','3']})
    assert result['status']=='incomplete_form_ids'
    assert result['missing_form_ids']==['3']


def test_router_does_not_promote_wrong_scope_on_extracted_slots():
    route=route_query('Danh sách sản phẩm OCOP 3 sao ở Gia Lai năm 2025')
    assert route.slots['region']=='Gia Lai'
    assert route.slots['star_rating']==3
    assert route.slots['recognition_year']==2025


def test_backend_errors_are_recorded_without_fake_results(tmp_path,monkeypatch):
    agent=OcopAgent(tmp_path)
    route=route_query('Thủ tục OCOP gồm những gì')
    plan=build_plan(route)
    monkeypatch.setattr(agent.tools,'dispatch',lambda *args,**kw: (_ for _ in ()).throw(OSError('unavailable')))
    output=agent.execute({'query':'Thủ tục OCOP gồm những gì',
        'route':route.model_dump(mode='json'),'plan':plan})
    assert output['results']
    assert all(x['output']['status']=='tool_unavailable' and not x['output']['results'] for x in output['results'])


def test_followup_rejects_user_supplied_graph_seed_ids():
    prior={'last_query':'Liên hệ giữa nhóm sản phẩm OCOP','intent':'MULTIHOP_REASONING',
           'slots':{'graph_seed_ids':['untrusted-node'], 'product_name':'cà phê',
                    'years':['2025']}}
    result=route_query('Thế ở Gia Lai?',session=prior)
    assert 'graph_seed_ids' not in result.slots
    assert result.slots['product_name']=='cà phê'
    assert result.slots['region']=='Gia Lai'
    assert result.slots['years']==['2025']


def test_followup_blocks_injected_authorization_and_source_ids():
    prior={'last_query':'Tiêu chí cà phê OCOP', 'intent':'CRITERIA_LOOKUP',
           'slots':{'authenticated':True,'tenant_id':'victim','evidence_unit_id':'fabricated',
                    'graph_seed_ids':['x'], 'criterion_id':'2.1'}}
    route=route_query('Thế còn mẫu 02?',session=prior)
    assert not set(route.slots)&{'authenticated','tenant_id','evidence_unit_id','graph_seed_ids'}
    assert 'criterion_id' not in route.slots and route.slots['form_id']=='2'  # a new target replaces the old one


def test_explicit_national_decision_cannot_override_local_deadline_scope(fixture_index,monkeypatch):
    sources=fixture_index/'configs/ocop_sources.json';sources.parent.mkdir(parents=True)
    sources.write_text(json.dumps({'sources':[{'source_id':'LOCAL-1',
        'source_kind':'local_guidance','jurisdiction':'Gia Lai'}]}),encoding='utf-8')
    monkeypatch.setattr(ToolRegistry,'_resolve_source_id',lambda self,code:'NATIONAL')
    called=[]
    monkeypatch.setattr('ai_core.orchestration.ocop.tools.search',lambda *a,**k:called.append(k))
    result=ToolRegistry(fixture_index).dispatch('search_regulations',
        query='Hạn nộp OCOP Gia Lai trong Quyết định 26/2026',
        slots={'region':'Gia Lai','document_code':'26/2026'})
    assert result['status']=='local_guidance_document_scope_mismatch'
    assert called==[]


def test_local_guidance_deduplicates_and_rejects_adapter_cross_scope(fixture_index,monkeypatch):
    configs=fixture_index/'configs/ocop_sources.json';configs.parent.mkdir(parents=True)
    configs.write_text(json.dumps({'sources':[
        {'source_id':'LOCAL-1','source_kind':'local_guidance','jurisdiction':'Gia Lai'},
        {'source_id':'LOCAL-2','source_kind':'local_guidance','jurisdiction':'Gia Lai'}
    ]}),encoding='utf-8')
    def search_stub(_index,_query,**kwargs):
        return [
            {'chunk_id':'same','source_id':kwargs['source_id'],'source_spans':[{'pdf_page':2}]},
            {'chunk_id':'malicious','source_id':'NATIONAL','source_spans':[{'pdf_page':4}]}
        ]
    monkeypatch.setattr('ai_core.orchestration.ocop.tools.search',search_stub)
    result=ToolRegistry(fixture_index).dispatch('search_regulations',
        query='Hạn nộp OCOP tại Gia Lai',slots={'region':'Gia Lai'})
    assert all(x['source_id'] in {'LOCAL-1','LOCAL-2'} for x in result['results'])
    assert len(result['results'])==1  # two adapters must not duplicate identical chunk IDs


@pytest.mark.parametrize('status',['not_found','tool_unavailable','unexpected_backend_status'])
def test_private_dossier_failure_cannot_be_labeled_provisional(tmp_path,status):
    from ai_core.orchestration.ocop.contracts import Route,Intent
    route=Route(intent=Intent.DOSSIER_REVIEW,strategy='agentic',
                required_tools=['review_dossier'])
    answer=OcopAgent(tmp_path).answer({'query':'Rà soát hồ sơ',
        'route':route.model_dump(mode='json'),
        'results':[{'tool':'review_dossier','output':{'status':status}}]})['answer']
    assert answer['status']!='provisional'
    assert answer['citations']==[]


def test_missing_private_dossier_with_auth_returns_clear_unresolved_status(tmp_path):
    from ai_core.orchestration.ocop.contracts import AuthContext
    answer=OcopAgent(tmp_path).ask('Rà soát hồ sơ của tôi còn thiếu gì?',
        session={'dossier_id':'does-not-exist'},
        auth_context=AuthContext(principal_id='user-1',tenant_id='tenant-1'))
    assert answer.status=='dossier_not_found'
    assert answer.citations==[]


@pytest.mark.parametrize('status',['local_guidance_not_in_corpus', 'local_guidance_document_scope_mismatch'])
def test_local_deadline_failures_use_clear_response_status(tmp_path,status):
    from ai_core.orchestration.ocop.contracts import Route,Intent
    route=Route(intent=Intent.PROCEDURE_FORM,strategy='hybrid',
        required_tools=['search_regulations'],slots={'region':'Gia Lai'})
    answer=OcopAgent(tmp_path).answer({'query':'Hạn nộp OCOP Gia Lai',
        'route':route.model_dump(mode='json'),
        'results':[{'tool':'search_regulations','output':{'status':status,'results':[]}}]})['answer']
    assert answer['status']=='insufficient_local_guidance_scope'
    assert answer['citations']==[]


def test_form_comparison_never_joins_different_document_versions(fixture_index):
    jsonl(fixture_index/'data/processed/ocop/index/structured.jsonl',[
        {'record_kind':'form_candidates','form_number':2,'title':'Mẫu 02',
         'source_id':'VN.OCOP.QD26.2026','review_status':'verified','source_spans':[{'pdf_page':3}]},
        {'record_kind':'form_candidates','form_number':3,'title':'Mẫu 03',
         'source_id':'VN.OCOP.QD148.2023','review_status':'verified','source_spans':[{'pdf_page':3}]},
    ])
    result=ToolRegistry(fixture_index).dispatch('lookup_form',query='So sánh mẫu 02 và 03',
          slots={'form_ids':['2','3']})
    assert result['status']=='form_source_scope_unverified'
    assert result['results']==[]
    route=route_query('So sánh mẫu 02 và 03')
    answer=OcopAgent(fixture_index).answer({'query':'So sánh mẫu 02 và 03',
          'route':route.model_dump(mode='json'),
          'results':[{'tool':'lookup_form','output':result}]})['answer']
    assert answer['status']=='insufficient_form_scope'


def test_form_comparison_requires_document_if_two_complete_versions_exist(fixture_index):
    rows=[]
    for source_id in ['DOC-2023','DOC-2026']:
        for form_id in (2,3):
            rows.append({'record_kind':'form_candidates','form_number':form_id,
                'title':f'Mẫu {form_id:02d}','source_id':source_id,
                'review_status':'verified','source_spans':[{'pdf_page':form_id}]})
    jsonl(fixture_index/'data/processed/ocop/index/structured.jsonl',rows)
    result=ToolRegistry(fixture_index).dispatch('lookup_form',query='So sánh mẫu 02 và 03',
          slots={'form_ids':['2','3']})
    assert result['status']=='form_version_ambiguous'
    assert not result['results']


def test_form_comparison_returns_all_requested_ids_even_many_duplicates(fixture_index):
    rows=[{'record_kind':'form_candidates','form_number':2,'title':'Mẫu 02',
        'source_id':'SAME-DOC','review_status':'verified','source_spans':[{'pdf_page':i}]}
        for i in range(1,26)]
    rows.append({'record_kind':'form_candidates','form_number':3,'title':'Mẫu 03',
        'source_id':'SAME-DOC','review_status':'verified','source_spans':[{'pdf_page':26}]})
    jsonl(fixture_index/'data/processed/ocop/index/structured.jsonl',rows)
    result=ToolRegistry(fixture_index).dispatch('lookup_form',query='So sánh mẫu 02 và 03',
          slots={'form_ids':['2','3']})
    assert {int(row['form_number']) for row in result['results']}=={2,3}


def test_producer_question_routes_to_recognition_with_clean_product_slot():
    from ai_core.orchestration.ocop.router import route_query
    from ai_core.orchestration.ocop.contracts import Intent
    cases = {
        "QĐ525: sản phẩm HANA do chủ thể nào sản xuất?": "HANA",
        "Sản phẩm Gạo ruộng rươi ST25 của chủ thể nào?": "Gạo ruộng rươi ST25",
        "Ai sản xuất sản phẩm Nước mắm cá thu?": "Nước mắm cá thu",
        "Chủ thể của sản phẩm HANA là ai?": "HANA",
    }
    for question, product in cases.items():
        # As in the Agent: the index confirms the named product exists in the corpus.
        route = route_query(question, indexed_content_bigram_coverage=lambda q: 1.0)
        assert route.intent == Intent.RECOGNITION_LOOKUP, question
        assert route.slots["product_name"] == product, question


def test_bare_category_name_is_still_canonical():
    from ai_core.orchestration.ocop.router import route_query
    assert route_query("Sản phẩm mật ong được công nhận mấy sao?").slots["product_name"] == "mật ong"


def test_unknown_product_producer_question_without_index_support_is_not_forced_in_scope():
    from ai_core.orchestration.ocop.router import route_query
    from ai_core.orchestration.ocop.contracts import Intent
    route = route_query("Sản phẩm HANA do ai sản xuất?", indexed_content_bigram_coverage=lambda q: 0.0)
    assert route.intent == Intent.OUT_OF_SCOPE


def test_authority_questions_route_to_exact_lookup_with_legal_tools():
    from ai_core.orchestration.ocop.router import route_query
    from ai_core.orchestration.ocop.contracts import Intent
    authority_questions = [
        "Cơ quan nào có thẩm quyền công nhận sản phẩm OCOP 5 sao?",
        "Ai công nhận sản phẩm OCOP 5 sao?",
        "Thẩm quyền công nhận sản phẩm OCOP 4 sao thuộc về cơ quan nào?",
        "UBND cấp tỉnh có thẩm quyền công nhận sản phẩm OCOP mấy sao?",
        "Cơ quan nào quyết định công nhận kết quả đánh giá phân hạng OCOP?",
        "Ai có thẩm quyền cấp giấy chứng nhận sản phẩm OCOP?",
    ]
    for q in authority_questions:
        route = route_query(q)
        assert route.intent == Intent.EXACT_LOOKUP, f"Failed intent for: {q} (got {route.intent})"
        assert "lookup_legal_unit" in route.required_tools, f"Missing lookup_legal_unit for: {q}"
        assert "search_regulations" in route.required_tools, f"Missing search_regulations for: {q}"
