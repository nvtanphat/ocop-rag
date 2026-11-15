"""Rule-derived links between evidence units and checked nodes; fabricated corpus only."""

from __future__ import annotations

from ai_core.graph.ocop.links import LINK_RELATIONS, SetLinker, derive_links

SHA = "a" * 64


def unit(uid, source, kind, text):
    span = {"pdf_page": 1, "bbox": [0.0, 0.0, 10.0, 10.0], "source_sha256": SHA}
    return {"unit_id": uid, "source_id": source, "unit_kind": kind, "text": text, "spans": [span], "structured": {}}


def unit_node(uid, source):
    return {
        "node_id": "n:" + uid,
        "node_type": "EvidenceUnit",
        "source_id": source,
        "evidence_unit_ids": [uid],
        "check": "passed",
        "label": uid,
    }


UNITS = {
    u["unit_id"]: u
    for u in [
        unit("a1", "LAW.A", "article", "Điều 1. Phạm vi\nDoanh nghiệp thực hiện theo quy định tại Điều 2 của Luật này."),
        unit("a2", "LAW.A", "article", "Điều 2. Nghĩa vụ\nNội dung nghĩa vụ."),
        unit("b1", "DEC.B", "article", "Điều 5. Hồ sơ\nThực hiện theo Điều 2 của Luật số 10/2020/QH14 và Điều 1 Quyết định này."),
        unit("b2", "DEC.B", "article", "Điều 1. Đối tượng\nTổ chức đăng ký."),
        unit("m1", "AMEND.C", "article", "Điều 1. Sửa đổi, bổ sung Điều 2 của Nghị định số 7/2019/NĐ-CP như sau"),
        unit("t1", "BASE.D", "article", "Điều 2. Nội dung gốc\nNội dung gốc cần sửa."),
        unit("c1", "BASE.D", "article", "Điều 3. Khác\nTham chiếu Điều 2 trong chính văn bản."),
    ]
}
NODES = [unit_node(uid, u["source_id"]) for uid, u in UNITS.items()] + [
    {"node_id": "doc:C", "node_type": "SourceDocument", "source_id": "AMEND.C", "check": "passed", "label": "C"},
    {"node_id": "doc:D", "node_type": "SourceDocument", "source_id": "BASE.D", "check": "passed", "label": "D"},
]
EDGES = [
    {
        "edge_id": "e1",
        "relation_type": "AMENDS",
        "source_entity_id": "doc:C",
        "target_entity_id": "doc:D",
        "check": "passed",
    }
]
REGISTRY = {
    "LAW.A": {"document_number": "10/2020/QH14", "source_kind": "law"},
    "DEC.B": {"document_number": "5/QĐ-X", "source_kind": "decision"},
    "AMEND.C": {"document_number": "9/2021/NĐ-CP", "source_kind": "decree"},
    "BASE.D": {"document_number": "7/2019/NĐ-CP", "source_kind": "decree"},
}


def derive():
    rows, _ = derive_links(NODES, EDGES, UNITS, REGISTRY, "test")
    return [(r["relation_type"], r["source_entity_id"], r["target_entity_id"]) for r in rows], rows


def test_article_reference_inside_the_same_document_links_the_cited_article():
    found, _ = derive()
    assert ("CITES", "n:a1", "n:a2") in found


def test_numbered_document_reference_links_the_article_of_that_document():
    found, _ = derive()
    assert ("CITES", "n:b1", "n:a2") in found  # "Điều 2 của Luật số 10/2020/QH14"
    assert ("CITES", "n:b1", "n:b2") in found  # "Điều 1 Quyết định này"


def test_an_amending_decision_links_the_provision_it_changes_not_its_own_article():
    found, _ = derive()
    assert ("AMENDS_PROVISION", "n:m1", "n:t1") in found
    assert ("CITES", "n:m1", "n:a2") not in found and ("CITES", "n:m1", "n:t1") not in found


def test_a_bare_article_of_the_amended_document_text_does_not_cite_the_amending_decisions_own_article():
    found, _ = derive()
    assert not [f for f in found if f[0] == "CITES" and f[1] == "n:m1"]


def test_every_link_carries_the_quote_and_both_ends_as_source_citations():
    _, rows = derive()
    assert rows and all(r["relation_type"] in LINK_RELATIONS for r in rows)
    for row in rows:
        assert row["check"] == "passed" and row["validation"]["legal_verified"] is False
        assert row["citations"][0]["quote"] in UNITS[row["citations"][0]["evidence_unit_id"]]["text"]
        assert {c["evidence_unit_id"] for c in row["citations"]} == set(row["evidence_unit_ids"])


def test_links_are_deterministic():
    assert derive()[0] == derive()[0]


def test_product_set_linker_names_the_set_listing_the_product():
    texts = ["tiêu chí đánh giá"] * 30 + ["Tương nước mắm gia vị"] * 3
    labels = {"s1": "1. Bộ sản phẩm: Rau, củ, quả", "s9": "9. Bộ sản phẩm: Tương, nước mắm, gia vị dạng lỏng"}
    linker = SetLinker(texts)
    assert linker.rank("Nước mắm Cát Hải", labels) == ["s9"]
    assert linker.rank("Điện thoại", labels) == []
