"""Shape constraints use only synthetic candidate dictionaries."""
import pytest
from ai_core.knowledge.ocop.shapes import audit_shapes


def ent(kind,attrs=None,eid='e'):
    return {'entity_id':eid,'kind':kind,'source_id':'S','label':'literal',
            'attributes':attrs or {},'evidence':[]}


def rel(kind,src,dst):
    return {'relation_type':kind,'source_entity_id':src,'target_entity_id':dst}


@pytest.mark.parametrize('kind,attrs',[
    ('ScoreOption',{'points_candidate':'2','parent_identified':True}),
    ('Criterion',{'level':True,'max_points_candidate':None}),
    ('CriterionSheet',{}),('StarLevel',{'star_level':'5'}),('ProcedureStep',{})])
def test_required_properties_and_exact_types(kind,attrs):
    audit=audit_shapes([],{'business_entities':[ent(kind,attrs)]})
    assert audit['counts']['required_property_type']>=1


@pytest.mark.parametrize('kind,relation',[
    ('ScoreOption','HAS_OPTION'),('Criterion','HAS_SUBCRITERION'),('ProcedureStep','RESPONSIBLE_FOR')])
def test_parent_missing_and_present(kind,relation):
    e=ent(kind)
    assert audit_shapes([],{'business_entities':[e]})['counts']['parent_cardinality']==1
    assert 'parent_cardinality' not in audit_shapes([],{'business_entities':[e],
        'business_relations':[rel(relation,'parent','e')]})['counts']


def test_multiple_criterion_parents_and_explicit_authority_omission():
    layers={'business_entities':[ent('Criterion'),ent('ProcedureStep',
        {'authority_omission_reason':'literal collective actor unresolved'},'step')],
        'business_relations':[rel('HAS_CRITERION','sheet','e'),rel('HAS_SUBCRITERION','group','e')]}
    rows=audit_shapes([],layers)['violations']
    assert [v['entity_id'] for v in rows if v['constraint']=='parent_cardinality']==['e']


def test_sheet_observed_vs_index_only_and_framework_counts():
    units=[{'unit_id':'u','source_id':'S','text':'1. Bộ sản phẩm: Example',
            'unit_kind':'paragraph','structured':{'source_kind':'ocop_framework'},'spans':[]}]
    result=audit_shapes(units,{'business_entities':[ent('CriterionSheet',{'sheet_number':'1'})]})
    assert result['counts']['sheet_requires_criterion']==1
    assert result['counts']['framework_count']==2
    units[0]['text']='index only'
    assert audit_shapes(units,{'business_entities':[ent('CriterionSheet',{'sheet_number':'1'})]})['counts']['sheet_source_not_observed']==1


def test_bbox_threshold_configurable_and_non_mutating():
    e=ent('Authority');e['evidence']=[{'source_id':'S','evidence_unit_id':'u','pdf_page':1,
        'bbox':[0,0,100,60],'quote':'literal'}]
    u={'unit_id':'u','source_id':'S','unit_kind':'page','text':'literal',
       'spans':[{'pdf_page':1,'bbox':[0,0,100,100]}]}
    assert audit_shapes([u],{'business_entities':[e]})['counts']['citation_page_area']==1
    assert 'citation_page_area' not in audit_shapes([u],{'business_entities':[e]},max_page_area_ratio=.7)['counts']
    assert e['evidence'][0]['bbox']==[0,0,100,60]


@pytest.mark.parametrize('kind',['SourceDocument','Article','Clause','RecognitionDecision','LocalGuidance','CriterionSheet'])
def test_container_large_literal_quote_is_valid_but_outside_page_is_not(kind):
    e=ent(kind,{'sheet_number':'1'});e['evidence']=[{'source_id':'S','evidence_unit_id':'u',
        'pdf_page':1,'bbox':[0,0,100,80],'quote':'literal'}]
    u={'unit_id':'u','source_id':'S','unit_kind':'page','text':'literal',
       'spans':[{'pdf_page':1,'bbox':[0,0,100,100]}],
       'structured':{'quote_lines':[{'text':'literal','pdf_page':1,'bbox':[0,0,100,80]}]}}
    audit=audit_shapes([u],{'business_entities':[e]})
    assert 'citation_page_area' not in audit['counts']
    e['evidence'][0]['bbox']=[-10,0,100,80]
    assert audit_shapes([u],{'business_entities':[e]})['counts']['citation_outside_page']==1


def test_pending_source_is_not_a_gate_violation():
    audit=audit_shapes([],{'business_entities':[ent('CriterionSheet',{'sheet_number':'9'})]})
    assert audit['severity_counts']=={'pending_source':1}
    assert audit['violations'][0]['severity']=='pending_source'


def test_container_bbox_must_match_quote_lines_in_both_directions():
    e=ent('Article');e['evidence']=[{'source_id':'S','evidence_unit_id':'u','pdf_page':1,
        'bbox':[10,10,20,20],'quote':'literal'}]
    u={'unit_id':'u','source_id':'S','unit_kind':'paragraph','text':'literal',
       'spans':[{'pdf_page':1,'bbox':[0,0,100,80]}],
       'structured':{'quote_lines':[{'text':'literal','pdf_page':1,'bbox':[0,0,100,80]}]}}
    assert audit_shapes([u],{'business_entities':[e]})['counts']['citation_quote_geometry_mismatch']==1
