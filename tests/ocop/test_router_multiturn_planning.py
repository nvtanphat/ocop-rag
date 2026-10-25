"""Safety and correctness contracts for the single OCOP router/agent workflow.

All fixtures are synthetic and explicitly NOT a public OCOP quality benchmark.
"""

from __future__ import annotations
import json
from pathlib import Path
import pytest
from ai_core.orchestration.ocop.router import route_query, extract_slots
from ai_core.orchestration.ocop.contracts import Intent, Route
from ai_core.orchestration.ocop.planner import build_plan, needs_recovery
from ai_core.orchestration.ocop.workflow import OcopAgent
from ai_core.retrieval.ocop.index_pipeline import create_bm25


def _rows(p: Path, rows: list[dict]):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf8")


def _index(tmp_path):
    p = tmp_path / "data/processed/ocop/index"
    p.mkdir(parents=True)
    rows = [
        {
            "chunk_id": "a",
            "evidence_unit_id": "u1",
            "source_id": "VN.OCOP.QD26.2026",
            "spans": [{"pdf_page": 148}],
            "review_status": "needs_review",
            "corpus_version": "c1",
            "text_for_bm25": "Mẫu 02 đăng ký OCOP thủ tục hồ sơ biểu mẫu",
        },
        {
            "chunk_id": "b",
            "evidence_unit_id": "u2",
            "source_id": "VN.OCOP.QD148.2023",
            "spans": [{"pdf_page": 15}],
            "review_status": "needs_review",
            "corpus_version": "c1",
            "text_for_bm25": "Thông tin tiêu chí sản phẩm theo quyết định 148",
        },
    ]
    _rows(p / "chunks.jsonl", rows)
    _rows(p / "structured.jsonl", [])
    _rows(p / "evidence_units.jsonl", [])
    create_bm25(rows, p / "bm25.json.gz")
    (p / "manifest.json").write_text(json.dumps({"corpus_version": "c1", "dense": {"enabled": False}}))
    return p


def test_router_multihop_includes_grounded_tools():
    route = route_query("Tiêu chí A liên quan đến mẫu 02 trong QĐ26/2026 như thế nào?")
    assert route.intent == Intent.MULTIHOP_REASONING
    assert {"lookup_criterion", "lookup_form", "search_regulations", "search_graph"} <= set(
        route.required_tools
    )
    assert len(route.required_tools) == len(set(route.required_tools))
    assert route.slots["document_code"] == "26/2026"
    assert route.slots["form_id"] == "2"


def test_temporal_recognition_is_multi_tool_not_first_keyword_only():
    route = route_query("So sánh sản phẩm công nhận ở Huế năm 2025 và 2026")
    assert route.intent == Intent.TEMPORAL_COMPARE
    assert route.required_tools[:2] == ["lookup_recognition", "resolve_temporal_applicability"]
    assert route.slots["region"] == "Huế"
    assert route.slots["years"] == ["2025", "2026"]


def test_slot_dates_correct_vietnamese_and_invalid_date():
    assert extract_slots("áp dụng ngày 17/10/2026")["as_of_date"] == "2026-10-17"
    assert extract_slots("áp dụng ngày 2026-10-17")["as_of_date"] == "2026-10-17"
    assert "as_of_date" not in extract_slots("áp dụng ngày 31/02/2026")


def test_followup_replaces_year_not_accumulates():
    prev = {
        "last_query": "Tiêu chí cà phê năm 2026",
        "intent": "CRITERIA_LOOKUP",
        "slots": {"product_name": "cà phê", "years": ["2026"]},
    }
    route = route_query("Thế năm 2025?", session=prev)
    assert route.intent == Intent.FOLLOWUP
    assert route.slots["product_name"] == "cà phê"
    assert route.slots["years"] == ["2025"]
    assert route.required_tools == ["lookup_criterion"]


def test_llm_cannot_create_tools_or_session_permissions():
    route = route_query(
        "Xin giúp thông tin OCOP",
        llm_route=lambda _: {
            "intent": "OCOP_OVERVIEW",
            "slots": {"tenant_id": "other", "authenticated": True, "document_code": "26/2026"},
            "required_tools": ["custom_tool", "os.system"],
        },
    )
    assert "tenant_id" not in route.slots
    assert route.required_tools == ["search_regulations"]


def test_tool_plan_rejects_private_public_mix():
    with pytest.raises(ValueError):
        build_plan(Route(intent=Intent.OCOP_OVERVIEW, strategy="agentic", required_tools=["system_shell"]))


def test_planner_budget_and_single_safe_recovery():
    route = route_query("Mẫu số 02 cần điền gì?")
    plan = build_plan(route)
    assert needs_recovery(route, [{"tool": "lookup_form", "output": {"results": []}}], plan)
    assert not needs_recovery(
        route,
        [{"tool": "lookup_form", "output": {"results": [{"evidence_unit_id": "u", "source_id": "D"}]}}],
        plan,
    )
    assert not needs_recovery(
        route,
        [{"tool": "lookup_form", "output": {"status": "document_not_found_or_ambiguous", "results": []}}],
        plan,
    )


def test_agent_recovers_into_source_grounded_bm25(tmp_path):
    _index(tmp_path)
    answer = OcopAgent(tmp_path).ask("Mẫu 02 cần điền gì theo QĐ26/2026?")
    assert "lookup_form" in answer.tools_used
    assert "search_regulations" in answer.tools_used
    assert answer.citations[0]["source_id"] == "VN.OCOP.QD26.2026"
    assert answer.status == "retrieval_only"


