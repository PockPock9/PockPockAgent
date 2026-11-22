"""Runner events as the desktop app's run events, and plain-language text for a sequence plan.

The runner reports `{"event": "step_started", "step_id": ...}` and so on; the app reads events by
`type`. This module turns each runner event into the events the PockPock Agent view already shows:
`plan_step` ("Step 3 of 8" in the run bar and plan card), steps for checks and retries, and an `error`
when a step cannot be finished. It also describes each step's done condition for the plan card, and
writes the short reply shown when the run ends.
"""

from __future__ import annotations

import json
from typing import Any

LABEL = 160
OUTPUT_LIMIT = 6000


def tool_output_text(result: dict[str, Any]) -> str:
    """The text a step's model sees from one tool call. Tools return different fields: project file
    tools give `content`, `files` or `matches`, artifact tools a `name` and `path`, others `output`."""
    if not isinstance(result, dict):
        return str(result)[:OUTPUT_LIMIT]
    for key in ("output", "content", "text"):
        value = result.get(key)
        if isinstance(value, str) and value:
            return value[:OUTPUT_LIMIT]
    if isinstance(result.get("files"), list):
        return "\n".join(str(item) for item in result["files"])[:OUTPUT_LIMIT]
    if isinstance(result.get("matches"), list):
        return json.dumps(result["matches"], ensure_ascii=False, default=str)[:OUTPUT_LIMIT]
    shown = {key: value for key, value in result.items() if key not in {"diff", "data"}}
    return json.dumps(shown, ensure_ascii=False, default=str)[:OUTPUT_LIMIT]


def done_condition_text(condition: dict[str, Any] | None) -> str:
    condition = condition or {}
    kind = condition.get("type")
    path = str(condition.get("path") or "")
    if kind == "file_exists":
        return f"{path} exists"
    if kind == "file_contains":
        return f"{path} contains “{str(condition.get('pattern') or '')[:60]}”"
    if kind == "command_exit_0":
        return "The command finishes without an error"
    if kind == "value_equals":
        return f"{condition.get('field')} is {str(condition.get('expected') or '')[:60]}"
    return "The step finishes without an error"


def _position(steps: list[dict[str, Any]], step_id: Any) -> tuple[int, str]:
    for index, step in enumerate(steps):
        if step.get("id") == step_id:
            return index + 1, " ".join(str(step.get("goal") or "").split())[:LABEL]
    return 0, ""


def ui_events(event: dict[str, Any], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The app events for one runner event (none for events the app does not show)."""
    name = event.get("event")
    number, goal = _position(steps, event.get("step_id"))
    total = len(steps)
    detail = " ".join(str(event.get("detail") or "").split())[:300]
    if name == "step_started" and number:
        return [
            {"type": "plan_step", "step": number, "total": total, "label": goal},
            {"type": "status", "message": f"Step {number} of {total}: {goal}"[:200]},
        ]
    if name == "step_verified" and number:
        passed = event.get("status") == "passed"
        return [{"type": "sequence_check", "step": number, "total": total, "passed": passed,
                 "message": (f"Step {number} checked: {detail}" if passed else f"Step {number} check failed: {detail}")[:240]}]
    if name == "step_retry" and number:
        return [{"type": "sequence_retry", "step": number, "attempt": event.get("attempt"), "message": f"Trying step {number} again: {detail}"[:240]}]
    if name == "replan_needed" and number:
        return [{"type": "error", "status": "partial", "step": number,
                 "message": f"Step {number} of {total} could not be finished ({detail or 'its check did not pass'}). The steps before it are kept; retry from step {number} to plan the rest again."[:500]}]
    return []


def final_reply(result: dict[str, Any], steps: list[dict[str, Any]], planner: str, executor: str) -> str:
    finished = sum(1 for step in result.get("steps") or [] if isinstance(step, dict) and step.get("status") == "passed")
    lines = [f"Finished all {len(steps)} steps." if result.get("status") == "completed" else f"Finished {finished} of {len(steps)} steps."]
    lines.append(f"Planned by {planner}; each step was done by {executor} and checked before the next one started.")
    for index, step in enumerate(steps, 1):
        lines.append(f"{index}. {step.get('goal')} — {done_condition_text(step.get('done_condition'))}")
    return "\n".join(lines)
