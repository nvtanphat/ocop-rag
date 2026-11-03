from ai_core.orchestration.ocop.answer import _applies_star_band

BAND4 = {"star_level": 4, "min_points": 70, "max_points": 90, "min_inclusive": True, "max_inclusive": False,
         "places": frozenset({("VN.OCOP.QD26.2026", 3)})}
CITED = [{"source_id": "VN.OCOP.QD26.2026", "pdf_page": 3}]
ASKED = "Sản phẩm đạt 72 điểm thì được mấy sao theo bộ tiêu chí mới?"


def test_a_score_the_user_gave_inside_the_cited_band_names_that_star_level():
    claim = "Sản phẩm đạt 72 điểm thuộc khoảng từ 70 đến dưới 90 điểm nên được xếp hạng 4 sao."
    assert _applies_star_band(claim, [1], CITED, ASKED, (BAND4,))


def test_the_wrong_level_a_score_outside_the_band_or_an_uncited_band_never_pass():
    assert not _applies_star_band("Sản phẩm 72 điểm được 5 sao.", [1], CITED, ASKED, (BAND4,))
    assert not _applies_star_band("Sản phẩm 72 điểm được 4 sao.", [1], CITED, "Sản phẩm 95 điểm được mấy sao?", (BAND4,))
    other_page = [{"source_id": "VN.OCOP.QD26.2026", "pdf_page": 17}]
    assert not _applies_star_band("Sản phẩm 72 điểm được 4 sao.", [1], other_page, ASKED, (BAND4,))


def test_a_score_the_user_did_not_give_is_not_excused():
    assert not _applies_star_band("Hạt sen của HTX Sen Huế đạt 75 điểm, hạng 4 sao.", [1], CITED, ASKED, (BAND4,))
