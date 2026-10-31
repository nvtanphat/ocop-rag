import io
import json

import pytest

from ai_core.orchestration.ocop.answer import assemble


def outputs():
    return [
        {
            "output": {
                "results": [
                    {
                        "source_id": "SYN",
                        "unit_id": str(i),
                        "text": f"Synthetic excerpt {i}",
                        "review_status": "needs_review",
                        "spans": [{"pdf_page": i + 1, "source_sha256": "a" * 64}],
                    }
                    for i in range(8)
                ]
            }
        }
    ]


class Model:
    def chat(self, *args, **kwargs):
        return "Synthetic excerpt 7 [S8]."


@pytest.mark.parametrize("llm", [None, Model()])
def test_all_selected_excerpts_remain_visible_in_retrieval_or_rejected_generation(llm):
    answer = assemble("Two parts on different pages?", outputs(), llm=llm)
    assert "Synthetic excerpt 7" in answer["answer"]
    assert "[S8]" in answer["answer"]
    assert answer["citations"][7]["pdf_page"] == 8
    assert answer["citations"][7]["source_sha256"] == "a" * 64


def test_unverified_source_failure_reports_actual_layer_without_score_claim():
    answer = assemble("?", outputs(), llm=Model())
    assert answer["status"] == "citation_verification_failed"
    assert answer["claim_verification"]["claims"][0]["reason"] == "source_not_verified"
    assert answer["generation_diagnostics"]["layer"] == "claim_verification"
    assert answer["generation_diagnostics"]["reasons"] == ["source_not_verified"]
    assert "source_not_verified" in answer["answer"]


def test_sheet_evidence_scope_filters_before_bm25_top_k(tmp_path):
    from ai_core.retrieval.ocop.index_pipeline import create_bm25
    from ai_core.retrieval.ocop.search import search

    rows = [
        {
            "chunk_id": f"chunk-{i:03}",
            "evidence_unit_id": f"unit-{i}",
            "source_id": "SYN",
            "text_for_bm25": "environment packaging" if i < 60 else "environment " + "continuation " * 40,
            "review_status": "needs_review",
            "corpus_version": "synthetic",
            "spans": [{"pdf_page": i + 1, "source_sha256": "a" * 64}],
        }
        for i in range(62)
    ]
    (tmp_path / "chunks.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf8")
    bm25 = create_bm25(rows, tmp_path / "bm25.json.gz")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"corpus_version": "synthetic", "bm25": bm25}), encoding="utf8"
    )
    assert not any(
        row["evidence_unit_id"] == "unit-61"
        for row in search(tmp_path, "environment packaging", source_id="SYN", top_k=40)
    )
    results = search(
        tmp_path, "environment packaging", source_id="SYN", top_k=8, evidence_unit_ids={"unit-60", "unit-61"}
    )
    assert {row["evidence_unit_id"] for row in results} == {"unit-60", "unit-61"}
    assert search(tmp_path, "environment", evidence_unit_ids=set()) == []


def test_checked_sheet_tool_keeps_cross_page_option_despite_other_sheet_text(tmp_path):
    from tests.fixtures.criteria import fixture
    from tests.fixtures.legal import extract, unit
    from ai_core.graph.ocop.builder import build_graph
    from ai_core.orchestration.ocop.tools import ToolRegistry
    from ai_core.retrieval.ocop.index_pipeline import build_chunks, create_bm25

    units = fixture()
    semantics = extract(units)
    # Unrelated paragraphs in the same document dominate document-wide top-K.
    units += [
        unit("DOC.CURRENT", i, "Phương án cao Phương án thấp " * 20, "paragraph") for i in range(10, 70)
    ]
    for row in units:
        row["review_status"] = "needs_review"
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "manifest.json").write_text(
        json.dumps({"complete": False, "corpus_version": "synthetic-sheet"}), encoding="utf8"
    )
    for name, rows in [
        ("evidence_units", units),
        ("business_entities", semantics["business_entities"]),
        ("business_relations", semantics["business_relations"]),
    ]:
        (knowledge / f"{name}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf8"
        )
    graph = tmp_path / "data/processed/ocop/graph"
    build_graph(knowledge, graph, allow_partial=True)
    index = tmp_path / "data/processed/ocop/index"
    index.mkdir(parents=True)
    chunks = build_chunks(units, "synthetic-sheet-index")
    (index / "chunks.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in chunks), encoding="utf8"
    )
    bm25 = create_bm25(chunks, index / "bm25.json.gz")
    (index / "manifest.json").write_text(
        json.dumps(
            {
                "corpus_version": "synthetic-sheet-index",
                "source_knowledge_version": "synthetic-sheet",
                "source_complete": False,
                "bm25": bm25,
            }
        ),
        encoding="utf8",
    )
    result = ToolRegistry(tmp_path).dispatch(
        "search_regulations",
        query="Phương án cao Phương án thấp",
        slots={"sheet_number": 1},
        context={"allow_partial_debug": True},
    )
    assert result["status"] == "checked_sheet_text"
    assert any("Phương án cao" in row["text"] for row in result["results"])
    assert {row["pdf_page"] for row in result["results"]} <= {3, 4}
    assert all(row["review_status"] != "verified" for row in result["results"])


@pytest.mark.parametrize(
    "payload,reason",
    [
        ({"choices": [{"message": None}]}, "model_unavailable"),
        ({"choices": [{"message": {"content": "unfinished"}, "finish_reason": "length"}]}, "model_output_truncated"),
        ({"choices": [{"message": {"content": "Synthetic OCOP excerpt [S1]."}, "finish_reason": "stop"}]}, "source_not_verified"),
    ],
)
def test_public_api_preserves_generation_failure_diagnostics(
    tmp_path, monkeypatch, payload, reason, api_client
):
    from ai_core.orchestration.ocop import llm
    from ai_core.retrieval.ocop.index_pipeline import create_bm25

    monkeypatch.setenv("OCOP_ANSWER_OPENAI_API_KEY", "test-key")
    index = tmp_path / "data/processed/ocop/index"
    index.mkdir(parents=True, exist_ok=True)
    row = {
        "chunk_id": "synthetic-chunk",
        "evidence_unit_id": "synthetic-unit",
        "source_id": "SYN",
        "text_for_bm25": "Synthetic OCOP excerpt",
        "review_status": "needs_review",
        "corpus_version": "synthetic",
        "spans": [{"pdf_page": 1, "source_sha256": "a" * 64}],
    }
    (index / "chunks.jsonl").write_text(json.dumps(row) + "\n", encoding="utf8")
    bm25 = create_bm25([row], index / "bm25.json.gz")
    (index / "manifest.json").write_text(
        json.dumps({"corpus_version": "synthetic", "source_complete": True, "bm25": bm25}), encoding="utf8"
    )
    monkeypatch.setattr(
        llm.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode())
    )
    client = api_client
    response = client.post("/api/ocop/query", json={"query": "OCOP là gì?", "use_llm": True})
    assert response.status_code == 200
    answer = response.json()
    assert (
        answer["status"]
        == {
            "model_unavailable": "model_unavailable_retrieval_only",
            "model_output_truncated": "model_unavailable_retrieval_only",
            "source_not_verified": "citation_verification_failed",
        }[reason]
    )
    assert reason in answer["generation_diagnostics"]["reasons"]
    assert answer["status"] != "generated_claims_verified"
