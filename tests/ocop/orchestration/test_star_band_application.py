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


def test_a_count_of_recognised_products_passes_only_when_the_checked_records_hold_it():
    from ai_core.orchestration.ocop.answer import _counts_checked_records

    recognized = {("VN.HUE.QD797.2026", 4): frozenset({"mut", "siro"}), ("VN.HUE.QD797.2026", 3): frozenset({"hat_sen"})}
    cited = [{"source_id": "VN.HUE.QD797.2026", "pdf_page": 3}]
    assert _counts_checked_records("Quyết định số 797/QĐ-UBND công nhận 02 sản phẩm OCOP 4 sao.", [1], cited, recognized)
    assert _counts_checked_records("Quyết định 797/QĐ-UBND công nhận 3 sản phẩm hạng 3 sao và 4 sao.", [1], cited, recognized)
    assert not _counts_checked_records("Quyết định 797/QĐ-UBND công nhận 5 sản phẩm OCOP 4 sao.", [1], cited, recognized)
    other = [{"source_id": "VN.HAIPHONG.QD525.2026", "pdf_page": 3}]
    assert not _counts_checked_records("Quyết định công nhận 02 sản phẩm OCOP 4 sao.", [1], other, recognized)


def test_an_owners_count_passes_only_for_the_one_owner_it_names_and_its_cited_records():
    from ai_core.orchestration.ocop.answer import _counts_owner_records

    owners = {
        "Công ty TNHH MTV Hichagol": {"keys": frozenset({"hichagol"}), "records": {"VN.HUE.QD797.2026": frozenset({"r1", "r2"})}},
        "HTX Sen Huế": {"keys": frozenset({"sen hue"}), "records": {"VN.HUE.QD797.2026": frozenset({"r3"})}},
    }
    cited = [{"source_id": "VN.HUE.QD797.2026", "pdf_page": 3}]
    assert _counts_owner_records("Công ty Hichagol có 2 sản phẩm OCOP.", [1], cited, owners, {})
    assert not _counts_owner_records("Công ty Hichagol có 3 sản phẩm OCOP.", [1], cited, owners, {})
    assert not _counts_owner_records("Một công ty có 2 sản phẩm OCOP.", [1], cited, owners, {})
