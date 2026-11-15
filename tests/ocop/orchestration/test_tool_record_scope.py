"""Adapter scope applies to complete source-backed records, not isolated cells."""

import json
import unicodedata
from types import SimpleNamespace

import pytest

from ai_core.orchestration.ocop import tools as module
from ai_core.orchestration.ocop.router import extract_slots

SOURCE = "VN.TEST.QD900.2044"
ALPHA = "Gạo ALPHA"
BETA = "Gạo BETA"
MISSING = "Gạo MISSING"


@pytest.fixture
def store(tmp_path, monkeypatch):
    index = tmp_path / "data/processed/ocop/index"
    index.mkdir(parents=True)
    (index / "chunks.jsonl").write_text(json.dumps({"source_id": SOURCE}) + "\n", encoding="utf8")
    nodes = {
        "pa": {"node_type": "Product", "label": ALPHA},
        "pb": {"node_type": "Product", "label": BETA},
        "pm": {"node_type": "Product", "label": MISSING},
        "oa": {"node_type": "Organization", "label": "Producer SAMPLE"},
        "ob": {"node_type": "Organization", "label": "Producer SAMPLE Plus"},
        "ra": {"node_type": "RecognitionRecord", "label": "record-a"},
        "rb": {"node_type": "RecognitionRecord", "label": "record-b"},
        "f": {"node_type": "FormTemplate", "label": "1", "form_number": 1},
        "c": {"node_type": "Criterion", "label": "1.1", "criterion_id": "1.1"},
        "s": {"node_type": "ProductSubgroup", "label": "SAMPLE subgroup"},
    }
    nodes = {key: {**value, "node_id": key, "source_id": SOURCE} for key, value in nodes.items()}
    edges = [{"relation_type": relation, "source_entity_id": record, "target_entity_id": target,
              "edge_id": f"{record}-{target}"}
             for relation, record, target in [("RECOGNIZES", "ra", "pa"), ("RECOGNIZES", "rb", "pb"),
                                               ("DECLARED_BY", "ra", "oa"), ("DECLARED_BY", "rb", "ob")]]
    cells = {
        "ra": [{"text": ALPHA}, {"text": "Producer SAMPLE"}, {"text": "4 sao"}],
        "rb": [{"text": BETA}, {"text": "Producer SAMPLE Plus"}, {"text": "3 sao"}],
    }

    def node_rows(selected):
        result = []
        for node in selected:
            for number, cell in enumerate(cells.get(node["node_id"], [{"text": node["label"]}])):
                result.append({**node, "graph_node_type": node["node_type"], "graph_node_ids": [node["node_id"]],
                               "evidence_unit_id": f"unit-{node['node_id']}-{number}", "review_status": "verified",
                               "jurisdiction": "Sample", "star_rating_candidate": 4,
                               "source_spans": [{"pdf_page": 2, "bbox": [0, 0, 1, 1], "source_sha256": "a" * 64}],
                               **cell})
        return result

    graph = SimpleNamespace(nodes=nodes, edges=edges, units={}, node_rows=node_rows, cells=cells)
    monkeypatch.setattr(module, "GraphEvidence", lambda *args, **kwargs: graph)

    def no_search(*args, **kwargs):
        raise AssertionError("record lookup must not broaden scope through text search")

    monkeypatch.setattr(module, "search", no_search)
    return module.ToolRegistry(tmp_path), graph


@pytest.mark.parametrize("tool", ["lookup_recognition", "lookup_form", "lookup_criterion", "lookup_product_subgroup"])
def test_unknown_document_never_removes_a_structured_lookup_scope(store, tool):
    registry, _ = store
    result = registry.dispatch(tool, query="specific document", slots={"document_code": "missing-document", "form_id": "1"})
    assert result["results"] == []
    assert result["status"] == "document_not_found_or_ambiguous"


@pytest.mark.parametrize("code", ["invented900", "NĐ900"])
def test_document_resolver_does_not_discard_an_unknown_prefix_or_wrong_family(store, code):
    registry, _ = store
    assert registry._resolve_source_id(code) is None


