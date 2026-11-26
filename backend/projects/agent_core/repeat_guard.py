"""Stops an agent run from repeating the same tool call.

Small local models sometimes call one tool with the same arguments again and again (a read of the
same file, the same search), spending the run's turns and context without progress. The guard lets
an identical call run twice; a third identical call is not run, and the model is told to use the
result it already has or try something else. After ``MAX_REFUSALS`` refused calls the run stops
with a clear message instead of using up its remaining turns.

"Identical" means the same tool name and the same arguments since the last call that could change
state (any tool whose risk is not ``read``): after a file is written, reading it again is new work.
"""

from __future__ import annotations

import json
from typing import Any

#: Identical calls allowed before the next one is refused.
MAX_IDENTICAL_CALLS = 2
#: Refused calls after which the run stops.
MAX_REFUSALS = 3


def call_key(name: str, arguments: Any) -> str:
    """A stable key for one call: tool name plus canonical JSON arguments."""
    try:
        canonical = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        canonical = repr(arguments)
    return f"{name}\x00{canonical}"


class RepeatGuard:
    def __init__(self, max_identical: int = MAX_IDENTICAL_CALLS, max_refusals: int = MAX_REFUSALS) -> None:
        self.max_identical = max_identical
        self.max_refusals = max_refusals
        self.counts: dict[str, int] = {}
        self.refusals = 0

    def check(self, name: str, arguments: Any) -> str | None:
        """Record a call about to run. Returns None to run it, or the message to give the model instead."""
        key = call_key(name, arguments)
        seen = self.counts.get(key, 0)
        if seen < self.max_identical:
            self.counts[key] = seen + 1
            return None
        self.refusals += 1
        return (
            f"Not run: you already called {name} with exactly these arguments {seen} times, and nothing has "
            "changed since, so the result would be the same. Use the result you already have, call it with "
            "different arguments, use another tool, or give your final answer."
        )

    @property
    def exhausted(self) -> bool:
        """Whether the run should stop: the model kept repeating after being told."""
        return self.refusals >= self.max_refusals

    def state_changed(self) -> None:
        """A call that may change state ran: earlier identical reads may now give a different result."""
        self.counts.clear()

    def after_call(self, risk_level: str | None) -> None:
        if risk_level != "read":
            self.state_changed()
