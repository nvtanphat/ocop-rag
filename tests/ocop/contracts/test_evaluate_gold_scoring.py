"""Page-level scoring of the gold-set harness, checked on hand-made rows (no agent run)."""

from tools.evaluate_gold import score_question, totals

DOC = "VN.OCOP.QD26.2026"


def _row(pages, cited=None, claims=None):
    return {"ok": True, "pages": pages, "cited_pages": cited or [], "claims": claims, "s": 1.0}


def test_retrieval_counts_rank_and_takes_an_alternative_page_as_complete():
    q = {"gold_evidence": [{"source_id": DOC, "pdf_page": 4}], "alternative_evidence": [{"source_id": DOC, "pdf_page": 5}]}
    second = score_question("retrieval", q, _row([[DOC, 9], [DOC, 4]]))
    alternative = score_question("retrieval", q, _row([[DOC, 5]]))
    assert second == {"any": True, "all": True, "top1": False, "rank": 2}
    assert alternative["all"] and alternative["top1"]
    result = totals("retrieval", [second, alternative, score_question("retrieval", q, _row([[DOC, 1]]))])
    assert (result["any"], result["top1"], result["mrr"]) == (2, 1, 0.5)


def test_a_session_turn_without_gold_pages_is_not_scored():
    verdicts = [score_question("session", {"gold_evidence": []}, _row([])),
                score_question("session", {"gold_evidence": [{"source_id": DOC, "pdf_page": 2}]}, _row([[DOC, 2]]))]
    assert totals("session", verdicts)["scored"] == 1 and totals("session", verdicts)["any"] == 1


def test_a_multihop_step_is_met_by_the_page_of_any_of_its_units():
    q = {
        "gold_evidence": [{"source_id": DOC, "pdf_page": 2, "evidence_unit_id": "u1"},
                          {"source_id": DOC, "pdf_page": 33, "evidence_unit_id": "u2"}],
        "reasoning_steps": [{"evidence_unit_ids": ["u1"]}, {"evidence_unit_ids": ["u2"]}],
    }
    assert score_question("multihop", q, _row([[DOC, 33]])) == {"steps": 1, "of": 2, "full": False}


def test_an_answer_without_a_citation_marker_counts_as_a_refusal():
    q = {"expected_behavior": "ABSTAIN"}
    refused = score_question("abstention", q, _row([[DOC, 1]]))
    answered = score_question("abstention", q, _row([[DOC, 1]], cited=[[DOC, 1]]))
    t = totals("abstention", [refused, answered])
    assert (t["correct_rejections"], t["false_answers"], t["should_refuse"]) == (1, 1, 2)


def test_citation_recall_and_precision_are_counted_on_cited_pages():
    q = {"gold_citations": [{"source_id": DOC, "pdf_page": 1}, {"source_id": DOC, "pdf_page": 17}],
         "required_claims": [{}, {}]}
    v = score_question("citation", q, _row([[DOC, 1], [DOC, 9]], cited=[[DOC, 1], [DOC, 9]],
                                           claims=[{"status": "supported"}, {"status": "unsupported"}]))
    t = totals("citation", [v])
    assert (t["citation_recall"], t["citation_precision"], t["claims_supported"]) == (0.5, 0.5, 1)
