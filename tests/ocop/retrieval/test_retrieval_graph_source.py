import json
import sys
from types import SimpleNamespace

import pytest

from ai_core.orchestration.ocop.tools import ToolRegistry


def test_recognition_lookup_reads_checked_graph_without_candidate_index(tmp_path):
    from tests.ocop.graph.test_graph_entailment_acceptance import recognition_graph

    nodes, _, _ = recognition_graph(tmp_path)
    registry = ToolRegistry(tmp_path)
    registry.graph_dir = tmp_path / "graph"
    product = next(n for n in nodes if n["node_type"] == "Product" and n["check"] == "passed")
    result = registry.dispatch(
        "lookup_recognition", query=product["label"], slots={"product_name": product["label"]}
    )
    assert result["results"]
    assert all(row["check"] == "passed" for row in result["results"])
    assert all(row["source_spans"] and row["graph_node_ids"] for row in result["results"])
    assert any("HTX Sen Huế" in row["text"] for row in result["results"])


def test_candidate_file_cannot_supply_runtime_lookup(tmp_path):
    index = tmp_path / "data/processed/ocop/index"
    index.mkdir(parents=True)
    (index / "manifest.json").write_text(json.dumps({"corpus_version": "synthetic"}))
    (index / "structured.jsonl").write_text(
        json.dumps(
            {
                "record_kind": "form_candidates",
                "form_number": "2",
                "source_id": "SYN",
                "review_status": "verified",
                "evidence_unit_id": "fake",
                "source_spans": [{"pdf_page": 1}],
                "text": "Untrusted parallel file",
            }
        )
        + "\n"
    )
    result = ToolRegistry(tmp_path).dispatch("lookup_form", query="Mẫu 02", slots={"form_id": "2"})
    assert result["results"] == []
    assert result["status"] == "graph_not_built"


def test_fusion_covers_multiple_criterion_facets_beyond_first_eight():
    from ai_core.orchestration.ocop.answer import assemble

    rows = [
        {
            "source_id": "SYN",
            "unit_id": str(i),
            "text": "1.6. Environmental option " + str(i),
            "spans": [{"pdf_page": 2, "bbox": [0, 0, 10, 10], "source_sha256": "a" * 64}],
        }
        for i in range(9)
    ]
    rows.append(
        {
            "source_id": "SYN",
            "unit_id": "note",
            "text": "1.1. Origin note",
            "spans": [{"pdf_page": 3, "bbox": [0, 0, 10, 10], "source_sha256": "a" * 64}],
        }
    )
    result = assemble("Phiếu 3: mục 1.6 và ghi chú 1.1?", [{"output": {"results": rows}}])
    assert "Origin note" in result["answer"]
    assert result["evidence_fusion"]["missing_facets"] == []


def test_excerpt_budget_is_tokens_and_not_a_four_or_eight_row_cutoff():
    from ai_core.orchestration.ocop.answer import assemble
    from ai_core.retrieval.ocop.settings import get_settings
    from ai_core.retrieval.ocop.structure_chunker import estimated_tokens

    limit = get_settings().context.max_source_blocks
    rows = [
        {
            "source_id": "SYN",
            "unit_id": str(i),
            "text": f"Short synthetic paragraph {i}",
            "spans": [{"pdf_page": i + 1, "bbox": [0, 0, 10, 10], "source_sha256": "a" * 64}],
        }
        for i in range(limit + 4)
    ]
    result = assemble("?", [{"output": {"results": rows + rows}}])
    assert result["evidence_fusion"]["excerpt_count"] == limit
    assert estimated_tokens(result["answer"]) < 3600
    assert len(result["citations"]) == limit


def test_uncovered_facet_is_explicit_instead_of_answering_one_half():
    from ai_core.orchestration.ocop.answer import assemble

    row = {
        "source_id": "SYN",
        "unit_id": "unit-1",
        "text": "1.6. Only one criterion",
        "spans": [{"pdf_page": 1, "bbox": [0, 0, 10, 10], "source_sha256": "a" * 64}],
    }
    result = assemble("Mục 1.6 và 1.1?", [{"output": {"results": [row]}}])
    assert result["status"] == "insufficient_facet_evidence"
    assert result["evidence_fusion"]["missing_facets"] == ["1.1"]