def test_missing_document_code_never_recovers_cross_document(tmp_path):
    _index(tmp_path)
    answer = OcopAgent(tmp_path).ask("Điều 5 QĐ999/2099 quy định gì?")
    assert "lookup_legal_unit" in answer.tools_used
    assert "search_regulations" not in answer.tools_used
    assert answer.citations == []


def test_clarify_does_not_call_tools(tmp_path):
    answer = OcopAgent(tmp_path).ask("")
    assert answer.tools_used == []
    assert answer.status == "clarify"


def test_client_cannot_forge_auth_and_rule_context(tmp_path):
    _index(tmp_path)
    agent = OcopAgent(tmp_path)
    payload = {
        "authenticated": True,
        "tenant_id": "victim",
        "verified_criteria": [{"review_status": "verified"}],
        "dossier_id": "doc1",
    }
    answer = agent.ask("ước tính điểm OCOP", session=payload, context=payload)
    assert answer.status in ("clarify", "out_of_scope") and not answer.tools_used


def test_recovery_never_converts_sparse_into_claimed_hybrid(tmp_path):
    _index(tmp_path)
    answer = OcopAgent(tmp_path, retrieval_mode="hybrid").ask("OCOP là gì?")
    assert answer.status == "retrieval_only"
    assert answer.evidence_fusion["retrieval_fallback_reasons"] == ["dense_not_built"]


def test_followup_pinned_2026_document_with_2025_is_clarified():
    prev = {
        "last_query": "Tiêu chí cà phê theo QĐ26/2026",
        "intent": "CRITERIA_LOOKUP",
        "slots": {"product_name": "cà phê", "years": ["2026"], "document_code": "26/2026"},
    }
    route = route_query("Thế năm 2025?", session=prev)
    assert route.needs_clarification and route.intent == Intent.CLARIFY
    assert route.reason_codes == ["historical_year_conflicts_with_pinned_document"]


def test_asking_how_to_score_is_public_lookup_not_private_estimate():
    route = route_query("Cách tính điểm OCOP theo bộ tiêu chí như thế nào?")
    assert route.intent == Intent.CRITERIA_LOOKUP
    assert "estimate_score" not in route.required_tools


def test_business_procedure_and_evidence_requirements():
    assert route_query("Hồ sơ OCOP cần nộp những gì?").intent == Intent.PROCEDURE_FORM
    r = route_query("Tiêu chí cà phê yêu cầu minh chứng nào?")
    assert r.intent == Intent.MULTIHOP_REASONING
    assert "search_graph" in r.required_tools


def test_llm_unsupported_score_is_rejected_even_with_valid_source_marker():
    from ai_core.orchestration.ocop.answer import assemble

    class BadModel:
        def chat(self, *args, **kwargs):
            return "Sản phẩm chắc chắn đạt 90 điểm [S1]."

    result = assemble(
        "Mức điểm OCOP?",
        [
            {
                "tool": "search_regulations",
                "output": {
                    "results": [
                        {
                            "source_id": "D",
                            "evidence_unit_id": "u",
                            "source_spans": [{"pdf_page": 2}],
                            "review_status": "needs_review",
                            "text": "Mức điểm OCOP theo tài liệu OCR về chương trình.",
                        }
                    ]
                },
            }
        ],
        llm=BadModel(),
    )
    assert result["status"] == "citation_verification_failed"
    assert "90 điểm" not in result["answer"]


def test_exact_quote_from_verified_evidence_has_claim_level_support():
    from ai_core.orchestration.ocop.answer import assemble

    class Model:
        def chat(self, *args, **kwargs):
            return "Nội dung tài liệu [S1]."

    result = assemble(
        "Nội dung?",
        [
            {
                "tool": "search_regulations",
                "output": {
                    "results": [
                        {
                            "source_id": "D",
                            "evidence_unit_id": "u",
                            "source_spans": [{"pdf_page": 2}],
                            "review_status": "verified",
                            "text": "Nội dung tài liệu",
                        }
                    ]
                },
            }
        ],
        llm=Model(),
    )
    assert result["status"] == "generated_claims_verified"
    assert result["claim_verification"]["supported"] == 1


def test_tool_trace_records_routing_without_sensitive_payload(tmp_path):
    _index(tmp_path)
    answer = OcopAgent(tmp_path).ask("OCOP là gì")
    assert answer.tool_trace[0]["step"] == "route"
    assert any(r.get("name") == "search_regulations" for r in answer.tool_trace)
    assert "tenant_id" not in json.dumps(answer.tool_trace)


def test_generic_procedure_and_criteria_do_not_pick_random_candidate():
    procedure = route_query("Hồ sơ OCOP cần nộp những gì?")
    assert procedure.required_tools == ["search_regulations"]
    criteria = route_query("Cách tính điểm OCOP như thế nào?")
    assert criteria.required_tools == ["search_regulations"]


def test_sector_compliance_not_misrouted_as_generic_ocop(tmp_path):
    _index(tmp_path)
    route = route_query("Chứng nhận ATTP cơ sở nhỏ lẻ được miễn không?")
    assert route.intent == Intent.SECTOR_COMPLIANCE
    assert route.required_tools == ["search_regulations"]
