from tools.evaluate_reviewed_claims import eligible


def test_only_questions_whose_every_target_page_is_reviewed_are_eligible():
    pages = {"S1": {3, 4}}
    questions = [
        {"id": 1, "source_id": "S1", "pages": [3]},
        {"id": 2, "source_id": "S1", "pages": [3, 5]},
        {"id": 3, "source_id": "S2", "pages": [3]},
        {"id": 4, "source_id": "S1", "pages": []},
        {"id": 5, "source_id": "S1", "pages": [4], "turns": ["a", "b"]},
    ]
    assert [q["id"] for q in eligible(questions, pages)] == [1]
