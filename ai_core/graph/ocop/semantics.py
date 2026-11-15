"""Materialize typed, source-anchored semantic proposals without calling a model.

Derived rows require their own human decision before public traversal. Existing
rows and their identities are never rewritten by this projection.
"""

from collections import Counter, defaultdict
import hashlib
import json
import re
import unicodedata

from ocop_contracts.ids import stable_id
from ai_core.orchestration.ocop.language import get_language
from ai_core.retrieval.ocop.settings import get_settings

NORM_TYPES = {"obligation": "Obligation", "permission": "Permission", "prohibition": "Prohibition",
              "exemption": "Exemption", "temporal": "Transition"}
SEMANTIC_NODE_TYPES = frozenset({*NORM_TYPES.values(), "DocumentVersion", "Concept", "ProductSet",
                                  "ScoreBand", "Deadline", "Certificate", "SubjectType", "Procedure", "Mention"})
PROVISION_TYPES = frozenset({"Article", "Clause", "Point", "Annex", "FormTemplate"})
SUBJECT_TYPES = frozenset({"Organization", "SubjectType"})
OBJECT_TYPES = frozenset({"Product", "ProductGroup", "ProductSubgroup", "CriterionSheet", "FormTemplate", "Concept"})
SEMANTIC_ENDPOINTS = {
    "SUPPORTED_BY": (SEMANTIC_NODE_TYPES, frozenset({"EvidenceUnit"})),
    "HAS_NORM": (PROVISION_TYPES | {"EvidenceUnit"}, frozenset(NORM_TYPES.values())),
    "IN_VERSION": (PROVISION_TYPES | SEMANTIC_NODE_TYPES, frozenset({"DocumentVersion"})),
    "HAS_SUBJECT": (frozenset(NORM_TYPES.values()), SUBJECT_TYPES),
    "HAS_OBJECT": (frozenset(NORM_TYPES.values()), OBJECT_TYPES),
    "HAS_AUTHORITY": (frozenset(NORM_TYPES.values()), frozenset({"Authority"})),
    "HAS_DEADLINE": (frozenset(NORM_TYPES.values()) | {"Procedure", "ProcedureStep"}, frozenset({"Deadline"})),
    "DEFINES": (PROVISION_TYPES | {"EvidenceUnit"}, frozenset({"Concept"})),
    "REFERS_TO": (frozenset({"Mention"}), frozenset({"SourceDocument", "Concept"}) | PROVISION_TYPES),
    "SAME_CONCEPT": (frozenset({"Concept"}), frozenset({"Concept"})),
    "CLASSIFIED_AS": (frozenset({"Product"}), frozenset({"ProductSet"})),
    "SCORE_MAPS_TO_RATING": (frozenset({"ScoreBand"}), frozenset({"StarLevel"})),
    "USES_SHEET": (frozenset({"ProductSet"}), frozenset({"CriterionSheet"})),
}
LINK_ENDPOINTS = {
    "CITES": (frozenset({"EvidenceUnit"}), frozenset({"EvidenceUnit"})),
    "AMENDS_PROVISION": (frozenset({"EvidenceUnit"}), frozenset({"EvidenceUnit"})),
    "CLASSIFIED_UNDER": (frozenset({"Product"}), frozenset({"CriterionSheet"})),
    "HAS_STAR": (frozenset({"RecognitionRecord"}), frozenset({"StarLevel"})),
    "AUTHORITY_RULE": (frozenset({"StarLevel"}), frozenset({"EvidenceUnit"})),
}
MODEL_ENDPOINTS = {
    "ELIGIBLE_SUBJECT": (frozenset(NORM_TYPES.values()) | {"DocumentVersion", "SourceDocument", "Procedure"}, SUBJECT_TYPES),
    "EXEMPT_FROM": (frozenset(NORM_TYPES.values()) | SUBJECT_TYPES, frozenset(NORM_TYPES.values()) | {"Concept", "EvidenceType"}),
    "MUST_MEET": (frozenset(NORM_TYPES.values()) | SUBJECT_TYPES | {"Product"}, frozenset({"Criterion", "Condition", "Concept"})),
    "MEETS_SCORE_BAND": (frozenset({"RecognitionRecord"}), frozenset({"ScoreBand"})),
    "CERTIFIED_BY": (frozenset({"StarLevel"}), frozenset({"Authority"})),
    "SUBMITS_FOR_EVALUATION": (SUBJECT_TYPES, frozenset({"Procedure", "ProcedureStep"})),
    "REQUIRES_FORM": (frozenset(NORM_TYPES.values()) | {"Procedure", "ProcedureStep"}, frozenset({"FormTemplate"})),
    "SUBMITTED_AT": (frozenset({"Procedure", "ProcedureStep"}), frozenset({"Authority", "AdministrativeArea"})),
    "CERT_VALID_FOR": (frozenset(NORM_TYPES.values()) | {"Certificate"}, frozenset({"Deadline"})),
    "GRANTS_BRAND_USE": (frozenset(NORM_TYPES.values()) | {"Certificate"}, frozenset({"Permission", "Concept"})),
    "SUPERSEDES": (PROVISION_TYPES | {"DocumentVersion", "SourceDocument"}, PROVISION_TYPES | {"DocumentVersion", "SourceDocument"}),
    "SUSPENDS": (PROVISION_TYPES | {"DocumentVersion", "SourceDocument"}, PROVISION_TYPES | {"DocumentVersion", "SourceDocument"}),
    "APPLIES_INSTEAD": (PROVISION_TYPES | {"Transition"}, PROVISION_TYPES),
    "PRESERVES_UNDER_TRANSITION": (frozenset({"Transition"}), frozenset(NORM_TYPES.values()) | {"Certificate", "DocumentVersion"}),
    "REQUIRES_DECLARATION": (frozenset(NORM_TYPES.values()) | SUBJECT_TYPES, frozenset({"FormTemplate", "Concept", "Procedure"})),
    "REQUIRES_LABEL": (frozenset(NORM_TYPES.values()) | {"Product"}, frozenset({"Concept"})),
    "REQUIRES_TRACEABILITY": (frozenset(NORM_TYPES.values()) | SUBJECT_TYPES, frozenset({"Concept", "Procedure"})),
    "REQUIRES_RECALL": (frozenset(NORM_TYPES.values()) | SUBJECT_TYPES, frozenset({"Concept", "Procedure"})),
}