@pytest.mark.parametrize("kind", ["embedding", "reranker"])
def test_model_loaders_forbid_network_downloads(monkeypatch, kind):
    from ai_core.retrieval.ocop.index_pipeline import _load_embedding
    from ai_core.retrieval.ocop.search import _load_reranker

    seen = {}

    def constructor(model, **kwargs):
        seen.update(kwargs)
        raise OSError("synthetic model missing locally")

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=constructor, CrossEncoder=constructor),
    )
    load = _load_embedding if kind == "embedding" else _load_reranker
    load.cache_clear()
    with pytest.raises(OSError):
        load("synthetic-no-download")
    assert seen["local_files_only"] is True
    assert seen["trust_remote_code"] is False
    load.cache_clear()


def test_vietnamese_bm25_handles_decomposed_accents_and_exact_form_criterion(tmp_path):
    import unicodedata
    from ai_core.retrieval.ocop.index_pipeline import create_bm25
    from ai_core.retrieval.ocop.search import search

    bodies = [
        "Mẫu 12. Mục 1.60. Hồ sơ OCOP",
        unicodedata.normalize("NFD", "Mẫu 02. Mục 1.6. Hồ sơ OCOP"),
        "Mẫu 03. Mục 1.7. Hồ sơ OCOP",
    ]
    rows = [
        {
            "chunk_id": f"synthetic-{i}",
            "source_id": "SYN",
            "evidence_unit_id": f"u-{i}",
            "text_for_bm25": text,
            "review_status": "needs_review",
            "corpus_version": "fixture",
            "spans": [{"pdf_page": i + 1, "bbox": [0, 0, 10, 10], "source_sha256": "a" * 64}],
        }
        for i, text in enumerate(bodies)
    ]
    (tmp_path / "chunks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf8")
    bm25 = create_bm25(rows, tmp_path / "bm25.json.gz")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"corpus_version": "fixture", "bm25": bm25}), encoding="utf8"
    )
    found = search(tmp_path, "Mau 2 muc 1.6", mode="hybrid")
    assert found[0]["chunk_id"] == "synthetic-1"
    assert found[0]["retrieval_mode"] == "sparse"
    assert found[0]["retrieval_fallback_reason"] == "dense_not_built"


def test_structural_context_keeps_cross_page_parent_and_original_row(tmp_path):
    from tests.ocop.graph.test_graph_entailment_acceptance import sheet_graph
    from ai_core.retrieval.ocop.index_pipeline import build_chunks
    from ai_core.retrieval.ocop.graph_context import enrich_chunks

    _, _, units = sheet_graph(tmp_path)
    for unit in units:
        unit["review_status"] = "needs_review"
    chunks = build_chunks(units, "synthetic")
    enrich_chunks(chunks, tmp_path / "graph")
    rows = [row for row in chunks if row["spans"][0]["pdf_page"] == 4 and "Phương án cao" in row["raw_text"]]
    assert rows
    assert "1.1" in rows[0]["context"]["criterion_codes"]
    assert any(ref["pdf_page"] == 3 for ref in rows[0]["context"]["parent_source_spans"])
    assert "Phương án cao" in rows[0]["text_for_bm25"]
    assert all(span["source_sha256"] == "a" * 64 for span in rows[0]["spans"])


def test_table_chunks_do_not_fill_budget_with_another_criterion():
    from tests.fixtures.criteria import table
    from ai_core.retrieval.ocop.structure_chunker import plan_chunks

    unit = table(
        3,
        [
            ("1.1. Nguồn gốc", 3),
            ("Yêu cầu: ghi chú nguyên văn", ""),
            ("Phương án thứ nhất", 1),
            ("1.2. Chứng nhận", 2),
            ("Phương án khác", 2),
        ],
    )
    chunks = plan_chunks(unit)
    assert len(chunks) >= 2
    assert not any("1.1." in chunk.raw_text and "1.2." in chunk.raw_text for chunk in chunks)
    assert any("1.1." in chunk.raw_text and "ghi chú nguyên văn" in chunk.raw_text for chunk in chunks)


