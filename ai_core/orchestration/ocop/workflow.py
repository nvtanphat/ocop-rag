"""A single OCOP workflow: route -> bounded tools -> evidence -> answer.

LangGraph uses conditional branches, rather than running an agent loop for
simple lookups. The dependency-free runner shares exactly the same nodes.
External model and graph services are optional, never simulated.
"""

from __future__ import annotations
import json
import os
import re
from pathlib import Path
from time import monotonic
from typing import TypedDict
from ai_core.orchestration.ocop.contracts import AgentResponse, Route, Intent, AuthContext
from ai_core.orchestration.ocop.router import OWN_SCOPE_SLOTS, route_query, extract_slots, _merge_followup
from ai_core.orchestration.ocop import aspects, diacritics_model, followup_model, memory, scope_model, semantic_route
from ai_core.orchestration.ocop.planner import (
    ToolPlan, build_plan, evidence_ids, recovery_safe, executed_tool_count, RECOVERY_BLOCKING_STATUSES,
)
from ai_core.orchestration.ocop.capabilities import ENRICHMENT_TOOLS, Capability
from ai_core.orchestration.ocop.tools import ToolRegistry
from ai_core.orchestration.ocop.answer import assemble, BAD_RESULT_STATUSES
from ai_core.system.telemetry import traced
from ai_core.system.checkpoints import SQLiteCheckpoint, thread_key, should_checkpoint
from ai_core.orchestration.ocop.evidence_grader import grade_evidence, bounded_rewrite, tokens as grade_tokens
from ai_core.orchestration.ocop.llm import OpenAICompatClient
from ai_core.retrieval.ocop.search import query_content_bigram_coverage
from ai_core.retrieval.ocop.settings import get_settings
from ai_core.orchestration.ocop.catalog import load_catalog
from ai_core.orchestration.ocop.language import fold, get_language
from ai_core.orchestration.ocop.privacy import redact


MEMORY_ROWS = 3  # remembered evidence rows added to a follow-up turn at most
# Record lookups that found nothing in scope: in a compound question they leave only their own part unanswered.
PART_SCOPED_STATUSES = frozenset({"recognition_scope_unverified", "entity_not_found"})



# What a dependency returns when it ran correctly and found nothing (not a service failure).
EMPTY_DEPENDENCY_STATUSES = frozenset({"no_results", "not_found", "entity_not_found"})

class OcopState(TypedDict, total=False):
    query: str
    effective_query: str
    context: dict
    session: dict
    route: dict
    plan: ToolPlan
    results: list[dict]
    answer: dict
    auth: AuthContext | None
    trace: list[dict]
    evidence_coverage: dict
    evidence_grade: dict
    rewrite_method: str


# First line of every answer served from a partial corpus; clients show it as a notice, not as content.
PARTIAL_CORPUS_NOTICE = "[Corpus chưa đầy đủ — kết quả chỉ để thử nghiệm]"


