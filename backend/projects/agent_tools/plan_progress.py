"""Plan-step progress: the agent says which approved plan step it is starting.

`report_plan_step` is not a registered project tool. It has no side effects, needs no permission,
and is handled by the gateway itself: each valid call becomes a `plan_step` run event
(`{"type": "plan_step", "step": 3, "total": 5, "label": "..."}`) that the desktop shows as
"Step 3 of 5". Small local models sometimes skip or misuse extra tools, so the app shows a step
only when one was reported and otherwise counts finished tool steps.
"""

from __future__ import annotations

import os
from typing import Any

PLAN_STEP_TOOL = "report_plan_step"
LABEL_LIMIT = 160


def plan_step_reports_enabled(steps: list[str], *, delegated: bool, has_tools: bool) -> bool:
    """Offered for a run of an approved plan with two or more steps that uses tools.

    Delegates run one subtask with a pinned tool list, so they never get it.
    POCKPOCK_PLAN_STEP_REPORTS=0 turns it off.
    """
    if os.environ.get("POCKPOCK_PLAN_STEP_REPORTS", "1").strip().lower() in {"0", "false", "off", "no"}:
        return False
    return not delegated and has_tools and len(steps) >= 2


def plan_step_tool_spec(total: int) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": PLAN_STEP_TOOL,
            "description": (
                f"Say which step of the approved plan (1 to {total}) you are starting, so the user can follow "
                "along. Call it once before each step's work. It does nothing else."
            ),
            "parameters": {
                "type": "object",
                "properties": {"step": {"type": "integer", "minimum": 1, "maximum": total, "description": "The plan step number."}},
                "required": ["step"],
                "additionalProperties": False,
            },
        },
    }


def plan_step_prompt(total: int) -> str:
    # Wording chosen from live probes with qwen3.5:9b: it makes one tool call per reply, ignored a
    # "same reply" instruction at the end of the system prompt, and reported steps 2 onwards when asked
    # to report first, separately, with an example, next to the numbered plan.
    return (
        f"Progress: before you start each of the {total} numbered steps, first call {PLAN_STEP_TOOL} "
        f"with its number, then do the step. Start now with {PLAN_STEP_TOOL}(step=1)."
    )


def plan_step_event(arguments: object, steps: list[str]) -> dict[str, Any] | None:
    """The run event for a call, or None when the step number is not one of the plan's."""
    value = arguments.get("step") if isinstance(arguments, dict) else None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= len(steps):
        return None
    label = " ".join(str(steps[value - 1]).split())
    if len(label) > LABEL_LIMIT:
        label = label[: LABEL_LIMIT - 1].rstrip() + "…"
    return {"type": "plan_step", "step": value, "total": len(steps), "label": label}


def plan_step_reply(event: dict[str, Any] | None, total: int) -> str:
    """What the model sees as the call's result."""
    if event is None:
        return f"Not recorded: give a step number from 1 to {total}. Continue with the task."
    return f"Recorded: step {event['step']} of {event['total']}. Continue with the step."
