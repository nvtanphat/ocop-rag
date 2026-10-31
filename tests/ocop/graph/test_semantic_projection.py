from copy import deepcopy

from ai_core.graph.ocop.semantics import derive_semantics
from ai_core.graph.ocop.grounding import usable


def _unit(text, uid="u", sid="D"):
    return {"unit_id": uid, "source_id": sid, "unit_kind": "article", "text": text,
            "spans": [{"pdf_page": 1, "bbox": [0, 0, 100, 100], "source_sha256": "a" * 64}]}


def _node(identity, kind, label, unit, **properties):
    return {"node_id": identity, "node_type": kind, "label": label, "source_id": unit["source_id"],
            "evidence_unit_ids": [unit["unit_id"]], "check": "passed", "origin": "deterministic",
            "properties": properties, "corpus_version": "fixture",
            "citations": [{**unit["spans"][0], "source_id": unit["source_id"],
                           "evidence_unit_id": unit["unit_id"], "quote": unit["text"]}]}


def test_rule_projection_is_typed_anchored_and_does_not_promote_trust():
    unit = _unit("Cơ sở ALPHA phải lưu hồ sơ về nguyên liệu.")
    rule = _node("rule", "RuleCandidate", unit["text"], unit, modality="obligation")
    subject = _node("alpha", "Organization", "Cơ sở ALPHA", unit)
    before = deepcopy([rule, subject])
    nodes, edges, stats = derive_semantics([rule, subject], [], {"u": unit}, {}, "fixture")
    norm = next(n for n in nodes if n["node_type"] == "Obligation")
    assert norm["derived"] is True
    assert norm["properties"]["subject_ids"] == ["alpha"]
    assert norm["properties"]["valid_to"] is None
    assert norm["citations"][0]["quote"] in unit["text"]
    assert usable(norm) and norm["validation"]["legal_verified"] is False
    assert [rule, subject] == before
    assert any(e["relation_type"] == "HAS_SUBJECT" for e in edges)
    assert stats["nodes"]["Obligation"] == 1


def test_invalid_quote_or_unknown_modality_never_creates_a_norm():
    unit = _unit("BETA phải ghi nhãn hàng hóa.")
    bad = _node("bad", "RuleCandidate", unit["text"], unit, modality="obligation")
    bad["citations"][0]["quote"] = "BETA được miễn ghi nhãn hàng hóa."
    unknown = _node("unknown", "RuleCandidate", unit["text"], unit, modality="invented")
    nodes, _, _ = derive_semantics([bad, unknown], [], {"u": unit}, {}, "fixture")
    assert not any(n["node_type"] in {"Obligation", "Permission", "Exemption"} for n in nodes)


def test_duplicate_rules_have_one_norm_and_order_independent_ids():
    unit = _unit("GAMMA không được dùng chất bị cấm.")
    rules = [_node(key, "RuleCandidate", unit["text"], unit, modality="prohibition") for key in ("a", "b")]
    first = derive_semantics(rules, [], {"u": unit}, {}, "fixture")
    second = derive_semantics(rules[::-1], [], {"u": unit}, {}, "fixture")
    assert first == second
    assert sum(n["node_type"] == "Prohibition" for n in first[0]) == 1


def test_numbered_document_reference_requires_one_registry_target():
    unit = _unit("Xem văn bản 7/2030/XY.")
    target = _unit("Văn bản gốc", "target", "T")
    doc = _node("doc", "SourceDocument", "7/2030/XY", target)
    mention = _node("mention", "Mention", "7/2030/XY", unit)
    registry = {"T": {"document_number": "7/2030/XY"}}
    _, edges, _ = derive_semantics([doc, mention], [], {"u": unit, "target": target}, registry, "fixture")
    refs = [e for e in edges if e["relation_type"] == "REFERS_TO"]
    assert [(e["source_entity_id"], e["target_entity_id"]) for e in refs] == [("mention", "doc")]
    other = {**doc, "node_id": "other", "source_id": "OTHER"}
    registry["OTHER"] = {"document_number": "7/2030/XY"}
    _, edges, _ = derive_semantics([doc, other, mention], [], {"u": unit}, registry, "fixture")
    assert not any(e["relation_type"] == "REFERS_TO" for e in edges)