def normalized(text):
    return " ".join(unicodedata.normalize("NFC", str(text or "")).casefold().split())


def config_digest():
    lang = get_language()
    body = {key: value for key, value in lang.cues.items() if key.startswith("graph_semantic_")}
    body["definition_max_words"] = get_settings().agent.graph_definition_max_words
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def repair_document_anchors(nodes, units):
    """A document identity needs its own source anchor, not every mention of that document.

    Keep existing accepted identities unchanged. A repaired assertion retains
    its ID and takes the corrected literal provenance.
    """
    from ai_core.graph.ocop.links import _quote_citation

    available = {uid for node in nodes if node["node_type"] == "EvidenceUnit"
                 and node.get("check") == "passed" for uid in node.get("evidence_unit_ids", [])}
    repaired = []
    for node in nodes:
        if node["node_type"] != "SourceDocument":
            continue
        refs = node.get("citations", [])
        if refs and set(node.get("evidence_unit_ids", [])) <= available and all(
            ref.get("source_id") == node["source_id"] for ref in refs
        ):
            continue
        own = sorted((u for uid, u in units.items() if uid in available
                      and u["source_id"] == node["source_id"] and u.get("unit_kind") != "page"),
                     key=lambda u: (min(int(s["pdf_page"]) for s in u["spans"]), u["unit_id"]))
        ref = next((ref for unit in own if (ref := _quote_citation(unit, unit.get("text", "")))), None)
        if ref is None:
            continue
        node.update(citations=[ref], evidence_unit_ids=[ref["evidence_unit_id"]],
                    check="passed", review_status="needs_review", derived=True)
        for key in ("machine_candidate", "check_reason", "construction_error"):
            node.pop(key, None)
        repaired.append(node)
    return repaired