@pytest.mark.parametrize("code", ["missing-document", "NĐ900"])
def test_graph_lookup_rejects_unresolved_document_before_opening_graph(store, code, monkeypatch):
    registry, _ = store

    def forbidden(*args, **kwargs):
        raise AssertionError("an unresolved document must not open or traverse a graph")

    monkeypatch.setattr(module, "GraphEvidence", forbidden)
    monkeypatch.setattr(module, "traverse", forbidden)
    result = registry.dispatch("search_graph", query=ALPHA, slots={"document_code": code})
    assert result["results"] == []
    assert result["status"] == "document_not_found_or_ambiguous"


@pytest.mark.parametrize("code", ["900", "QĐ900", SOURCE])
def test_document_resolver_accepts_number_known_family_and_exact_source(store, code):
    registry, _ = store
    assert registry._resolve_source_id(code) == SOURCE


def test_router_keeps_a_type_that_contradicts_the_only_matching_document(store, monkeypatch):
    registry, _ = store
    monkeypatch.setenv("OCOP_ROOT", str(registry.root))
    slots = extract_slots("Nghị định 900 quy định gì?")
    assert registry._resolve_source_id(slots["document_code"]) is None


def test_router_keeps_distinct_types_when_document_numbers_collide(store, monkeypatch):
    registry, _ = store
    other = "VN.TEST.ND900.2045"
    (registry.index_dir / "chunks.jsonl").write_text(
        "\n".join(json.dumps({"source_id": value}) for value in [SOURCE, other]) + "\n", encoding="utf8")
    monkeypatch.setenv("OCOP_ROOT", str(registry.root))
    slots = extract_slots("So sánh Quyết định 900 và Nghị định 900")
    assert len(slots["document_codes"]) == 2
    assert {registry._resolve_source_id(code) for code in slots["document_codes"]} == {SOURCE, other}


def test_star_filter_preserves_owner_cells_of_the_qualifying_record(store):
    registry, _ = store
    result = registry.dispatch("lookup_recognition", query="filter records", slots={"star_rating": 4})
    assert [row["text"] for row in result["results"]] == [ALPHA, "Producer SAMPLE", "4 sao"]


def test_contradictory_stars_cannot_be_hidden_by_filtering_out_one_cell(store):
    registry, graph = store
    graph.cells["ra"].append({"text": "5 sao"})
    result = registry.dispatch("lookup_recognition", query="filter records", slots={"product_name": ALPHA, "star_rating": 4})
    assert result["results"] == []
    assert result["status"] == "recognition_scope_unverified"


def test_candidate_star_metadata_or_unqualified_source_cannot_satisfy_the_filter(store):
    registry, graph = store
    graph.cells["ra"][-1]["review_status"] = "needs_review"
    result = registry.dispatch("lookup_recognition", query="filter records", slots={"product_name": ALPHA, "star_rating": 4})
    assert result["results"] == []


def test_wrong_region_remains_an_explicit_empty_result(store):
    registry, _ = store
    result = registry.dispatch("lookup_recognition", query="filter records", slots={"product_name": ALPHA, "region": "Other"})
    assert result["results"] == []
    assert result["status"] == "recognition_scope_unverified"


def test_partial_named_set_reports_which_identity_has_no_recognition_record(store):
    registry, _ = store
    result = registry.dispatch("lookup_recognition", query="both identities", slots={"product_names": [ALPHA, MISSING]})
    assert result["results"]
    assert result["status"] == "incomplete_entity_set"
    assert result["missing_entities"] == [MISSING]


def test_known_product_without_recognition_record_has_an_explicit_empty_status(store):
    registry, _ = store
    result = registry.dispatch("lookup_recognition", query="one identity", slots={"product_name": MISSING})
    assert result["results"] == []
    assert result["status"] == "no_results"
    assert result["missing_entities"] == [MISSING]


def test_named_set_completeness_is_measured_after_star_filter(store):
    registry, _ = store
    result = registry.dispatch("lookup_recognition", query="both identities with filter",
                               slots={"product_names": [ALPHA, BETA], "star_rating": 4})
    assert {row["node_id"] for row in result["results"]} == {"ra"}
    assert result["status"] == "incomplete_entity_set"
    assert result["missing_entities"] == [BETA]


