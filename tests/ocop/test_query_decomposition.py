from ai_core.retrieval.ocop.decompose import sub_queries


def test_contrastive_question_is_split_into_its_sides():
    parts = sub_queries('Hồ sơ đánh giá lại khác gì hồ sơ lần đầu và nộp trước thời điểm nào?')
    assert 'Hồ sơ đánh giá lại' in parts and 'hồ sơ lần đầu' in parts


def test_simple_question_is_not_split():
    assert sub_queries('Điều 6 quy định hồ sơ lần đầu ra sao?') == []


def test_parts_without_enough_content_are_dropped():
    assert sub_queries('UBND cấp xã và cấp tỉnh') == []


def test_unaccented_question_keeps_original_spelling_in_parts():
    parts = sub_queries('ho so danh gia lai khac gi ho so lan dau')
    assert parts == ['ho so danh gia lai', 'ho so lan dau']