def derive_semantics(nodes, edges, units, registry, version):
    from ai_core.graph.ocop.builder import _specific_citation
    from ai_core.graph.ocop.links import _quote_citation
    from ai_core.knowledge.ocop.contracts import contains_document_number

    lang = get_language()
    limits = get_settings().agent
    output, relations = {}, {}
    existing = {node["node_id"]: node for node in nodes}
    existing_by_unit = defaultdict(list)
    units_by_source = defaultdict(list)
    for unit in units.values():
        if unit.get("unit_kind") != "page":
            units_by_source[unit["source_id"]].append(unit)
    for node in nodes:
        for uid in node.get("evidence_unit_ids", []):
            existing_by_unit[uid].append(node)

    def anchors(row):
        found = []
        for ref in row.get("citations", []):
            unit = units.get(ref.get("evidence_unit_id"))
            if unit and ref.get("source_id") == unit["source_id"]:
                checked = _specific_citation(ref, unit)
                if checked and checked not in found:
                    found.append(checked)
        return sorted(found, key=lambda ref: json.dumps(ref, ensure_ascii=False, sort_keys=True))

    def add_node(kind, sid, label, refs, properties, identity=None):
        if not refs:
            return None
        identity = identity or [kind, normalized(label), properties]
        nid = stable_id("semantic_node", sid, identity, revision=version)
        if nid not in output:
            output[nid] = {"node_id": nid, "node_type": kind, "label": label, "source_id": sid,
                           "evidence_unit_ids": sorted({r["evidence_unit_id"] for r in refs}),
                           "citations": refs, "properties": {**properties, "derived": True},
                           "origin": "deterministic", "derived": True, "check": "passed",
                           "review_status": "needs_review", "corpus_version": version,
                           "validation": {"status": "source_grounded", "method": "semantic_projection",
                                          "legal_verified": False}}
        else:
            combined = {json.dumps(ref, ensure_ascii=False, sort_keys=True): ref
                        for ref in [*output[nid]["citations"], *refs]}
            output[nid]["citations"] = [combined[key] for key in sorted(combined)]
            output[nid]["evidence_unit_ids"] = sorted({r["evidence_unit_id"] for r in combined.values()})
        return output[nid]

    def literal_refs(unit, quote):
        ref = _quote_citation(unit, quote)
        return anchors({"citations": [ref]}) if ref else []

    def own_document_refs(doc):
        def available(uid):
            backing = [n for n in existing_by_unit[uid] if n["node_type"] == "EvidenceUnit"]
            return not backing or any(n.get("check") != "failed" and n.get("review_status") != "rejected" for n in backing)

        refs = [r for r in anchors(doc) if r["source_id"] == doc["source_id"] and available(r["evidence_unit_id"])]
        if refs:
            return refs
        for unit in sorted(units_by_source[doc["source_id"]], key=lambda u: u["unit_id"]):
            if available(unit["unit_id"]) and unit.get("text") and (refs := literal_refs(unit, unit["text"])):
                return refs
        return []

    def add_edge(kind, src, dst, refs):
        if not src or not dst or not refs:
            return
        src_types, dst_types = SEMANTIC_ENDPOINTS[kind]
        if src["node_type"] not in src_types or dst["node_type"] not in dst_types:
            raise ValueError("semantic endpoint type mismatch: " + kind)
        eid = stable_id("semantic_edge", src["source_id"], [src["node_id"], kind, dst["node_id"]], revision=version)
        relations[eid] = {"edge_id": eid, "relation_type": kind, "source_entity_id": src["node_id"],
                          "target_entity_id": dst["node_id"], "source_id": src["source_id"],
                          "evidence_unit_ids": sorted({r["evidence_unit_id"] for r in refs}),
                          "citations": refs, "properties": {"derived": True}, "derived": True,
                          "origin": "deterministic", "check": "passed", "review_status": "needs_review",
                          "corpus_version": version,
                          "validation": {"status": "source_grounded", "method": "semantic_projection",
                                         "legal_verified": False}}

    versions = {}
    for doc in sorted(nodes, key=lambda node: node["node_id"]):
        if doc["node_type"] != "SourceDocument" or doc.get("check") == "failed":
            continue
        refs = own_document_refs(doc)
        shas = sorted({r["source_sha256"] for r in refs})
        if len(shas) != 1:
            continue
        sid = doc["source_id"]
        versions[sid] = add_node("DocumentVersion", sid, doc["label"], refs,
                                {"document_id": doc["node_id"], "source_sha256": shas[0],
                                 "valid_from": None, "valid_to": None, "validity_basis": "unknown"},
                                [sid, shas[0]])

    concepts = []
    scope = re.compile(r"(?<!\w)" + lang.alternation("graph_semantic_definition_scope") + r"(?!\w)", re.I)
    copula = lang.alternation("graph_semantic_definition_copula")
    numbering = r"(?:\d+[.)]|[^\W\d_]\))\s+"
    definition = re.compile(rf"^\s*{numbering}(?P<term>[\s\S]+?)\s+{copula}\s+(?P<body>[\s\S]+)$", re.I)
    continuation_scopes = {}
    for source_units in units_by_source.values():
        current = None
        ordered = sorted(source_units, key=lambda u: (
            min((int(s["pdf_page"]), *(s.get("bbox") or [0, 0])[:2][::-1]) for s in u["spans"]), u["unit_id"]))
        for unit in ordered:
            if unit.get("unit_kind") != "paragraph":
                header = re.split(r"(?m)^\s*" + numbering, unit.get("text", ""), maxsplit=1)[0]
                current = unit if unit.get("unit_kind") == "article" and scope.search(header) else None
            elif current is not None:
                continuation_scopes[unit["unit_id"]] = current

    def definition_scope(unit):
        if unit["unit_id"] in continuation_scopes:
            return True
        seen = set()
        while unit and unit["unit_id"] not in seen:
            seen.add(unit["unit_id"])
            if unit.get("unit_kind") == "page":
                return False
            if scope.search(unit.get("text", "")):
                return True
            unit = units.get(unit.get("parent_unit_id"))
        return False

    for uid, unit in sorted(units.items()):
        if unit.get("unit_kind") == "page" or not definition_scope(unit):
            continue
        for line in re.split(r"(?m)(?=^\s*" + numbering + r")", unit.get("text", "")):
            match = definition.match(line)
            if not match or len(match["term"].split()) > limits.graph_definition_max_words:
                continue
            refs = literal_refs(unit, match.group(0).strip())
            if not refs:
                continue
            heading = continuation_scopes.get(uid)
            if heading:
                scope_match = scope.search(heading["text"])
                refs += literal_refs(heading, scope_match.group())
            term = " ".join(match["term"].split())
            concept = add_node("Concept", unit["source_id"], term, refs,
                               {"definition": match["body"].strip(), "aliases": [],
                                "document_version_id": (versions.get(unit["source_id"]) or {}).get("node_id")},
                               [normalized(match["term"]), normalized(match["body"])])
            if concept:
                concepts.append(concept)
                for provision in existing_by_unit[uid]:
                    if provision["node_type"] in PROVISION_TYPES | {"EvidenceUnit"} and provision.get("check") != "failed":
                        add_edge("DEFINES", provision, concept, refs)
                if lang.hit(match["body"], "graph_semantic_subject_definition"):
                    add_node("SubjectType", unit["source_id"], term, refs,
                             {"definition_concept_id": concept["node_id"], "scope": "document_version"},
                             [concept["node_id"], "subject_type"])

    match_indexes = {}

    def matching(text, sid, kinds):
        key = frozenset(kinds)
        if key not in match_indexes:
            grouped = defaultdict(list)
            for node in [*nodes, *output.values()]:
                if node["node_type"] in kinds and node.get("check") != "failed":
                    grouped[normalized(node["label"])].append(node)
            match_indexes[key] = [(re.compile(r"(?<!\w)" + re.escape(label).replace(r"\ ", r"\s+") + r"(?!\w)"), candidates)
                                  for label, candidates in grouped.items() if label]
        found = []
        text = normalized(text)
        for pattern, candidates in match_indexes[key]:
            if not pattern.search(text):
                continue
            local = [node for node in candidates if node["source_id"] == sid]
            candidates = local or candidates
            if len(candidates) == 1:
                found.append(candidates[0])
        return sorted(found, key=lambda node: node["node_id"])

    action_cues = lang.cues["graph_semantic_action_cues"]
    deadline_pattern = re.compile(r"(?<!\w)" + lang.alternation("graph_semantic_deadline_prefix") +
                                  r"\s+(?P<value>\d+)\s+(?P<unit>" +
                                  lang.alternation("graph_semantic_deadline_unit") + r")(?!\w)", re.I)
    for rule in sorted(nodes, key=lambda node: node["node_id"]):
        modality = rule.get("properties", {}).get("modality")
        if rule["node_type"] != "RuleCandidate" or modality not in NORM_TYPES:
            continue
        refs = anchors(rule)
        if not refs:
            continue
        text, sid = refs[0]["quote"], rule["source_id"]
        # The extracted norm frame narrows each field to its own span of the sentence; only spans that are
        # verbatim in the quote are used, otherwise the whole sentence is searched as before.
        frame = {name: value for name, value in (rule.get("properties", {}).get("frame") or {}).items()
                 if isinstance(value, str) and value and value in text}
        subjects = matching(frame.get("actor", text), sid, SUBJECT_TYPES) or matching(text, sid, SUBJECT_TYPES)
        objects = matching(frame.get("object", text), sid, OBJECT_TYPES) or matching(text, sid, OBJECT_TYPES)
        authorities = matching(text, sid, {"Authority"})
        trigger = re.search(r"(?<!\w)" + lang.alternation(action_cues[modality]) + r"(?!\w)", text, re.I)
        action = frame.get("action") or (text[trigger.end():].strip() if trigger else None)
        props = {"statement": text, "kind": NORM_TYPES[modality], "action": action,
                 "actor": frame.get("actor"), "object": frame.get("object"),
                 "condition": frame.get("condition"), "exception": frame.get("exception"), "time": frame.get("time"),
                 "subject_ids": [n["node_id"] for n in subjects], "object_ids": [n["node_id"] for n in objects],
                 "authority_ids": [n["node_id"] for n in authorities], "condition_ids": [], "exception_ids": [],
                 "deadline_ids": [], "valid_from": None, "valid_to": None, "validity_basis": "unknown",
                 "applicability_event": None,
                 "document_version_id": (versions.get(sid) or {}).get("node_id"),
                 "missing_fields": ["validity"] + [name for name, field in (("conditions", "condition"),
                                                                           ("exceptions", "exception"))
                                                   if field not in frame] +
                                   (["subject"] if not subjects else []) + (["action"] if not action else []),
                 "executable": False}
        norm = add_node(NORM_TYPES[modality], sid, text, refs, props,
                        [modality, [(r["evidence_unit_id"], r["quote"]) for r in refs]])
        if not norm:
            continue
        if str(rule.get("origin", "")).startswith("llm"):
            norm["origin"] = rule["origin"]
        for duration in deadline_pattern.finditer(text):
            deadline = add_node("Deadline", sid, duration.group(), refs,
                                {"duration_value": int(duration["value"]), "duration_unit": duration["unit"],
                                 "anchor_event": None, "comparison": None,
                                 "missing_fields": ["anchor_event", "comparison"]},
                                [norm["node_id"], duration.start(), duration.group()])
            norm["properties"]["deadline_ids"] = sorted(set(norm["properties"]["deadline_ids"] + [deadline["node_id"]]))
            add_edge("HAS_DEADLINE", norm, deadline, refs)
        for kind, targets in (("HAS_SUBJECT", subjects), ("HAS_OBJECT", objects), ("HAS_AUTHORITY", authorities)):
            for target in targets:
                add_edge(kind, norm, target, refs + anchors(target))
        for uid in norm["evidence_unit_ids"]:
            for provision in existing_by_unit[uid]:
                if provision["node_type"] in PROVISION_TYPES | {"EvidenceUnit"} and provision.get("check") != "failed":
                    add_edge("HAS_NORM", provision, norm, refs)
        add_edge("IN_VERSION", norm, versions.get(sid), refs)

    marker = lang.alternation("graph_semantic_product_set")
    product_set = re.compile(marker + r"\s*:\s*(?P<label>[^\n]+)", re.I)
    sets = {}
    for sheet in sorted(nodes, key=lambda node: node["node_id"]):
        if sheet["node_type"] != "CriterionSheet" or sheet.get("check") == "failed":
            continue
        refs = anchors(sheet)
        match = next((m for ref in refs if (m := product_set.search(ref["quote"]))), None)
        if match:
            sets[sheet["node_id"]] = add_node("ProductSet", sheet["source_id"], match["label"].strip(), refs,
                                              {"sheet_id": sheet["node_id"], "scope": "document_version"},
                                              [sheet["node_id"], normalized(match["label"])])
            add_edge("USES_SHEET", sets[sheet["node_id"]], sheet, refs)
    for edge in edges:
        if edge["relation_type"] == "CLASSIFIED_UNDER" and edge.get("check") != "failed":
            src = existing.get(edge["source_entity_id"])
            target = sets.get(edge["target_entity_id"])
            add_edge("CLASSIFIED_AS", src, target, anchors(edge))

    for star in nodes:
        if star["node_type"] != "StarLevel" or star.get("check") == "failed":
            continue
        props = star.get("properties", {})
        if props.get("min_points") is None and props.get("max_points") is None:
            continue
        band = add_node("ScoreBand", star["source_id"], star["label"], anchors(star),
                        {key: props.get(key) for key in ("min_points", "max_points", "min_inclusive", "max_inclusive")},
                        [star["node_id"], "interval"])
        add_edge("SCORE_MAPS_TO_RATING", band, star, anchors(star))

    resolved = set()
    form_number = re.compile(r"(?:" + lang.alternation(lang.structure_nouns["form"]) + r")\s*0*(\d+)", re.I)
    for mention in nodes:
        if mention["node_type"] != "Mention":
            continue
        label = mention["label"]
        targets = [node for node in nodes if node["node_type"] == "SourceDocument"
                   and (number := registry.get(node["source_id"], {}).get("document_number"))
                   and contains_document_number(label, number)]
        if not targets:
            form_match = form_number.fullmatch(label.strip())
            if form_match:
                targets = [n for n in nodes if n["node_type"] == "FormTemplate"
                           and n["source_id"] == mention["source_id"]
                           and str(n.get("properties", {}).get("form_id", "")).lstrip("0") == str(int(form_match[1]))]
        if not targets:
            targets = [node for node in concepts if normalized(node["label"]) == normalized(label)]
            local = [node for node in targets if node["source_id"] == mention["source_id"]]
            targets = local or targets
        mention_refs = anchors(mention)
        if not mention_refs:
            for uid in mention.get("evidence_unit_ids", []):
                unit = units.get(uid)
                if not unit:
                    continue
                match = re.search(r"(?<!\w)" + re.escape(label).replace(r"\ ", r"\s+") + r"(?!\w)", unit.get("text", ""), re.I)
                if match:
                    mention_refs.extend(literal_refs(unit, match.group()))
        if len(targets) == 1 and mention_refs:
            target_refs = own_document_refs(targets[0]) if targets[0]["node_type"] == "SourceDocument" else anchors(targets[0])
            if target_refs:
                replacement = {**mention, "citations": mention_refs, "derived": True, "check": "passed",
                               "review_status": "needs_review", "origin": "deterministic",
                               "validation": {"status": "source_grounded", "method": "resolved_reference_candidate", "legal_verified": False},
                               "properties": {**mention.get("properties", {}), "derived": True,
                                              "resolved_candidate_ids": [targets[0]["node_id"]]}}
                replacement.pop("check_reason", None)
                replacement.pop("construction_error", None)
                replacement.pop("machine_candidate", None)
                output[mention["node_id"]] = replacement
                add_edge("REFERS_TO", output.get(mention["node_id"], mention), targets[0], mention_refs + target_refs)
                resolved.add(mention["node_id"])

    for node in output.values():
        for uid in node["evidence_unit_ids"]:
            for evidence in existing_by_unit[uid]:
                if evidence["node_type"] == "EvidenceUnit":
                    add_edge("SUPPORTED_BY", node, evidence,
                             [ref for ref in node["citations"] if ref["evidence_unit_id"] == uid])

    return ([output[key] for key in sorted(output)], [relations[key] for key in sorted(relations)],
            {"nodes": dict(Counter(n["node_type"] for n in output.values())),
             "edges": dict(Counter(e["relation_type"] for e in relations.values())),
             "mentions_with_candidate_target": len(resolved),
             "mentions_without_unique_target": sum(n["node_type"] == "Mention" for n in nodes) - len(resolved),
             "config_sha256": config_digest()})
