"""Production gates for source-backed claims, evidence grading and eval harness."""

from __future__ import annotations
import json
import pytest
from ai_core.orchestration.ocop.verification import verify_claims
from ai_core.orchestration.ocop.evidence_grader import grade_evidence, bounded_rewrite
from ai_core.evaluation.ocop.harness import load_cases, evaluate_retrieval, release_gate


def _fact(text="Hạt sen của HTX Sen Huế được công nhận 3 sao.", review_status="verified"):
    return {
        "source_id": "VN.HUE.QD797.2026",
        "evidence_unit_id": "u1",
        "text": text,
        "source_spans": [{"pdf_page": 2}],
        "review_status": review_status,
    }


def _cite():
    return [{"source_id": "VN.HUE.QD797.2026", "evidence_unit_id": "u1", "pdf_page": 2}]


def test_claim_verification_rejects_valid_marker_with_wrong_star():
    found = verify_claims("Hạt sen được công nhận 5 sao [S1].", _cite(), [_fact()])
    assert found["status"] == "unsupported"
    assert found["unsupported_critical"]
    assert any("numbers" in x["reason"] for x in found["claims"])


def test_claim_verification_never_promotes_unreviewed_ocr():
    found = verify_claims(
        "Hạt sen của HTX Sen Huế được công nhận 3 sao [S1].", _cite(), [_fact(review_status="needs_review")]
    )
    assert found["status"] == "not_verified"


def test_claim_missing_reference_fails_even_if_source_is_present():
    found = verify_claims("Hạt sen đã được công nhận 3 sao.", _cite(), [_fact()])
    assert found["status"] == "unsupported"


def test_exact_verified_quote_is_supported():
    found = verify_claims("Hạt sen của HTX Sen Huế được công nhận 3 sao [S1].", _cite(), [_fact()])
    assert found["status"] == "verified"
    assert found["supported"] == 1


def test_paraphrase_without_semantic_verifier_is_not_mislabeled_supported():
    found = verify_claims("HTX Sen Huế có sản phẩm hạt sen đạt hạng ba sao [S1].", _cite(), [_fact()])
    assert found["status"] == "not_verified"


def test_evidence_grader_reports_missing_structured_capabilities_and_ignores_bad_page():
    report = grade_evidence(
        "Mật ong có đủ minh chứng không?",
        [
            {
                "tool": "lookup_criterion",
                "output": {"results": [{"source_id": "D", "spans": [{"pdf_page": 0}], "text": "mật ong"}]},
            },
            {"tool": "lookup_evidence_requirements", "output": {"status": "unknown", "results": []}},
        ],
        expected_tools=["lookup_criterion", "lookup_evidence_requirements"],
    )
    assert report["status"] == "none"
    assert "lookup_evidence_requirements" in report["missing_tools"]


def test_bounded_rewrite_preserves_date_and_document_code():
    q = "Điều 6 QĐ26/2026 áp dụng cho hồ sơ 2025?"
    out = bounded_rewrite(q, ["resolve_temporal_applicability"], {})
    assert out.startswith(q)
    assert "2025" in out and "2026" in out
    with pytest.raises(ValueError):
        bounded_rewrite(q, ["shell_exec"], {})


def test_harness_skips_pending_and_prevents_duplicate_labels(tmp_path):
    data = tmp_path / "case.jsonl"
    data.write_text(
        "\n".join(
            [
                json.dumps(
                    {"case_id": "a", "query": "q", "source_id": "s", "label_status": "pdf_page_confirmed"}
                ),
                json.dumps({"case_id": "pending", "query": "q", "label_status": "needs_manual_annotation"}),
            ]
        ),
        encoding="utf8",
    )
    assert len(load_cases(data)) == 1
    assert len(load_cases(data, only_approved=False)) == 2
    data.write_text(
        "\n".join([json.dumps({"case_id": "a", "query": "q", "label_status": "pdf_page_confirmed"})] * 2),
        encoding="utf8",
    )
    with pytest.raises(ValueError, match="Duplicate"):
        load_cases(data)


