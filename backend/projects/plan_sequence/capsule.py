"""State capsule construction and rendering (Plan-and-Sequence P0).

The capsule is the only state passed between steps: file paths, record
IDs, and short summaries — pointers, never payloads. It is capped at
``MAX_CAPSULE_TOKENS`` (400) tokens.

Trimming order, oldest first within each kind:

1. ``"summary"`` entries (the most expendable),
2. then ``"value"`` entries,
3. ``"path"`` / ``"id"`` entries are never dropped while any summary or
   value entry remains. Only when the capsule is still over budget after
   every summary and value is gone are the oldest pointers dropped anyway,
   and that loss is recorded on the capsule (``dropped_pointers=True``) and
   logged, because a later step may need the pointer to re-read its input.
"""

from __future__ import annotations

import logging
from typing import Sequence

from pydantic import ValidationError

from projects.agent_tools.tool_retriever import estimate_tokens

from .contracts import (
    MAX_CAPSULE_TOKENS,
    CapsuleEntry,
    StateCapsule,
    _entries_to_text,
)

logger = logging.getLogger(__name__)

# Pydantic bound on StateCapsule.entries; enforced here because trimming
# happens before the capsule is constructed.
MAX_CAPSULE_ENTRIES = 24


def _parse_entries(entries: Sequence[dict | CapsuleEntry] | StateCapsule) -> tuple[list[CapsuleEntry], bool]:
    """Normalise the input into validated entries plus a prior pointer-loss flag."""
    if isinstance(entries, StateCapsule):
        return list(entries.entries), entries.dropped_pointers
    parsed: list[CapsuleEntry] = []
    for index, item in enumerate(entries):
        if isinstance(item, CapsuleEntry):
            parsed.append(item)
            continue
        try:
            parsed.append(CapsuleEntry.model_validate(item))
        except ValidationError as exc:
            raise ValueError(f"Invalid capsule entry at index {index}: {exc}") from exc
    return parsed, False


def build_capsule(
    entries: Sequence[dict | CapsuleEntry] | StateCapsule,
    *,
    max_tokens: int = MAX_CAPSULE_TOKENS,
) -> StateCapsule:
    """Build a capsule from entries, trimming to ``max_tokens`` tokens.

    Accepts a list of dicts, a list of :class:`CapsuleEntry`, or an existing
    :class:`StateCapsule` (re-trimmed). Oldest ``"summary"`` entries are
    dropped first, then oldest ``"value"`` entries; ``"path"`` / ``"id"``
    entries are dropped only as a last resort, and the capsule records that
    with ``dropped_pointers=True``. The result never exceeds ``max_tokens``
    tokens (unless a single entry alone is larger) and never holds more
    than 24 entries.
    """
    working, dropped_pointers = _parse_entries(entries)
    while working and estimate_tokens(_entries_to_text(working)) > max_tokens:
        summary_index = next(
            (index for index, entry in enumerate(working) if entry.kind == "summary"),
            None,
        )
        if summary_index is not None:
            del working[summary_index]
            continue
        value_index = next(
            (index for index, entry in enumerate(working) if entry.kind == "value"),
            None,
        )
        if value_index is not None:
            del working[value_index]
            continue
        # Only pointers remain: drop the oldest one and record the loss.
        del working[0]
        dropped_pointers = True
    while len(working) > MAX_CAPSULE_ENTRIES:
        dropped = working.pop(0)
        if dropped.kind in ("path", "id"):
            dropped_pointers = True
    capsule = StateCapsule(entries=working, dropped_pointers=dropped_pointers)
    if dropped_pointers:
        logger.warning(
            "State capsule dropped path/id pointer(s) to fit %d tokens; "
            "later steps may need to re-derive the pointer.",
            max_tokens,
        )
    return capsule


def capsule_to_text(capsule: StateCapsule) -> str:
    """Render a capsule as ``key: value`` lines, grouped by source step."""
    return capsule.to_text()


def capsule_token_estimate(text: str) -> int:
    """Token estimate for capsule text (``~4 chars per token``)."""
    return estimate_tokens(text)
