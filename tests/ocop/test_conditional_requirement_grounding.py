import pytest

from ai_core.graph.ocop.grounding import _entails


@pytest.mark.parametrize('statement', [
    'Các nhãn hiệu (trường hợp sản phẩm đã được bảo hộ nhãn hiệu tập thể; '
    'nhãn hiệu chứng nhận thì phải có văn bản ghi nhận quyền sử dụng).',
    'Các nhãn hiệu (trưởng hợp sản phẩm đã được bảo hộ nhãn hiệu tập thể '
    'thì phải có văn bản ghi nhận quyền sử dụng).',
])
def test_conditional_table_note_cannot_become_an_unconditional_requirement(statement):
    source={'label':'3.5. Sở hữu trí tuệ','properties':{},'citations':[{'quote':statement}]}
    target={'label':'văn bản ghi nhận quyền sử dụng','properties':{}}
    assert not _entails({'relation_type':'REQUIRES_EVIDENCE'},source,target,{})


def test_standalone_mandatory_note_stays_supported():
    source={'label':'Công bố chất lượng','properties':{},'citations':[
        {'quote':'Bản tiêu chuẩn sản phẩm phải có phiếu kiểm nghiệm các chỉ tiêu an toàn thực phẩm.'}]}
    target={'label':'phiếu kiểm nghiệm','properties':{}}
    assert _entails({'relation_type':'REQUIRES_EVIDENCE'},source,target,{})