def test_parent_context_never_compares_row_numbers_across_pages(tmp_path, monkeypatch):
    from tests.fixtures import criteria as sheets
    from tests.ocop.graph.test_graph_entailment_acceptance import sheet_graph
    from ai_core.retrieval.ocop.index_pipeline import build_chunks
    from ai_core.retrieval.ocop.graph_context import enrich_chunks

    units = sheets.fixture()
    units[5] = sheets.table(
        3,
        [("Phần A: SẢN PHẨM", 40), ("1. TỔ CHỨC SẢN XUẤT", 40)]
        + [("Ghi chú: nguyên văn", "")] * 20
        + [("1.1. Tiêu chí", 40), ("Phương án thấp", 20)],
    )
    monkeypatch.setattr(sheets, "fixture", lambda: units)
    sheet_graph(tmp_path)
    for unit in units:
        unit["review_status"] = "needs_review"
    chunks = enrich_chunks(build_chunks(units, "synthetic"), tmp_path / "graph")
    target = next(row for row in chunks if "2.1." in row["raw_text"])
    assert "1.1" not in target["context"]["criterion_codes"]


def test_fusion_removes_redundant_cell_but_keeps_inherited_owner_cell():
    from ai_core.retrieval.ocop.fusion import deduplicate

    def row(text, number, cell=None):
        span = {
            "pdf_page": 1,
            "table_id": "table",
            "row": number,
            "evidence_unit_id": "unit",
            "source_sha256": "a" * 64,
            "bbox": [0, 0, 10, 10],
        }
        if cell:
            span["cell_id"] = cell
        return {
            "source_id": "SYN",
            "unit_id": "unit",
            "text": text,
            "review_status": "needs_review",
            "source_spans": [span],
        }

    rows = [row("Product | 3", 2), row("3", 2, "table:r2:c1"), row("Owner", 1, "table:r1:c0")]
    assert [r["text"] for r in deduplicate(rows)] == ["Product | 3", "Owner"]


def test_lookup_rejects_tampered_immutable_snapshot_with_graph_reason(tmp_path):
    from tests.ocop.graph.test_graph_entailment_acceptance import recognition_graph

    recognition_graph(tmp_path)
    graph = tmp_path / "graph"
    header = json.loads((graph / "manifest.json").read_text(encoding="utf8"))
    path = graph / "snapshots" / header["graph_version"] / "edges.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    registry = ToolRegistry(tmp_path)
    registry.graph_dir = graph
    result = registry.dispatch("lookup_recognition", query="Product", slots={})
    assert result["results"] == []
    assert result["status"] == "graph_integrity_failed" and result["layer"] == "graph"


def test_graph_seeds_use_a_product_name_the_user_wrote():
    from ai_core.orchestration.ocop.tools import graph_seeds

    nodes = [
        {"node_id": "p1", "node_type": "Product", "label": "Gạo ruộng rươi giống HANA", "source_id": "D"},
        {"node_id": "p2", "node_type": "Product", "label": "Gạo ruộng rươi ST25", "source_id": "D"},
        {"node_id": "u1", "node_type": "EvidenceUnit", "label": "HANA", "source_id": "D"},
    ]
    assert graph_seeds(nodes, "Chủ thể của sản phẩm HANA liên quan quyết định nào?", "HANA", None) == ["p1"]
    # A slot the user never wrote (e.g. proposed by a model) is not an alias.
    assert graph_seeds(nodes, "Chủ thể của sản phẩm này là ai?", "HANA", None) == []
    # A substring inside another word is not a match.
    assert graph_seeds(nodes, "sản phẩm ANA là gì?", "ANA", None) == []