def test_named_set_completeness_is_measured_after_event_year_filter(store):
    registry, graph = store
    for record, year in [("ra", 2043), ("rb", 2044)]:
        for cell in graph.cells[record]:
            cell["recognition_event_year"] = year
    result = registry.dispatch("lookup_recognition", query="both identities with event year",
                               slots={"product_names": [ALPHA, BETA], "recognition_year": 2043})
    assert {row["node_id"] for row in result["results"]} == {"ra"}
    assert result["status"] == "incomplete_entity_set"
    assert result["missing_entities"] == [BETA]


def test_output_limit_keeps_each_record_before_repeating_its_cells(store):
    registry, graph = store
    graph.cells["ra"].extend({"text": f"extra cell {index}"} for index in range(16))
    result = registry.dispatch("lookup_recognition", query="all recognized products", slots={})
    assert len(result["results"]) == 15
    assert {row["node_id"] for row in result["results"]} == {"ra", "rb"}
    assert BETA in [row["text"] for row in result["results"]]


def test_recognition_result_budget_is_configurable(store, monkeypatch):
    registry, _ = store
    settings = module.get_settings()
    agent = settings.agent.model_copy(update={"lookup_max_rows": 2})
    monkeypatch.setattr(module, "get_settings", lambda: settings.model_copy(update={"agent": agent}))
    result = registry.dispatch("lookup_recognition", query="all recognized products", slots={})
    assert len(result["results"]) == 2
    assert [row["text"] for row in result["results"]] == [ALPHA, BETA]


def test_recognition_star_noun_is_read_from_language_config(store, monkeypatch):
    registry, graph = store
    graph.cells["ra"][-1]["text"] = "4 customlevel"
    language = module.get_language()
    language = type(language).model_validate({**language.model_dump(), "star_noun": ["customlevel"]})
    monkeypatch.setattr(module, "get_language", lambda: language)
    result = registry.dispatch("lookup_recognition", query="one identity with rating",
                               slots={"product_name": ALPHA, "star_rating": 4})
    assert [row["text"] for row in result["results"]] == [ALPHA, "Producer SAMPLE", "4 customlevel"]


def test_evidence_search_expansion_is_read_from_language_config(store, monkeypatch):
    registry, _ = store
    language = module.get_language()
    language = type(language).model_validate({**language.model_dump(), "cues": {
        **language.cues, "evidence_search_terms": ["custom expansion"],
    }})
    monkeypatch.setattr(module, "get_language", lambda: language)
    calls = []

    def search(index, query, **kwargs):
        calls.append(query)
        return []

    monkeypatch.setattr(module, "search", search)
    registry.dispatch("lookup_evidence_requirements", query="sample request", slots={})
    assert calls == ["custom expansion sample request"]


def test_exact_product_identity_does_not_expand_to_a_longer_product_name(store):
    registry, graph = store
    graph.nodes["pb"]["label"] = ALPHA + " PLUS"
    result = registry.dispatch("lookup_recognition", query="one identity", slots={"product_name": ALPHA})
    assert {row["node_id"] for row in result["results"]} == {"ra"}


def test_canonical_identity_keeps_diacritics_and_accepts_decomposed_unicode(store):
    registry, graph = store
    graph.nodes["pa"]["label"] = "Trà Thúy"
    graph.nodes["pb"]["label"] = "Trà Thụy"
    result = registry.dispatch("lookup_recognition", query="one identity",
                               slots={"product_name": unicodedata.normalize("NFD", "Trà Thúy")})
    assert {row["node_id"] for row in result["results"]} == {"ra"}


def test_exact_organization_identity_does_not_include_a_longer_organization(store):
    registry, _ = store
    result = registry.dispatch("lookup_recognition", query="one producer", slots={"organization_name": "Producer SAMPLE"})
    assert {row["node_id"] for row in result["results"]} == {"ra"}


def test_unique_whole_token_alias_remains_usable(store):
    registry, _ = store
    result = registry.dispatch("lookup_recognition", query="one identity", slots={"product_name": "ALPHA"})
    assert {row["node_id"] for row in result["results"]} == {"ra"}


