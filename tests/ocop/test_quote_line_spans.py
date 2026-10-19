from ai_core.processing.ocop.knowledge_extract import page_units
from ai_core.domain.ocop_citations import quote_bbox


def test_split_ocr_blocks_on_same_line_have_one_quote_span():
    page={'source_id':'S','source_sha256':'a'*64,'pdf_page':1,
          'width_pt':100,'height_pt':100,'extracted_text':'UBND xã\nkiểm tra hồ sơ',
          'blocks':[{'block_id':'a','text':'UBND','bbox':[0,0,20,10]},
                    {'block_id':'b','text':'xã','bbox':[25,0,35,10]},
                    {'block_id':'c','text':'kiểm tra hồ sơ','bbox':[0,15,80,25]}]}
    u=next(u for u in page_units(page) if u['unit_kind']=='paragraph')
    assert len(u['spans'])==3  # original block IDs/provenance remain intact
    assert quote_bbox(u,1,'xã')==(0,0,35,10)
    assert quote_bbox(u,1,'kiểm tra hồ sơ')==(0,15,80,25)
