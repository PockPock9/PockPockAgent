"""Small, deterministic routing evaluation with synthetic examples only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from planner.routing import choose_candidate


@dataclass(frozen=True)
class RoutingEvaluationCase:
    case_id: str
    task: str
    preferred: str | None
    expected: str
    fallback: str = "missing"


@dataclass(frozen=True)
class RoutingCaseResult:
    case_id: str
    selected: str
    expected: str
    passed: bool


@dataclass(frozen=True)
class RoutingEvaluationReport:
    suite: str
    case_count: int
    passed: int
    accuracy: float
    results: tuple[RoutingCaseResult, ...]


ROUTING_EVALUATION_CASES = (
    RoutingEvaluationCase("workspace-build", "Build a small website", "fast-tools", "fast-tools"),
    RoutingEvaluationCase("public-research", "Research official documentation", "no-tools", "steady-tools", "steady-tools"),
    RoutingEvaluationCase("general-question", "Explain a short concept", None, "fast-tools"),
)

DEFAULT_ROUTING_PROFILES = (
    {"name": "fast-tools", "capabilities": ["tools"], "context_window": 16384, "avg_latency_ms": 420},
    {"name": "steady-tools", "capabilities": ["tools"], "context_window": 32768, "avg_latency_ms": 900},
    {"name": "no-tools", "capabilities": ["completion"], "context_window": 32768, "avg_latency_ms": 100},
)


def evaluate_routing(
    profiles: Sequence[Mapping[str, Any]] = DEFAULT_ROUTING_PROFILES,
) -> RoutingEvaluationReport:
    results = []
    for case in ROUTING_EVALUATION_CASES:
        selected, _ = choose_candidate(
            list(profiles),
            task=case.task,
            preferred=case.preferred,
            fallback=case.fallback,
        )
        results.append(RoutingCaseResult(
            case_id=case.case_id,
            selected=selected,
            expected=case.expected,
            passed=selected == case.expected,
        ))
    passed = sum(result.passed for result in results)
    return RoutingEvaluationReport(
        suite="local-routing-v1",
        case_count=len(results),
        passed=passed,
        accuracy=passed / len(results) if results else 1.0,
        results=tuple(results),
    )