@pytest.mark.parametrize("slots", [{}, {"evidence_unit_id": "unknown"}])
def test_open_span_reports_empty_result_explicitly(store, slots):
    registry, _ = store
    result = registry.dispatch("open_source_span", query="open source", slots=slots)
    assert result["results"] == []
    assert result["status"] == "no_results"


def test_document_fanout_decomposes_the_question_once(tmp_path):
    calls = []

    class Registry(module.ToolRegistry):
        def dispatch(self, name, *, query, slots, context=None, auth=None):
            context = context or {}
            codes = slots.get("document_codes")
            if name == "search_regulations" and context.get("_part") and not (isinstance(codes, list) and len(codes) > 1):
                calls.append((query, slots.get("document_code")))
                return {"results": [{"chunk_id": f"{slots.get('document_code')}:{query}", "text": query}], "status": "ok"}
            return super().dispatch(name, query=query, slots=slots, context=context, auth=auth)

    question = "Điều kiện theo Quyết định 900 và hồ sơ theo Quyết định 901"
    result = Registry(tmp_path).dispatch("search_regulations", query=question,
                                       slots={"document_code": "900", "document_codes": ["900", "901"]})
    assert len(calls) == 4
    assert {code for _, code in calls} == {"900", "901"}
    assert len({row["chunk_id"] for row in result["results"]}) == 4


@pytest.mark.parametrize("cue,kind,status", [
    ("deadline", "local_guidance", "local_guidance_scoped"),
    ("local_document", "local_decision", "local_document_scoped"),
])
def test_local_search_uses_configured_cues(store, monkeypatch, cue, kind, status):
    registry, _ = store
    config = registry.root / "configs"
    config.mkdir()
    (config / "ocop_sources.json").write_text(json.dumps({"sources": [
        {"source_id": SOURCE, "source_kind": kind, "jurisdiction": "Sample"},
    ]}), encoding="utf8")
    language = module.get_language()
    language = type(language).model_validate({
        **language.model_dump(), "cues": {**language.cues, cue: ["custom sample request"]},
    })
    monkeypatch.setattr(module, "get_language", lambda: language)
    calls = []

    def search(*args, **kwargs):
        calls.append(kwargs.get("source_id"))
        return [{"source_id": SOURCE, "chunk_id": "result", "text": "source text"}]

    monkeypatch.setattr(module, "search", search)
    result = registry.dispatch("search_regulations", query="custom sample request", slots={"region": "Sample"})
    assert result.get("status") == status
    assert calls == [SOURCE]


def test_graph_relation_selection_uses_configured_cues(store, monkeypatch):
    from ai_core.graph.ocop import integrity
    from ai_core.graph.ocop.builder import SCHEMA_REVISION

    registry, _ = store
    registry.graph_dir.mkdir(parents=True)
    for name in ["manifest.json", "nodes.jsonl", "edges.jsonl"]:
        (registry.graph_dir / name).write_text("", encoding="utf8")
    (registry.graph_dir / "snapshots/fixture").mkdir(parents=True)
    monkeypatch.setattr(integrity, "validate_graph_snapshot", lambda *args, **kwargs: {
        "graph_version": "fixture", "checks": {"ok": True}, "schema_revision": SCHEMA_REVISION,
        "source_knowledge_version": "fixture",
    })
    language = module.get_language()
    language = type(language).model_validate({**language.model_dump(), "cues": {
        **language.cues, "relation_predicates": {"REPLACES": ["custom relation request"]},
    }})
    monkeypatch.setattr(module, "get_language", lambda: language)
    calls = []

    def traverse(*args, **kwargs):
        calls.append(kwargs["relations"])
        return {"nodes": [], "edges": []}

    monkeypatch.setattr(module, "traverse", traverse)
    registry.dispatch("search_graph", query="custom relation request",
                      slots={"document_code": "900", "graph_seed_ids": ["pa"]})
    assert calls == [["REPLACES"]]