def test_definition_requires_definition_scope_not_an_incidental_copula():
    good = _unit("Giải thích từ ngữ\n1. DELTA là tổ chức thực hiện dịch vụ.")
    ordinary = _unit("DELTA là tổ chức thực hiện dịch vụ.", "ordinary")
    nodes, edges, _ = derive_semantics([], [], {"u": good, "ordinary": ordinary}, {}, "fixture")
    concepts = [n for n in nodes if n["node_type"] == "Concept"]
    assert len(concepts) == 1
    assert concepts[0]["label"] == "DELTA"
    assert concepts[0]["evidence_unit_ids"] == ["u"]
    assert not any(e["relation_type"] == "SAME_CONCEPT" for e in edges)


def test_unknown_actor_is_explicitly_missing_instead_of_invented():
    unit = _unit("Phải hoàn thành báo cáo.")
    rule = _node("rule", "RuleCandidate", unit["text"], unit, modality="obligation")
    nodes, _, _ = derive_semantics([rule], [], {"u": unit}, {}, "fixture")
    norm = next(n for n in nodes if n["node_type"] == "Obligation")
    assert norm["properties"]["subject_ids"] == []
    assert "subject" in norm["properties"]["missing_fields"]


def test_lookup_exposes_a_derived_node_that_passed_the_source_checks(tmp_path, monkeypatch):
    from ai_core.graph.ocop import lookup
    unit = _unit("DELTA phải lưu hồ sơ.")
    row = _node("norm", "Obligation", unit["text"], unit)
    row["derived"] = True
    monkeypatch.setattr(lookup, "validate_graph_snapshot", lambda *a, **k:
                        {"graph_version": "g", "schema_revision": lookup.SCHEMA_REVISION})
    monkeypatch.setattr(lookup, "records", lambda path: [row] if path.name == "nodes.jsonl" else [])
    graph = lookup.GraphEvidence(tmp_path)
    assert "norm" in graph.nodes


def test_wrapped_definition_and_letter_prefix_keep_literal_quote():
    unit = _unit("Giải thích từ ngữ\nb) Bao bì phụ là lớp\nbao gói bên ngoài.")
    nodes, _, _ = derive_semantics([], [], {"u": unit}, {}, "fixture")
    concept = next(n for n in nodes if n["node_type"] == "Concept")
    assert concept["label"] == "Bao bì phụ"
    assert "\n" in concept["citations"][0]["quote"]
    assert concept["citations"][0]["quote"] in unit["text"]


def test_page_containing_a_definition_heading_does_not_retype_other_articles():
    page = _unit("Giải thích từ ngữ\n1. Các yêu cầu khác là nội dung độc lập.", "page")
    page["unit_kind"] = "page"
    child = _unit("1. Các yêu cầu khác là nội dung độc lập.")
    child["parent_unit_id"] = "page"
    nodes, _, _ = derive_semantics([], [], {"u": child, "page": page}, {}, "fixture")
    assert not any(n["node_type"] == "Concept" for n in nodes)


def test_duration_keeps_unknown_start_event_instead_of_computing_a_date():
    unit = _unit("DELTA phải trả kết quả trong thời hạn 12 ngày.")
    rule = _node("rule", "RuleCandidate", unit["text"], unit, modality="obligation")
    nodes, _, _ = derive_semantics([rule], [], {"u": unit}, {}, "fixture")
    deadline = next(n for n in nodes if n["node_type"] == "Deadline")
    assert deadline["properties"]["duration_value"] == 12
    assert deadline["properties"]["anchor_event"] is None


def test_cross_document_relation_requires_usable_endpoints():
    from ai_core.graph.ocop.grounding import relation_usable

    nodes = {key: {"source_id": key, "check": "passed"} for key in ("A", "B")}
    edge = {"source_entity_id": "A", "target_entity_id": "B", "check": "passed"}
    assert relation_usable(edge, nodes)
    nodes["B"]["check"] = "failed"
    assert not relation_usable(edge, nodes)


def test_multi_page_quote_uses_line_page_and_abstains_without_mapping():
    from ai_core.graph.ocop.links import _quote_citation

    unit = _unit("FIRST\nSECOND")
    unit["spans"].append({**unit["spans"][0], "pdf_page": 2})
    assert _quote_citation(unit, "SECOND") is None
    unit["structured"] = {"quote_lines": [
        {"text": "FIRST", "pdf_page": 1, "bbox": [0, 0, 100, 100]},
        {"text": "SECOND", "pdf_page": 2, "bbox": [0, 0, 100, 100]},
    ]}
    ref = _quote_citation(unit, "SECOND")
    assert ref["pdf_page"] == 2 and ref["source_sha256"] == "a" * 64
    assert _quote_citation(unit, unit["text"]) is None