def test_authority_lookup_picks_the_clause_that_recognises_the_requested_star_level():
    from ai_core.graph.ocop.lookup import authority_nodes

    def node(i, label, kind="Point"):
        return {"node_id": f"n{i}", "node_type": kind, "label": label, "source_id": "D"}

    nodes = [
        node(
            1,
            "a) UBND cấp tỉnh tổ chức đánh giá, phân hạng và quyết định công nhận, cấp giấy chứng nhận "
            "cho sản phẩm OCOP 3 sao, 4 sao.",
        ),
        node(
            2,
            "b) Bộ Nông nghiệp và Môi trường chủ trì, phối hợp với các bộ, ngành liên quan tổ chức đánh giá, "
            "phân hạng và quyết định công nhận, cấp giấy chứng nhận cho sản phẩm OCOP 5 sao.",
        ),
        node(3, "Đơn đăng ký nhãn hiệu đã được cơ quan có thẩm quyền chấp nhận", "ScoreOption"),
        node(4, "a) Hạng 5 sao (cấp quốc gia): Tổng điểm trung bình đạt từ 90 đến 100 điểm"),
    ]
    assert [n["node_id"] for n in authority_nodes(nodes, star_rating=5)] == ["n2"]
    assert [n["node_id"] for n in authority_nodes(nodes, star_rating=4)] == ["n1"]
    assert [n["node_id"] for n in authority_nodes(nodes, star_rating=None)] == ["n1", "n2"]


def test_a_passage_whose_heading_the_question_names_is_seeded():
    from ai_core.retrieval.ocop.search import _title_seeds

    ordered = [
        {"chunk_id": "a", "context": {"legal_heading": "Điều 3. Hiệu lực thi hành"}},
        {"chunk_id": "b", "context": {"legal_heading": "Điều 4. Trách nhiệm thi hành"}},
        {"chunk_id": "c", "context": {"legal_heading": "Phụ lục III"}},
        {"chunk_id": "d", "context": {}},
    ]
    seeds = _title_seeds("Từ ngày nào Nghị định này bắt đầu có hiệu lực thi hành?", ordered, lambda cid: True)
    assert seeds[0] == "a" and "c" not in seeds and "d" not in seeds
    assert _title_seeds("Ai chịu trách nhiệm?", ordered, lambda cid: cid != "b") == []


def test_a_heading_that_is_only_a_label_takes_its_name_from_the_next_line():
    from ai_core.retrieval.ocop.search import _title_seeds

    ordered = [{"chunk_id": "annex", "context": {"legal_heading": "Phụ lục III"},
                "raw_text": "Phụ lục III\nBỘ TIÊU CHÍ ĐÁNH GIÁ SẢN PHẨM OCOP\n(Kèm theo Quyết định)"}]
    assert _title_seeds("Bộ tiêu chí đánh giá sản phẩm OCOP nằm ở phụ lục nào?", ordered, lambda cid: True) == ["annex"]


def test_the_cross_encoder_reorders_rows_fused_across_tools(monkeypatch):
    from ai_core.orchestration.ocop import answer
    from ai_core.retrieval.ocop import search

    def fake_rerank(query, candidates, model_id, revision=None, pair_token_budget=None):
        return sorted(candidates, key=lambda c: "lao động" not in c["text"])

    monkeypatch.setattr(search, "_rerank", fake_rerank)
    rows = [
        {"tool": "lookup_product_subgroup", "source_id": "S", "evidence_unit_id": "title", "text": "7. Bộ sản phẩm: rau"},
        {"tool": "search_regulations", "source_id": "S", "evidence_unit_id": "row", "text": "Sử dụng lao động tại xã"},
        {"tool": "search_regulations", "source_id": "S", "evidence_unit_id": "other", "text": "Ghi chú"},
    ]
    ordered = answer.rerank_fused("lao động địa phương", rows)
    assert ordered[0]["evidence_unit_id"] == "row"  # a tie between tools' first rows goes to the cross-encoder
    assert {r["evidence_unit_id"] for r in ordered} == {"title", "row", "other"}
