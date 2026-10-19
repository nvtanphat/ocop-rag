"""Synthetic literal-source fixtures; no real PDF or OCR gold labels."""
from ai_core.knowledge.ocop.extractor import extract_semantics
from ai_core.processing.ocop.business_candidates import candidates


REGISTRY = {
    'DOC.CURRENT': {'document_number':'26/2026/QĐ-TTg'},
    'DOC.OLD': {'document_number':'148/QĐ-TTg'},
    'DOC.AMEND': {'document_number':'1489/QĐ-TTg'},
    'DOC.RECOGNITION': {'document_number':'525/QĐ-UBND'},
}


def unit(sid, page, text, kind='article'):
    return {'source_id':sid, 'unit_id':f'evidence:{sid}:{page}:{kind}',
            'unit_kind':kind, 'text':text, 'structured':{},
            'spans':[{'pdf_page':page,'bbox':[0,0,500,700], 'source_sha256':'a'*64}]}


def extract(units, kinds=None, registry=None):
    kinds = kinds or {'DOC.CURRENT':'ocop_framework','DOC.AMEND':'ocop_amendment'}
    return extract_semantics(units, kinds, candidates(units,kinds),
                             source_registry=registry or REGISTRY)


def test_document_header_and_expiry_do_not_create_false_amendment():
    units = [unit('DOC.CURRENT',1,
        'THỦ TƯỚNG CHÍNH PHỦ\nSố: 26/2026/QĐ-TTg\nHà Nội, ngày 22 tháng 5 năm 2026\nQUYẾT ĐỊNH', 'paragraph'),
        unit('DOC.CURRENT',13,
        'Điều 11. Hiệu lực thi hành\n1. Quyết định này có hiệu lực thi hành từ ngày 22 tháng 5 năm 2026.\n'
        '2. Quyết định số 148/QĐ-TTg và Quyết định số 1489/QĐ-TTg sửa đổi Quyết định 148/QĐ-TTg '
        'hết hiệu lực sau 60 ngày kể từ ngày Quyết định này có hiệu lực thi hành.')]
    result = extract(units)
    doc = next(e for e in result['business_entities'] if e['kind']=='SourceDocument' and not e['attributes']['reference_only'])
    assert doc['attributes']['signed_at_candidate'] == '2026-05-22'
    assert doc['attributes']['issuer_candidate'] == 'THỦ TƯỚNG CHÍNH PHỦ'
    assert doc['attributes']['document_number_candidate'] == '26/2026/QĐ-TTg'
    assert doc['attributes']['effective_from'] == '2026-05-22'
    edges = [r for r in result['business_relations'] if r['relation_type']=='REPLACES']
    assert not any(r['relation_type']=='AMENDS' for r in result['business_relations'])
    assert len(edges) == 2 and {e['relation_type'] for e in edges} == {'REPLACES'}
    assert all(e['attributes']['expires_after_days'] == 60 for e in edges)
    assert all(e['attributes']['effective_from'] == '2026-05-22' for e in edges)
    assert all(e['status'] == 'candidate' for e in result['business_entities'] + edges)


def test_operative_amendment_and_no_unregistered_target():
    result = extract([unit('DOC.AMEND',1,
        'Điều 1. Sửa đổi, bổ sung Quyết định số 148/QĐ-TTg và 999/QĐ-TTg.\n'
        '1. Sửa đổi nội dung như sau.')])
    edges = [r for r in result['business_relations'] if r['relation_type']=='AMENDS']
    assert len(edges) == 1
    assert {e['attributes']['registry_source_id'] for e in result['business_entities'] if e['kind']=='SourceDocument'} == {'DOC.AMEND','DOC.OLD'}
    assert {'reason':'legal_reference_not_uniquely_registered','count':1} in result['business_omissions']
    entities = {e['entity_id']:e for e in result['business_entities']}
    edge = edges[0]
    assert entities[edge['source_entity_id']]['source_id'] == 'DOC.AMEND'
    assert entities[edge['target_entity_id']]['source_id'] == 'DOC.OLD'
    assert {e['source_id'] for e in edge['evidence']} == {'DOC.AMEND'}