class OcopAgent:
    def __init__(
        self,
        root: Path,
        *,
        llm: OpenAICompatClient | None = None,
        retrieval_mode: str = "sparse",
        rerank: bool = False,
        allow_partial_debug: bool = False,
    ):
        self.root = Path(root)
        self.tools = ToolRegistry(self.root)
        self.llm = llm
        self.retrieval_mode = retrieval_mode
        self.rerank = rerank
        self.allow_partial_debug = allow_partial_debug is True
        self._checkpoint = None
        # Semantic tier of the router (example utterances, embedding similarity); None switches it off.
        self.semantic_route = semantic_route.for_index(self.tools.index_dir)

    def _catalog(self):
        try:
            return load_catalog(self.tools.index_dir)
        except (OSError, ValueError, KeyError):
            return load_catalog(self.root / "data/processed/ocop/none")

    def route(self, state: OcopState) -> dict:
        query = state["query"]
        session = state.get("session") or {}
        # Identity originates only from a trusted AuthContext, never a session.
        safe_session = {
            key: session[key]
            for key in ("last_query", "slots", "intent", "capabilities", "unresolved")
            if key in session
        }
        if "memory" in session:
            safe_session["memory"] = memory.sanitize(session["memory"])
        auth = state.get("auth")
        if isinstance(auth, AuthContext):
            safe_session["tenant_id"] = auth.tenant_id
        def decide(text: str):
            return route_query(
                text,
                session=safe_session,
                # The model proposes an intent only for a question no deterministic signal covers, and costs one extra
                # model round trip: opt-in (OCOP_LLM_ROUTER=1). The deterministic route is the default.
                llm_route=(self.llm.route if self.llm and os.getenv("OCOP_LLM_ROUTER") == "1" else None),
                # Asked only where no deterministic signal separates a follow-up from an off-topic question.
                llm_scope=((lambda question: scope_model.propose(self.llm, question)) if self.llm else None),
                semantic_route=self.semantic_route,
                indexed_content_bigram_coverage=lambda question: query_content_bigram_coverage(
                    self.tools.index_dir, question
                ),
                catalog=self._catalog(),
            )

        method = "none"
        # Every step below reads accented Vietnamese; a question typed without diacritics is restored first, and only
        # when removing the marks again gives back the user's exact text (diacritics_model).
        if self.llm is not None and diacritics_model.needs_restoring(query):
            if restored := diacritics_model.propose(self.llm, query, self.tools.abbreviations()):
                query, method = restored, "diacritics_restored"
        choice = decide(query)
        effective = query
        # A reference the rules cannot place ("phiếu đó" when no sheet number was ever typed) is not dangling when the
        # question before names what it points at in words ("...phiếu chấm nhóm nào?"). ViCAS-RAG restates a follow-up
        # with the model before it routes; here the rules still decide first and only a restatement that passes the
        # validator (no name or number the conversation did not say) replaces the clarification, routed as a question of
        # its own. Without one the user is asked, as before.
        if "reference_unresolved" in choice.reason_codes and self.llm is not None:
            recent = (safe_session.get("memory") or {}).get("recent") or []
            if recent and (restated := followup_model.propose(self.llm, query, recent[::-1])):
                choice, effective, method = decide(restated), restated, "model_rewrite"
        if choice.dialogue.acts and choice.dialogue.action == "task":
            from ai_core.orchestration.ocop.dialogue import understand

            _, effective = understand(query)
            method = "dialogue_task_remainder"
        if "dialogue_revalidate_topic" in choice.reason_codes:
            effective = (safe_session.get("memory") or {}).get("standalone") or safe_session["last_query"]
            method = "dialogue_revalidate_topic"
        elif "clarification_resumed" in choice.reason_codes:
            effective = str(safe_session["unresolved"]["question"]) + " " + query
            method = "clarification_resumed"
        if choice.intent == Intent.FOLLOWUP or "followup_slot_override" in choice.reason_codes:
            updates = extract_slots(effective, catalog=self._catalog())
            carried = memory.plural_referents(effective, safe_session.get("memory"), updates)
            if (safe_session.get("memory") or {}).get("standalone"):
                effective, method = memory.rewrite(
                    effective,
                    safe_session["memory"],
                    choice.slots,
                    updates,
                    carried=carried,
                    previous_slots=safe_session.get("slots"),
                )
                if carried:
                    method += "+compare"
                # A follow-up is restated by the model from the recent questions (ViCAS-RAG, Legal-RAG): the rules state
                # the scope of the thing named last, which "hãng đó" or "siro lúc nãy" may not mean, and an elliptical
                # turn with no pronoun at all ("vậy nộp hồ sơ cho ai?") has nothing for them to replace. A turn that is
                # already self-contained comes back unchanged and the validator keeps the rule rewrite.
                # The restatement says what the question is about: a carried name it no longer writes is dropped and the
                # names it writes are taken, else the last turn's slots scope the tools to the thing "nó" no longer
                # means ("nó" = chè khô after nước mắm searched the fish-sauce sheet). The route stays a follow-up.
                recent = safe_session["memory"]["recent"]
                if self.llm is not None and recent:
                    if restated := followup_model.propose(self.llm, query, recent[::-1]):
                        effective, method = restated, "model_rewrite"
                        kept = {
                            key: value
                            for key, value in choice.slots.items()
                            if not isinstance(value, str) or fold(value) in fold(restated)
                        }
                        choice = choice.model_copy(
                            update={"slots": {**kept, **extract_slots(restated, catalog=self._catalog())}}
                        )
            elif choice.intent == Intent.FOLLOWUP:
                previous = str(session.get("last_query") or "")
                if "years" in updates:
                    previous = re.sub(r"\b20\d{2}\b", updates["years"][-1], previous)
                # Text query is only for ranking. Structured tools use effective
                # merged slots, so stale values in prose cannot change their scope.
                # Only the two questions' own words: a label word added here would be searched for like evidence.
                effective = previous + " " + query
                method = "legacy_concat"
        # "Ai là chủ thể sản xuất?" after a question about one product: no rule found a signal of its own, the intent
        # came only from example utterances, and the question names no scope. In a conversation that is a follow-up
        # the router did not see; the model restates it under the same validator (a self-contained question comes back
        # unchanged). Questions any rule understood are left alone: restating those cost ranking on the session set.
        recent = (safe_session.get("memory") or {}).get("recent") or []
        if (
            method == "none"
            and recent
            and self.llm is not None
            and "semantic_intent" in choice.reason_codes
            and not set(extract_slots(query, catalog=self._catalog())) & OWN_SCOPE_SLOTS
            and (restated := followup_model.propose(self.llm, query, recent[::-1]))
        ):
            effective, method = restated, "model_rewrite"
            choice = choice.model_copy(
                update={"slots": {**choice.slots, **extract_slots(restated, catalog=self._catalog())}}
            )
        return {
            "route": choice.model_dump(mode="json"),
            "effective_query": effective,
            "rewrite_method": method,
            "trace": [
                {
                    "step": "route",
                    "intent": choice.intent.value,
                    "tools": list(choice.required_tools),
                    "reasons": choice.reason_codes,
                    "retrieval_path": choice.retrieval_path.value,
                }
            ],
        }

    def plan(self, state: OcopState) -> dict:
        route = Route.model_validate(state["route"])
        # Backend capability is checked at execution planning time, not guessed
        # from the user's question or an LLM-supplied tool list.
        graph_dir = getattr(self.tools, "graph_dir", None)
        graph_ready = bool(
            graph_dir is not None
            and (graph_dir / "manifest.json").is_file()
            and (graph_dir / "nodes.jsonl").is_file()
            and (graph_dir / "edges.jsonl").is_file()
        )
        plan = build_plan(route, graph_available=graph_ready)
        route.retrieval_path = plan.retrieval_path
        route.required_tools = list(plan.required_names)
        route.secondary_tools = sorted(plan.optional)
        trace = list(state.get("trace") or [])
        trace.append(
            {
                "step": "retrieval_strategy",
                "retrieval_path": plan.retrieval_path.value,
                "tools": list(plan.names),
                "reason": plan.decision_reason,
                "graph_available": graph_ready,
            }
        )
        return {"plan": plan, "route": route.model_dump(mode="json"), "trace": trace}

    def _trusted_context(self, state: OcopState) -> dict:
        provided = state.get("context") or {}
        route = Route.model_validate(state["route"])
        slots = route.slots
        # Never import authenticated, tenant, verified_criteria, verified_answers,
        # graph_seed_ids, temporal_rule or server permissions from a user dict.
        context = {
            "retrieval_mode": self.retrieval_mode,
            "rerank": self.rerank,
            "allow_partial_debug": self.allow_partial_debug,
            "business_intent": route.intent.value,
            "prefer_current": not self._asks_version(route),
        }
        # A compound question is restated as self-contained sub-questions once per question (model, validated).
        query = state.get("effective_query", state["query"])
        if self.llm is not None and self._compound(query, route):
            cache = self.__dict__.setdefault("_aspect_cache", {})
            if query not in cache:
                cache[query] = aspects.propose(self.llm, query)
            if cache[query]:
                context["aspects"] = cache[query]
        if slots.get("as_of_date"):
            context["as_of_date"] = slots["as_of_date"]
        elif isinstance(provided.get("as_of_date"), str) and re.fullmatch(
            r"20\d{2}-\d{2}-\d{2}", provided["as_of_date"]
        ):
            context["as_of_date"] = provided["as_of_date"]
        return context

    @staticmethod
    def _asks_version(route: Route) -> bool:
        """A question that names a year, a document or a change over time may be about an older version on purpose."""
        return bool(
            route.slots.get("years")
            or route.slots.get("document_code")
            or route.slots.get("document_codes")
            or Capability.TEMPORAL.value in route.capabilities
        )

    @staticmethod
    def _verified_slots(results: list[dict]) -> dict:
        # The only additional slots propagated between tasks must come from
        # *verified source-backed* unique values, not LLM/candidate OCR.
        candidates: dict[str, set[str]] = {}
        for entry in results:
            for row in (entry.get("output") or {}).get("results", []):
                if not isinstance(row, dict) or row.get("review_status") != "verified":
                    continue
                if not row.get("source_id") or not any(
                    isinstance(span, dict) and isinstance(span.get("pdf_page"), int) and span["pdf_page"] > 0
                    for span in (row.get("source_spans") or row.get("spans") or [])
                ):
                    continue
                for name in ("product_group", "product_subgroup", "criterion_id", "sheet_id"):
                    if isinstance(row.get(name), str) and row[name].strip():
                        candidates.setdefault(name, set()).add(row[name].strip())
        return {k: next(iter(values)) for k, values in candidates.items() if len(values) == 1}

    @staticmethod
    def _validate_output(output: object) -> dict:
        """Tool adapters are an untrusted failure boundary, even if allowlisted."""
        if (
            not isinstance(output, dict)
            or not isinstance(output.get("results", []), list)
            or not all(isinstance(row, dict) for row in output.get("results", []))
        ):
            return {"results": [], "status": "invalid_tool_output"}
        if "status" in output and not isinstance(output["status"], str):
            return {"results": [], "status": "invalid_tool_output"}
        return output

    @staticmethod
    def _dependency_ready(output: dict) -> bool:
        """Only verified, source-backed observations may feed dependent tools."""
        if output.get("status") in (
            "tool_unavailable",
            "dependency_unavailable",
            "dependency_empty",
            "invalid_tool_output",
            "not_found",
            "not_ready",
            "unknown",
            "recognition_scope_unverified",
            "entity_not_found",
            "assessment_year_scope_unverified",
            "recognition_year_scope_unverified",
            "text_evidence_fallback",
            "document_not_found_or_ambiguous",
        ) or output.get("fallback"):
            return False
        return any(
            isinstance(row, dict)
            and row.get("review_status") == "verified"
            and bool(row.get("source_id"))
            and any(
                isinstance(span, dict) and isinstance(span.get("pdf_page"), int) and span["pdf_page"] > 0
                for span in (row.get("source_spans") or row.get("spans") or [])
            )
            for row in output.get("results", [])
        )

    @staticmethod
    def _graph_seed_rows(output: dict) -> list[dict]:
        """Source locations may seed a checked graph without becoming business facts."""
        if output.get("status") in BAD_RESULT_STATUSES or output.get("fallback"):
            return []
        return [
            row
            for row in output.get("results", [])
            if isinstance(row, dict)
            and row.get("review_status") != "rejected"
            and row.get("source_id")
            and (row.get("evidence_unit_id") or row.get("unit_id"))
            and any(
                isinstance(span, dict)
                and isinstance(span.get("pdf_page"), int)
                and span["pdf_page"] > 0
                and isinstance(span.get("bbox"), (list, tuple))
                and len(span["bbox"]) == 4
                and re.fullmatch(r"[0-9a-f]{64}", str(span.get("source_sha256") or ""))
                for span in (row.get("source_spans") or row.get("spans") or [])
            )
        ]

    def execute(self, state: OcopState) -> dict:
        route = Route.model_validate(state["route"])
        plan = state.get("plan") or build_plan(route)
        results = []
        trace = list(state.get("trace") or [])
        if route.needs_clarification or route.intent in (Intent.OUT_OF_SCOPE, Intent.CONVERSATION):
            return {"results": [], "trace": trace}
        context = self._trusted_context(state)
        ordered = plan.tasks or tuple()
        task_map = {task.name: task for task in ordered}
        finished = {}

        def predecessor_names(name: str) -> set[str]:
            seen = set()
            pending = list(task_map[name].depends_on)
            while pending:
                parent = pending.pop()
                if parent in seen:
                    continue
                seen.add(parent)
                if parent in task_map:
                    pending.extend(task_map[parent].depends_on)
            return seen

        for task in ordered:
            name = task.name
            if executed_tool_count(results) >= plan.max_calls:
                break
            if task.optional:
                primary = [entry for entry in results if not entry.get("optional")]
                blocking = {
                    (entry.get("output") or {}).get("status") for entry in primary
                } & RECOVERY_BLOCKING_STATUSES
                # A record lookup that found nothing in scope settles only its own part of a compound question.
                blocked = bool(blocking) and not (
                    name == "search_regulations"
                    and blocking <= PART_SCOPED_STATUSES
                    and self._compound(state.get("effective_query", state["query"]), route)
                )
                grade = grade_evidence(
                    state.get("effective_query", state["query"]), primary,
                    slots=route.slots, expected_tools=list(plan.required_names),
                )
                complete = (
                    name == "search_regulations"
                    and grade["status"] == "sufficient_for_generation"
                    and any(g.get("direct_lookup_complete") for g in grade["tool_grades"])
                )
                if blocked or complete:
                    output = {"results": [], "status": "not_needed"}
                    results.append({"tool": name, "output": output, "optional": True, "skipped": True})
                    finished[name] = output
                    trace.append({"step": "tool", "name": name, "skipped": True, "optional": True,
                                  "status": "not_needed", "reason": "required_tool_blocked" if blocked else "direct_lookup_complete",
                                  "hits": 0, "latency_ms": 0.0})
                    continue
            failed = [
                dep
                for dep in task.depends_on
                if not self._dependency_ready(finished.get(dep, {}))
                and not (name == "search_graph" and self._graph_seed_rows(finished.get(dep, {})))
            ]
            if failed:
                # A dependency that ran and found nothing is an ordinary miss: the child is skipped, but the bounded text
                # recovery may still answer. Only a failed service (or policy stop) blocks recovery.
                empty = all((finished.get(dep) or {}).get("status") in EMPTY_DEPENDENCY_STATUSES for dep in failed)
                output = {"results": [], "status": "dependency_empty" if empty else "dependency_unavailable"}
                results.append(
                    {
                        "tool": name,
                        "output": output,
                        "skipped": True,
                        **({"optional": True} if task.optional else {}),
                    }
                )
                finished[name] = output
                trace.append(
                    {
                        "step": "tool",
                        "name": name,
                        "dependencies": list(task.depends_on),
                        "optional": task.optional,
                        "status": output["status"],
                        "hits": 0,
                        "latency_ms": 0.0,
                    }
                )
                continue
            # Only propagate verified source evidence from completed prerequisites.
            # An explicit user slot overrides enrichment from those prerequisites.
            ancestors = predecessor_names(name)
            predecessors = [entry for entry in results if entry["tool"] in ancestors]
            tool_slots = {**self._verified_slots(predecessors), **route.slots}
            context["retrieved_evidence_ids"] = evidence_ids(results, verified_only=True)
            if name == "search_graph":
                context["retrieved_evidence_ids"] = evidence_ids(
                    [
                        {"output": {"results": self._graph_seed_rows(entry.get("output") or {})}}
                        for entry in results
                    ]
                )
            started = monotonic()
            try:
                output = self.tools.dispatch(
                    name,
                    query=state.get("effective_query", state["query"]),
                    slots=tool_slots,
                    context=context,
                    auth=state.get("auth"),
                )
            except (RuntimeError, FileNotFoundError, TimeoutError, OSError) as exc:
                if isinstance(exc, RuntimeError) and (
                    "Dense index not built" in str(exc)
                    or "qdrant-client is required" in str(exc)
                    or "sentence-transformers required" in str(exc)
                ):
                    raise
                output = {"results": [], "status": "tool_unavailable", "error_type": type(exc).__name__}
            output = self._validate_output(output)
            results.append({"tool": name, "output": output, **({"optional": True} if task.optional else {})})
            finished[name] = output
            trace.append(
                {
                    "step": "tool",
                    "name": name,
                    "dependencies": list(task.depends_on),
                    "optional": task.optional,
                    "status": output.get("status", "ok"),
                    "hits": len(output.get("results", [])),
                    "latency_ms": round((monotonic() - started) * 1000, 2),
                }
            )
        results.extend(self._memory_evidence(state, route, results, trace))
        return {"results": results, "trace": trace}

    def _memory_evidence(
        self, state: OcopState, route: Route, results: list[dict], trace: list[dict]
    ) -> list[dict]:
        """Evidence the conversation already cited, re-read from the corpus when this turn is a follow-up.

        Only references are remembered; text comes from the current index, and a reference is dropped when the corpus
        changed or the new question is scoped to documents that do not include its source.
        """
        session = state.get("session") or {}
        if (
            not (route.intent == Intent.FOLLOWUP or "followup_slot_override" in route.reason_codes)
            or not session.get("memory")
            or not get_settings().agent.memory_evidence_reuse
        ):
            return []
        slots = route.slots
        codes = slots.get("document_codes") or (
            [slots["document_code"]] if slots.get("document_code") else []
        )
        scope = None
        if codes:
            scope = {sid for sid in (self.tools._resolve_source_id(str(c)) for c in codes) if sid}
        kept, dropped = memory.reusable_evidence(
            session["memory"], corpus_version=self._corpus_version(), source_ids=scope
        )
        have = {
            r.get("chunk_id")
            for entry in results
            for r in (entry.get("output") or {}).get("results", [])
            if isinstance(r, dict)
        }
        # Reuse is for a question that leans on what was already shown ("Nó thì sao?", "Hai mẫu này khác nhau ở đâu?"). When
        # the user swapped in a new thing ("Còn Điều 7?") the old evidence is about something else.
        how = str(state.get("rewrite_method") or "")
        if not (
            how.split(":")[0].split("+")[0] in ("previous_standalone", "state_scope")
            or how.endswith("+compare")
        ):
            return []
        rows = self.tools.chunks_by_reference(kept, exclude=have, limit=40)
        wanted = grade_tokens(state.get("effective_query", state["query"]))
        scored = sorted(
            (
                (len(wanted & grade_tokens(str(r.get("raw_text") or r.get("text")))), i, r)
                for i, r in enumerate(rows)
            ),
            key=lambda x: (-x[0], x[1]),
        )
        rows = [r for score, _, r in scored if score > 0][:MEMORY_ROWS]
        if not rows:
            return []
        trace.append({"step": "memory_evidence", "reused": len(rows), "dropped": len(dropped)})
        return [
            {
                "tool": "memory_evidence",
                "output": {"results": rows, "status": "ok"},
                "memory": True,
                "optional": True,
            }
        ]

    def recover(self, state: OcopState) -> dict:
        route = Route.model_validate(state["route"])
        plan = state.get("plan") or build_plan(route)
        results = list(state.get("results") or [])
        trace = list(state.get("trace") or [])
        grade = state.get("evidence_grade") or grade_evidence(
            state.get("effective_query", state["query"]),
            results,
            slots=route.slots,
            expected_tools=list(plan.required_names),
        )
        if not self._should_recover(state, grade):
            return {"results": results, "trace": trace}
        context = self._trusted_context(state)
        started = monotonic()
        # Targeted: evidence already found for the covered parts stays; only the parts nothing speaks to are searched,
        # each scoped by what it names itself. Without uncovered parts (a missing structured tool) the question is rewritten.
        parts = list(grade.get("uncovered_parts") or [])[:plan.max_calls - executed_tool_count(results)]
        call_count = 0
        rewritten = bounded_rewrite(
            state.get("effective_query", state["query"]), grade.get("missing_tools", []), route.slots
        )
        try:
            if parts:
                found = []
                for part in parts:
                    call_count += 1
                    found.append(self.tools.search_part(part, route.slots, context, state.get("auth")))
                rows = [
                    {**row, "query_part": part}
                    for part, one in zip(parts, found)
                    for row in one.get("results", [])[:4]
                ]
                payload = {"results": rows, "status": "ok" if rows else "no_results"}
            else:
                call_count = 1
                payload = self.tools.dispatch(
                    "search_regulations",
                    query=rewritten,
                    slots=route.slots,
                    context=context,
                    auth=state.get("auth"),
                )
        except (RuntimeError, FileNotFoundError, TimeoutError, OSError) as exc:
            if isinstance(exc, RuntimeError) and (
                "Dense index not built" in str(exc)
                or "qdrant-client is required" in str(exc)
                or "sentence-transformers required" in str(exc)
            ):
                raise
            payload = {"results": [], "status": "tool_unavailable", "error_type": type(exc).__name__}
        payload = self._validate_output(payload)
        results.append({"tool": "search_regulations", "output": payload, "recovery": True, "call_count": call_count})
        trace.append(
            {
                "step": "recovery",
                "name": "search_regulations",
                "reason": "uncovered_question_parts" if parts else "insufficient_or_irrelevant_evidence",
                "parts": parts,
                "call_count": call_count,
                "status": payload.get("status", "ok"),
                "hits": len(payload.get("results", [])),
                "latency_ms": round((monotonic() - started) * 1000, 2),
            }
        )
        return {"results": results, "trace": trace}

    @classmethod
    def _passages_state_year(cls, items: list[dict], slots: dict) -> bool:
        """Text may stand in for an undated record only when the passages themselves name the year asked about; a year
        no passage mentions (a future year, another cycle) stays a refusal rather than being answered from a neighbour."""
        years = {
            str(slots[key]) for key in ("recognition_year", "assessment_year") if slots.get(key)
        } or {str(y) for y in slots.get("years") or []}
        text = " ".join(
            str(row.get("text") or row.get("evidence_text") or "")
            for item in items
            if cls._usable_rows(item)
            for row in (item.get("output") or {}).get("results", [])
            if isinstance(row, dict)
        )
        return bool(years) and all(re.search(r"(?<!\d)" + re.escape(year) + r"(?!\d)", text) for year in years)

    @staticmethod
    def _compound(query: str, route: Route) -> bool:
        """The question asks several things: the router found several capabilities or the retriever splits it."""
        from ai_core.retrieval.ocop.decompose import sub_queries

        return len(route.capabilities) > 1 or bool(sub_queries(query))

    @staticmethod
    def _usable_rows(item: dict) -> bool:
        output = item.get("output") or {}
        return output.get("status") not in BAD_RESULT_STATUSES and any(
            isinstance(r, dict) and r.get("source_id") for r in output.get("results", [])
        )

    def grade(self, state: OcopState) -> dict:
        route = Route.model_validate(state["route"])
        plan = state.get("plan") or build_plan(route)
        result = grade_evidence(
            state.get("effective_query", state["query"]),
            state.get("results") or [],
            slots=route.slots,
            expected_tools=list(plan.required_names),
        )
        trace = list(state.get("trace") or [])
        trace.append(
            {
                "step": "evidence_grade",
                "status": result["status"],
                "relevant_evidence": result["relevant_evidence_count"],
                "missing_tools": result["missing_tools"],
            }
        )
        return {"evidence_grade": result, "trace": trace}

    def _should_recover(self, state: OcopState, grade: dict | None = None) -> bool:
        route = Route.model_validate(state["route"])
        plan = state.get("plan") or build_plan(route)
        outputs = state.get("results") or []
        if not recovery_safe(route, outputs, plan):
            return False
        result = (
            grade
            or state.get("evidence_grade")
            or grade_evidence(
                state.get("effective_query", state["query"]),
                outputs,
                slots=route.slots,
                expected_tools=list(plan.required_names),
            )
        )
        return result["status"] in ("none", "partial")

    def verify(self, state: OcopState) -> dict:
        """Report tool/evidence coverage; never mistake citation presence for entailment.

        An empty structured result or an unknown temporal verdict remains
        visibly incomplete even if another tool found related text.
        """
        route = Route.model_validate(state["route"])
        outputs = state.get("results") or []
        if route.needs_clarification or route.intent in (Intent.OUT_OF_SCOPE, Intent.CONVERSATION):
            return {"evidence_coverage": {"status": "not_applicable", "tools": []}}
        checks = []
        for entry in [x for x in outputs if not x.get("optional")]:
            output = entry.get("output") or {}
            rows = output.get("results", [])
            usable = bool(rows) and any(
                isinstance(row, dict)
                and row.get("source_id")
                and (row.get("source_spans") or row.get("spans"))
                for row in rows
            )
            # Temporal rules with 'unknown' are not considered verified source.
            if entry.get("tool") == "resolve_temporal_applicability":
                usable = (
                    output.get("status") == "checked_verified_rules"
                    and bool(rows)
                    and all(
                        isinstance(r, dict)
                        and r.get("verdict", {}).get("status") in ("applicable", "not_applicable")
                        for r in rows
                    )
                )
            structured_names = {
                "lookup_product_subgroup",
                "lookup_criterion",
                "lookup_evidence_requirements",
                "lookup_form",
                "lookup_recognition",
                "resolve_temporal_applicability",
            }
            # This metric refers to *verified structured business outcomes*,
            # not successful text retrieval (or valid citation markers).
            business_resolved = (
                usable
                and entry.get("tool") in structured_names
                and (
                    not output.get("fallback")
                    and (
                        (output.get("status") == "checked_verified_rules" and usable)
                        or bool(rows)
                        and all(isinstance(r, dict) and r.get("review_status") == "verified" for r in rows)
                    )
                )
            )
            checks.append(
                {
                    "name": entry.get("tool"),
                    "has_source_evidence": usable,
                    "business_resolved": business_resolved,
                    "status": output.get("status", "ok"),
                }
            )
        ok = sum(int(x["has_source_evidence"]) for x in checks)
        if ok == 0:
            status = "none"
        elif ok == len(checks):
            status = "complete"
        else:
            status = "partial"
        grade = state.get("evidence_grade") or {}
        if grade.get("status") in ("none", "partial") and status == "complete":
            status = "partial"
        return {
            "evidence_coverage": {
                "status": status,
                "tools": checks,
                "source_coverage_ratio": round(ok / len(checks), 3) if checks else 0,
                "grader_status": grade.get("status", "not_run"),
                "missing_tools": grade.get("missing_tools", []),
                "verified_business_resolution_ratio": round(
                    sum(int(x["business_resolved"]) for x in checks) / len(checks), 3
                )
                if checks
                else 0,
            }
        }

    def answer(self, state: OcopState) -> dict:
        route = Route.model_validate(state["route"])
        if route.intent == Intent.CONVERSATION:
            from ai_core.orchestration.ocop.dialogue import respond

            return {"answer": {"answer": respond(route.dialogue), "status": "conversation", "citations": []}}
        if route.needs_clarification:
            if "tool_budget_exceeded" in route.reason_codes:
                return {
                    "answer": {
                        "answer": "Câu hỏi gồm nhiều phần tra cứu độc lập. "
                        "Vui lòng gửi từng câu riêng, chẳng hạn phân nhóm sản phẩm, tiêu chí "
                        "hoặc hồ sơ/minh chứng, để không bỏ sót nguồn cần đối chiếu.",
                        "status": "clarify",
                        "citations": [],
                    }
                }
            messages = get_language().messages
            return {
                "answer": {
                    "answer": messages.clarify_prefix
                    + ", ".join(messages.clarify_slots.get(slot, slot) for slot in route.missing_slots),
                    "status": "clarify",
                    "citations": [],
                }
            }
        if route.intent == Intent.OUT_OF_SCOPE:
            return {
                "answer": {
                    "answer": get_language().messages.private_unsupported
                    if "private_dossier_unsupported" in route.reason_codes
                    else get_language().messages.out_of_scope,
                    "status": "out_of_scope",
                    "citations": [],
                }
            }
        every = state.get("results") or []
        # Optional (secondary) tools enrich an answer; their gaps are reported, never block it.
        outputs = [item for item in every if not item.get("optional")]
        if any(
            (item.get("output") or {}).get("status") == "requested_pdf_page_not_indexed" for item in outputs
        ):
            return {
                "answer": {
                    "answer": "Trang PDF được yêu cầu chưa có trong corpus đã lập chỉ mục; "
                    "không dùng trang khác để suy ra nội dung trang này.",
                    "status": "insufficient_page_scope",
                    "citations": [],
                }
            }
        notices = []
        temporal_unverified = False  # a notice states that no verified validity rule was applied
        unresolved = sorted(
            {
                str(code)
                for item in outputs
                for code in (item.get("output") or {}).get("unresolved_documents", [])
            }
        )
        absent = (
            "Không có trong dữ liệu đã lập chỉ mục: văn bản "
            + ", ".join(unresolved)
            + "; không dùng văn bản khác thay thế."
            if unresolved
            else ""
        )
        if absent:
            notices.append(absent)
        narrower = sorted({
            label for item in outputs for label in ((item.get("output") or {}).get("narrower_scope") or [])
        })
        if narrower:
            notices.append("Nguồn này là hướng dẫn riêng của " + "; ".join(narrower) + ", chưa chắc áp dụng cho toàn địa bàn được hỏi.")
        ambiguous_sheet = [item for item in outputs if (item.get("output") or {}).get("status") == "sheet_document_ambiguous"]
        if ambiguous_sheet:
            # Several documents carry a sheet with this number: ask which one, naming the candidates.
            candidates = list(
                dict.fromkeys(
                    doc for item in ambiguous_sheet for doc in ((item.get("output") or {}).get("candidate_documents") or [])
                )
            )
            question = "Phiếu này có trong nhiều văn bản (" + "; ".join(candidates) + "). Bạn muốn tra phiếu của văn bản nào?"
            if any(self._usable_rows(item) for item in outputs if item not in ambiguous_sheet):
                notices.append(question)
            else:
                return {"answer": {"answer": question, "status": "clarify", "citations": []}}
        if any((item.get("output") or {}).get("status") == "sheet_scope_unavailable" for item in outputs):
            # Another sheet's options are never substituted. If other tools found grounded evidence the answer is
            # built from that and says which part could not be resolved; otherwise nothing is answered.
            if any(
                self._usable_rows(item)
                for item in outputs
                if (item.get("output") or {}).get("status") != "sheet_scope_unavailable"
            ):
                notices.append(
                    "Chưa dựng được phiếu đã kiểm tra khớp số phiếu và văn bản được hỏi; không dùng phương án của phiếu khác."
                )
            else:
                return {
                    "answer": {
                        "answer": "Tầng tra cứu chưa có cây phiếu đã kiểm tra khớp số phiếu và nguồn "
                        "được hỏi; không dùng phương án của phiếu khác.",
                        "status": "insufficient_sheet_scope",
                        "citations": [],
                    }
                }
        # A dated law/criteria comparison requires verified temporal rules,
        # not just PDFs with publication years in filenames. Text retrieval
        # may provide background, but never silently certify applicability.
        if "resolve_temporal_applicability" in route.required_tools and not any(
            item.get("tool") == "resolve_temporal_applicability"
            and (item.get("output") or {}).get("status") == "checked_verified_rules"
            and (item.get("output") or {}).get("applicability_status") == "applicable"
            for item in outputs
        ):
            # Text the documents themselves state may be reported; which version applies in a given year or on a
            # given date may not, so the answer carries a notice and the model is told not to conclude it.
            if not any(
                self._usable_rows(item)
                for item in outputs
                if item.get("tool") != "resolve_temporal_applicability"
            ):
                return {
                    "answer": {
                        "answer": "Chưa đủ quy tắc hiệu lực/chuyển tiếp đã xác minh để "
                        "đối chiếu chính xác các thời điểm hoặc năm được hỏi. "
                        "Cần nguồn quy định và phạm vi thời gian được xác minh; "
                        "không suy diễn từ năm ban hành văn bản." + (" " + absent if absent else ""),
                        "status": "insufficient_temporal_verification",
                        "citations": [],
                    }
                }
            temporal_unverified = True
            notices.append(
                "Mình chưa có quy định đã xác minh về văn bản nào áp dụng cho từng năm hay ngày cụ thể, nên dưới đây chỉ nêu những gì từng văn bản "
                "ghi, không kết luận văn bản nào áp dụng."
            )
        if any(
            (item.get("output") or {}).get("status")
            in ("local_guidance_not_in_corpus", "local_guidance_document_scope_mismatch")
            for item in outputs
        ):
            return {
                "answer": {
                    "answer": "Chưa có nguồn hướng dẫn hạn nộp hợp lệ "
                    "cho địa phương và văn bản được hỏi. Không sử dụng văn bản quốc gia "
                    "hoặc nguồn của địa phương khác để suy ra hạn nộp.",
                    "status": "insufficient_local_guidance_scope",
                    "citations": [],
                }
            }
        form_gap = [
            item
            for item in outputs
            if (item.get("output") or {}).get("status")
            in ("incomplete_form_ids", "form_source_scope_unverified", "form_version_ambiguous")
        ]
        if form_gap:
            missing = sorted(
                {
                    str(form)
                    for item in form_gap
                    for form in ((item.get("output") or {}).get("missing_form_ids") or [])
                },
                key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else 0, x),
            )
            candidates = list(
                dict.fromkeys(
                    doc for item in form_gap for doc in ((item.get("output") or {}).get("candidate_documents") or [])
                )
            )
            named = (
                "Các mẫu còn thiếu hoặc chưa xác minh: " + ", ".join(missing)
                if missing
                else "Các mẫu này có trong nhiều văn bản (" + "; ".join(candidates) + "). Bạn muốn tra mẫu của văn bản nào?"
                if candidates
                else "Chưa xác định được phiên bản văn bản chung cho các mẫu"
            )
            # What the documents say *about* the forms is evidence; the forms' own content is not available. Report the
            # gap, answer from the rest, never describe a template that was not verified.
            if any(self._usable_rows(item) for item in every if item not in form_gap):
                notices.append(
                    "Chưa có biểu mẫu đã xác minh. "
                    + named
                    + ". Nội dung dưới đây chỉ nêu điều các văn bản ghi về "
                    "các mẫu này; không mô tả nội dung của biểu mẫu."
                )
            else:
                return {
                    "answer": {
                        # Several documents carry the forms: ask which one, naming the candidates found in the corpus.
                        "answer": named if candidates and not missing else "Chưa có đầy đủ biểu mẫu để đối chiếu. " + named,
                        "status": "clarify" if candidates and not missing else "insufficient_form_scope",
                        "citations": [],
                    }
                }
        missing_entity = [
            name
            for item in outputs
            if (item.get("output") or {}).get("status") == "entity_not_found"
            for name in (item.get("output") or {}).get("entity") or []
        ]
        # In a compound question the other parts may still be answered from source text: the record gap becomes a
        # notice naming the unanswered part, never an assertion drawn from that text.
        answered_elsewhere = self._compound(state.get("effective_query", state["query"]), route) and any(
            self._usable_rows(item)
            for item in every
            if (item.get("output") or {}).get("status") not in PART_SCOPED_STATUSES
        )
        if missing_entity and answered_elsewhere:
            notices.append(
                "Không tìm thấy sản phẩm “" + "”, “".join(dict.fromkeys(missing_entity)) + "” trong các quyết định "
                "công nhận đã lập chỉ mục, nên phần hỏi về sản phẩm này chưa được trả lời; nội dung dưới đây chỉ trả "
                "lời các ý còn lại từ tài liệu."
            )
        elif missing_entity:
            return {
                "answer": {
                    "answer": "Không tìm thấy sản phẩm “" + "”, “".join(dict.fromkeys(missing_entity)) + "” trong các quyết định "
                    "công nhận đã lập chỉ mục. Hãy kiểm tra lại tên sản phẩm hoặc hỏi theo số hiệu quyết định.",
                    "status": "entity_not_found",
                    "citations": [],
                }
            }
        scope_gap = any(
            (item.get("output") or {}).get("status") == "recognition_scope_unverified" for item in outputs
        )
        if scope_gap and answered_elsewhere:
            notices.append(
                "Chưa có bản ghi công nhận đã xác minh khớp đầy đủ địa phương và mức sao được yêu cầu, nên phần hỏi "
                "về hạng/công nhận chưa được trả lời; nội dung dưới đây chỉ trả lời các ý còn lại từ tài liệu."
            )
        elif scope_gap:
            return {
                "answer": {
                    "answer": "Chưa có bản ghi công nhận đã xác minh khớp đầy đủ "
                    "địa phương và mức sao bạn hỏi, nên mình không ước đoán số liệu.",
                    "status": "insufficient_recognition_scope",
                    "citations": [],
                }
            }
        year_gap = [
            item
            for item in outputs
            if (item.get("output") or {}).get("status")
            in ("recognition_year_scope_unverified", "assessment_year_scope_unverified")
        ]
        if (
            year_gap
            and all(
                (item.get("output") or {}).get("status")
                in ("recognition_year_scope_unverified", "assessment_year_scope_unverified")
                for item in year_gap
            )
            and (
                self._passages_state_year([item for item in every if item not in year_gap], route.slots)
                or answered_elsewhere
            )
        ):
            # No record carries a verified event year, but the documents themselves may state it in their own text
            # ("công nhận ... năm 2025"). Answer from those passages and say the structured record could not be dated.
            notices.append(
                "Chưa có bản ghi hay biểu mẫu đã gắn đúng năm được hỏi; nội dung dưới đây lấy từ chính đoạn văn bản nguồn "
                "và nêu rõ văn bản nào, không suy từ năm ban hành."
            )
            outputs = [item for item in outputs if item not in year_gap]
        elif year_gap:
            return {
                "answer": {
                    "answer": "Chưa có bản ghi đã xác minh đúng năm sự kiện/đánh giá "
                    "hoặc đúng phiên bản tài liệu để trả lời an toàn. "
                    "Năm ban hành quyết định không thể tự coi là năm công nhận hay năm đánh giá.",
                    "status": "insufficient_year_scope",
                    "citations": [],
                }
            }
        outputs = every
        question = state.get("effective_query", state["query"])
        asks_version = self._asks_version(route)
        response = assemble(
            question,
            outputs,
            llm=self.llm,
            catalog=self._catalog(),
            rerank=self.rerank,
            replaced=frozenset() if asks_version else self.tools.replaced_sources(),
            # Graph facts the claim checker applies deterministically (score bands, counts of recognised products).
            checked={
                "star_bands": self.tools.star_bands(),
                "recognized": self.tools.recognized_products(),
                "owners": self.tools.owner_records(),
                "scores": self.tools.record_scores(),
                "abbreviations": self.tools.abbreviations(),
            },
            **({"style": "simple"} if route.dialogue.action == "rephrase" else {}),
        )
        gaps = [
            item["tool"]
            for item in outputs
            if item.get("optional")
            and item["tool"] not in ENRICHMENT_TOOLS
            and (item.get("output") or {}).get("status") != "not_needed"
            # A tool the question gave nothing to look up (no product named) found nothing because nothing was asked.
            and not (item.get("output") or {}).get("input_missing")
            and (
                item.get("skipped")
                or (item.get("output") or {}).get("status") in BAD_RESULT_STATUSES
                or not (item.get("output") or {}).get("results")
            )
        ]
        if gaps and response["status"] not in ("insufficient_evidence",):
            response["optional_gaps"] = gaps  # reported to the client, not written into the answer by tool name
        if notices and response["status"] != "insufficient_evidence":
            response["answer"] = "[" + " ".join(notices) + "]" + chr(10) + response["answer"]
            response["status"] = (
                "partial_temporal_unverified"
                if response["status"]
                in ("generated_claims_verified", "generated_unverified_claims", "partial_claims_verified")
                and temporal_unverified
                else response["status"]
            )
        coverage = state.get("evidence_coverage") or {}
        if coverage.get("status") == "partial":
            missing = list(
                dict.fromkeys(
                    [x["name"] for x in coverage.get("tools", []) if not x["has_source_evidence"]]
                    + coverage.get("missing_tools", [])
                )
            )
            # A gap that a notice above already explains in words is not repeated by its internal tool name.
            if temporal_unverified:
                missing = [name for name in missing if name != "resolve_temporal_applicability"]
            # Tool coverage is about lookups, not about the answer: a lookup can come back empty, or with graph nodes and
            # no passage, while the search found the passage that answers. The answer says in the user's words what
            # the documents lack ("Chưa tìm thấy trong tài liệu: …"); internal lookup names would only contradict a
            # correct answer. The gap stays in evidence_coverage and lowers the status.
            if missing and response["status"] in ("generated_claims_verified", "generated_unverified_claims"):
                response["status"] = "partial_evidence"
        return {"answer": response}

    def graph(self, *, checkpointer=None):
        try:
            from langgraph.graph import StateGraph, START, END
        except ImportError as exc:
            raise RuntimeError(
                "langgraph not installed; install project dependencies or use fallback mode"
            ) from exc
        graph = StateGraph(OcopState)
        graph.add_node("route", self.route)
        graph.add_node("plan", self.plan)
        graph.add_node("execute", self.execute)
        graph.add_node("recover", self.recover)
        graph.add_node("grade", self.grade)
        graph.add_node("grade_after_recovery", self.grade)
        graph.add_node("verify", self.verify)
        graph.add_node("answer", self.answer)
        graph.add_edge(START, "route")
        graph.add_conditional_edges(
            "route",
            lambda s: "answer"
            if s["route"].get("needs_clarification")
            or s["route"]["intent"] in (Intent.OUT_OF_SCOPE.value, Intent.CONVERSATION.value)
            else "plan",
            {"answer": "answer", "plan": "plan"},
        )
        graph.add_edge("plan", "execute")
        graph.add_edge("execute", "grade")
        graph.add_conditional_edges(
            "grade",
            lambda s: "recover" if self._should_recover(s) else "verify",
            {"recover": "recover", "verify": "verify"},
        )
        graph.add_edge("recover", "grade_after_recovery")
        graph.add_edge("grade_after_recovery", "verify")
        graph.add_edge("verify", "answer")
        graph.add_edge("answer", END)
        return graph.compile(checkpointer=checkpointer)

    @staticmethod
    def _checkpoint_public_input(initial: OcopState) -> OcopState:
        """Minimize plaintext checkpoint state; no credentials/auth payloads.

        The question and the previous question are masked (configs/ocop_privacy.yaml) before they are persisted;
        deployment owners must still choose a private protected checkpoint volume.
        """
        original = initial.get("session") or {}
        safe_session = {
            k: original[k]
            for k in ("session_id", "last_query", "intent", "capabilities")
            if k in original and isinstance(original[k], str) and len(original[k]) <= 4096
        }
        if isinstance(original.get("slots"), dict):
            safe_session["slots"] = _merge_followup({"slots": original["slots"]}, {})
        if isinstance(original.get("capabilities"), list):
            from ai_core.orchestration.ocop.capabilities import Capability

            allowed = {item.value for item in Capability}
            safe_session["capabilities"] = [
                item for item in original["capabilities"][:24] if isinstance(item, str) and item in allowed
            ]
        if isinstance(original.get("memory"), dict):
            safe_session["memory"] = memory.sanitize(original["memory"])
        pending = original.get("unresolved")
        if isinstance(pending, dict) and isinstance(pending.get("question"), str):
            missing = pending.get("missing_slots")
            safe_session["unresolved"] = {
                "question": redact(pending["question"])[:600],
                "missing_slots": [key for key in missing[:16] if isinstance(key, str) and len(key) <= 64]
                if isinstance(missing, list)
                else [],
            }
        provided = initial.get("context") or {}
        safe_context = {}
        if isinstance(provided.get("as_of_date"), str) and re.fullmatch(
            r"20\d{2}-\d{2}-\d{2}", provided["as_of_date"]
        ):
            safe_context["as_of_date"] = provided["as_of_date"]
        if isinstance(safe_session.get("last_query"), str):
            safe_session["last_query"] = redact(safe_session["last_query"])
        return {
            **initial,
            "query": redact(initial["query"]),
            "session": safe_session,
            "context": safe_context,
            "auth": None,
        }

    @traced("ocop.agent.ask")
    def ask(
        self,
        query: str,
        *,
        session: dict | None = None,
        context: dict | None = None,
        auth_context: AuthContext | None = None,
        require_langgraph: bool = False,
    ) -> AgentResponse:
        for folder in (
            self.tools.index_dir,
            getattr(self.tools, "graph_dir", self.root / "data/processed/ocop/graph"),
        ):
            manifest_file = folder / "manifest.json"
            if manifest_file.is_file():
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                partial = manifest.get("source_complete") is False or str(
                    manifest.get("status", "")
                ).startswith("partial_")
                if partial and not self.allow_partial_debug:
                    raise RuntimeError("partial corpus requires explicit allow_partial_debug=True")
        initial: OcopState = {
            "query": query,
            "session": session or {},
            "context": context or {},
            "auth": auth_context,
        }
        engine = "langgraph"
        checkpointer = None
        invoke_config = None
        if should_checkpoint(env=os.environ, auth=auth_context, session=session or {}, private_tools=set()):
            if self._checkpoint is None:
                location = os.environ.get("OCOP_LANGGRAPH_CHECKPOINT_PATH")
                if not location:
                    raise RuntimeError("Set OCOP_LANGGRAPH_CHECKPOINT_PATH to a private writable location")
                self._checkpoint = SQLiteCheckpoint(Path(location))
            key = thread_key(auth_context.tenant_id, auth_context.principal_id, session["session_id"])
            checkpointer = self._checkpoint.saver
            invoke_config = {"configurable": {"thread_id": key}}
            initial = self._checkpoint_public_input(initial)
        try:
            compiled = self.graph(checkpointer=checkpointer)
            final = (
                compiled.invoke(initial, config=invoke_config) if invoke_config else compiled.invoke(initial)
            )
        except RuntimeError as exc:
            if require_langgraph or "langgraph not installed" not in str(exc):
                raise
            engine = "deterministic_fallback"
            final = dict(initial)
            final.update(self.route(final))
            if not final["route"].get("needs_clarification") and final["route"]["intent"] not in (
                Intent.OUT_OF_SCOPE.value,
                Intent.CONVERSATION.value,
            ):
                final.update(self.plan(final))
                final.update(self.execute(final))
                final.update(self.grade(final))
                if self._should_recover(final):
                    final.update(self.recover(final))
                    final.update(self.grade(final))
            final.update(self.verify(final))
            final.update(self.answer(final))
        route = Route.model_validate(final["route"])
        payload = final["answer"]
        if self.allow_partial_debug:
            payload = {
                **payload,
                "answer": PARTIAL_CORPUS_NOTICE + "\n" + payload["answer"],
                "status": "partial_debug_corpus",
                "claim_verification": {
                    **payload.get("claim_verification", {}),
                    "answer_status": payload["status"],
                    "corpus_status": "partial_debug_corpus",
                },
            }
        return AgentResponse(
            answer=payload["answer"],
            intent=route.intent,
            status=payload["status"],
            citations=payload["citations"],
            tools_used=[
                r["tool"] for r in final.get("results", []) if not r.get("skipped") and not r.get("memory")
            ],
            tools_skipped=[r["tool"] for r in final.get("results", []) if r.get("skipped")],
            workflow_engine=engine,
            route=route,
            corpus_version=self._corpus_version(),
            standalone_query=final.get("effective_query"),
            tool_trace=final.get("trace", []),
            evidence_coverage=final.get("evidence_coverage", {}),
            evidence_grade=final.get("evidence_grade", {}),
            claim_verification=payload.get("claim_verification", {}),
            generation_diagnostics=payload.get("generation_diagnostics", {}),
            evidence_fusion=payload.get("evidence_fusion", {}),
        )

    def _corpus_version(self):
        path = self.tools.index_dir / "manifest.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8")).get("corpus_version")
