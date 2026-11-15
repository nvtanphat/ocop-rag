"""Domain-aware evidence grading before generation.

No LLM verdict is promoted to a verified OCOP rule. Relevance and coverage
are retrieval diagnostics, not a proof of legal applicability. Conservative,
source-aware, and suitable for offline deterministic regression tests.
"""

from __future__ import annotations
import re
import unicodedata

from ai_core.retrieval.ocop.settings import get_settings
from ai_core.orchestration.ocop.language import fold, get_language
from ai_core.orchestration.ocop.query_frames import identity_request, identity_coverage
from ai_core.orchestration.ocop.planner import RECOVERY_BLOCKING_STATUSES

STOPWORDS = frozenset(
    "cho tôi về là những các của và theo cần có với một trong được như nào gì hãy thì khi OCOP sản phẩm".casefold().split()
)
STRUCTURED_TOOLS = frozenset(
    {
        "lookup_product_subgroup",
        "lookup_criterion",
        "lookup_evidence_requirements",
        "lookup_form",
        "lookup_recognition",
        "resolve_temporal_applicability",
    }
)


def tokens(text: str) -> set[str]:
    cleaned = unicodedata.normalize("NFC", text).casefold()
    return {t for t in re.findall(r"[\wÀ-ỹ]+", cleaned) if len(t) > 1 and t not in STOPWORDS}


def rows_for(entry: dict) -> list[dict]:
    data = entry.get("output") or {}
    if not isinstance(data, dict):
        return []
    return [r for r in data.get("results", []) if isinstance(r, dict)]


def has_provenance(row: dict) -> bool:
    spans = row.get("source_spans") or row.get("spans")
    return (
        bool(row.get("source_id"))
        and isinstance(spans, list)
        and any(
            isinstance(s, dict) and isinstance(s.get("pdf_page"), int) and s["pdf_page"] > 0 for s in spans
        )
    )


def _text(row: dict) -> str:
    return " ".join(
        str(row.get(k) or "")
        for k in ("text", "evidence_text", "row_text", "label_candidate", "title", "source_id")
    )


def uncovered_parts(query: str, row_tokens: list[set[str]]) -> list[str]:
    """Parts of a compound question that no scope-valid evidence row speaks to (a part is covered when one row holds
    at least agent.part_min_coverage of its content words). A question that is not compound has no parts to miss."""
    from ai_core.retrieval.ocop.decompose import sub_queries

    missed = []
    for part in sub_queries(query):
        wanted = tokens(part)
        if wanted and not any(len(wanted & row) / len(wanted) >= get_settings().agent.part_min_coverage for row in row_tokens):
            missed.append(part)
    return missed