@pytest.mark.parametrize("has_units", [True, False])
def test_criterion_fallback_preserves_sheet_units_and_rerank(store, monkeypatch, has_units):
    registry, graph = store
    graph.nodes = {
        "sheet": {"node_id": "sheet", "node_type": "CriterionSheet", "source_id": SOURCE,
                  "label": "Sample sheet", "properties": {"sheet_number": 1}},
        "criterion": {"node_id": "criterion", "node_type": "Criterion", "source_id": SOURCE,
                      "label": "Sample criterion", "evidence_unit_ids": ["scoped-unit"] if has_units else []},
    }
    graph.units = {"scoped-unit": {}, "other-sheet-unit": {}}
    graph.descendants = lambda seeds, relations: ({"sheet", "criterion"}, [])
    graph.node_rows = lambda nodes: []
    calls = []

    def search(*args, **kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(module, "search", search)
    result = registry.dispatch("lookup_criterion", query="sample criterion request",
                               slots={"document_code": "900", "sheet_number": 1, "criterion_id": "1.1"},
                               context={"retrieval_mode": "hybrid", "rerank": True})
    if has_units:
        assert len(calls) == 1
        assert calls[0]["source_id"] == SOURCE
        assert calls[0]["evidence_unit_ids"] == {"scoped-unit"}
        assert calls[0]["rerank"] is True
    else:
        assert not calls
        assert result["status"] == "sheet_scope_unavailable"


def test_criterion_fallback_keeps_section_continuations_before_the_next_sheet(store, monkeypatch):
    registry, graph = store
    graph.nodes = {
        "sheet": {"node_id": "sheet", "node_type": "CriterionSheet", "source_id": SOURCE,
                  "properties": {"sheet_number": 1}, "evidence_unit_ids": ["intro"]},
        "next-sheet": {"node_id": "next-sheet", "node_type": "CriterionSheet", "source_id": SOURCE,
                       "properties": {"sheet_number": 2}, "evidence_unit_ids": ["next-intro"]},
        "criterion": {"node_id": "criterion", "node_type": "Criterion", "source_id": SOURCE,
                      "evidence_unit_ids": ["intro", "later-cell"]},
    }
    def unit(order, source=SOURCE, kind="paragraph"):
        return {"source_id": source, "properties": {"source_order": order, "unit_kind": kind}}
    graph.units = {
        "before": unit(9), "intro": unit(10), "continuation": unit(11),
        "later-cell": unit(13), "next-intro": unit(14), "next-cell": unit(15),
        "other-document": unit(11, "OTHER"), "whole-page": unit(12, kind="page"),
    }
    graph.descendants = lambda seeds, relations: ({"sheet", "criterion"}, [])
    graph.node_rows = lambda nodes: []
    calls = []
    monkeypatch.setattr(module, "search", lambda *args, **kwargs: calls.append(kwargs) or [])
    registry.dispatch("lookup_criterion", query="sample continuation",
                      slots={"document_code": "900", "sheet_number": 1, "criterion_id": "1.6"},
                      context={"retrieval_mode": "hybrid", "rerank": True})
    assert calls[0]["evidence_unit_ids"] == {"intro", "continuation", "later-cell"}


@pytest.mark.parametrize("asked,expected,narrower", [
    ("Province - Locality", "local_guidance_scoped", None),
    ("Locality", "local_guidance_scoped", None),
    ("Province", "local_guidance_scoped", ["Province - Locality"]),
    ("Elsewhere", "local_guidance_not_in_corpus", None),
])
def test_a_local_guidance_answers_for_its_province_and_says_how_narrow_it_is(store, monkeypatch, asked, expected, narrower):
    registry, _ = store
    config = registry.root / "configs"
    config.mkdir()
    (config / "ocop_sources.json").write_text(json.dumps({"sources": [
        {"source_id": SOURCE, "source_kind": "local_guidance", "jurisdiction": "Province - Locality"},
    ]}), encoding="utf8")
    language = module.get_language()
    language = type(language).model_validate({
        **language.model_dump(), "cues": {**language.cues, "deadline": ["custom sample request"]},
    })
    monkeypatch.setattr(module, "get_language", lambda: language)
    monkeypatch.setattr(module, "search", lambda *a, **k: [{"source_id": SOURCE, "chunk_id": "r", "text": "t"}])
    result = registry.dispatch("search_regulations", query="custom sample request", slots={"region": asked})
    assert result["status"] == expected
    assert result.get("narrower_scope") == narrower
