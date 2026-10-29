"""Runtime excerpts preserve source text, requested facets and hard budgets."""

import pytest

from ai_core.orchestration.ocop.answer import _evidence, _most_relevant
from ai_core.orchestration.ocop.context import fit_budget, select_window
from ai_core.retrieval.ocop.settings import get_settings


@pytest.mark.parametrize("middle,terms", [
    ("ALPHA được giao nhiệm vụ kiểm tra hồ sơ và BETA hỗ trợ thực hiện", ["alpha"]),
    ("ALPHA " + "nội dung chung " * 18 + "BETA cùng chịu trách nhiệm", ["alpha", "beta"]),
])
def test_long_unbroken_passage_keeps_the_matching_clause(middle, terms):
    text = "phần mở đầu " * 40 + middle + " phần kết thúc" * 40
    window, left, right = select_window(text, terms, 400)
    assert "ALPHA" in window and "BETA" in window
    assert len(window) <= 400 and window in text
    assert left and right


def test_passage_coverage_is_scored_on_the_window_that_can_actually_fit():
    long = "ALPHA " + "nội dung chung " * 40 + "BETA " + "nội dung chung " * 40 + "GAMMA"
    answer = "ALPHA và BETA cùng ký hồ sơ."
    window, left, right = select_window(long + "\n" + answer, ["alpha", "beta", "gamma"], 400)
    assert window == answer and left and not right


def test_locator_only_question_keeps_source_context_instead_of_the_shortest_line():
    text = "Điều 9. Nội dung\n" + "Nội dung điều khoản có căn cứ nguồn. " * 20 + "\nx"
    window, left, right = select_window(text, [], 400)
    assert window.startswith("Điều 9.") and "Nội dung điều khoản" in window
    assert window in text and len(window) <= 400 and not left and right


def _row(identity, text, **extra):
    return {
        "source_id": "DOC", "evidence_unit_id": "unit", "chunk_id": identity,
        "text": text, "review_status": "verified", "graph_edge_id": "edge",
        "source_spans": [{"pdf_page": 2, "bbox": [0, 0, 100, 100], "source_sha256": "a" * 64}],
        **extra,
    }


@pytest.mark.parametrize("with_source", [False, True])
def test_graph_relation_description_is_not_a_quotable_source_passage(with_source):
    description = _row("graph:edge", "DOC-ALPHA [REPLACES] DOC-BETA")
    source = _row("graph-evidence:quote", "Văn bản DOC-BETA hết hiệu lực sau thời hạn chuyển tiếp.")
    citations, contexts, selected = _evidence(
        [description, *([source] if with_source else [])], question="Văn bản nào bị thay thế?",
    )
    assert len(citations) == int(with_source)
    assert all(not citation["chunk_id"].startswith("graph:") for citation in citations)
    assert all("[REPLACES]" not in context for context in contexts)
    assert [row["text"] for row in selected] == ([source["text"]] if with_source else [])


def test_budget_cannot_keep_a_source_when_its_header_alone_exceeds_the_budget():
    row = {"raw_text": "Nội dung nguồn ngắn."}
    assert fit_budget([row], [False], [], get_settings().context, 100, [200]) == [None]


def _entry(identity, text, *, table=None, **extra):
    span = {"pdf_page": 2, **({"table_id": table} if table else {})}
    row = {"text": text, "raw_text": text, **extra}
    return (("DOC", 2, identity, identity), row, span, bool(table))


def test_explicit_facet_keeps_its_evidence_even_when_there_are_no_content_terms():
    generic = [_entry(str(index), "Nội dung chung") for index in range(2)]
    requested = _entry("requested", "1.6. Phần được hỏi", context={"criterion_codes": ["1.6"]})
    kept = _most_relevant([*generic, requested], [], 2, facets=["1.6"])
    assert requested in kept
    assert len(kept) <= 2


def test_facet_reservation_matches_the_heading_instead_of_first_incidental_code():
    unrelated = _entry("other", "1.6. Nội dung khác\nNguồn gốc sản phẩm được nhắc ở phần khác.")
    requested = _entry("requested", "1.6. Nguồn gốc sản phẩm\nYêu cầu theo nguồn.")
    kept = _most_relevant([unrelated, requested], ["nguon", "goc", "san", "pham"], 1, facets=["1.6"])
    assert kept == [requested]


def test_unshown_parent_quotes_cannot_donate_relevance_to_an_unrelated_passage():
    unrelated = _entry("other", "Thủ tục khác", context={
        "parent_source_spans": [{"quote": "ALPHA BETA"}], "parent_chain": ["Danh mục"],
    })
    requested = _entry("requested", "ALPHA BETA")
    assert _most_relevant([unrelated, requested], ["alpha", "beta"], 1) == [requested]


def test_parent_heading_actually_shown_to_the_model_can_guide_relevance():
    unrelated = _entry("other", "Thông tin chung")
    requested = _entry("requested", "Thủ tục theo nguồn", context={"parent_chain": ["ALPHA"]})
    assert _most_relevant([unrelated, requested], ["alpha"], 1) == [requested]


def test_reserved_relation_evidence_fits_inside_the_source_block_limit():
    generic = [_entry(str(index), "alpha") for index in range(2)]
    relation = _entry("relation", "beta", graph_edge_id="edge")
    kept = _most_relevant([*generic, relation], ["alpha"], 2)
    assert relation in kept
    assert len(kept) <= 2


def test_table_siblings_fit_inside_the_source_block_limit():
    generic = [_entry(str(index), "nội dung chung") for index in range(5)]
    product = _entry("product", "ALPHA", table="table")
    owner = _entry("owner", "Tổ chức SAMPLE", table="table")
    kept = _most_relevant([*generic, product, owner], ["alpha", "noi", "dung", "chung"], 2)
    assert product in kept and owner in kept
    assert len(kept) <= 2


def test_table_siblings_follow_the_same_record_not_just_the_same_pdf_table():
    generic = [_entry(str(index), "nội dung chung") for index in range(2)]
    product = _entry("product", "ALPHA", table="table", graph_node_ids=["record-a"])
    unrelated = _entry("unrelated", "Tổ chức OTHER", table="table", graph_node_ids=["record-b"])
    owner = _entry("owner", "Tổ chức SAMPLE", table="table", graph_node_ids=["record-a"])
    kept = _most_relevant([*generic, product, unrelated, owner], ["alpha", "noi", "dung", "chung"], 2)
    assert unrelated not in kept
    assert product in kept and owner in kept
    assert len(kept) <= 2