def grade_evidence(
    query: str,
    results: list[dict],
    *,
    slots: dict | None = None,
    expected_tools: list[str] | tuple[str, ...] = (),
    min_relevance: float | None = None,
) -> dict:
    """Inspect all required capabilities, not just whether some BM25 hit exists.

    grade status is *retrieval-sufficient*, never 'legal verified'. Unknown
    applicability is explicitly distinguished from contradictory evidence.
    """
    slots = slots or {}
    min_relevance = get_settings().agent.grader_min_relevance if min_relevance is None else min_relevance
    relevant_query = tokens(query)
    scored = []
    capabilities = []
    missing = []
    expected = set(expected_tools)
    scoped_rows = []
    for entry in results:
        name = str(entry.get("tool") or "")
        output = entry.get("output") or {}
        rows = rows_for(entry)
        graded = []
        source_rows = []
        for row in rows:
            if not has_provenance(row):
                continue
            tt = tokens(_text(row))
            relevance = len(relevant_query & tt) / len(relevant_query) if relevant_query else 0.0
            scope = "unknown"
            if slots.get("document_code"):
                # Wrong document must not be counted as applicable. Some tools
                # already resolve the code into source_id; preserve source. A comparison names several documents.
                wanted = slots.get("document_codes") or [slots["document_code"]]
                if not any(
                    all(
                        re.search(r"(?<!\d)" + re.escape(part) + r"(?!\d)", str(row.get("source_id", "")))
                        for part in re.findall(r"\d+", str(code))
                    )
                    for code in wanted
                    if re.findall(r"\d+", str(code))
                ):
                    relevance = 0.0
                    scope = "mismatch"
            region = slots.get("region")
            jurisdiction = str(row.get("jurisdiction") or "")
            nationwide = {fold(label) for label in get_language().nationwide_labels}
            if region and jurisdiction and fold(jurisdiction) not in {*nationwide, fold(str(region))}:
                scope = "mismatch"
                relevance = 0.0
            elif scope != "mismatch" and (not region or jurisdiction):
                scope = "not_contradicted"
            if relevance > 0 or not relevant_query:
                scoped_rows.append(tt)
            graded.append(
                {
                    "evidence_unit_id": row.get("evidence_unit_id") or row.get("unit_id"),
                    "source_id": row.get("source_id"),
                    "relevance": round(relevance, 3),
                    "review_status": row.get("review_status", "needs_review"),
                    "applicability": scope,
                }
            )
            source_rows.append(row)
        requested = identity_request(query, name, slots)
        identities = None
        if requested and not output.get("fallback") and output.get("status", "ok") not in RECOVERY_BLOCKING_STATUSES:
            eligible = [r for r, g in zip(source_rows, graded) if r.get("review_status") == "verified" and g["applicability"] == "not_contradicted"]
            identities = identity_coverage(eligible, requested, name)
            if identities:
                for row, item in zip(source_rows, graded):
                    key = (row.get("source_id"), tuple(sorted(row.get("graph_node_ids") or [])))
                    if key in identities and row.get("review_status") == "verified" and item["applicability"] == "not_contradicted":
                        item["structured_identity_match"] = True
        hits = [v for v in graded if (v["relevance"] >= min_relevance or v.get("structured_identity_match")) and v["applicability"] != "mismatch"]
        # A structured business tool with a legitimate zero/unknown result is
        # *not* considered solved by a nearby generic search snippet.
        resolved = bool(hits) and (
            name not in STRUCTURED_TOOLS
            or (
                output.get("status") not in RECOVERY_BLOCKING_STATUSES | {"unknown"}
                and (
                    name != "resolve_temporal_applicability"
                    or (
                        output.get("status") == "checked_verified_rules"
                        and output.get("applicability_status") in ("applicable", "not_applicable")
                        and all(
                            isinstance(r.get("verdict"), dict)
                            and r["verdict"].get("status") in ("applicable", "not_applicable")
                            for r in rows
                        )
                    )
                )
                and not output.get("fallback")
                and all(x["review_status"] == "verified" for x in hits)
                and identities != set()
            )
        )
        if name in STRUCTURED_TOOLS and not resolved and not entry.get("optional"):
            missing.append(name)
        capabilities.append(
            {
                "tool": name,
                "evidence_count": len(graded),
                "relevant_count": len(hits),
                "structured_resolved": resolved,
                "status": output.get("status", "ok"),
                "optional": bool(entry.get("optional")),
                "direct_lookup_complete": bool(identities) and resolved,
            }
        )
        scored.extend(graded)
    present = {entry.get("tool") for entry in results}
    missing.extend(sorted(expected - present))
    missing = list(dict.fromkeys(missing))
    relevant = sum(c["relevant_count"] for c in capabilities)
    direct_coverage = any(c["direct_lookup_complete"] for c in capabilities)
    uncovered = uncovered_parts(query, scoped_rows) if relevant and not direct_coverage else []
    if not relevant:
        status = "none"
    elif missing or uncovered:
        status = "partial"
    else:
        status = "sufficient_for_generation"
    return {
        "status": status,
        "missing_tools": missing,
        "uncovered_parts": uncovered,
        "tool_grades": capabilities,
        "evidence_grades": scored[:80],
        "relevant_evidence_count": relevant,
        "verified_business_resolution": all(
            c["structured_resolved"] for c in capabilities if c["tool"] in STRUCTURED_TOOLS and not c["optional"]
        )
        and not missing,
        "applicability_verdict": "unconfirmed"
        if slots.get("as_of_date")
        and not any(
            c["tool"] == "resolve_temporal_applicability" and c["structured_resolved"] for c in capabilities
        )
        else "not_contradicted",
    }


def bounded_rewrite(query: str, missing_tools: list[str], slots: dict) -> str:
    """No generative rewrite that can silently replace years, localities or IDs."""
    from ai_core.orchestration.ocop.capabilities import TOOL_REGISTRY

    bad = set(missing_tools) - set(TOOL_REGISTRY)
    if bad:
        raise ValueError("Unregistered tool supplied to rewrite")
    from ai_core.orchestration.ocop.language import get_language

    terms = get_language().cues["tool_search_terms"]
    supplements = " ".join(" ".join(terms[k]) for k in missing_tools if k in terms)
    # Ensure original query remains intact at front, including years/decision.
    return (query.strip() + " " + supplements).strip()
