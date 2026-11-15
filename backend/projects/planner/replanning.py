"""Small, bounded replanning state used by the agent gateway."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
import re
from typing import Any


MAX_IDENTICAL_FAILURES = 2
MAX_REVISIONS = 5


def incomplete_success_checks(answer: object, checks: list[str]) -> list[str]:
    """Require an explicit evidence-bearing PASS line for each approved check."""
    text = answer if isinstance(answer, str) else ""
    text = re.sub(
        r"(?<![\r\n])(?<=[.!?])\s+[-*]?\s*(?=CHECK\s+\d+\s*:)",
        "\n- ",
        text,
        flags=re.IGNORECASE,
    )
    incomplete = []
    for index, check in enumerate(checks, 1):
        match = re.search(
            rf"(?im)^\s*(?:\[CHECK\s+{index}\s*:\s*(PASS|INCOMPLETE)\]\s*(.*)|"
            rf"(?:[-*]\s*)?CHECK\s+{index}\s*:\s*(PASS|INCOMPLETE)\s*[-:]\s*(.*))$",
            text,
        )
        if not match:
            incomplete.append(check)
            continue
        status = match.group(1) or match.group(3)
        evidence = match.group(2) or match.group(4) or ""
        if status.upper() != "PASS" or len(evidence.strip()) < 8:
            incomplete.append(check)
    return incomplete


class ReplanningBudget:
    def __init__(self) -> None:
        self._failures: Counter[str] = Counter()
        self._revisions = 0
        self.completed_steps: list[str] = []

    def record(self, *, tool: str, arguments: dict[str, Any], status: str, error: dict[str, Any] | None) -> dict[str, Any] | None:
        """Record an outcome and return a privacy-safe revision event when work should adapt."""
        if status == "success":
            if tool not in self.completed_steps:
                self.completed_steps.append(tool)
            return None
        if status != "error":
            return None
        fingerprint = hashlib.sha256(json.dumps(
            {"tool": tool, "arguments": arguments, "code": (error or {}).get("code", "tool_failed")},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        self._failures[fingerprint] += 1
        self._revisions += 1
        if self._revisions > MAX_REVISIONS:
            return {"stop": True, "reason": "The run reached its five-revision replanning limit."}
        if self._failures[fingerprint] >= MAX_IDENTICAL_FAILURES:
            return {"stop": True, "reason": "The same tool action failed twice; the agent stopped to avoid repeating it."}
        return {
            "stop": False,
            "revision": self._revisions,
            "trigger": "tool_unavailable" if (error or {}).get("code") in {"tool_timeout", "tool_unavailable", "provider_unavailable"} else "tool_failure",
            "completed_steps": list(self.completed_steps),
            "changed_steps": [f"Reassess the remaining plan after {tool} failed; retry only with a meaningfully changed action."],
            "rationale": str((error or {}).get("message", "Tool failed"))[:240],
        }
