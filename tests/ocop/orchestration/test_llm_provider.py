"""Synthetic tests for the extraction-only LLM client and grounded proposer; no network calls."""

import io
import json

import pytest

from ai_core.knowledge.ocop import llm_proposals
from ai_core.knowledge.ocop.llm_proposals import propose
from ai_core.orchestration.ocop import llm as llm_mod
from ai_core.orchestration.ocop.llm import OpenAICompatClient, make_extraction_client

SHA = "a" * 64


@pytest.fixture(autouse=True)
def _no_env_file(monkeypatch):
    monkeypatch.setattr(llm_mod, "load_env_file", lambda path=None: None)
    for key in (
        "OCOP_EXTRACT_LLM_PROVIDER",
        "OCOP_EXTRACT_LLM_MODEL",
        "OCOP_EXTRACT_OPENAI_BASE_URL",
        "OCOP_EXTRACT_OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_default_extraction_provider_is_the_openai_compatible_api(monkeypatch):
    monkeypatch.setenv("OCOP_EXTRACT_OPENAI_API_KEY", "k")
    client = make_extraction_client()
    assert isinstance(client, OpenAICompatClient) and client.model == "gpt-6-sol"


def test_openai_provider_requires_key(monkeypatch):
    monkeypatch.setenv("OCOP_EXTRACT_LLM_PROVIDER", "openai")
    with pytest.raises(RuntimeError, match="OCOP_EXTRACT_OPENAI_API_KEY"):
        make_extraction_client()


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("OCOP_EXTRACT_LLM_PROVIDER", "other")
    with pytest.raises(RuntimeError, match="Unsupported"):
        make_extraction_client()


def test_openai_chat_sends_json_mode_and_hides_key(monkeypatch):
    monkeypatch.setenv("OCOP_EXTRACT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OCOP_EXTRACT_OPENAI_BASE_URL", "https://example.invalid/v1/")
    monkeypatch.setenv("OCOP_EXTRACT_OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("OCOP_EXTRACT_LLM_MODEL", "m1")
    seen = {}

    def fake_urlopen(req, timeout):
        seen.update(url=req.full_url, auth=req.get_header("Authorization"), body=json.loads(req.data))
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": '{"entities":[]}'}}]}).encode())

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", fake_urlopen)
    client = make_extraction_client()
    assert isinstance(client, OpenAICompatClient)
    assert client.chat("s", "u", format_json=True) == '{"entities":[]}'
    assert seen["url"] == "https://example.invalid/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test-secret"
    assert seen["body"]["model"] == "m1"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert "sk-test-secret" not in repr(client)


def test_openai_malformed_response_raises_runtime_error(monkeypatch):
    monkeypatch.setattr(
        llm_mod.urllib.request, "urlopen", lambda req, timeout: io.BytesIO(b'{"choices": []}')
    )
    client = OpenAICompatClient(model="m1", base_url="https://example.invalid/v1", api_key="k", retries=0)
    with pytest.raises(RuntimeError):
        client.chat("s", "u")


class FakeLLM:
    model = "fake"

    def __init__(self, response):
        self.response = response
        self.calls = 0

    def chat(self, system, user, *, format_json=False, max_tokens=1024):
        self.calls += 1
        return json.dumps(
            self.response(user) if callable(self.response) else self.response, ensure_ascii=False
        )


def _unit(lines, pages=None, uid="unit:1"):
    pages = pages or [3] * len(lines)
    spans = [
        {
            "pdf_page": p,
            "bbox": [10, 10 + 20 * i, 200, 25 + 20 * i],
            "block_id": f"b{i}",
            "source_sha256": SHA,
        }
        for i, p in enumerate(pages)
    ]
    return {
        "source_id": "VN.TEST.DOC",
        "unit_id": uid,
        "unit_kind": "paragraph",
        "text": "\n".join(lines),
        "spans": spans,
        "structured": {},
    }


UNIT = _unit(
    [
        "Sản phẩm: Mật ong hoa nhãn, đóng chai thủy tinh",
        "Chủ thể: HTX Ong Mật Bình Minh",
        "Mật ong hoa nhãn do HTX Ong Mật Bình Minh sản xuất",
    ]
)


def test_grounded_entities_attributes_and_relation():
    llm = FakeLLM(
        {
            "entities": [
                {
                    "kind": "Product",
                    "anchor": "Mật ong hoa nhãn",
                    "attributes": {
                        "packaging": "chai thủy tinh",
                        "brand": "Không có trong nguồn",
                        "points": "5",
                        "origin_area": 7,
                    },
                },
                {
                    "kind": "Organization",
                    "anchor": "HTX Ong Mật Bình Minh",
                    "attributes": {"organization_form": "HTX"},
                },
                {"kind": "Product", "anchor": "Mật ong rừng"},  # hallucinated: not in source
                {"kind": "StarLevel", "anchor": "Sản phẩm"},  # kind not permitted
            ],
            "relations": [
                {
                    "type": "OWNED_BY",
                    "source_anchor": "Mật ong hoa nhãn",
                    "target_anchor": "HTX Ong Mật Bình Minh",
                    "proof": "Mật ong hoa nhãn do HTX Ong Mật Bình Minh sản xuất",
                },
                {
                    "type": "OWNED_BY",
                    "source_anchor": "Mật ong hoa nhãn",
                    "target_anchor": "HTX Ong Mật Bình Minh",
                    "proof": "Chủ thể: HTX Ong Mật Bình Minh",
                },  # model proof ignored: span is recomputed; same relation
                {"type": "MINIMUM_FOR", "source_anchor": "x", "target_anchor": "y", "proof": "Sản phẩm"},
            ],
            "rules": [{"kind": "obligation", "anchor": "không có câu này"}],
        }
    )
    out = propose([UNIT], llm, max_units=5)
    ents = {e["label"]: e for e in out["entities"]}
    assert set(ents) == {"Mật ong hoa nhãn", "HTX Ong Mật Bình Minh"}
    product = ents["Mật ong hoa nhãn"]
    assert product["attributes"] == {"packaging_candidate": "chai thủy tinh"}
    assert product["status"] == "candidate" and product["extraction_method"] == "llm_candidate:fake"
    ref = product["evidence"][0]
    assert ref["pdf_page"] == 3 and ref["source_sha256"] == SHA and ref["quote"] == "Mật ong hoa nhãn"
    assert [r["relation_type"] for r in out["relations"]] == ["OWNED_BY"]
    assert out["rules"] == []
    assert out["grounding"] == {
        "dropped_entities": 2,
        "dropped_attributes": 3,
        "dropped_relations": 1,
        "dropped_rules": 1,
    }


def test_anchor_spanning_two_pages_is_not_assigned_a_guessed_page():
    unit = _unit(["Phiếu kiểm nghiệm", "Phiếu kiểm nghiệm"], pages=[4, 5])
    out = propose([unit], FakeLLM({"entities": [{"kind": "EvidenceType", "anchor": "Phiếu kiểm nghiệm"}]}))
    assert out["entities"] == [] and out["grounding"]["dropped_entities"] == 1


def test_same_label_merges_evidence_and_flags_conflicting_features():
    a = _unit(["Hồ sơ: Phiếu kiểm nghiệm do Sở cấp"], uid="unit:a")
    b = _unit(["Phiếu kiểm nghiệm do Bộ cấp"], uid="unit:b")

    def response(text):
        issuer = "Sở" if "Sở" in text else "Bộ"
        return {
            "entities": [
                {"kind": "EvidenceType", "anchor": "Phiếu kiểm nghiệm", "attributes": {"issuer": issuer}}
            ]
        }

    out = propose([a, b], FakeLLM(response))
    assert len(out["entities"]) == 1
    entity = out["entities"][0]
    assert {e["evidence_unit_id"] for e in entity["evidence"]} == {"unit:a", "unit:b"}
    assert entity["attributes"] == {"issuer_candidate": None, "issuer_conflict": True}


def test_long_units_are_chunked_not_truncated(monkeypatch):
    monkeypatch.setattr(llm_proposals, "CHUNK_CHARS", 60)
    monkeypatch.setattr(llm_proposals, "CHUNK_OVERLAP", 10)
    lines = [f"Dòng đệm số {i} không có thực thể" for i in range(6)] + ["Chủ thể: HTX Cuối Văn Bản"]
    llm = FakeLLM(
        lambda text: {"entities": [{"kind": "Organization", "anchor": "HTX Cuối Văn Bản"}]}
        if "HTX Cuối Văn Bản" in text
        else {"entities": []}
    )
    out = propose([_unit(lines)], llm)
    assert out["chunk_count"] > 1 and [e["label"] for e in out["entities"]] == ["HTX Cuối Văn Bản"]


def test_cache_makes_reruns_reproducible_without_calls(tmp_path):
    first = FakeLLM({"entities": [{"kind": "Organization", "anchor": "HTX Ong Mật Bình Minh"}]})
    out1 = propose([UNIT], first, cache_dir=tmp_path)
    second = FakeLLM({"entities": []})
    out2 = propose([UNIT], second, cache_dir=tmp_path, max_workers=4)
    assert second.calls == 0 and out1["entities"] == out2["entities"]


def test_invalid_json_is_recorded_as_error_not_raised():
    class Broken(FakeLLM):
        def chat(self, *a, **k):
            return "not json"

    out = propose([UNIT], Broken(None))
    assert out["entities"] == [] and out["errors"] == [
        {"evidence_unit_id": "unit:1", "error_type": "JSONDecodeError"}
    ]
    assert out["processed_unit_count"] == 0


def test_context_gate_rejects_wrong_kinds():
    unit = _unit(
        [
            "Đăng ký đánh giá, phân hạng lại",
            "UBND phường tiếp nhận hồ sơ của HTX Ong Mật Bình Minh",
            "Các chủ thể tham gia",
        ]
    )
    llm = FakeLLM(
        {
            "entities": [
                {
                    "kind": "Criterion",
                    "anchor": "Đăng ký đánh giá, phân hạng lại",
                },  # scoring kind outside a table
                {"kind": "Organization", "anchor": "UBND phường"},  # state agency
                {"kind": "Organization", "anchor": "Các chủ thể"},  # generic group
                {"kind": "Organization", "anchor": "HTX Ong Mật Bình Minh"},
            ]
        }
    )
    out = propose([unit], llm)
    assert [e["label"] for e in out["entities"]] == ["HTX Ong Mật Bình Minh"]
    table = dict(unit, unit_id="unit:t", unit_kind="table")
    out = propose(
        [table], FakeLLM({"entities": [{"kind": "Criterion", "anchor": "Đăng ký đánh giá, phân hạng lại"}]})
    )
    assert [e["kind"] for e in out["entities"]] == ["Criterion"]


def test_whitespace_tolerant_alignment_keeps_source_text_verbatim():
    unit = _unit(["Hợp tác xã sản", "xuất Thụy Hương"])
    out = propose(
        [unit], FakeLLM({"entities": [{"kind": "Organization", "anchor": "Hợp tác xã sản xuất Thụy Hương"}]})
    )
    entity = out["entities"][0]
    assert entity["label"] == "Hợp tác xã sản xuất Thụy Hương"
    assert entity["evidence"][0]["quote"] == "Hợp tác xã sản\nxuất Thụy Hương"
    # Characters are never fuzzed: an OCR spelling difference is not aligned.
    out = propose(
        [unit], FakeLLM({"entities": [{"kind": "Organization", "anchor": "Hợp tác xã sản xuất Thuỵ Hương"}]})
    )
    assert out["entities"] == []


def test_case_variants_merge_into_one_entity():
    unit = _unit(["Công bố chất lượng sản phẩm", "kèm công bố chất lượng"])
    out = propose(
        [unit],
        FakeLLM(
            {
                "entities": [
                    {"kind": "EvidenceType", "anchor": "Công bố chất lượng"},
                    {"kind": "EvidenceType", "anchor": "công bố chất lượng"},
                ]
            }
        ),
    )
    assert len(out["entities"]) == 1


def test_gleaning_pass_adds_missed_items_and_is_cached(tmp_path):
    def response(prompt):
        if "PREVIOUS EXTRACTION" in prompt:
            return {
                "entities": [{"kind": "Organization", "anchor": "HTX Ong Mật Bình Minh"}],
                "relations": [],
                "rules": [],
            }
        return {"entities": [{"kind": "Product", "anchor": "Mật ong hoa nhãn"}], "relations": [], "rules": []}

    llm = FakeLLM(response)
    out = propose([UNIT], llm, gleanings=1, cache_dir=tmp_path)
    assert {e["kind"] for e in out["entities"]} == {"Product", "Organization"} and llm.calls == 2
    again = FakeLLM({"entities": []})
    assert propose([UNIT], again, gleanings=1, cache_dir=tmp_path)["entities"] == out["entities"]
    assert again.calls == 0


def test_reconcile_folds_llm_entities_into_deterministic_ones():
    from ai_core.knowledge.ocop.llm_proposals import reconcile

    llm = FakeLLM(
        {
            "entities": [
                {
                    "kind": "Product",
                    "anchor": "Mật ong hoa nhãn",
                    "attributes": {"packaging": "chai thủy tinh"},
                },
                {"kind": "Organization", "anchor": "HTX Ong Mật Bình Minh"},
            ],
            "relations": [
                {
                    "type": "OWNED_BY",
                    "source_anchor": "Mật ong hoa nhãn",
                    "target_anchor": "HTX Ong Mật Bình Minh",
                    "proof": "Mật ong hoa nhãn do HTX Ong Mật Bình Minh sản xuất",
                }
            ],
        }
    )
    proposed = propose([UNIT], llm)
    det = [
        {
            "entity_id": "det:product",
            "kind": "Product",
            "label": "mật ong  hoa nhãn",
            "source_id": "VN.TEST.DOC",
            "attributes": {},
            "evidence": proposed["entities"][0]["evidence"][:],
        },
        {
            "entity_id": "det:org",
            "kind": "Organization",
            "label": "HTX Ong Mật Bình Minh",
            "source_id": "VN.TEST.DOC",
            "attributes": {},
            "evidence": proposed["entities"][1]["evidence"][:],
        },
    ]
    rels = [{"relation_type": "OWNED_BY", "source_entity_id": "det:product", "target_entity_id": "det:org"}]
    out = reconcile(proposed, det, rels)
    assert out["entities"] == [] and out["relations"] == []
    assert det[0]["attributes"] == {
        "packaging_candidate": "chai thủy tinh",
        "llm_enriched_attributes": "packaging_candidate",
    }
    assert out["reconciled"] == {
        "merged_entities": 2,
        "enriched_attributes": 1,
        "duplicate_relations": 1,
        "ungrounded_after_merge": 0,
        "unanchored_scoring_entities": 0,
        "kind_conflicts": 0,
    }
    assert det[0]["evidence"][0]["evidence_unit_id"] == "unit:1"


def test_reconcile_anchors_criteria_by_code_stripped_label_and_page():
    from ai_core.knowledge.ocop.llm_proposals import reconcile

    table = dict(
        _unit(["1.3. Gia tăng giá trị", "(có hợp đồng liên kết)", "Bao bì sản phẩm"]), unit_kind="table"
    )
    llm = FakeLLM(
        {
            "entities": [
                {"kind": "Criterion", "anchor": "Gia tăng giá trị", "attributes": {"code": "1.3"}},
                {"kind": "Condition", "anchor": "(có hợp đồng liên kết)"},
                {"kind": "Criterion", "anchor": "Bao bì sản phẩm"},  # no deterministic match
                {"kind": "Condition", "anchor": "Bao bì sản phẩm"},
            ],
            "relations": [
                {
                    "type": "HAS_CONDITION",
                    "source_anchor": "Gia tăng giá trị",
                    "target_anchor": "(có hợp đồng liên kết)",
                    "proof": "Gia tăng giá trị\n(có hợp đồng liên kết)",
                }
            ],
        }
    )
    proposed = propose([table], llm)
    ev = {"evidence_unit_id": "unit:1", "pdf_page": 3}
    det = [
        {
            "entity_id": "det:c13",
            "kind": "Criterion",
            "label": "1.3. Gia tăng giá trị",
            "source_id": "VN.TEST.DOC",
            "attributes": {"level": 2},
            "evidence": [ev],
        },
        {
            "entity_id": "det:c13-other-sheet",
            "kind": "Criterion",
            "label": "1.3. Gia tăng giá trị",
            "source_id": "VN.TEST.DOC",
            "attributes": {"level": 2},
            "evidence": [{"evidence_unit_id": "u9", "pdf_page": 28}],
        },
    ]
    out = reconcile(proposed, det, [])
    assert [e["kind"] for e in out["entities"]] == ["Condition"]
    assert [(r["relation_type"], r["source_entity_id"]) for r in out["relations"]] == [
        ("HAS_CONDITION", "det:c13")
    ]
    assert det[0]["attributes"] == {"level": 2}  # scoring tree untouched
    assert out["reconciled"]["unanchored_scoring_entities"] == 2  # unmatched Criterion + orphan Condition


def test_scoring_rows_repeated_on_two_sheets_stay_separate():
    a = dict(_unit(["1.3. Gia tăng giá trị"], uid="unit:sheet1"), unit_kind="table")
    b = dict(_unit(["1.3. Gia tăng giá trị"], pages=[28], uid="unit:sheet3"), unit_kind="table")
    out = propose([a, b], FakeLLM({"entities": [{"kind": "Criterion", "anchor": "Gia tăng giá trị"}]}))
    assert sorted(e["evidence"][0]["evidence_unit_id"] for e in out["entities"]) == [
        "unit:sheet1",
        "unit:sheet3",
    ]


def test_llm_group_colliding_with_criterion_sheet_is_dropped_and_no_subgroup_edges():
    from ai_core.knowledge.ocop.llm_proposals import ALLOWED_TRIPLES, reconcile

    assert "HAS_SUBGROUP" not in ALLOWED_TRIPLES
    unit = dict(_unit(["14 | Bộ sản phẩm: Rượu trắng"]), unit_kind="table")
    proposed = propose([unit], FakeLLM({"entities": [{"kind": "ProductGroup", "anchor": "Rượu trắng"}]}))
    det = [
        {
            "entity_id": "det:sheet14",
            "kind": "CriterionSheet",
            "label": "Bộ sản phẩm: Rượu trắng",
            "source_id": "VN.TEST.DOC",
            "attributes": {},
            "evidence": [{"evidence_unit_id": "unit:1", "pdf_page": 3}],
        }
    ]
    out = reconcile(proposed, det, [])
    assert out["entities"] == [] and out["reconciled"]["kind_conflicts"] == 1


def test_index_relations_get_a_computed_verbatim_proof():
    llm = FakeLLM(
        {
            "entities": [
                {"kind": "Product", "anchor": "Mật ong hoa nhãn"},
                {"kind": "Organization", "anchor": "HTX Ong Mật Bình Minh"},
            ],
            "relations": [
                {"type": "OWNED_BY", "source": 0, "target": 1},
                {"type": "OWNED_BY", "source": 1, "target": 0},  # wrong direction/kinds
                {"type": "OWNED_BY", "source": 0, "target": 9},
            ],
        }
    )  # bad index
    out = propose([UNIT], llm)
    assert len(out["relations"]) == 1
    quote = out["relations"][0]["evidence"][0]["quote"]
    assert quote in UNIT["text"] and "Mật ong hoa nhãn" in quote and "HTX Ong Mật Bình Minh" in quote
    assert len(quote) < len(UNIT["text"])  # shortest covering span, not the whole unit
    assert out["grounding"]["dropped_relations"] == 2


def test_condition_that_restates_an_answer_option_is_dropped():
    from ai_core.knowledge.ocop.llm_proposals import reconcile

    table = dict(
        _unit(["1.2. Vùng nguyên liệu", "Không được cấp giấy chứng nhận chất lượng"]), unit_kind="table"
    )
    proposed = propose(
        [table],
        FakeLLM({"entities": [{"kind": "Condition", "anchor": "Không được cấp giấy chứng nhận chất lượng"}]}),
    )
    det = [
        {
            "entity_id": "det:o",
            "kind": "ScoreOption",
            "label": "Không được cấp giấy chứng nhận chất lượng",
            "source_id": "VN.TEST.DOC",
            "attributes": {},
            "evidence": [{"evidence_unit_id": "unit:1", "pdf_page": 3}],
        }
    ]
    out = reconcile(proposed, det, [])
    assert out["entities"] == [] and out["reconciled"]["kind_conflicts"] == 1


def test_graph_keeps_llm_provenance_only_for_llm_rows():
    from ai_core.graph.ocop.builder import _with_provenance

    assert _with_provenance(
        {"attributes": {"a": 1}, "extraction_method": "deterministic_from_structure"}
    ) == {"a": 1}
    assert _with_provenance({"attributes": {}, "extraction_method": "llm_candidate:gpt-6-sol"}) == {
        "extraction_method": "llm_candidate:gpt-6-sol"
    }


def test_answer_client_defaults_to_the_openai_compatible_api(monkeypatch):
    from ai_core.orchestration.ocop.llm import make_answer_client

    for key in ("OCOP_ANSWER_LLM_PROVIDER", "OCOP_ANSWER_LLM_MODEL", "OCOP_EXTRACT_LLM_MODEL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OCOP_EXTRACT_OPENAI_API_KEY", "k")
    client = make_answer_client()
    assert isinstance(client, OpenAICompatClient) and client.model == "gpt-6-sol"


def test_answer_client_reuses_the_extraction_api_when_openai(monkeypatch):
    from ai_core.orchestration.ocop.llm import make_answer_client

    monkeypatch.setenv("OCOP_ANSWER_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OCOP_EXTRACT_OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OCOP_EXTRACT_OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OCOP_EXTRACT_LLM_MODEL", "m-extract")
    for key in ("OCOP_ANSWER_LLM_MODEL", "OCOP_ANSWER_OPENAI_BASE_URL", "OCOP_ANSWER_OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    client = make_answer_client()
    assert isinstance(client, OpenAICompatClient)
    assert client.model == "m-extract" and client.url == "https://example.invalid/v1"


def test_openai_length_finish_is_reported_as_truncation(monkeypatch):
    from ai_core.orchestration.ocop.llm import ModelOutputTruncated

    payload = {"choices": [{"finish_reason": "length", "message": {"content": "nửa câu"}}]}
    monkeypatch.setattr(
        llm_mod.urllib.request, "urlopen", lambda req, timeout: io.BytesIO(json.dumps(payload).encode())
    )
    client = OpenAICompatClient(model="m", base_url="https://example.invalid/v1", api_key="k", retries=0)
    with pytest.raises(ModelOutputTruncated):
        client.chat("s", "u")


def test_refused_connection_fails_fast_without_backoff(monkeypatch):
    import urllib.error

    from ai_core.orchestration.ocop import llm

    calls = []

    def refuse(*args, **kwargs):
        calls.append(1)
        raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))

    monkeypatch.setattr(llm.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(llm.time, "sleep", lambda s: calls.append(("sleep", s)))
    client = llm.OpenAICompatClient(model="m", base_url="http://127.0.0.1:9/v1", api_key="k")
    try:
        client.chat("s", "u")
    except RuntimeError as exc:
        assert "unavailable" in str(exc)
    assert calls == [1]  # one attempt, no sleep
