from types import SimpleNamespace

from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.sessions import SessionStore

PRIOR = {
    "last_query": "QĐ26/2026 Điều 6 quy định hồ sơ lần đầu ra sao?",
    "intent": "EXACT_LOOKUP",
    "slots": {"document_code": "26/2026", "article_id": "6", "years": ["2026"]},
    "capabilities": ["exact_article"],
}


def _response(intent, slots, *, clarify=False, missing=()):
    return SimpleNamespace(
        intent=SimpleNamespace(value=intent),
        route=SimpleNamespace(
            slots=slots, capabilities=["x"], needs_clarification=clarify, missing_slots=list(missing)
        ),
    )


def test_a_new_target_replaces_the_old_target_and_keeps_the_document():
    route = route_query("Còn mẫu số 02?", session=PRIOR)
    assert route.slots["document_code"] == "26/2026" and route.slots["form_id"] == "2"
    assert "article_id" not in route.slots


def test_a_closing_cue_without_scope_continues_the_conversation():
    prior = {
        "last_query": "Hạn nộp hồ sơ OCOP phường Thành Sen năm 2026 là khi nào?",
        "intent": "PROCEDURE_FORM",
        "slots": {"region": "Thành Sen", "years": ["2026"]},
        "capabilities": [],
    }
    assert route_query("Nơi tiếp nhận hồ sơ thì sao?", session=prior).slots.get("region") == "Thành Sen"
    # the same words with a scope of their own are a new question
    assert "region" not in route_query("Nơi tiếp nhận hồ sơ ở Hải Phòng thì sao?", session=prior).slots.get(
        "region", ""
    )


def test_a_demonstrative_continues_the_topic():
    prior = {
        "last_query": "QĐ525 có tên sản phẩm HANA không?",
        "intent": "RECOGNITION_LOOKUP",
        "slots": {"document_code": "525", "product_name": "HANA"},
        "capabilities": [],
    }
    assert (
        route_query("Chủ thể sản xuất sản phẩm đó là ai?", session=prior).slots.get("product_name") == "HANA"
    )


def test_a_clarification_turn_does_not_move_the_conversation_scope():
    store = SessionStore()
    store.save(
        "s", "QĐ26/2026 Điều 6 quy định hồ sơ lần đầu ra sao?", _response("EXACT_LOOKUP", PRIOR["slots"])
    )
    store.save(
        "s",
        "Còn năm 2023?",
        _response(
            "CLARIFY",
            {"document_code": "26/2026", "years": ["2023"]},
            clarify=True,
            missing=["document_version_or_event_year"],
        ),
    )
    kept = store.get("s")
    assert kept["slots"]["years"] == ["2026"] and kept["last_query"].startswith("QĐ26/2026 Điều 6")
    assert kept["unresolved"]["missing_slots"] == ["document_version_or_event_year"]
    store.save("s", "Còn Điều 7?", _response("EXACT_LOOKUP", {"document_code": "26/2026", "article_id": "7"}))
    assert "unresolved" not in store.get("s") and store.get("s")["slots"]["article_id"] == "7"


def _memory(**overrides):
    from ai_core.orchestration.ocop import memory

    state = memory.update(
        None,
        slots={"document_code": "26/2026", "form_id": "1"},
        standalone="Mẫu số 01 dùng để làm gì?",
        citations=[
            {"source_id": "VN.OCOP.QD26.2026", "pdf_page": 4, "chunk_id": "c1", "evidence_unit_id": "u1"}
        ],
        corpus_version="v1",
    )
    state = memory.update(
        state,
        slots={"document_code": "26/2026", "form_id": "2"},
        standalone="Mẫu số 02 dùng để làm gì?",
        citations=[{"source_id": "VN.OCOP.QD26.2026", "pdf_page": 4, "chunk_id": "c2"}],
        corpus_version="v1",
    )
    return {**state, **overrides}


def test_plural_reference_resolves_to_the_two_discussed_items_in_order():
    from ai_core.orchestration.ocop import memory

    carried = memory.plural_referents("Hai mẫu này khác nhau ở đâu?", _memory(), {})
    assert carried == {"form_ids": ["1", "2"], "form_id": "1"}
    # nothing discussed twice -> nothing to resolve, nothing invented
    assert (
        memory.plural_referents(
            "Hai mẫu này khác nhau ở đâu?",
            memory.update(None, slots={"form_id": "1"}, standalone="x", citations=[], corpus_version="v1"),
            {},
        )
        == {}
    )
    assert memory.plural_referents(
        "So sánh với mẫu số 01", _memory(), {"form_id": "1", "form_ids": None} | {"form_id": "1"}
    ) == {"form_ids": ["2", "1"], "form_id": "2"}


