from ai_core.orchestration.ocop.verification import check_sensitive_claims, label_table_rows

TABLE = (
    "Cột: STT | Tổ chức/cá nhân | Sản phẩm | Địa chỉ | Chủ thể | Điểm đánh giá | Xếp loại\n"
    "1 | Công ty Quang Hải | Nước mắm Chắt cao cấp | Thôn Lục Độ | Bùi Trắc Vinh | 83,8 | 4 sao\n"
    "2 | Nước mắm Cá Thu | 84,1 | 4 sao"
)
ROW = {"source_id": "S", "evidence_unit_id": "u", "text": TABLE, "review_status": "verified"}
CITATIONS = [{"source_id": "S", "evidence_unit_id": "u"}]


def unsupported(claim):
    return check_sensitive_claims(claim, [ROW], CITATIONS)["unsupported_score_or_star_claims"]


def test_continuation_rows_take_their_labels_from_the_right():
    assert "Điểm đánh giá: 84,1" in label_table_rows(TABLE).split("\n")[2]


def test_a_score_in_a_table_row_binds_to_that_row_only():
    assert unsupported("Nước mắm Chắt cao cấp được 83,8 điểm [S1].") == []
    assert unsupported("Nước mắm Cá Thu được 84,1 điểm [S1].") == []
    assert unsupported("Nước mắm Cá Thu được 83,8 điểm [S1].") == ["83,8 điểm"]


def test_text_that_is_not_a_table_is_unchanged():
    assert label_table_rows("Hạng 4 sao: từ 70 đến dưới 90 điểm.") == "Hạng 4 sao: từ 70 đến dưới 90 điểm."


def test_a_chunk_cut_from_its_table_takes_the_header_its_source_has():
    cut = (
        "Văn bản 525/QĐ-UBND, trang 5. | 17 | Hộ A | Điếu cày rồng | Số 1 | Nguyễn Lê Tuấn | 60,6 | 3 sao |\n"
        "| 18 | Hộ A | Đèn trâu | Số 1 | Nguyễn Lê Tuấn | 60,1 | 3 sao |"
    )
    row = {"source_id": "VN.HAIPHONG.QD525.2026", "evidence_unit_id": "u", "text": cut, "review_status": "needs_review"}
    cites = [{"source_id": "VN.HAIPHONG.QD525.2026", "evidence_unit_id": "u"}]
    check = lambda claim: check_sensitive_claims(claim, [row], cites)["unsupported_score_or_star_claims"]  # noqa: E731
    assert check("Điếu cày rồng được 60,6 điểm [S1].") == []
    assert check("Điếu cày rồng được 60,1 điểm [S1].") == ["60,1 điểm"]