def test_cross_document_validation_requires_registry_and_whole_number():
    import pytest
    from ai_core.knowledge.ocop.contracts import (
        BusinessEntity, BusinessRelation, contains_document_number, validate_business_graph)
    result = extract([unit('DOC.AMEND',1,'Điều 1. Sửa đổi Quyết định số 148/QĐ-TTg.')])
    entities = [BusinessEntity.model_validate(e) for e in result['business_entities']]
    relations = [BusinessRelation.model_validate(r) for r in result['business_relations']]
    with pytest.raises(ValueError,match='explicit resolution'):
        validate_business_graph(entities,relations)
    validate_business_graph(entities,relations,source_registry=REGISTRY)
    assert not contains_document_number('1148/QĐ-TTg','148/QĐ-TTg')
    assert not contains_document_number('148/QĐ-TTg-OTHER','148/QĐ-TTg')


def test_recognition_basis_only_in_bases_and_exact_number():
    result = extract([unit('DOC.RECOGNITION',1,
        'Căn cứ Quyết định số 148/QĐ-TTg;\nTheo đề nghị về Quyết định số 1489/QĐ-TTg;', 'paragraph')],
        {'DOC.RECOGNITION':'recognition_decision'})
    edges = result['business_relations']
    assert len(edges) == 1 and edges[0]['relation_type'] == 'BASED_ON'
    target = next(e for e in result['business_entities'] if e['entity_id'] == edges[0]['target_entity_id'])
    assert target['attributes']['registry_source_id'] == 'DOC.OLD'


def test_missing_metadata_is_unknown_and_transition_stays_inert():
    text = 'Điều 12. Điều khoản chuyển tiếp\n1. Giấy chứng nhận tiếp tục có giá trị đến hết hạn.'
    result = extract([unit('DOC.CURRENT',13,text)])
    doc = next(e for e in result['business_entities'] if e['kind']=='SourceDocument')
    assert doc['attributes']['signed_at_candidate'] is None
    assert doc['attributes']['effective_from'] is None
    rule = next(r for r in result['business_rules'] if r['statement'] == text)
    assert rule['kind'] == 'temporal' and rule['status'] == 'candidate'
    assert rule['if_all'] == [] and rule['consequence'] == {}


def test_body_citation_date_does_not_become_signing_or_effective_date():
    import copy
    registry = copy.deepcopy(REGISTRY)
    result = extract([unit('DOC.CURRENT',1,
        'Cơ quan: VĂN PHÒNG\nCHÍNH PHỦ\n'
        'THỦ TƯỚNG CHÍNH PHỦ CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM\n'
        'Số: 26/2026/QĐ-TTg\nQUYẾT ĐỊNH\nCăn cứ Quyết định 148/QĐ-TTg ngày 24 tháng 02 năm 2023;',
        'paragraph')],registry=registry)
    own = next(e for e in result['business_entities'] if e['kind']=='SourceDocument' and not e['attributes']['reference_only'])
    assert own['attributes']['issuer_candidate'] == 'THỦ TƯỚNG CHÍNH PHỦ'
    assert own['attributes']['signed_at_candidate'] is None
    assert own['attributes']['effective_from'] is None
    assert registry == REGISTRY
    assert all(e['source_sha256'] == 'a'*64 for e in own['evidence'])


def test_ambiguous_registry_reference_is_not_resolved():
    result = extract([unit('DOC.CURRENT',13,
        'Điều 11. Quyết định 148/QĐ-TTg hết hiệu lực sau 60 ngày kể từ ngày Quyết định này có hiệu lực.')],
        registry={**REGISTRY, 'DOC.DUPLICATE':{'document_number':'148/QĐ-TTg'}})
    assert not any(r['relation_type']=='REPLACES' for r in result['business_relations'])


