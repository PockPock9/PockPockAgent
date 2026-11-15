"""Privacy-safe model candidate filtering and ranking."""

from __future__ import annotations

import math
import re
from typing import Any


def required_context_tokens(task: str) -> int:
    # Conservative upper bound for task text plus tool and answer room.
    return max(4096, min(32768, math.ceil(len(task) / 3) + 8192))


def task_capability(task: str) -> str:
    if re.search(r"\b(code|coding|program|app|application|website|web app|game|bug|fix|feature|project|workspace|script|software|build|implement|edit|refactor)\b", task, re.I):
        return "workspace"
    if re.search(r"\b(research|search|sources|compare|citations|browse|web)\b", task, re.I):
        return "research"
    return "general"


def choose_candidate(
    profiles: list[dict[str, Any]],
    *,
    task: str,
    preferred: str | None,
    fallback: str,
) -> tuple[str, str]:
    """Choose only tool-capable, context-compatible profiles; unknown context stays eligible."""
    needed = required_context_tokens(task)
    eligible = []
    for item in profiles:
        name = item.get("name")
        capabilities = item.get("capabilities")
        context = item.get("context_window")
        if not isinstance(name, str) or not isinstance(capabilities, list) or "tools" not in capabilities:
            continue
        if isinstance(context, int) and context < needed:
            continue
        eligible.append(item)
    if not eligible:
        raise ValueError("No enabled tool-capable model has enough context for this task.")
    by_name = {item["name"]: item for item in eligible}
    if preferred and preferred in by_name:
        return preferred, f"Kept the selected model because it supports tool calls and has enough context for this {task_capability(task)} task."
    fallback_item = by_name.get(fallback)
    if fallback_item:
        reason = f"Used the configured fallback because the preferred model was unavailable or lacked required capabilities; task type: {task_capability(task)}."
        return fallback, reason
    ranked = sorted(eligible, key=lambda item: (item.get("avg_latency_ms") if isinstance(item.get("avg_latency_ms"), (int, float)) else float("inf"), item["name"]))
    selected = ranked[0]
    latency = selected.get("avg_latency_ms")
    reason = f"Selected the fastest measured compatible local model for a {task_capability(task)} task" + (f" ({round(latency)} ms average call latency)." if isinstance(latency, (int, float)) else "; no latency history is available.")
    return selected["name"], reason
