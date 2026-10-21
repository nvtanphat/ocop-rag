from ai_core.graph.ocop.grounding import _entails, _entity_typed


def fixture():
    labels=['1. TỔ CHỨC SẢN XUẤT','a) Nguồn gốc','Phương án nguồn gốc',
            'b) Gia tăng giá trị','Phương án gia tăng']
    unit={'unit_id':'u','text':'\n'.join(labels),'structured':{'table_id':'t',
        'cells':[{'row':i,'col':0,'text':label} for i,label in enumerate(labels)]}}
    def node(row, letter=None):
        return {'source_id':'HIST','label':labels[row],'node_type':'Criterion',
            'properties':{'row':row,'table_id':'t','sheet_number_candidate':'1',
                          'criterion_letter':letter},
            'evidence_unit_ids':['u'],
            'citations':[{'row':row,'evidence_unit_id':'u','pdf_page':1,'quote':labels[row]}]}
    return {'u':unit},node


def test_lettered_child_has_literal_type_and_bounded_group_parent():
    units,node=fixture()
    assert _entity_typed(node(1,'a'),units)
    assert _entails({'relation_type':'HAS_SUBCRITERION'},node(0),node(1,'a'),units)
    assert not _entity_typed(node(1,'b'),units)


def test_letter_heading_stops_an_option_from_borrowing_an_older_parent():
    units,node=fixture()
    edge={'relation_type':'HAS_OPTION'}
    option=node(4)
    option['properties']['parent_identified']=True
    assert not _entails(edge,node(0),option,units)
    assert not _entails(edge,node(1,'a'),option,units)
    assert _entails(edge,node(3,'b'),option,units)


def test_noisy_numbered_heading_is_a_barrier_without_becoming_a_verified_parent():
    units,node=fixture()
    units['u']['structured']['cells'][1]['text']='j 1.6. Bảo vệ môi trường'
    option=node(2)
    option['properties']['parent_identified']=True
    assert not _entails({'relation_type':'HAS_OPTION'},node(0),option,units)