def test_a_plural_product_reference_resolves_to_the_two_latest_products_or_asks_which():
    from ai_core.orchestration.ocop import memory
    from ai_core.orchestration.ocop.catalog import EntityCatalog
    from ai_core.orchestration.ocop.router import route_query

    labels = ["Gạo giống HANA", "Gạo ST25"]
    catalog = EntityCatalog({"entities": {"product": [{"label": x, "source_ids": []} for x in labels]}})
    state = None
    for label in labels:
        state = memory.update(
            state, slots={"product_name": label}, standalone=f"{label} được mấy sao?", citations=[], corpus_version="v"
        )
    session = {"last_query": "Gạo ST25 được mấy sao?", "slots": {"product_name": "Gạo ST25"}, "memory": state}
    route = route_query("Hai sản phẩm đó của hợp tác xã nào?", catalog=catalog, session=session)
    assert route.slots["product_names"] == ["Gạo giống HANA", "Gạo ST25"]
    lone = route_query("Hai sản phẩm đó của hợp tác xã nào?", catalog=catalog)
    assert lone.needs_clarification and lone.missing_slots == ["referent_product"]


def test_rewrite_swaps_another_product_into_the_previous_question():
    from ai_core.orchestration.ocop import memory

    state = memory.update(
        None,
        slots={"product_name": "Gạo ruộng rươi giống HANA"},
        standalone="Gạo ruộng rươi giống HANA được mấy sao?",
        citations=[],
        corpus_version="v1",
    )
    text, method = memory.rewrite(
        "Còn ST25 thì sao?",
        state,
        {"product_name": "Gạo ruộng rươi ST25"},
        {"product_name": "Gạo ruộng rươi ST25"},
        previous_slots={"product_name": "Gạo ruộng rươi giống HANA"},
    )
    assert text == "Gạo ruộng rươi ST25 được mấy sao?" and method == "substitute:product"
    # a product named in words (not a code) is swapped in the same way, not kept as the whole question
    text, method = memory.rewrite(
        "Còn Hạt ngọc 9?",
        state,
        {"product_name": "Gạo ruộng rươi Hạt ngọc 9"},
        {"product_name": "Gạo ruộng rươi Hạt ngọc 9"},
        previous_slots={"product_name": "Gạo ruộng rươi giống HANA"},
    )
    assert text == "Gạo ruộng rươi Hạt ngọc 9 được mấy sao?" and method == "substitute:product"


def test_rewrite_swaps_the_new_thing_in_and_keeps_words_of_the_question():
    from ai_core.orchestration.ocop import memory

    state = memory.update(
        None,
        slots={"document_code": "26/2026", "article_id": "6"},
        standalone="QĐ26/2026 Điều 6 quy định hồ sơ lần đầu ra sao?",
        citations=[],
        corpus_version="v1",
    )
    assert memory.rewrite(
        "Còn Điều 7?", state, {"document_code": "26/2026", "article_id": "7"}, {"article_id": "7"}
    ) == ("QĐ26/2026 Điều 7 quy định hồ sơ lần đầu ra sao?", "substitute:article")
    assert (
        memory.rewrite("Nó thì sao?", state, {"document_code": "26/2026", "article_id": "6"}, {})[1]
        == "previous_standalone"
    )
    text, method = memory.rewrite(
        "Cơ quan tiếp nhận hồ sơ thì sao?", state, {"document_code": "26/2026", "article_id": "6"}, {}
    )
    assert (
        method == "state_scope"
        and text.startswith("Cơ quan tiếp nhận hồ sơ")
        and "Điều 6" in text
        and "26/2026" in text
    )


def test_remembered_evidence_is_dropped_when_the_corpus_or_the_document_scope_changed():
    from ai_core.orchestration.ocop import memory

    state = _memory()
    kept, dropped = memory.reusable_evidence(state, corpus_version="v1", source_ids={"VN.OCOP.QD26.2026"})
    assert len(kept) == 2 and not dropped
    kept, dropped = memory.reusable_evidence(state, corpus_version="v1", source_ids={"VN.OTHER"})
    assert not kept and {d["reason"] for d in dropped} == {"scope_changed"}
    kept, dropped = memory.reusable_evidence(state, corpus_version="v2", source_ids=None)
    assert not kept and {d["reason"] for d in dropped} == {"corpus_version_changed"}


