from ocop_contracts.layout import layout_page


def test_adjacent_text_lines_with_tall_boxes_cannot_share_overlapping_x_ranges():
    boxes = [('left first', [112, 107, 390, 134]),
             ('right second', [367, 122, 557, 144]),
             ('right first', [390, 107, 557, 135]),
             ('left second', [112, 123, 367, 145])]
    blocks = [{'text':text, 'bbox':box, 'layout_region':{'label':'text', 'order':0}}
              for text,box in boxes]
    ordered, _ = layout_page(blocks, 600, 800)
    assert [b['text'] for b in ordered] == ['left first','right first','left second','right second']
    assert {b['text']:b['bbox'] for b in ordered} == dict(boxes)