def test_suspension_requires_operative_heading_and_registered_number():
    result = extract([unit('DOC.CURRENT',1,
        'Điều 1. Tạm ngưng hiệu lực Quyết định số 148/QĐ-TTg và 999/QĐ-TTg.')])
    edges = [r for r in result['business_relations'] if r['relation_type']=='SUSPENDS']
    assert len(edges)==1 and edges[0]['status']=='candidate'
    assert edges[0]['attributes']['interpretation_verified'] is False


def test_temporal_effect_does_not_capture_reference_in_another_clause():
    result = extract([unit('DOC.CURRENT',13,
        'Điều 11. Hiệu lực\n1. Quyết định 148/QĐ-TTg hết hiệu lực sau 60 ngày '
        'kể từ ngày Quyết định này có hiệu lực.\n2. Tham khảo Quyết định 1489/QĐ-TTg.')])
    edges = [r for r in result['business_relations'] if r['relation_type']=='REPLACES']
    assert len(edges)==1
    entities = {e['entity_id']:e for e in result['business_entities']}
    assert entities[edges[0]['target_entity_id']]['source_id']=='DOC.OLD'
    result = extract([unit('DOC.AMEND',1,
        'Điều 1. Sửa đổi Quyết định 1148/QĐ-TTg.\n1. Tham khảo Quyết định 148/QĐ-TTg.')])
    assert not any(r['relation_type']=='AMENDS' for r in result['business_relations'])


def test_owner_relation_uses_the_same_record_and_explicit_merged_owner():
    from tests.ocop.test_business_knowledge_upgrade import _recognition_fixture
    u = _recognition_fixture()
    result = extract_semantics([u],{u['source_id']:'recognition_decision'},
                               candidates([u],{u['source_id']:'recognition_decision'}))
    owners = [r for r in result['business_relations'] if r['relation_type'] == 'OWNED_BY']
    declared = [r for r in result['business_relations'] if r['relation_type'] == 'DECLARED_BY']
    assert len(owners) == 2
    assert {r['target_entity_id'] for r in owners} == {r['target_entity_id'] for r in declared}
    assert all(any(e['cell_id'] == 'table:native:0:r1:c1' for e in r['evidence']) for r in owners)


def test_document_relations_materialize_with_attributes_and_no_rejections(tmp_path):
    import json
    from ai_core.graph.ocop.builder import build_graph
    units = [unit('DOC.CURRENT',13,
        'Điều 11. Hiệu lực thi hành\n1. Quyết định này có hiệu lực thi hành từ ngày 22 tháng 5 năm 2026.\n'
        '2. Quyết định số 148/QĐ-TTg hết hiệu lực sau 60 ngày kể từ ngày Quyết định này có hiệu lực thi hành.')]
    result = extract(units)
    knowledge = tmp_path/'knowledge'
    knowledge.mkdir()
    (knowledge/'manifest.json').write_text(json.dumps({'complete':True,'corpus_version':'synthetic',
                                                       'document_registry':REGISTRY}))
    for name, rows in {'evidence_units':units, **result}.items():
        (knowledge/f'{name}.jsonl').write_text(
            ''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    graph = tmp_path/'graph'
    manifest = build_graph(knowledge,graph)
    assert manifest['counts']['rejected'] == 0
    edges = [json.loads(s) for s in (graph/'edges.jsonl').read_text(encoding='utf-8').splitlines()]
    nodes = [json.loads(s) for s in (graph/'nodes.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len([n for n in nodes if n['node_type']=='SourceDocument' and n['source_id']=='DOC.CURRENT'])==1
    edge = next(e for e in edges if e['relation_type'] == 'REPLACES')
    assert edge['properties']['effective_from'] == '2026-05-22'
    assert edge['properties']['expires_after_days'] == 60
    assert all(c['source_sha256'] == 'a'*64 for c in edge['citations'])
