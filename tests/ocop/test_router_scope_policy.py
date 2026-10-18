"""Safety contracts for the third revision; fabricated records only."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from ai_core.orchestration.ocop.router import route_query, extract_slots
from ai_core.orchestration.ocop.tools import ToolRegistry
from ai_core.orchestration.ocop.workflow import OcopAgent
from ai_core.orchestration.ocop.planner import build_plan
from ai_core.orchestration.ocop.retrieval_strategy import RetrievalPath


def store(path: Path, records: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records), encoding='utf-8')


@pytest.fixture
def registry(tmp_path):
    idx=tmp_path/'data/processed/ocop/index';idx.mkdir(parents=True)
    (idx/'manifest.json').write_text('{"corpus_version":"contract-fixture"}')
    store(idx/'chunks.jsonl',[])
    store(idx/'evidence_units.jsonl',[{'unit_id':'backing-1','source_id':'VN.TEST.2026',
                                    'source_spans':[{'pdf_page':1}], 'text':'Fixture rule'}])
    store(idx/'structured.jsonl',[
        {'record_kind':'recognition_candidates','source_id':'VN.GIALAI.TEST',
         'row_text':'Product A 3 sao','recognition_event_year':2025,
         'source_spans':[{'pdf_page':1}], 'review_status':'verified'},
        {'record_kind':'recognition_candidates','source_id':'VN.HUE.TEST',
         'row_text':'Product B 3 sao','recognition_event_year':2025,
         'source_spans':[{'pdf_page':1}], 'review_status':'verified'},
        {'record_kind':'recognition_candidates','source_id':'VN.GIALAI.TEST',
         'row_text':'Product C 4 sao','recognition_event_year':2025,
         'source_spans':[{'pdf_page':1}], 'review_status':'verified'},
        {'record_kind':'recognition_candidates','source_id':'VN.GIALAI.TEST',
         'row_text':'Product D 3 sao','recognition_event_year':2025,
         'source_spans':[{'pdf_page':1}], 'review_status':'needs_review'},
        {'record_kind':'recognition_candidates','source_id':'VN.GIALAI.TEST',
         'row_text':'Product E 3 sao', 'source_spans':[{'pdf_page':1}],
         'review_status':'verified'},
    ])
    return ToolRegistry(tmp_path)


def test_compressed_multiple_forms_and_no_spurious_number():
    r=route_query('So sánh mẫu 02, 03 và 04 khác nhau thế nào?')
    assert r.slots['form_ids']==['2','3','4']
    assert 'star_rating' not in r.slots


def test_explicit_year_in_pinned_decision_is_event_not_issue_date():
    slots=extract_slots('Quyết định 26/2026 công nhận sản phẩm năm 2025')
    assert slots['document_code']=='26/2026'
    assert slots['recognition_year']==2025


def test_region_rating_year_intersection_after_all_filters(registry):
    slots=route_query('Danh sách sản phẩm OCOP 3 sao Gia Lai năm 2025').slots
    rows=registry.dispatch('lookup_recognition', query='danh sách',slots=slots)['results']
    assert [r['row_text'] for r in rows]==['Product A 3 sao']


def test_fail_closed_when_recognition_region_metadata_missing(registry):
    result=registry.dispatch('lookup_recognition',query='OCOP 3 sao Đà Nẵng',
                             slots={'region':'Đà Nẵng','star_rating':3})
    assert result['status']=='recognition_scope_unverified' and not result['results']


def test_region_scope_does_not_allow_text_recovery(registry):
    agent=OcopAgent(registry.root)
    route=route_query('Danh sách sản phẩm OCOP 3 sao Đà Nẵng')
    result=registry.dispatch('lookup_recognition',query='OCOP 3 sao Đà Nẵng',slots=route.slots)
    state={'query':'OCOP 3 sao Đà Nẵng','route':route.model_dump(mode='json'),
           'results':[{'tool':'lookup_recognition','output':result}]}
    assert not agent._should_recover(state)
    assert agent.answer(state)['answer']['status']=='insufficient_recognition_scope'


def test_unresolved_temporal_rule_even_with_backing(registry):
    rules=registry.root/'data/processed/ocop/knowledge/verified_temporal_rules.jsonl'
    store(rules,[{'rule_id':'unknown', 'review_status':'verified','evidence_unit_id':'backing-1',
                  'source_id':'VN.TEST.2026','corpus_version':'contract-fixture'}])
    result=registry.dispatch('resolve_temporal_applicability',query='test',slots={},
                             context={'as_of_date':'2026-10-17'})
    assert result['status']=='unknown' and result['applicability_status']=='unknown'


def test_unsupported_temporal_source_cannot_certify_applicability(registry):
    rules=registry.root/'data/processed/ocop/knowledge/verified_temporal_rules.jsonl'
    store(rules,[{'rule_id':'unbacked', 'review_status':'verified','evidence_unit_id':'missing',
                  'source_id':'VN.TEST.2026', 'effective_from':'2026-01-01',
                  'corpus_version':'contract-fixture'}])
    result=registry.dispatch('resolve_temporal_applicability',query='test',slots={},
                             context={'as_of_date':'2026-10-17'})
    assert result['status']=='unknown'
    assert result['results'][0]['verdict']['reason']=='verified_rule_missing_matching_source_evidence'


def test_verified_backed_temporal_can_be_checked(registry):
    rules=registry.root/'data/processed/ocop/knowledge/verified_temporal_rules.jsonl'
    store(rules,[{'rule_id':'backed', 'review_status':'verified','evidence_unit_id':'backing-1',
                  'source_id':'VN.TEST.2026','effective_from':'2026-01-01',
                  'corpus_version':'contract-fixture'}])
    result=registry.dispatch('resolve_temporal_applicability',query='test',slots={},
                             context={'as_of_date':'2026-10-17'})
    assert result['status']=='checked_verified_rules' and result['applicability_status']=='applicable'


def test_graph_strategy_fallback_if_no_graph_manifest(tmp_path):
    query='Liên hệ giữa các nhóm sản phẩm OCOP'
    route=route_query(query)
    plan=OcopAgent(tmp_path).plan({'query':query,'route':route.model_dump(mode='json'),'trace':[]})
    assert 'search_graph' not in plan['plan'].names
    assert 'search_regulations' in plan['plan'].names
    assert plan['route']['retrieval_path']==RetrievalPath.TEXT.value
    assert plan['trace'][-1]['reason']=='graph_index_unavailable_text_fallback'


def test_graph_strategy_bootstraps_seed_if_index_exists(tmp_path):
    graph=tmp_path/'data/processed/ocop/graph'
    graph.mkdir(parents=True);(graph/'manifest.json').write_text('{}')
    store(graph/'nodes.jsonl',[])
    store(graph/'edges.jsonl',[])
    query='Liên hệ giữa các nhóm sản phẩm OCOP'
    route=route_query(query)
    result=OcopAgent(tmp_path).plan({'query':query,'route':route.model_dump(mode='json')})
    assert result['plan'].names==('search_regulations','search_graph')
    assert result['plan'].retrieval_path==RetrievalPath.HYBRID_GRAPH


def test_non_comparison_year_scoped_procedure_requests_temporal_validation():
    r=route_query('Thủ tục đăng ký OCOP năm 2025 cần những gì?')
    assert 'resolve_temporal_applicability' in build_plan(r).names
    outcome=OcopAgent(Path('/nonexistent')).answer({'query':'Thủ tục đăng ký OCOP năm 2025',
        'route':r.model_dump(mode='json'),'results':[{'tool':'resolve_temporal_applicability',
        'output':{'status':'unknown','results':[]}}]})['answer']
    assert outcome['status']=='insufficient_temporal_verification'


def test_metadata_conflicts_fail_closed():
    from ai_core.orchestration.ocop.tools import _verified_recognition_scope
    base={'review_status':'verified','source_id':'VN.GIALAI.X','row_text':'A 3 sao'}
    assert not _verified_recognition_scope({**base,'jurisdiction':'Huế'},region='Gia Lai',stars=3)
    assert not _verified_recognition_scope({**base,'star_rating':4},region='Gia Lai',stars=3)
    assert not _verified_recognition_scope({**base,'star_rating':4},region='Gia Lai',stars=4)
    assert _verified_recognition_scope({**base,'jurisdiction':'Gia Lai','star_rating':3},region='Gia Lai',stars=3)