def test_malformed_memory_is_discarded():
    from ai_core.orchestration.ocop import memory

    assert (
        memory.sanitize(
            {"referents": {"form": "not-a-list"}, "evidence": [{"source_id": 3}, "x"], "standalone": 5}
        )
        == memory.empty()
    )


def test_a_form_gap_is_reported_while_the_rest_of_the_evidence_is_answered():
    from ai_core.orchestration.ocop.answer import assemble  # noqa: F401 (the gate lives in the workflow; see below)
    from ai_core.orchestration.ocop.workflow import OcopAgent

    agent = OcopAgent.__new__(OcopAgent)
    agent.rerank = False
    row = {
        "source_id": "VN.X",
        "evidence_unit_id": "u1",
        "review_status": "needs_review",
        "text": "Mẫu số 01 là phiếu đăng ký.",
        "source_spans": [{"pdf_page": 4}],
        "chunk_id": "c1",
    }
    state = {
        "route": {
            "intent": "PROCEDURE_FORM",
            "strategy": "x",
            "slots": {},
            "required_tools": ["lookup_form"],
        },
        "query": "Mẫu số 01 dùng để làm gì?",
        "results": [
            {
                "tool": "lookup_form",
                "output": {"results": [], "status": "incomplete_form_ids", "missing_form_ids": ["1"]},
            },
            {"tool": "search_regulations", "output": {"results": [row], "status": "ok"}},
        ],
    }
    agent.llm = None
    agent._catalog = lambda: None
    out = agent.answer(state)["answer"]
    assert out["status"] != "insufficient_form_scope" and out["citations"]
    assert "không mô tả nội dung của biểu mẫu" in out["answer"]
    only_gap = agent.answer({**state, "results": state["results"][:1]})["answer"]
    assert only_gap["status"] == "insufficient_form_scope"


def test_a_new_target_the_earlier_question_never_mentioned_is_asked_afresh_inside_the_scope():
    from ai_core.orchestration.ocop import memory

    state = memory.update(
        None,
        slots={"document_code": "26/2026"},
        standalone="Quyết định 26/2026 quy định gì về hồ sơ?",
        citations=[],
        corpus_version="v1",
    )
    text, method = memory.rewrite(
        "Còn Điều 7?", state, {"document_code": "26/2026", "article_id": "7"}, {"article_id": "7"}
    )
    assert (
        method == "generic_target" and text == "Điều 7 của Quyết định 26/2026 nói gì?"
    )  # not "...về hồ sơ?"


def test_naming_only_a_new_target_with_a_closing_cue_inherits_the_document():
    prior = {
        "last_query": "Quyết định 26/2026 quy định gì về hồ sơ?",
        "intent": "OCOP_OVERVIEW",
        "slots": {"document_code": "26/2026", "years": ["2026"]},
        "capabilities": [],
    }
    route = route_query("Mẫu số 02 thì sao?", session=prior)
    assert route.slots["document_code"] == "26/2026" and route.slots["form_id"] == "2"
    # a document of its own makes it a new question about that document
    assert (
        route_query("Mẫu số 02 của QĐ148/2023 thì sao?", session=prior).slots["document_code"] == "148/2023"
    )


def test_public_app_keeps_serving_after_a_failed_request(api_client):
    with api_client as client:
        assert client.post("/api/ocop/query", json={"query": ""}).status_code == 422
        assert (
            client.post("/api/ocop/query", json={"query": "x", "retrieval_mode": "bogus"}).status_code == 422
        )
        broken = client.post("/api/ocop/query", json={"query": "OCOP là gì?", "use_llm": False})
        assert broken.status_code in (200, 503)  # an empty corpus root is reported, never an unhandled 500
        assert (
            client.post("/api/ocop/query", json={"query": ""}).status_code == 422
        )  # and the app is still up


