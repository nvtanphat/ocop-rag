from types import SimpleNamespace

from PIL import Image, ImageDraw
import pytest

from ocop_ocr.table_parser import raster_tables


@pytest.mark.parametrize('partial_rule', [False, True])
def test_floating_text_stroke_is_not_a_row_but_connected_partial_rule_is(partial_rule):
    image = Image.new('RGB', (1000, 700), 'white')
    draw = ImageDraw.Draw(image)
    for x in [100, 750, 900]:
        draw.line((x, 100, x, 500), fill='black', width=3)
    for y in [100, 200, 400, 500]:
        draw.line((100, y, 900, y), fill='black', width=3)
    # A long bold text stroke survives morphology and regional projection,
    # but does not connect the table's vertical rules.
    draw.line((140, 280, 400, 280), fill='black', width=3)
    if partial_rule:
        # A real border of a merged cell need not span the whole table.
        draw.line((100, 330, 750, 330), fill='black', width=3)
    page = SimpleNamespace(rect=SimpleNamespace(width=1000, height=700))
    tables = raster_tables(image, page, [])
    table = max(tables, key=lambda t: len(t['cells']))
    assert table['col_count'] == 2
    assert table['row_count'] == (4 if partial_rule else 3)
    assert table['bbox'][3] == pytest.approx(500, abs=2)
