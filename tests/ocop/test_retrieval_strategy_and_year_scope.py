"""Second-stage retrieval routing and conservative event-year contracts.

All rows and expected values are fabricated fixtures, NOT verified OCOP law.
"""
from __future__ import annotations
import json
from ai_core.orchestration.ocop.retrieval_strategy import choose_retrieval_path, RetrievalPath
from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.tools import ToolRegistry
from ai_core.orchestration.ocop.workflow import OcopAgent


def _write(path, rows):
    if path.name=='structured.jsonl':
        from tests.ocop.lookup_graph_fixture import write_lookup_graph
        write_lookup_graph(path.parent,rows)
        return
    path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')


def _store(tmp_path):
    idx=tmp_path/'data/processed/ocop/index'
    idx.mkdir(parents=True)
    (idx/'manifest.json').write_text('{"corpus_version":"fixture-1"}',encoding='utf-8')
    _write(idx/'evidence_units.jsonl',[])
    rows=[
        {'record_kind':'recognition_candidates','source_id':'VN.HUE.QD1.2026','row_text':'Hạt sen 4 sao',
         'recognition_event_year':2025, 'review_status':'verified', 'source_spans':[{'pdf_page':1}]},
        {'record_kind':'recognition_candidates','source_id':'VN.HUE.QD2.2026','row_text':'Trà sen 3 sao',
         'recognition_event_year':2026, 'review_status':'verified', 'source_spans':[{'pdf_page':2}]},
        {'record_kind':'recognition_candidates','source_id':'VN.HUE.QD3.2026','row_text':'Mật ong 4 sao',
         'review_status':'needs_review', 'source_spans':[{'pdf_page':3}]},
        {'record_kind':'criterion_candidates','source_id':'VN.OCOP.QD26.2026','label_candidate':'Tiêu chí',
         'review_status':'needs_review', 'source_spans':[{'pdf_page':4}]},
        {'record_kind':'form_candidates','source_id':'VN.OCOP.QD26.2026','form_number':2,
         'review_status':'needs_review','source_spans':[{'pdf_page':5}]},
        {'record_kind':'form_candidates','source_id':'VN.OCOP.QD26.2026','form_number':3,
         'review_status':'needs_review','source_spans':[{'pdf_page':6}]},
    ]
    _write(idx/'structured.jsonl',rows)
    return ToolRegistry(tmp_path)


def test_path_phase_reflects_allowlisted_tools():
    assert choose_retrieval_path([])==RetrievalPath.NONE
    assert choose_retrieval_path(['lookup_form'])==RetrievalPath.PINPOINT
    assert choose_retrieval_path(['search_regulations'])==RetrievalPath.TEXT
    assert choose_retrieval_path(['search_graph'])==RetrievalPath.GRAPH
    assert choose_retrieval_path(['search_regulations','search_graph'])==RetrievalPath.HYBRID_GRAPH
    assert choose_retrieval_path(['estimate_score'])==RetrievalPath.AGENTIC


def test_two_level_router_keeps_business_intent():
    simple=route_query('Mật ong thuộc nhóm nào?')
    assert simple.retrieval_path==RetrievalPath.PINPOINT
    compound=route_query('Đối chiếu tiêu chí chất lượng với mẫu hồ sơ OCOP?')
    assert compound.retrieval_path==RetrievalPath.HYBRID_GRAPH
    private=route_query('Rà soát hồ sơ của tôi còn thiếu gì?')
    assert private.needs_clarification  # no authenticated dossier in session
    assert private.retrieval_path==RetrievalPath.NONE


def test_vi_without_accents_form_code_and_region():
    r=route_query('Mau so 02 can dien gi de dang ky OCOP tai Hue?')
    assert r.slots['form_id']=='2' and r.slots['region']=='Huế'
    assert r.retrieval_path==RetrievalPath.PINPOINT


def test_form_comparison_keeps_both_ids_and_never_calls_temporal(tmp_path):
    r=route_query('So sánh mẫu số 02 và mẫu 03 khác nhau thế nào?')
    assert r.slots['form_ids']==['2','3']
    assert 'resolve_temporal_applicability' not in r.required_tools
    output=_store(tmp_path).dispatch('lookup_form',query='so sánh mẫu 02 và 03',slots=r.slots)
    assert sorted(row['form_number'] for row in output['results'])==[2,3]


def test_2026_decision_does_not_imply_2026_recognition_event(tmp_path):
    r=route_query('Danh sách sản phẩm OCOP năm 2025')
    assert r.slots['recognition_year']==2025
    output=_store(tmp_path).dispatch('lookup_recognition',query='Danh sách sản phẩm OCOP năm 2025',slots=r.slots)
    assert len(output['results'])==1
    assert output['results'][0]['recognition_event_year']==2025
    assert output['results'][0]['source_id'].endswith('2026')


def test_unknown_recognition_event_year_denied_not_inferred(tmp_path):
    reg=_store(tmp_path)
    output=reg.dispatch('lookup_recognition',query='2024',slots={'years':['2024'],'recognition_year':2024})
    assert output['results']==[] and output['status']=='recognition_year_scope_unverified'


def test_criterion_issuance_year_not_assessment_year(tmp_path):
    reg=_store(tmp_path)
    output=reg.dispatch('lookup_criterion',query='2025',slots={'assessment_year':2025,'years':['2025']})
    assert output['results']==[] and output['status']=='assessment_year_scope_unverified'


def test_no_silent_recovery_from_year_scope_unverified(tmp_path):
    reg=_store(tmp_path)
    agent=OcopAgent(tmp_path)
    state={'query':'Danh sách sản phẩm OCOP năm 2024','route':route_query('Danh sách sản phẩm OCOP năm 2024').model_dump(mode='json'),
           'results':[{'tool':'lookup_recognition', 'output':reg.dispatch('lookup_recognition',query='2024',
                       slots={'recognition_year':2024,'years':['2024']})}]}
    assert not agent._should_recover(state)


def test_non_ocop_shopping_does_not_trigger_retrieval():
    r=route_query('Tôi muốn mua sản phẩm iPhone 17 giá tốt nhất')
    assert r.retrieval_path==RetrievalPath.NONE


def test_unverified_year_scope_surfaces_clear_user_status(tmp_path):
    reg=_store(tmp_path)
    agent=OcopAgent(tmp_path)
    route=route_query('Danh sách sản phẩm OCOP 4 sao năm 2024')
    result={'tool':'lookup_recognition','output':reg.dispatch('lookup_recognition',
        query='Danh sách sản phẩm OCOP 4 sao năm 2024',slots=route.slots)}
    response=agent.answer({'query':'Danh sách sản phẩm OCOP 4 sao năm 2024',
                           'route':route.model_dump(mode='json'),'results':[result]})['answer']
    assert response['status']=='insufficient_year_scope'
    assert not response['citations']


def test_temporal_without_verified_rules_does_not_ask_llm_for_claim(tmp_path):
    agent=OcopAgent(tmp_path)
    route=route_query('So sánh bộ tiêu chí OCOP năm 2025 và 2026')
    output=agent.answer({'query':'So sánh bộ tiêu chí OCOP năm 2025 và 2026',
                         'route':route.model_dump(mode='json'),
                         'results':[{'tool':'resolve_temporal_applicability',
                                     'output':{'status':'unknown','results':[]}},
                                    {'tool':'search_regulations','output':{'results':[]}}]})['answer']
    assert output['status']=='insufficient_temporal_verification'
    assert output['citations']==[]