def test_switching_document_keeps_the_topic_but_not_the_old_documents_form_article_or_sheet():
    from ai_core.orchestration.ocop import memory

    topic = memory.update(
        None,
        slots={"document_code": "26/2026"},
        standalone="Quyết định 26/2026 quy định gì về hồ sơ?",
        citations=[],
        corpus_version="v1",
    )
    assert memory.rewrite(
        "Còn QĐ148/2023?", topic, {"document_code": "148/2023"}, {"document_code": "148/2023"}
    ) == ("Quyết định 148/2023 quy định gì về hồ sơ?", "substitute:document")
    target = memory.update(
        None,
        slots={"document_code": "26/2026", "form_id": "2"},
        standalone="Mẫu số 02 của Quyết định 26/2026 nói gì?",
        citations=[],
        corpus_version="v1",
    )
    assert memory.rewrite(
        "Còn QĐ148/2023?", target, {"document_code": "148/2023"}, {"document_code": "148/2023"}
    ) == ("Quyết định 148/2023 nói gì?", "document_switch")
    # restating the target keeps it
    assert (
        memory.rewrite(
            "Còn Mẫu số 02 của QĐ148/2023?",
            target,
            {"document_code": "148/2023", "form_id": "2"},
            {"document_code": "148/2023", "form_id": "2"},
        )[1]
        != "document_switch"
    )


def test_document_switch_drops_the_old_documents_target_slots_but_a_restated_target_stays():
    prior = {
        "last_query": "Mẫu số 02 của QĐ26/2026?",
        "intent": "PROCEDURE_FORM",
        "slots": {"document_code": "26/2026", "form_id": "2", "years": ["2026"]},
        "capabilities": [],
    }
    switched = route_query("Còn Quyết định 525 thì sao?", session=prior)
    assert switched.slots["document_code"] == "525" and "form_id" not in switched.slots
    assert route_query("Còn Mẫu số 02 của Quyết định 525?", session=prior).slots["form_id"] == "2"


def test_a_comparison_with_a_pronoun_between_so_sanh_and_voi_resolves_the_two_forms():
    from ai_core.orchestration.ocop import memory

    state = memory.update(
        None,
        slots={"document_code": "26/2026", "form_id": "2"},
        standalone="Mẫu số 02 nói gì?",
        citations=[],
        corpus_version="v1",
    )
    assert memory.plural_referents("So sánh nó với mẫu số 01.", state, {"form_id": "1"}) == {
        "form_ids": ["2", "1"],
        "form_id": "2",
    }


def test_a_model_restatement_of_a_follow_up_adds_nothing_the_conversation_did_not_say():
    from ai_core.orchestration.ocop import followup_model

    history = ["Siro Atiso đỏ của Công ty Hichagol ở Huế được mấy sao?", "Hạt sen của HTX Sen Huế được mấy sao?"]
    question = "Quay lại siro lúc nãy, nó của đơn vị nào?"
    assert followup_model.refers_back(question)
    assert not followup_model.refers_back("Hạn nộp hồ sơ OCOP năm 2026 là ngày nào?")
    good = "Siro Atiso đỏ của Công ty Hichagol thuộc đơn vị nào?"
    assert followup_model.validate(question, history, good) == good
    assert followup_model.validate(question, history, "Siro Atiso đỏ đạt 5 sao năm 2027 của đơn vị nào?") is None
    assert followup_model.validate(question, history, "Siro Atiso đỏ của Công ty Vinamilk thuộc đơn vị nào?") is None


def test_memory_keeps_the_recent_standalone_questions_newest_first():
    from ai_core.orchestration.ocop import memory

    state = memory.empty()
    for q in ["Câu một?", "Câu hai?", "Câu ba?", "Câu bốn?"]:
        state = memory.update(state, slots={}, standalone=q, citations=[], corpus_version=None)
    assert state["recent"] == ["Câu bốn?", "Câu ba?", "Câu hai?"]
    assert memory.sanitize(state)["recent"] == state["recent"]


def test_a_new_product_the_previous_question_does_not_spell_out_keeps_the_users_question():
    from ai_core.orchestration.ocop import memory

    state = {**memory.empty(), "standalone": "Siro của Hichagol ở Huế đạt mấy sao OCOP vậy?"}
    updates = {"product_name": "Hạt sen", "organization_name": "HTX Sen Huế"}
    text, method = memory.rewrite(
        "Còn hạt sen của HTX Sen Huế được mấy sao?",
        state,
        {**updates, "region": "Huế"},
        updates,
        previous_slots={"product_name": "Mứt Atiso đỏ", "region": "Huế"},
    )
    assert "siro" not in text.casefold() and "hạt sen" in text.casefold(), text
    assert method == "state_scope"
