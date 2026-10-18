"""Adversarial contract checks, not part of OCOP project upstream test suite.
Fixtures are synthetic; they make no claims about real OCOP documents.
"""
from pathlib import Path
import json
import pytest
from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.tools import ToolRegistry
from ai_core.orchestration.ocop.planner import build_plan


def _write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(x, ensure_ascii=False)+'\n' for x in records), encoding='utf-8')

@pytest.fixture
def registry(tmp_path):
    index = tmp_path/'data/processed/ocop/index'
    index.mkdir(parents=True)
    (index/'manifest.json').write_text('{"corpus_version":"audit-fixture"}', encoding='utf-8')
    _write(index/'evidence_units.jsonl', [])
    _write(index/'structured.jsonl', [
        {'record_kind':'recognition_candidates','source_id':'VN.HUE.QD1.2025',
         'recognition_event_year':2025,'review_status':'verified','row_text':'Mật ong Huế 3 sao',
         'source_spans':[{'pdf_page':1}]},
        {'record_kind':'recognition_candidates','source_id':'VN.GIALAI.QD2.2025',
         'recognition_event_year':2025,'review_status':'verified','row_text':'Mật ong Gia Lai 4 sao',
         'source_spans':[{'pdf_page':1}]},
        {'record_kind':'recognition_candidates','source_id':'VN.GIALAI.QD3.2025',
         'recognition_event_year':2025,'review_status':'verified','row_text':'Mật ong Gia Lai 3 sao',
         'source_spans':[{'pdf_page':1}]},
    ])
    _write(tmp_path/'data/processed/ocop/knowledge/verified_temporal_rules.jsonl', [
        {'rule_id':'fixture-incomplete', 'review_status':'verified','evidence_unit_id':'mock-evidence',
         'source_id':'VN.TEST.2026','corpus_version':'audit-fixture'}
    ])
    return ToolRegistry(tmp_path)

def test_form_compressed_comparison_extracts_both():
    r=route_query('Mẫu 02 và 03 khác nhau ở mục nào?')
    assert r.slots.get('form_ids') == ['2','3']

def test_recognition_star_constraint_is_parsed():
    r=route_query('Danh sách sản phẩm OCOP 3 sao tại Gia Lai năm 2025')
    assert r.slots.get('star_rating') == 3

def test_recognition_region_and_star_are_respected(registry):
    q='Danh sách sản phẩm OCOP 3 sao tại Gia Lai năm 2025'
    r=route_query(q)
    rows=registry.dispatch('lookup_recognition',query=q,slots=r.slots)['results']
    assert [x['source_id'] for x in rows] == ['VN.GIALAI.QD3.2025']

def test_unknown_verdict_cannot_be_checked_verified(registry):
    result=registry.dispatch('resolve_temporal_applicability', query='quy định OCOP', slots={},
                             context={'as_of_date':'2026-10-17'})
    assert result['status'] != 'checked_verified_rules' or all(
        r['verdict']['status'] != 'unknown' for r in result['results'])

def test_criterion_question_not_marked_out_of_scope():
    r=route_query('Cần đáp ứng điều kiện gì để sản phẩm đạt 4 sao?')
    assert r.intent.value != 'OUT_OF_SCOPE'

def test_action_verb_does_not_extract_product_tra():
    r=route_query('Tra cứu quyết định số 26/2026 về OCOP')
    assert 'product_name' not in r.slots

def test_graph_only_route_has_linkable_seed_or_bootstrap():
    r=route_query('Liên hệ giữa các nhóm sản phẩm OCOP')
    plan=build_plan(r)
    assert not (plan.names == ('search_graph',) and not r.slots.get('graph_seed_ids'))
