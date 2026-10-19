"""Deterministic, capability-driven tool DAG with bounded execution.

A route advertises business capabilities; the planner resolves *server-owned*
ToolSpecs and dependencies. Language model output cannot register tools,
change authorization or bypass corpus provenance.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
from ai_core.orchestration.ocop.contracts import Intent, Route
from ai_core.orchestration.ocop.retrieval_strategy import RetrievalPath,choose_retrieval_path
from ai_core.orchestration.ocop.capabilities import (
    TOOL_REGISTRY, TOOL_DEPENDENCIES, PRIVATE_TOOLS, MAX_TOOL_CALLS)

MAX_TOOLS = MAX_TOOL_CALLS
# A transport/contract failure is not a legitimate zero-hit lookup. Never
# disguise these errors as a successful text recovery.
RECOVERY_BLOCKING_STATUSES = frozenset({
    'tool_unavailable', 'dependency_unavailable', 'invalid_tool_output',
    'backend_unavailable', 'index_unavailable', 'not_ready',
    'document_not_found_or_ambiguous', 'recognition_year_scope_unverified',
    'assessment_year_scope_unverified', 'recognition_scope_unverified',
    'local_guidance_not_in_corpus', 'incomplete_form_ids',
    'form_source_scope_unverified', 'form_version_ambiguous',
    'local_guidance_document_scope_mismatch',
})


def recovery_safe(route: Route, outputs: list[dict], plan: ToolPlan) -> bool:
    """Only recover ordinary non-scoped misses, never failed services or policies."""
    if not plan.text_recovery or len(outputs) >= plan.max_calls:
        return False
    if any(x.get('tool') == 'search_regulations' for x in outputs):
        return False
    if any((x.get('output') or {}).get('status') in RECOVERY_BLOCKING_STATUSES
           for x in outputs):
        return False
    # Region and assessment-year queries require a verified, scope-aware
    # lookup. Generic text recovery must not make a legal assertion about them.
    if any(route.slots.get(key) for key in (
        'region', 'recognition_year', 'assessment_year', 'as_of_date'
    )):
        return False
    # Router may extract the issuance year inside an explicit decision code.
    # That is not a separate historical event-year constraint, and the text
    # retriever still enforces the requested document's source ID.
    document_years=set(re.findall(r'20\d{2}',str(route.slots.get('document_code') or '')))
    requested_years={str(y) for y in (route.slots.get('years') or [])}
    if requested_years-document_years:
        return False
    return True



@dataclass(frozen=True)
class Task:
    name: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolPlan:
    names: tuple[str, ...]
    max_calls: int = MAX_TOOLS
    graph_hops: int = 2
    text_recovery: bool = False
    tasks: tuple[Task, ...] = ()
    retrieval_path: RetrievalPath = RetrievalPath.NONE
    decision_reason: str = ''


def _ordered_tasks(requested: tuple[str, ...]) -> tuple[Task, ...]:
    seen=set();visiting=set();order=[]
    requested_set=set(requested)
    def visit(name: str):
        if name in seen:return
        if name in visiting:raise ValueError('Circular OCOP tool dependency')
        if name not in TOOL_REGISTRY:raise ValueError('Routing requested an unregistered tool')
        visiting.add(name)
        for prereq in TOOL_DEPENDENCIES.get(name, ()):
            if prereq in requested_set:visit(prereq)
        visiting.remove(name)
        seen.add(name)
        order.append(Task(name,tuple(prereq for prereq in TOOL_DEPENDENCIES.get(name, ()) if prereq in requested_set)))
    for name in requested:visit(name)
    return tuple(order)


def build_plan(route: Route, *, graph_available: bool | None = None) -> ToolPlan:
    if route.needs_clarification or route.intent in (Intent.CLARIFY, Intent.OUT_OF_SCOPE):
        return ToolPlan(())
    requested=list(dict.fromkeys(route.required_tools))
    reasons=[]
    if 'search_graph' in requested:
        if graph_available is False:
            # Graph index absent: never pretend traversal ran successfully.
            requested=[name for name in requested if name!='search_graph']
            if 'search_regulations' not in requested:requested.append('search_regulations')
            reasons.append('graph_index_unavailable_text_fallback')
        elif not route.slots.get('graph_seed_ids') and 'search_regulations' not in requested:
            # Graph node IDs are not guessed from query text. First retrieve
            # evidence units, then link only their verified graph node IDs.
            requested.insert(0,'search_regulations')
            reasons.append('graph_seed_bootstrap_from_text_evidence')
    requested=tuple(requested)
    if len(requested)>MAX_TOOLS:
        raise ValueError('OCOP task plan exceeds configured tool budget; clarify/split query')
    if not set(requested).issubset(TOOL_REGISTRY):
        raise ValueError('Routing requested an unregistered tool')
    priv=set(requested)&PRIVATE_TOOLS
    if priv and len(priv)!=len(requested):
        raise PermissionError('Private dossier results cannot be mixed with public retrieval')
    tasks=_ordered_tasks(requested)
    # A bounded recall attempt is allowed if independent structured tools
    # yielded zero source evidence. Recovery never changes explicit source ID.
    recover=not priv and 'search_regulations' not in requested and route.strategy in (
        'exact','structured','graph_hybrid','hybrid')
    return ToolPlan(tuple(t.name for t in tasks), tasks=tasks, text_recovery=recover,
                    retrieval_path=choose_retrieval_path(list(requested)),
                    decision_reason=','.join(reasons) or 'intent_and_available_tools')


def evidence_ids(outputs: list[dict], *, verified_only: bool = False) -> list[str]:
    ids=[]
    for entry in outputs:
        payload=entry.get('output',{})
        if not isinstance(payload,dict):continue
        for row in payload.get('results',[]):
            if isinstance(row,dict):
                if verified_only and (row.get('review_status')!='verified' or
                    not row.get('source_id') or not any(
                        isinstance(span,dict) and isinstance(span.get('pdf_page'),int)
                        and span['pdf_page']>0 for span in
                        (row.get('source_spans') or row.get('spans') or []))):
                    continue
                ident=row.get('evidence_unit_id') or row.get('unit_id')
                if ident and ident not in ids:ids.append(str(ident))
    return ids[:20]


def needs_recovery(route: Route, outputs: list[dict], plan: ToolPlan) -> bool:
    if not recovery_safe(route, outputs, plan):
        return False
    return not evidence_ids(outputs)
