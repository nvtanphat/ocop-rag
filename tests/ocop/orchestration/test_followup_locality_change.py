from ai_core.orchestration.ocop.router import route_query


def test_asking_the_same_for_another_locality_leaves_the_first_localitys_decision():
    prior = {
        "last_query": "Quyết định 797 của Huế công nhận mấy sản phẩm?",
        "intent": "RECOGNITION_LOOKUP",
        "slots": {"document_code": "797", "region": "Huế"},
    }
    slots = route_query("Còn của Hải Phòng thì sao?", session=prior).slots
    assert slots["region"] == "Hải Phòng"
    assert "document_code" not in slots
