"""Check every assertion in the single graph, retaining failures for review.

Text alignment is necessary but not entailment. Each supported predicate has a
positive, bounded check; unsupported/ambiguous assertions get a reason, never a
truth label. Machine observations never acquire legal/scoring verified status.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import re
import math
import json

from ai_core.knowledge.ocop.authorities import find_authorities, resolve
from ai_core.knowledge.ocop.procedures import _subjects, _scope_header, ACTION, collective_authorities
from ai_core.processing.ocop.business_candidates import _recognition_layout, _row_text
from ai_core.knowledge.ocop.shapes import PARENT_SHAPES
from ai_core.knowledge.ocop.contracts import ENTITY_ATTRIBUTE_KEYS, contains_document_number


_LLM_PROVENANCE_KEYS = {"extraction_method", "llm_enriched_attributes"}
USABLE_CHECKS = frozenset({"passed", "human_verified"})


def usable(row):
    return row.get("check") in USABLE_CHECKS


def public_record(row):
    """Consumers never receive the unchecked originals retained for reviewers."""
    return {key: value for key, value in row.items()
            if key not in {"machine_candidate", "attribute_candidates", "human_review"}}


def _origin(row):
    method = row.get("properties", {}).get("extraction_method", "")
    return "llm:" + method.split(":", 1)[1] if method.startswith("llm_candidate:") else "deterministic"
_DOCUMENT_CUES = {
    "REPLACES": r"thay\s+thế|hết\s+hiệu\s+lực",
    "AMENDS": r"sửa\s+đổi|bổ\s+sung",
    "BASED_ON": r"căn\s+cứ",
    "SUSPENDS": r"tạm\s+(?:ngưng|ngừng|đình\s+chỉ)\s+hiệu\s+lực",
}
_UNCERTAIN = re.compile(r"\b(?:không|chưa|nếu|trường hợp|có thể|dự kiến|trừ khi)\b", re.I)


def _document_relation_supported(edge, source, target, registry):
    number = registry.get(target["source_id"], {}).get("document_number")
    if not number or edge["source_id"] != source["source_id"]:
        return False
    for citation in edge.get("citations", []):
        if citation.get("source_id") != source["source_id"]:
            continue
        # Preserve wrapped lines, but never borrow a cue from another numbered
        # clause, article, sentence or legal-basis item in the same EvidenceUnit.
        clauses = re.split(
            r"[;.!?]|\n\s*(?=(?:điều\s+\d+|\d+[.)]\s|[a-zđ][.)]\s|căn\s+cứ\b))",
            citation.get("quote", ""),
            flags=re.I,
        )
        for clause in clauses:
            text = norm(clause)
            if (
                contains_document_number(text, number)
                and not _UNCERTAIN.search(text)
                and re.search(_DOCUMENT_CUES[edge["relation_type"]], text)
            ):
                return True
    return False


def _checked_ownership_proof(edge, checked_edges, nodes):
    """Only an existing ownership edge can use a pair of checked same-row links."""
    if any(_UNCERTAIN.search(q) for q in _quotes(edge)):
        return []
    products, owners = {}, {}
    for link in checked_edges:
        record = nodes[link["source_entity_id"]]
        if record["node_type"] != "RecognitionRecord" or record["source_id"] != edge["source_id"]:
            continue
        if link["relation_type"] == "RECOGNIZES" and link["target_entity_id"] == edge["source_entity_id"]:
            products[record["node_id"]] = link
        elif link["relation_type"] == "DECLARED_BY" and link["target_entity_id"] == edge["target_entity_id"]:
            owners[record["node_id"]] = link
    proof = []
    for record in products.keys() & owners.keys():
        proof.extend(products[record]["citations"])
        proof.extend(owners[record]["citations"])
    return proof


def norm(text):
    return " ".join(str(text or "").split()).casefold()


def _literal(node):
    label = norm(node["label"])
    return len(label) >= 3 and any(label in norm(c.get("quote")) for c in node.get("citations", []))


def _quotes(row):
    return [norm(c.get("quote")) for c in row.get("citations", []) if c.get("quote")]


def _procedure_actor_labels(node, units):
    props=node.get('properties', {})
    statement=props.get('statement_candidate') or node['label']
    subjects=_subjects(statement)
    if subjects:
        return [m[0] for m in subjects]
    body=re.sub(r'^\s*(?:\d+[.)]|[a-zđ][.)])\s*', '', statement, flags=re.I)
    body=re.sub(r'^(?:Chủ\s+động|Thường\s+xuyên)\s+', '', body, flags=re.I)
    context=props.get('context_statement_candidate') or ''
    if not ACTION.match(body) or statement not in context:
        return []
    header=_scope_header(context).strip()
    if not any(context in units.get(uid, {}).get('text', '') for uid in node.get('evidence_unit_ids', [])):
        return []
    if not any(header == c.get('quote', '').strip() for c in node.get('citations', [])):
        return []
    collective=collective_authorities(header)
    if collective:
        return collective
    return [m[0] for m in _subjects(header) if re.fullmatch(r'\s*:\s*',header[m.end():])]


def _number(node):
    found = re.match(r"\s*(\d+(?:[.,]\d+)*)[.,)]?\s*(?=[^\W\d_])", node["label"])
    return found[1].replace(',', '.') if found else None


def _option_parent_supported(source, target, units):
    """Check row scope locally, or across one explicitly linked table boundary."""
    a, b = source['properties'], target['properties']
    def table_unit(node, props):
        for ref in node.get('citations', []):
            unit = units.get(ref.get('evidence_unit_id'), {})
            if (ref.get('row') == props['row']
                    and unit.get('structured', {}).get('table_id') == props.get('table_id')):
                return unit, ref.get('pdf_page')
        return {}, None

    previous, page = table_unit(source, a)
    current, next_page = table_unit(target, b)
    if not previous or not current:
        return False
    if previous['unit_id'] == current['unit_id']:
        if a['row'] >= b['row']:
            return False
        ranges = [(current, a['row'], b['row'])]
    else:
        if (page is None or next_page != page + 1
                or source['source_id'] != target['source_id']
                or a.get('sheet_number_candidate') is None
                or a.get('sheet_number_candidate') != b.get('sheet_number_candidate')):
            return False
        hints = current.get('structured', {}).get('table_continuity', [])
        if not any(h.get('from_pdf_page') == page and h.get('to_pdf_page') == next_page
                   and h.get('from_table_id') == a.get('table_id')
                   and h.get('to_table_id') == b.get('table_id') for h in hints):
            return False
        ranges = [(previous, a['row'], math.inf), (current, -1, b['row'])]
    for unit, start, end in ranges:
        for cell in unit.get('structured', {}).get('cells', []):
            text = str(cell.get('text') or '')
            if start < int(cell.get('row', -1)) < end and (
                    _number({'label': text}) or re.match(r'\s*phần\s+[abc]\b', text, re.I)):
                return False
    return True


def _recognition_role(node, units, role):
    for ref in node.get("citations", []):
        unit = units.get(ref.get("evidence_unit_id"), {})
        rows = _row_text(unit.get("structured", {}).get("cells", []))
        header, columns = _recognition_layout(rows)
        if header is None or role not in columns:
            continue
        for row in rows:
            if row["row"] == header:
                continue
            cell = row["resolved_columns"].get(str(columns[role]), {})
            if norm(cell.get("text")) == norm(node["label"]) and ref.get("row") == cell.get("row"):
                return True
    return False


def _record_rows(node, units):
    for ref in node.get("citations", []):
        if ref.get("row") is None or ref.get("cell_id"):
            continue
        unit = units.get(ref["evidence_unit_id"], {})
        rows = _row_text(unit.get("structured", {}).get("cells", []))
        header, columns = _recognition_layout(rows)
        if header is None or not {"sequence", "product", "producer"} <= columns.keys():
            continue
        for row in rows:
            sequence = row["resolved_columns"].get(str(columns["sequence"]), {}).get("text", "")
            if (
                row["row"] == ref["row"]
                and row["row"] != header
                and re.fullmatch(r"\d+", sequence)
                and sequence == str(node.get("properties", {}).get("row_number"))
            ):
                yield row, columns, ref["evidence_unit_id"]


def _entity_typed(node, units):
    """Reject unsupported role assignments even when the label occurs literally."""
    kind, label = node["node_type"], node["label"]
    contexts = [norm(units[uid].get("text")) for uid in node.get("evidence_unit_ids", []) if uid in units]
    if kind == "Article":
        return bool(re.match(r"điều\s+\d", norm(label)))
    if kind == "Clause":
        return bool(re.match(r"\d+[.)]\s", norm(label)))
    if kind == "Point":
        return bool(re.match(r"[a-zđ][.)]\s", norm(label)))
    if kind == "Criterion":
        return bool(_number(node) or re.match(r"phần\s+[abc]\b", norm(label)))
    if kind == "CriterionSheet":
        return bool(re.search(r"(?:bộ\s+)?sản phẩm\s*:", norm(label)))
    if kind == "ScoreOption":
        return (
            node.get("properties", {}).get("table_id") is not None
            and node.get("properties", {}).get("row") is not None
        )
    if kind == "Organization":
        return bool(
            re.match(r"(?:htx|hợp tác xã|công ty|doanh nghiệp|hộ kinh doanh|tổ hợp tác)\s+\S+", norm(label))
        )
    if kind == "Product":
        literal = re.escape(norm(label))
        return _recognition_role(node, units, "product") or any(
            re.search(
                r"(?:sản phẩm\s*:?\s*"
                + literal
                + r"|"
                + literal
                + r"\s*[,]?\s*đóng\b|"
                + literal
                + r"\s+(?:do|thuộc sở hữu của|có chủ sở hữu là)\s)",
                text,
            )
            for text in contexts
        )
    if kind == "RecognitionRecord":
        return next(_record_rows(node, units), None) is not None
    if kind in {"ProductGroup", "ProductSubgroup"}:
        literal = re.escape(norm(label))
        pattern = (
            r"sản phẩm\s*:\s*" + literal + r"\s*\.\s*nhóm\s*:"
            if kind == "ProductGroup"
            else r"nhóm\s*:\s*" + literal + r"(?:\s*\)|$)"
        )
        if any(re.search(pattern, text) for text in contexts):
            return True
        if kind == "ProductGroup":
            return any(
                any(norm(label) == item.strip() for item in match[1].split(";"))
                for text in contexts
                for match in re.finditer(r"\d+ nhóm sản phẩm\s*:\s*(.*?)\.\s*danh mục", text)
            )
        return False
    if kind == "FormTemplate":
        return bool(re.search(r"mẫu\s*(?:số\s*)?\d+", norm(label)))
    if kind == "EvidenceType":
        return bool(
            re.match(
                r"(?:bản|giấy|phiếu|hợp đồng|văn bản|báo cáo|hồ sơ|tài liệu|đơn|bằng|mẫu)\s+\S", norm(label)
            )
        )
    if kind == "ProcedureStep":
        return bool(_procedure_actor_labels(node, units))
    return kind in {"EvidenceUnit", "Authority", "FormField"}


def _has_citations(row):
    refs = row.get("citations", [])
    return bool(refs) and all(
        c.get("source_id")
        and c.get("evidence_unit_id")
        and isinstance(c.get("pdf_page"), int)
        and c["pdf_page"] >= 1
        and c.get("bbox")
        and len(c["bbox"]) == 4
        and all(isinstance(v, (int, float)) and math.isfinite(v) for v in c["bbox"])
        and c["bbox"][0] <= c["bbox"][2]
        and c["bbox"][1] <= c["bbox"][3]
        and re.fullmatch(r"[0-9a-f]{64}", str(c.get("source_sha256") or ""))
        for c in refs
    )


def _attribute_supported(claim, node, peers):
    """Only simple local feature frames; alternatives remain audit-only."""
    name = claim.get("attribute", "").removesuffix("_candidate")
    if name not in ENTITY_ATTRIBUTE_KEYS.get(node["node_type"], ()):
        return False
    value, label = norm(claim.get("value")), norm(node["label"])
    if not value:
        return False
    for ref in claim.get("evidence", []):
        text = norm(ref.get("quote"))
        if label not in text or value not in text:
            continue
        if re.search(r"\b(?:không|chưa|nếu|dự kiến|có thể|trường hợp|trừ khi)\b", text):
            continue
        # A second subject makes this small verifier abstain rather than borrow its feature.
        if any(
            p["node_id"] != node["node_id"]
            and p["node_type"] == node["node_type"]
            and norm(p["label"]) != label
            and norm(p["label"]) in text
            for p in peers
        ):
            continue
        a, v = re.escape(label), re.escape(value)
        patterns = {
            "packaging": rf"{a}\s*[,:(-]?\s*(?:được\s+)?(?:đóng|bao bì)\s+(?:bằng\s+)?{v}",
            "issuer": rf"{a}\s+do\s+{v}\s+cấp",
            "organization_form": rf"^{v}(?:\s|$)",
            "code": rf"{v}[.,)]?\s+{a}",
        }
        pattern = patterns.get(name)
        if pattern and re.search(pattern, label if name == "organization_form" else text):
            return True
    return False


def _entails(edge, source, target, units):
    relation = edge["relation_type"]
    a, b = source.get("properties", {}), target.get("properties", {})
    quotes = _quotes(edge)
    if relation == "SUPPORTED_BY":
        return bool(set(edge["evidence_unit_ids"]) & set(target["evidence_unit_ids"]))
    if relation == "LOCATED_IN":
        return source["source_id"] == target["source_id"]
    if relation == "HAS_ARTICLE":
        return bool(
            b.get("article_number")
            and any(
                re.search(r"^điều\s+" + re.escape(str(b["article_number"])) + r"(?:\b|[.:])", q)
                for q in _quotes(target)
            )
        )
    if relation == "HAS_CLAUSE":
        return bool(
            a.get("article_number")
            and a.get("article_number") == b.get("article_number")
            and b.get("clause_number")
            and any(re.match(re.escape(str(b["clause_number"])) + r"[.)]\s", q) for q in _quotes(target))
        )
    if relation == "HAS_POINT":
        return bool(
            a.get("clause_number")
            and b.get("point_letter")
            and any(re.match(re.escape(str(b["point_letter"])) + r"[.)]\s", q) for q in _quotes(target))
        )
    if relation == "HAS_CRITERION":
        return bool(
            str(a.get("sheet_number")) == str(b.get("sheet_number_candidate"))
            and b.get("part_letter")
            and any(
                re.match(r"phần\s+" + re.escape(str(b["part_letter"]).casefold()) + r"\b", q)
                for q in _quotes(target)
            )
        )
    if relation == "HAS_SUBCRITERION":
        child, parent = _number(target), _number(source)
        same_scope = (
            a.get("table_id") is not None
            and a.get("table_id") == b.get("table_id")
            or a.get("sheet_number_candidate") is not None
            and a.get("sheet_number_candidate") == b.get("sheet_number_candidate")
        )
        return bool(
            same_scope
            and child
            and (parent and child.rpartition(".")[0] == parent or a.get("part_letter") and "." not in child)
        )
    if relation == "HAS_OPTION":
        if not b.get("parent_identified") or a.get("row") is None or b.get("row") is None:
            return False
        if not _option_parent_supported(source, target, units):
            return False
        return not bool(
            re.match(r"\s*(?:không đánh giá|ghi chú|chú ý|chỉ áp dụng|tổng)", target["label"], re.I)
        )
    if relation == "DEFINES_GROUP":
        return any("nhóm sản phẩm:" in q and norm(target["label"]) in q for q in _quotes(source))
    if relation in {"HAS_SUBGROUP", "USES_SHEET"}:
        group = norm(source["label"]) if relation == "HAS_SUBGROUP" else None
        subgroup = norm(target["label"]) if relation == "HAS_SUBGROUP" else norm(source["label"])
        return any(
            re.search(
                r"sản phẩm\s*:\s*"
                + (re.escape(group) if group else r".+?")
                + r"\.\s*nhóm\s*:\s*"
                + re.escape(subgroup)
                + r"(?:\s*\)|$)",
                q,
            )
            for q in quotes
        )
    if relation == "HAS_FIELD":
        return bool(
            not a.get("reference_only")
            and _literal(target)
            and any(norm(target["label"]) in q for q in _quotes(source))
        )
    if relation == "RESPONSIBLE_FOR":
        statement = b.get("statement_candidate") or target["label"]
        conditional = r"\b(?:nếu|trường\s+hợp|trừ\s+khi|có\s+thể|dự\s+kiến|không|chưa)\b"
        scoped = r"^\s*(?:(?:\d+|[a-zđ])[.)]\s*)?đối\s+với\b"
        if re.search(conditional, statement, re.I) or re.search(scoped, statement, re.I):
            return False
        if re.search(r'đối\s+với', statement, re.I):
            # Only relax object phrases for an explicit, single inspection actor.
            # Recognition/withdrawal scopes and embedded actors still abstain.
            subjects = _subjects(statement)
            if len(subjects) != 1 or not re.fullmatch(
                    r'\s*(?:(?:\d+|[a-zđ])[.)]\s*)?', statement[:subjects[0].start()], re.I):
                return False
            if not re.match(r'\s*:?\s*(?:kiểm\s+tra|theo\s+dõi|giám\s+sát|xử\s+lý)\b',
                            statement[subjects[0].end():], re.I):
                return False
        # A split action can inherit a condition earlier in the same source
        # sentence. Do not discard it just because another actor starts a slice.
        for uid in target.get('evidence_unit_ids', []):
            text = units.get(uid, {}).get('text', '')
            if statement in text:
                prefix = text[:text.index(statement)]
                local_prefix = re.split(r'[;.!?]|\n\s*(?:\d+|[a-zđ])[.)]\s+', prefix, flags=re.I)[-1]
                if re.search(conditional, local_prefix, re.I) or re.search(scoped, local_prefix, re.I):
                    return False
        return any(
            (canonical := resolve(label)) and canonical["canonical_id"] == a.get("canonical_id")
            for label in _procedure_actor_labels(target, units)
        )
    if relation == "REQUIRES_EVIDENCE":
        # Re-read the parent statement, not a citation containing only the document noun.
        statements = [a.get("statement_candidate") or ""] + [
            c.get("quote", "") for c in source.get("citations", [])
        ]
        for statement in statements:
            text = norm(statement)
            for sentence in re.split(r"[;.!?]", text):
                label = norm(target["label"])
                if label not in sentence:
                    continue
                prefix = sentence[: sentence.index(label)]
                if _UNCERTAIN.search(sentence) or re.search(r"chỉ\s+áp\s+dụng", sentence):
                    continue
                if re.search(
                    r"(?:phải có|nộp|gửi kèm|cung cấp|hồ sơ[^;.!?]*(?:bao gồm|gồm))\s*:?[^;.!?]*$", prefix
                ):
                    # Output certificates are not documents the applicant must submit.
                    if not re.search(r"(?:cấp|thu hồi|ban hành)\s*$", prefix):
                        return True
        return False
    if relation == "OWNED_BY":
        # Co-occurrence or "sản xuất" alone is not ownership.
        product, owner = re.escape(norm(source["label"])), re.escape(norm(target["label"]))
        return any(
            re.search(product + r"\s+(?:thuộc sở hữu của|có chủ sở hữu là)\s+" + owner, q)
            and not _UNCERTAIN.search(q)
            for q in quotes
        )
    if relation == "HAS_RECORD":
        return (
            source["source_id"] == target["source_id"] and next(_record_rows(target, units), None) is not None
        )
    if relation in {"RECOGNIZES", "DECLARED_BY"}:
        role = "product" if relation == "RECOGNIZES" else "producer"
        for row, columns, uid in _record_rows(source, units):
            cell = row["resolved_columns"].get(str(columns[role]), {})
            if norm(cell.get("text")) == norm(target["label"]) and any(
                ref.get("evidence_unit_id") == uid
                and ref.get("row") == cell.get("row")
                and norm(ref.get("quote")) == norm(cell.get("text"))
                for ref in target.get("citations", [])
            ):
                return True
        return False
    # Temporal interpretation, stars, awards and free-text conditions need stronger
    # domain-specific verification. A citation or deterministic origin is insufficient.
    return False


def _prune_invalid_parents(accepted, edges, exclude):
    parent_shapes = {
        **PARENT_SHAPES,
        "FormField": ({"HAS_FIELD"}, 1, 1),
        "RecognitionRecord": ({"HAS_RECORD"}, 1, 1),
    }
    incoming = defaultdict(lambda: defaultdict(set))
    for edge in edges:
        incoming[edge["target_entity_id"]][edge["relation_type"]].add(edge["source_entity_id"])
    while True:
        drop = {}
        for identity, node in accepted.items():
            shape = parent_shapes.get(node["node_type"])
            if not shape:
                continue
            predicates, minimum, maximum = shape
            parents = {
                parent
                for relation in predicates
                for parent in incoming[identity][relation]
                if parent in accepted
            }
            if len(parents) < minimum:
                drop[identity] = "required_parent_not_accepted"
            elif maximum is not None and len(parents) > maximum:
                drop[identity] = "ambiguous_parentage"
        if not drop:
            break
        for identity, reason in drop.items():
            accepted.pop(identity)
            exclude("node", identity, reason)
        remaining = []
        for edge in edges:
            if edge["source_entity_id"] not in accepted or edge["target_entity_id"] not in accepted:
                exclude("edge", edge["edge_id"], "endpoint_removed_by_shape_check")
            else:
                remaining.append(edge)
        edges = remaining
    # A record can pass its local predicate checks and still lose its parent.
    # Ownership may only depend on record links that survive the shape check.
    remaining = []
    for edge in edges:
        if (
            edge["relation_type"] == "OWNED_BY"
            and edge.get("check") != "human_verified"
            and not _entails(edge, accepted[edge["source_entity_id"]], accepted[edge["target_entity_id"]], {})
            and not _checked_ownership_proof(edge, edges, accepted)
        ):
            exclude("edge", edge["edge_id"], "ownership_record_support_not_accepted")
        else:
            remaining.append(edge)
    return remaining


def _node_exclusion_reason(node, units, registry):
    kind = node["node_type"]
    reason = None
    if node.get("review_status") == "rejected":
        reason = "rejected_assertion"
    elif kind in {
        "RuleCandidate",
        "CandidateFact",
        "CriterionRowCandidate",
        "Mention",
        "StarLevel",
        "Condition",
    }:
        reason = "no_automatic_domain_verifier"
    elif kind == "SourceDocument":
        if not any(u["source_id"] == node["source_id"] and u.get("spans") for u in units.values()):
            reason = "source_not_in_evidence_registry"
    elif kind == "RecognitionDecision":
        if not (
            registry.get(node["source_id"], {}).get("source_kind") == "recognition_decision"
            and any(
                u.get("source_id") == node["source_id"] and re.search(r"công\s+nhận", u.get("text", ""), re.I)
                for u in units.values()
            )
        ):
            reason = "recognition_document_role_not_grounded"
    elif not _has_citations(node):
        reason = "incomplete_provenance"
    elif kind == "Authority":
        if not any(
            (canonical := resolve(label))
            and canonical["canonical_id"] == node.get("properties", {}).get("canonical_id")
            for c in node.get("citations", [])
            for label in ([m[0] for m in find_authorities(c.get("quote", ""))]
                          + collective_authorities(c.get("quote", "")))
        ):
            reason = "authority_alias_not_grounded"
    elif kind != "EvidenceUnit" and not _literal(node):
        reason = "entity_label_not_grounded"
    if (
        reason is None
        and kind not in {"SourceDocument", "RecognitionDecision"}
        and not _entity_typed(node, units)
    ):
        reason = "entity_type_not_supported_by_source_frame"
    return reason


def _add_supported_attributes(view, node, peers, exclude):
    claims = []
    for claim in node.get("attribute_claims", []):
        conflict = node.get("properties", {}).get(claim["attribute"].removesuffix("_candidate") + "_conflict")
        if not conflict and _attribute_supported(claim, node, peers):
            accepted_claim = deepcopy(claim)
            accepted_claim["attribute"] = claim["attribute"].removesuffix("_candidate")
            accepted_claim["status"] = "source_grounded"
            claims.append(accepted_claim)
            view["properties"][accepted_claim["attribute"]] = claim["value"]
        else:
            view.setdefault("attribute_checks", []).append({"attribute": claim["attribute"],
                "check": "failed", "check_reason": "attribute_association_not_proven_or_conflicting"})
            exclude(
                "attribute",
                node["node_id"] + ":" + claim["attribute"],
                "attribute_association_not_proven_or_conflicting",
            )
    if claims:
        view["attribute_claims"] = claims


def check_graph(nodes, edges, units, *, registry=None):
    registry = registry or {}
    accepted, exclusions = {}, []

    def exclude(kind, identity, reason):
        exclusions.append({"record_type": kind, "record_id": identity, "reason": reason})

    safe_properties = {
        "article_number",
        "clause_number",
        "point_letter",
        "position",
        "sheet_number",
        "sheet_number_candidate",
        "table_id",
        "row",
        "part_letter",
        "level",
        "form_number",
        "reference_only",
        "canonical_id",
        "unit_kind",
        "row_number",
        *_LLM_PROVENANCE_KEYS,
    }
    for node in nodes:
        identity, kind = node["node_id"], node["node_type"]
        human = node.get("check") == "human_verified"
        reason = node.get("construction_error") or (
            None if human and _has_citations(node) else _node_exclusion_reason(node, units, registry))
        if reason:
            exclude("node", identity, reason)
            continue
        view = {
            k: deepcopy(v)
            for k, v in node.items()
            if k not in {"machine_candidate", "human_review", "attribute_candidates", "attribute_claims"}
        }
        view["properties"] = {
            k.removesuffix("_candidate"): v
            for k, v in node.get("properties", {}).items()
            if k in safe_properties
        }
        if kind == "RecognitionRecord":
            view["label"] = "Dòng " + str(node["properties"]["row_number"]) + " — " + node["source_id"]
        elif kind == "SourceDocument":
            view["label"] = registry.get(node["source_id"], {}).get("document_number") or node["source_id"]
        # Keep verified business values in the reviewed view only; this automatic
        # view deliberately exposes observations, not legal/scoring decisions.
        _add_supported_attributes(view, node, nodes, exclude)
        if human:
            view["properties"] = deepcopy(node.get("properties", {}))
        if kind == 'EvidenceUnit' and len(node.get('evidence_unit_ids',[])) == 1:
            # Copy the backing transcription, never candidate business attributes.
            # Runtime lookup no longer needs a parallel candidates/evidence store.
            backing=units.get(node['evidence_unit_ids'][0],{})
            view['properties'].update({'evidence_text':backing.get('text',''),
                'source_spans':deepcopy(backing.get('spans',[])),
                'structured':deepcopy(backing.get('structured') or {}),
                'source_order':node.get('properties',{}).get('source_order',0)})
        view["validation"] = {
            "status": "source_grounded",
            "method": "literal_entity_or_registered_identity",
            "legal_verified": False,
        }
        accepted[identity] = view
    out_edges = []
    by_id = {n["node_id"]: n for n in nodes}
    # Record links must be checked before ownership, independent of file order.
    for edge in sorted(edges, key=lambda row: row["relation_type"] == "OWNED_BY"):
        src, dst = edge["source_entity_id"], edge["target_entity_id"]
        ownership_proof = (
            _checked_ownership_proof(edge, out_edges, by_id) if edge["relation_type"] == "OWNED_BY" else []
        )
        reason = None
        if edge.get("construction_error"):
            reason = edge["construction_error"]
        elif edge.get("review_status") == "rejected":
            reason = "rejected_assertion"
        elif src not in accepted or dst not in accepted:
            reason = "endpoint_not_accepted"
        elif not _has_citations(edge):
            reason = "incomplete_provenance"
        elif edge.get("check") != "human_verified" and not (
            ownership_proof
            or (
                _document_relation_supported(edge, by_id[src], by_id[dst], registry)
                if edge["relation_type"] in _DOCUMENT_CUES
                else _entails(edge, by_id[src], by_id[dst], units)
            )
        ):
            reason = "predicate_not_entailed_by_supported_verifier"
        if reason:
            exclude("edge", edge["edge_id"], reason)
            continue
        view = {
            k: deepcopy(v)
            for k, v in edge.items()
            if k not in {"properties", "attribute_candidates", "machine_candidate", "human_review"}
        }
        view["properties"] = {
            k: deepcopy(v) for k, v in edge.get("properties", {}).items() if k in _LLM_PROVENANCE_KEYS
        }
        # Include the actual parent/subject context used by the predicate check,
        # not just a document noun or an endpoint's name.
        proof = list(view["citations"]) + ownership_proof
        for endpoint in (by_id[src], by_id[dst]):
            proof.extend(
                c
                for c in endpoint.get("citations", [])
                if c.get("quote") and c.get("evidence_unit_id") in edge["evidence_unit_ids"]
            )
        unique = {json.dumps(c, sort_keys=True, ensure_ascii=False): c for c in proof}
        view["citations"] = list(unique.values())
        view["validation"] = {
            "status": "source_grounded",
            "method": "predicate:" + edge["relation_type"],
            "legal_verified": False,
        }
        out_edges.append(view)
    # Local predicate checks do not establish graph-wide cardinality. Ambiguous
    # parentage is excluded in full; never choose whichever parent was read first.
    out_edges = _prune_invalid_parents(accepted, out_edges, exclude)
    checked_edges = {row["edge_id"]: row for row in out_edges}
    reasons = {(r["record_type"], r["record_id"]): r["reason"] for r in exclusions}
    def annotate(original, accepted_row, kind, identity):
        row = deepcopy(accepted_row if accepted_row is not None else original)
        row.pop("construction_error", None)
        row.pop("check_reason", None)
        row["origin"] = _origin(original)
        if accepted_row is None:
            row["check"] = "failed"
            row["check_reason"] = reasons[(kind, identity)]
        else:
            row["check"] = "human_verified" if original.get("check") == "human_verified" else "passed"
            # Keep the exact reviewed content/hash while exposing only checked
            # properties to consumers. There is still one row per assertion.
            row["machine_candidate"] = deepcopy(original.get("machine_candidate") or original)
        if original.get("human_review"):
            row["human_review"] = deepcopy(original["human_review"])
        return row
    checked_nodes = [annotate(n, accepted.get(n["node_id"]), "node", n["node_id"]) for n in nodes]
    checked_relations = [annotate(e, checked_edges.get(e["edge_id"]), "edge", e["edge_id"]) for e in edges]
    summary = {"policy": "source_predicate_and_ledger_checks", "nodes": {}, "edges": {}}
    for category, rows in (("nodes", checked_nodes), ("edges", checked_relations)):
        counts = Counter(row["check"] for row in rows)
        summary[category] = {status: counts[status] for status in ("passed", "failed", "human_verified")}
    return checked_nodes, checked_relations, summary