def test_document_version_cannot_borrow_another_sources_sha():
    unit = _unit("Local original", "local", "LOCAL")
    foreign = _unit("Foreign quotation", "foreign", "OTHER")
    foreign["spans"][0]["source_sha256"] = "b" * 64
    doc = _node("doc", "SourceDocument", "Document", foreign)
    doc["source_id"] = "LOCAL"
    nodes, _, _ = derive_semantics([doc], [], {"local": unit, "foreign": foreign}, {}, "fixture")
    version = next(n for n in nodes if n["node_type"] == "DocumentVersion")
    assert version["properties"]["source_sha256"] == "a" * 64
    assert all(r["source_id"] == "LOCAL" for r in version["citations"])


def test_document_version_uses_an_available_source_anchor_instead_of_a_rejected_unit():
    rejected = _unit("Excluded original anchor", "a")
    available = _unit("Available original anchor", "b")
    doc = _node("doc", "SourceDocument", "Document", rejected)
    bad = _node("bad", "EvidenceUnit", "a", rejected)
    bad.update(check="failed", review_status="rejected")
    good = _node("good", "EvidenceUnit", "b", available)
    nodes, _, _ = derive_semantics([doc, bad, good], [], {"a": rejected, "b": available}, {}, "fixture")
    version = next(n for n in nodes if n["node_type"] == "DocumentVersion")
    assert version["evidence_unit_ids"] == ["b"]


def test_definition_scope_continues_on_next_page_and_stops_at_next_article():
    heading = _unit("Điều 2. Giải thích từ ngữ\n1. ALPHA là tổ chức cung cấp dịch vụ.", "heading")
    continuation = _unit("2. BETA là tổ chức nhận dịch vụ.", "next")
    continuation["unit_kind"] = "paragraph"
    continuation["spans"][0]["pdf_page"] = 2
    unrelated = _unit("Điều 3. Phạm vi khác\n1. GAMMA là nội dung ngoài định nghĩa.", "other")
    unrelated["spans"][0]["pdf_page"] = 3
    nodes, _, _ = derive_semantics([], [], {u["unit_id"]: u for u in (unrelated, continuation, heading)}, {}, "fixture")
    assert {n["label"] for n in nodes if n["node_type"] == "Concept"} == {"ALPHA", "BETA"}


def test_form_mention_resolves_only_with_one_local_numbered_target():
    unit = _unit("Sử dụng Mẫu 7 cho hồ sơ.")
    mention = _node("mention", "Mention", "Mẫu 7", unit)
    form = _node("form", "FormTemplate", "Mẫu số 07", unit, form_id="07")
    _, edges, _ = derive_semantics([mention, form], [], {"u": unit}, {}, "fixture")
    assert any(e["relation_type"] == "REFERS_TO" and e["target_entity_id"] == "form" for e in edges)
    _, edges, _ = derive_semantics([mention, form, {**form, "node_id": "ambiguous"}], [], {"u": unit}, {}, "fixture")
    assert not any(e["relation_type"] == "REFERS_TO" for e in edges)


def test_document_identity_repair_does_not_depend_on_all_mentions_or_rewrite_accepted_nodes():
    from ai_core.graph.ocop.semantics import repair_document_anchors
    own = _unit("Original document title and body.", "own", "A")
    foreign = _unit("Another document mentions this document.", "other", "B")
    doc = _node("doc", "SourceDocument", "Document", foreign)
    doc["source_id"] = "A"
    backing = _node("evidence", "EvidenceUnit", "own", own)
    backing.update(check="passed", review_status="verified")
    accepted = {**deepcopy(doc), "node_id": "accepted", "check": "passed"}
    repaired = repair_document_anchors([doc, accepted, backing], {"own": own, "other": foreign})
    assert [r["node_id"] for r in repaired] == ["doc", "accepted"]
    assert doc["evidence_unit_ids"] == ["own"] and doc["citations"][0]["source_id"] == "A"
    assert doc["derived"] and doc["check"] == "passed" and usable(doc)
