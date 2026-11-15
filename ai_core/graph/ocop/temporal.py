"""Conservative temporal applicability — never auto-upgrade date mentions to law."""

from __future__ import annotations
from datetime import date


def applicable(
    rule: dict, *, as_of_date: date, region: str | None = None, procedure: str | None = None
) -> dict:
    if rule.get("review_status") != "verified":
        return {"status": "unknown", "reason": "unverified_rule"}
    try:
        start = date.fromisoformat(rule["effective_from"]) if rule.get("effective_from") else None
        end = date.fromisoformat(rule["effective_to"]) if rule.get("effective_to") else None
    except (TypeError, ValueError):
        return {"status": "unknown", "reason": "invalid_date"}
    if not start:
        return {"status": "unknown", "reason": "no_verified_effective_from"}
    if region and rule.get("jurisdiction") not in (None, "nationwide", region):
        return {"status": "not_applicable", "reason": "different_jurisdiction"}
    if procedure and rule.get("procedure_type") not in (None, procedure):
        return {"status": "not_applicable", "reason": "different_procedure"}
    if rule.get("suspended") or rule.get("transition_window"):
        return {"status": "unknown", "reason": "requires_transition_resolution"}
    if as_of_date < start or end and as_of_date >= end:
        return {"status": "not_applicable", "reason": "outside_effective_period"}
    return {"status": "applicable", "reason": "verified_dates_and_scope"}


def resolve_event_applicability(
    rule: dict,
    *,
    as_of_date: date,
    event_year: int | None = None,
    region: str | None = None,
    procedure: str | None = None,
    corpus_version: str | None = None,
) -> dict:
    """Deny silent criterion migration across assessment years.

    A decision's issuance date is NOT the evaluation event year. The system
    requires a verified transition rule before moving a recognition case
    between 2023/2025/2026 OCOP assessment schemas.
    """
    if corpus_version and rule.get("corpus_version") != corpus_version:
        return {"status": "unknown", "reason": "corpus_version_mismatch"}
    verdict = applicable(rule, as_of_date=as_of_date, region=region, procedure=procedure)
    if verdict["status"] != "applicable":
        return verdict
    if event_year is not None:
        if not isinstance(event_year, int) or not 1900 <= event_year <= 2100:
            return {"status": "unknown", "reason": "invalid_event_year"}
        audited = rule.get("assessment_year")
        if audited is None:
            return {"status": "unknown", "reason": "no_verified_assessment_year"}
        if audited != event_year:
            return {"status": "not_applicable", "reason": "different_assessment_year"}
    if rule.get("recognition_issued_at") and rule.get("recognition_event_year") is None:
        return {"status": "unknown", "reason": "recognition_year_must_be_checked_separately"}
    return verdict
