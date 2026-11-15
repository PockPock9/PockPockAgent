"""Narrow interfaces for operational traces that must not contain prompt content."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol


class TraceSink(Protocol):
    def emit(self, event: Mapping[str, Any]) -> None:
        """Persist one prompt-free operational event."""


class PromptFreeTraceAdapter:
    _FORBIDDEN_FIELDS = frozenset({
        "content",
        "input",
        "messages",
        "output",
        "prompt",
        "source_task",
        "task",
        "user_text",
    })

    def __init__(self, save_event: Callable[[dict[str, Any]], None]):
        self._save_event = save_event

    def emit(self, event: Mapping[str, Any]) -> None:
        included = self._find_forbidden_fields(event)
        if included:
            raise ValueError(
                "Prompt-free trace cannot include fields: " + ", ".join(sorted(included))
            )
        self._save_event(dict(event))

    @classmethod
    def _find_forbidden_fields(cls, value: Any) -> set[str]:
        if isinstance(value, Mapping):
            included = set(value).intersection(cls._FORBIDDEN_FIELDS)
            for item in value.values():
                included.update(cls._find_forbidden_fields(item))
            return included
        if isinstance(value, (list, tuple)):
            included = set()
            for item in value:
                included.update(cls._find_forbidden_fields(item))
            return included
        return set()