def test_harness_metric_is_measured_not_invented(tmp_path):
    root = tmp_path
    idx = root / "data/processed/ocop/index"
    idx.mkdir(parents=True)
    (idx / "manifest.json").write_text(json.dumps({"corpus_version": "r1", "dense": {"enabled": False}}))
    data = root / "gold.jsonl"
    data.write_text(
        json.dumps(
            {
                "case_id": "a",
                "query": "q",
                "source_id": "D",
                "pdf_page": 2,
                "label_status": "pdf_page_confirmed",
            }
        )
        + "\n"
    )

    def fake_search(index, query, *, mode, top_k):
        return [{"source_id": "WRONG", "pdf_page": 2}, {"source_id": "D", "pdf_page": 2}]

    report = evaluate_retrieval(root, data, modes=("sparse", "hybrid"), runner=fake_search)
    assert report["results"]["sparse"]["mrr_at_10"] == 0.5
    assert report["results"]["hybrid"]["status"] == "not_run_missing_dense_index"
    assert release_gate(report)["status"] == "blocked"


def test_release_gate_blocks_recall_drop_and_forbidden_tool():
    baseline = {"results": {"sparse": {"evaluated": 10, "recall_at_10": 0.9}}}
    candidate = {
        "results": {"sparse": {"status": "completed", "evaluated": 10, "recall_at_10": 0.75}},
        "trajectory": {"forbidden_calls": 1},
    }
    gate = release_gate(candidate, baseline=baseline)
    assert gate["status"] == "blocked"
    assert any("recall_regression" in x for x in gate["failures"])
    assert "forbidden_tool_calls" in gate["failures"]


def test_event_year_is_not_derived_from_issue_date():
    from ai_core.graph.ocop.temporal import resolve_event_applicability
    from datetime import date

    rule = {
        "review_status": "verified",
        "effective_from": "2026-01-01",
        "recognition_issued_at": "2026-03-04",
        "recognition_event_year": 2025,
        "assessment_year": 2025,
        "corpus_version": "v",
    }
    result = resolve_event_applicability(
        rule, as_of_date=date(2026, 3, 4), event_year=2025, corpus_version="v"
    )
    assert result["status"] == "applicable"
    newer = resolve_event_applicability(
        rule, as_of_date=date(2026, 3, 4), event_year=2026, corpus_version="v"
    )
    assert newer["status"] == "not_applicable"
    missing = resolve_event_applicability(
        {k: v for k, v in rule.items() if k != "assessment_year"},
        as_of_date=date(2026, 3, 4),
        event_year=2025,
        corpus_version="v",
    )
    assert missing["status"] == "unknown"


def test_checkpoint_scoped_and_opt_in():
    from ai_core.system.checkpoints import thread_key, should_checkpoint

    assert thread_key("A", "p", "s") != thread_key("B", "p", "s")
    assert not should_checkpoint(
        env={"OCOP_LANGGRAPH_CHECKPOINT_ENABLED": "1"},
        auth=None,
        session={"session_id": "s"},
        private_tools=set(),
    )
    assert not should_checkpoint(
        env={"OCOP_LANGGRAPH_CHECKPOINT_ENABLED": "1"},
        auth=object(),
        session={"session_id": "s"},
        private_tools={"review_dossier"},
    )


def test_production_gate_requires_expert_gold_and_real_integrations():
    from ai_core.evaluation.ocop.harness import release_gate

    run = {"expert_verified_cases": 0, "results": {"sparse": {"status": "completed", "evaluated": 10}}}
    blocked = release_gate(run)
    assert blocked["status"] == "blocked"
    assert "no_domain_expert_gold_labels" in blocked["failures"]
    assert any("dense:integration_not_measured" in x for x in blocked["failures"])


def test_fault_injection_never_claims_success_for_failed_retrieval(tmp_path):
    from ai_core.evaluation.ocop.faults import evaluate_faults

    report = evaluate_faults(tmp_path)
    assert report["scenarios"] == 5
    assert report["safe_count"] == 5
    assert all(x["status"] != "generated_claims_verified" for x in report["cases"])


def test_release_admission_denies_missing_manifest(tmp_path):
    from ai_core.evaluation.ocop.release import validate_latest

    result = validate_latest(tmp_path, corpus_version="v1")
    assert result["status"] == "blocked"
    assert "no_evaluation_run_manifest" in result["failures"]
