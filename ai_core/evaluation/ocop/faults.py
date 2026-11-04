"""Isolated fault-injection harness; never call real side-effecting dossier tools.

Faults are injected into a controlled tool adapter with a fake deterministic
response; scenarios cover transient errors, bad payloads, and authorization.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from ai_core.orchestration.ocop.workflow import OcopAgent


@dataclass(frozen=True)
class FaultScenario:
    name: str
    query: str
    injected_tool: str
    fault: str  # timeout / os_error / empty / malformed / permission
    expected_status: str | None = None


SCENARIOS = (
    FaultScenario("timeout_recovery", "Hồ sơ OCOP yêu cầu những gì?", "search_regulations", "timeout"),
    FaultScenario("db_offline", "Hồ sơ OCOP yêu cầu những gì?", "search_regulations", "os_error"),
    FaultScenario("no_hits", "Hồ sơ OCOP yêu cầu những gì?", "search_regulations", "empty"),
    FaultScenario("malformed_result", "Hồ sơ OCOP yêu cầu những gì?", "search_regulations", "malformed"),
    FaultScenario("auth_denied", "Hồ sơ OCOP yêu cầu những gì?", "search_regulations", "permission"),
)


class SimulatedToolFailure:
    def __init__(self, target: str, fault: str):
        self.target = target
        self.fault = fault
        self.calls = []

    def replaced_sources(self) -> frozenset[str]:
        return frozenset()  # no graph behind a simulated failure, so no validity chain

    def star_bands(self) -> tuple[dict, ...]:
        return ()  # nor star bands

    def recognized_products(self) -> dict:
        return {}  # nor recognition records

    def owner_records(self) -> dict:
        return {}

    def record_scores(self) -> dict:
        return {}

    def criterion_points(self) -> dict:
        return {}

    def abbreviations(self) -> dict:
        return {}

    def dispatch(self, name: str, *, query: str, slots: dict, context=None, auth=None) -> dict:
        self.calls.append(name)
        if name != self.target:
            return {"status": "not_found", "results": []}
        if self.fault == "timeout":
            raise TimeoutError("simulated timeout")
        if self.fault == "os_error":
            raise OSError("simulated unavailable database")
        if self.fault == "empty":
            return {"status": "no_results", "results": []}
        if self.fault == "malformed":
            return {"status": "bad_schema", "results": []}
        if self.fault == "permission":
            raise PermissionError("simulated unauthorized action")
        raise ValueError("unknown fault")


def evaluate_faults(root: Path, scenarios=SCENARIOS) -> dict:
    report = []
    for scenario in scenarios:
        agent = OcopAgent(root)
        adapter = SimulatedToolFailure(scenario.injected_tool, scenario.fault)
        # In-memory deterministic adapter: all data is synthetic and read-only.
        agent.tools = adapter
        # ask() reads index manifest; use minimal ToolRegistry-like property.
        adapter.index_dir = root / "data/processed/ocop/index"
        start = monotonic()
        try:
            response = agent.ask(scenario.query)
            status = response.status
            safe = status in (
                "insufficient_evidence",
                "retrieval_only",
                "citation_verification_failed",
                "clarify",
                "out_of_scope",
                "model_unavailable_retrieval_only",
            )
            errored = False
        except Exception as exc:
            status = type(exc).__name__
            # Permission failure must fail closed; never convert permission
            # error into a public retrieval result or access grant.
            safe = isinstance(exc, PermissionError)
            errored = True
        report.append(
            {
                "scenario": scenario.name,
                "fault": scenario.fault,
                "status": status,
                "safe": safe,
                "raised": errored,
                "tool_calls": adapter.calls,
                "latency_ms": round((monotonic() - start) * 1000, 2),
            }
        )
    return {
        "scenarios": len(report),
        "safe_count": sum(bool(x["safe"]) for x in report),
        "failed_count": sum(not x["safe"] for x in report),
        "cases": report,
    }
