import io
import json
import pytest
from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.tools import ToolRegistry
from ai_core.graph.ocop.retriever import traverse
from ai_core.graph.ocop.builder import build_graph
from tests.ocop.test_graph_agent import _fixture


def test_partial_graph_traversal_requires_explicit_opt_in(tmp_path):
    knowledge = _fixture(tmp_path)
    manifest = knowledge / "manifest.json"
    data = json.loads(manifest.read_text())
    data["complete"] = False
    manifest.write_text(json.dumps(data))
    graph = tmp_path / "data/processed/ocop/graph"
    build_graph(knowledge, graph, allow_partial=True)
    with pytest.raises(ValueError):
        traverse(graph, ["doc"])
    result = traverse(graph, ["doc"], allow_partial_debug=True)
    assert result["nodes"] and all(n["check"] == "passed" for n in result["nodes"])
    registry = ToolRegistry(tmp_path)
    result = registry.dispatch(
        "search_graph",
        query="văn bản",
        slots={"graph_seed_ids": ["doc"]},
        context={"allow_partial_debug": True},
    )
    assert result.get("status") != "graph_integrity_failed"


@pytest.mark.parametrize("query", ["QĐ26/2026 thay thế văn bản nào?", "QĐ1489 sửa đổi văn bản nào?"])
def test_document_relationship_questions_request_graph(query):
    assert "search_graph" in route_query(query).required_tools


def test_explicit_pdf_page_is_an_exact_scope():
    route = route_query("QĐ26/2026 trang PDF 58 có nội dung gì?")
    assert route.slots["pdf_page"] == 58
    assert route.required_tools == ["lookup_legal_unit"]


def test_local_deadline_is_not_a_temporal_applicability_verdict():
    route = route_query("Hạn nộp hồ sơ OCOP tại phường Thành Sen năm 2026 là ngày nào?")
    assert route.slots["region"] == "Thành Sen"
    assert "resolve_temporal_applicability" not in route.required_tools


def test_ollama_answer_does_not_spend_budget_on_hidden_thinking(monkeypatch):
    from ai_core.orchestration.ocop import llm

    seen = {}

    def request(req, timeout):
        seen.update(json.loads(req.data))
        return io.BytesIO(b'{"message":{"content":"answer"},"done_reason":"stop"}')

    monkeypatch.setattr(llm.urllib.request, "urlopen", request)
    assert llm.OllamaClient().chat("system", "question") == "answer"
    assert seen["think"] is False


def test_missing_requested_page_cannot_recover_into_other_pages(tmp_path):
    from ai_core.orchestration.ocop.workflow import OcopAgent

    agent = OcopAgent(tmp_path)
    calls = []

    def dispatch(name, **kwargs):
        calls.append(name)
        return {"results": [], "status": "requested_pdf_page_not_indexed"}

    agent.tools.dispatch = dispatch
    result = agent.ask("QĐ26/2026 trang PDF 58 có nội dung gì?")
    assert calls == ["lookup_legal_unit"]
    assert not result.citations
    assert result.status == "insufficient_page_scope"


def test_graph_can_seed_literal_product_without_file_order_bias(tmp_path):
    from tests.ocop.test_graph_entailment_acceptance import recognition_graph

    nodes, _, _ = recognition_graph(tmp_path)
    product = next(n for n in nodes if n["node_type"] == "Product" and n["check"] == "passed")
    registry = ToolRegistry(tmp_path)
    registry.graph_dir = tmp_path / "graph"
    result = registry.dispatch(
        "search_graph", query=product["label"] + " thuộc chủ thể nào?", slots={}, context={}
    )
    assert product["node_id"] in result["seed_ids"]
    assert any("[OWNED_BY]" in r["text"] for r in result["results"])
    assert {n["node_id"] for n in result["nodes"] if n["node_type"] == "Product"} == {product["node_id"]}


def test_graph_evidence_is_not_dropped_after_eight_text_hits():
    from ai_core.orchestration.ocop.answer import assemble

    rows = [
        {
            "source_id": "SYN",
            "text": "Synthetic source paragraph",
            "unit_id": str(i),
            "spans": [{"pdf_page": 1, "bbox": [0, 0, 10, 10]}],
        }
        for i in range(8)
    ]
    fact = {
        "source_id": "SYN",
        "text": "Synthetic A [AMENDS] Synthetic B",
        "unit_id": "graph-unit",
        "graph_edge_id": "synthetic-edge",
        "source_spans": [{"pdf_page": 3, "bbox": [0, 0, 10, 10]}],
    }
    answer = assemble(
        "Which source amends another?",
        [
            {"tool": "search_regulations", "output": {"results": rows}},
            {"tool": "search_graph", "output": {"results": [fact], "status": "checked_source_graph"}},
        ],
    )
    assert any(c["pdf_page"] == 3 for c in answer["citations"])
    assert "[AMENDS]" in answer["answer"]


def test_exact_article_lookup_includes_continuation_but_not_next_article(tmp_path):
    from ai_core.retrieval.ocop.index_pipeline import build_chunks, create_bm25

    index = tmp_path / "data/processed/ocop/index"
    index.mkdir(parents=True)
    units = [
        {
            "unit_id": f"synthetic-unit-{i}",
            "source_id": "SYN.QD26.2026",
            "unit_kind": kind,
            "text": text,
            "review_status": "needs_review",
            "spans": [{"pdf_page": i, "bbox": [0, 0, 100, 100], "source_sha256": "a" * 64}],
        }
        for i, kind, text in [
            (1, "article", "Điều 7. Nộp hồ sơ."),
            (2, "paragraph", "Nâng hạng: chuẩn bị hồ sơ giấy và điện tử."),
            (3, "article", "Điều 8. Nội dung khác."),
        ]
    ]
    chunks = build_chunks(units, "synthetic")
    for name, rows in [("evidence_units", units), ("chunks", chunks), ("structured", [])]:
        (index / f"{name}.jsonl").write_text(
            "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf8"
        )
    bm25 = create_bm25(chunks, index / "bm25.json.gz")
    (index / "manifest.json").write_text(
        json.dumps({"corpus_version": "synthetic", "bm25": bm25}), encoding="utf8"
    )
    from tests.ocop.lookup_graph_fixture import build_legal_graph

    build_legal_graph(index, units)
    result = ToolRegistry(tmp_path).dispatch(
        "lookup_legal_unit",
        query="Điều 7 QĐ26/2026 nâng hạng cần hồ sơ gì?",
        slots={"document_code": "26/2026", "article_id": "7"},
    )
    assert any("Nâng hạng" in row["text"] for row in result["results"])
    assert not any("Điều 8." in row["text"] for row in result["results"])


def test_sheet_number_is_not_silently_ignored_when_graph_scope_is_missing(tmp_path):
    route = route_query("Theo phiếu 3 QĐ26/2026, mục 1.6 có phương án gì?")
    assert route.slots["sheet_number"] == 3
    result = ToolRegistry(tmp_path).dispatch(
        "search_regulations", query="phiếu 3", slots={"sheet_number": 3}, context={}
    )
    assert result["status"] == "sheet_scope_unavailable"
    assert not result["results"]
