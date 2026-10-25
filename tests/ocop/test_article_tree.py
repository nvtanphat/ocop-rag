"""Synthetic legal hierarchy fixtures with page boundaries and missing pages."""

from tests.ocop.test_legal_structure import extract, unit


def test_article_clause_point_tree_preserves_order_and_literal_evidence():
    text = (
        "Điều 11. Hiệu lực thi hành\n1. Quy định thứ nhất.\n"
        "2. Quy định thứ hai:\na) Nội dung A;\nB) Nội dung B."
    )
    result = extract([unit("DOC.CURRENT", 13, text)])
    es = {e["entity_id"]: e for e in result["business_entities"]}
    article = next(e for e in es.values() if e["kind"] == "Article")
    assert article["attributes"]["article_number"] == "11"
    clauses = [
        es[r["target_entity_id"]] for r in result["business_relations"] if r["relation_type"] == "HAS_CLAUSE"
    ]
    assert sorted(e["attributes"]["clause_number"] for e in clauses) == ["1", "2"]
    points = [
        es[r["target_entity_id"]] for r in result["business_relations"] if r["relation_type"] == "HAS_POINT"
    ]
    assert sorted(e["attributes"]["point_letter"] for e in points) == ["a", "b"]
    assert all(e["evidence"][0]["quote"] in text for e in es.values())
    assert all(e["status"] == "candidate" for e in es.values())


def test_point_list_continues_under_explicit_clause_on_consecutive_page(tmp_path):
    units = [
        unit("DOC.CURRENT", 2, "Điều 3. Phân hạng\n3. Có các hạng sau:"),
        unit("DOC.CURRENT", 3, "a) Hạng 5 sao;\nb) Hạng 4 sao.", "paragraph"),
        unit("DOC.CURRENT", 3, "Điều 4. Thẩm quyền\n1. Quy định khác."),
    ]
    result = extract(units)
    es = {e["entity_id"]: e for e in result["business_entities"]}
    points = [e for e in es.values() if e["kind"] == "Point"]
    assert len(points) == 2
    assert all({r["pdf_page"] for r in p["evidence"]} == {2, 3} for p in points)
    for r in result["business_relations"]:
        if r["relation_type"] == "HAS_POINT":
            assert es[r["source_entity_id"]]["attributes"]["article_number"] == "3"
            assert {e["pdf_page"] for e in r["evidence"]} == {2, 3}
    assert {e["attributes"]["article_number"] for e in es.values() if e["kind"] == "Article"} == {"3", "4"}
    import json
    from ai_core.graph.ocop.builder import build_graph

    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "manifest.json").write_text(json.dumps({"complete": True, "corpus_version": "continuation"}))
    for name, rows in {"evidence_units": units, **result}.items():
        (knowledge / f"{name}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
        )
    assert build_graph(knowledge, tmp_path / "graph")["counts"]["rejected"] == 0


def test_missing_page_and_new_section_stop_article_inheritance():
    result = extract(
        [
            unit("DOC.CURRENT", 2, "Điều 3. Phân hạng\n3. Có các hạng sau:"),
            unit("DOC.CURRENT", 13, "a) Không biết khoản cha.", "paragraph"),
        ]
    )
    assert not any(e["kind"] == "Point" for e in result["business_entities"])
    assert {"reason": "article_continuation_without_parent", "count": 1} in result["business_omissions"]


def test_native_style_clause_and_vietnamese_point_letter():
    result = extract(
        [
            unit(
                "DOC.CURRENT",
                1,
                "Điều 1. Phạm vi điều chỉnh\n1. Quy định về nhãn.\n2. Loại trừ:\nd) Tài sản;\nđ) Thực phẩm;\ne) Vật liệu.",
            )
        ]
    )
    assert sorted(
        e["attributes"]["point_letter"] for e in result["business_entities"] if e["kind"] == "Point"
    ) == ["d", "e", "đ"]
