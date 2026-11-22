"""Context compaction for the agent loop (tool-RAG Phase 2).

The agent loop appends every tool result to the message history, so a long
run grows the prompt without bound and the model ends up re-reading stale
tool output on every turn. This module keeps that growth bounded with three
cheap, deterministic steps, applied in order when the history passes
70-80% of the context window:

1.  Truncate over-long tool outputs at source (:func:`truncate_tool_output`):
    head + tail with a marker giving the original size and, when the full
    content lives on disk (a saved artifact, or the file that was read), a
    pointer to it.
2.  Prune old tool results (:func:`prune_tool_results`): cut the content of
    all but the most recent tool messages to its start and end, with a note
    telling the model to call the tool again rather than guess the rest. The
    assistant messages that made the calls are kept, so the call record
    (which tool, which arguments) survives.
3.  Summarise the old portion (:func:`compact_messages` step 2): replace the
    oldest messages with a structured summary — tools used, errors, file
    paths, the user task — while keeping a recent tail intact.

Everything is deterministic (no model call): compaction must never invent
facts about what happened. Thresholds are named constants, overridable by
environment variable (restart not required — they are read on each call).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

# ---------------------------------------------------------------------------
# Configuration (env-overridable; read on each call)
# ---------------------------------------------------------------------------

#: Assumed context window for the agent loop, in tokens. Local Qwen3.5
#: models report 256k, but the agent loop also pays per-turn latency on
#: long prompts, so the default is conservative; raise it on a machine
#: with a large window and a fast model.
DEFAULT_CONTEXT_WINDOW_TOKENS = 32_768

#: Compact when the estimated history passes this fraction of the window.
#: 0.75 sits inside the 70-80% band from the local-AI research.
DEFAULT_COMPACT_AT_FRACTION = 0.75

#: Recent messages kept verbatim when the old portion is summarised.
DEFAULT_KEEP_RECENT_MESSAGES = 6

#: Tool outputs longer than this are truncated at source.
DEFAULT_MAX_TOOL_RESULT_CHARS = 50_000

#: Head/tail kept by truncation (head + tail + marker ≈ the max above).
DEFAULT_TOOL_OUTPUT_HEAD_CHARS = 30_000
DEFAULT_TOOL_OUTPUT_TAIL_CHARS = 10_000

#: Tool results kept intact by pruning; older ones become one-line stubs.
DEFAULT_PRUNE_KEEP_LAST_TOOL_RESULTS = 3

#: File paths worth keeping in a summary (workspace / artifact paths).
_FILE_RE = re.compile(
    r"(?<![\w/.-])([\w.-]+(?:/[\w.-]+)*\.(?:py|js|mjs|cjs|jsx|ts|tsx|html|css|json|md|txt|csv|xlsx|docx|pptx|pdf))\b",
    re.IGNORECASE,
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def context_window_tokens() -> int:
    return _env_int("POCKPOCK_CONTEXT_WINDOW_TOKENS", DEFAULT_CONTEXT_WINDOW_TOKENS)


def compact_at_fraction() -> float:
    return _env_float("POCKPOCK_COMPACT_AT_FRACTION", DEFAULT_COMPACT_AT_FRACTION)


def keep_recent_messages() -> int:
    return _env_int("POCKPOCK_KEEP_RECENT_MESSAGES", DEFAULT_KEEP_RECENT_MESSAGES)


def max_tool_result_chars() -> int:
    return _env_int("POCKPOCK_MAX_TOOL_RESULT_CHARS", DEFAULT_MAX_TOOL_RESULT_CHARS)


def tool_output_head_chars() -> int:
    return _env_int("POCKPOCK_TOOL_OUTPUT_HEAD_CHARS", DEFAULT_TOOL_OUTPUT_HEAD_CHARS)


def tool_output_tail_chars() -> int:
    return _env_int("POCKPOCK_TOOL_OUTPUT_TAIL_CHARS", DEFAULT_TOOL_OUTPUT_TAIL_CHARS)


def prune_keep_last_tool_results() -> int:
    return _env_int(
        "POCKPOCK_PRUNE_KEEP_LAST_TOOL_RESULTS", DEFAULT_PRUNE_KEEP_LAST_TOOL_RESULTS
    )


def estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough token estimate for a message history (~4 chars per token)."""
    total = 0
    for message in messages:
        content = message.get("content", "") if isinstance(message, dict) else ""
        total += max(1, len(str(content)) // 4) + 8  # per-message overhead
    return total


# ---------------------------------------------------------------------------
# Step 1: truncate over-long tool outputs at source
# ---------------------------------------------------------------------------

def truncate_tool_output(
    text: str,
    *,
    pointer: str | None = None,
    max_chars: int | None = None,
    head_chars: int | None = None,
    tail_chars: int | None = None,
) -> str:
    """Truncate ``text`` to head + tail with a marker, or return it unchanged.

    ``pointer`` names where the full content lives on disk (for example the
    saved artifact path), and is quoted in the marker when given. Without a
    pointer the marker only records the original size — it never claims the
    full text is stored somewhere it is not.
    """
    limit = max_chars if max_chars is not None else max_tool_result_chars()
    head = head_chars if head_chars is not None else tool_output_head_chars()
    tail = tail_chars if tail_chars is not None else tool_output_tail_chars()
    if len(text) <= limit:
        return text
    marker = (
        f"\n[… tool output truncated: {len(text)} chars total, "
        f"showing first {head} and last {tail}"
    )
    if pointer:
        marker += f"; full content is in {pointer}"
    marker += "]"
    return text[:head] + marker + "\n" + text[-tail:] if tail else text[:head] + marker


# ---------------------------------------------------------------------------
# Step 2: prune old tool results, keeping the call record
# ---------------------------------------------------------------------------

def prune_tool_results(
    messages: list[dict[str, Any]],
    *,
    keep_last: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Replace old tool-result contents with one-line stubs.

    All but the most recent ``keep_last`` tool messages are stubbed; the
    assistant messages that made the calls are untouched, so the record of
    which tool was called with which arguments survives. Returns the new
    message list and the number of results pruned.
    """
    keep = keep_last if keep_last is not None else prune_keep_last_tool_results()
    tool_indices = [
        index for index, message in enumerate(messages)
        if isinstance(message, dict) and message.get("role") == "tool"
    ]
    if len(tool_indices) <= keep:
        return list(messages), 0
    stub_after = set(tool_indices[:-keep]) if keep else set(tool_indices)
    pruned = 0
    result: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        content = str(message.get("content", "")) if isinstance(message, dict) else ""
        if index in stub_after and len(content) > PRUNE_EXCERPT_HEAD_CHARS + PRUNE_EXCERPT_TAIL_CHARS:
            result.append({**message, "content": _pruned_stub(content)})
            pruned += 1
        else:
            result.append(message)
    return result, pruned


#: What a pruned result keeps. A bare "result no longer in context" stub made the model invent the
#: dropped values instead of reading again: live, qwen3.5:9b wrote two made-up codewords out of ten
#: after reading ten files (R&D validation 2026-11-21). The start and end of a result usually hold
#: what a step needs (a file's first and last lines, a status, a count), and the note says what to do.
PRUNE_EXCERPT_HEAD_CHARS = 200
PRUNE_EXCERPT_TAIL_CHARS = 300


def _pruned_stub(content: str) -> str:
    head = content[:PRUNE_EXCERPT_HEAD_CHARS]
    tail = content[-PRUNE_EXCERPT_TAIL_CHARS:]
    return (
        f"[tool result pruned to save context: {len(content)} chars, only the start and end are kept. "
        "Do not guess the missing part; call the same tool again if you need it.]\n"
        f"{head}\n[…]\n{tail}"
    )


# ---------------------------------------------------------------------------
# Step 3: summarise the old portion, keeping a recent tail intact
# ---------------------------------------------------------------------------

def summarise_messages(messages: list[dict[str, Any]]) -> str:
    """Structured summary of a message slice: tools, errors, files, task.

    Deterministic extraction only — no model call, no invented facts.
    "Decisions" are the tool calls that completed; "open items" are the
    tool calls that errored plus the latest user request in the slice.
    """
    tools_used: list[str] = []
    errored: list[str] = []
    user_texts: list[str] = []
    files: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content", "")
        text = str(content)
        if message.get("role") == "assistant":
            for call in message.get("tool_calls", []) or []:
                function = call.get("function", {}) if isinstance(call, dict) else {}
                name = function.get("name") if isinstance(function, dict) else None
                if isinstance(name, str) and name not in tools_used:
                    tools_used.append(name)
        if message.get("role") == "tool" and '"error"' in text:
            # The tool name is in the preceding assistant message; record
            # the error itself so the summary stays honest about failures.
            snippet = text[:160].replace("\n", " ")
            errored.append(snippet)
        if message.get("role") == "user" and text.strip():
            user_texts.append(text.strip())
        for match in _FILE_RE.findall(text):
            if match not in files:
                files.append(match)
    lines = [
        "[Context compacted — summary of the earlier part of this run; "
        f"{len(messages)} messages replaced. The most recent messages follow in full.]",
        f"User task: {(user_texts[0][:200] if user_texts else '(not recorded)')}",
        "Tools used: " + (", ".join(tools_used) if tools_used else "none"),
    ]
    if files:
        lines.append("Files mentioned: " + ", ".join(files[:20]))
    if errored:
        lines.append(f"Open items: {len(errored)} tool call(s) returned errors:")
        for snippet in errored[:5]:
            lines.append(f"  - {snippet}")
    elif user_texts:
        lines.append(f"Open items: latest request in this part: {user_texts[-1][:200]}")
    else:
        lines.append("Open items: none recorded.")
    return "\n".join(lines)


def _safe_cut(messages: list[dict[str, Any]], latest_start: int) -> int | None:
    """Latest index < ``latest_start`` where the history can be cut safely.

    A cut is safe after a tool message (its assistant call is before the
    cut, its result is before the cut) or after an assistant message
    without tool calls, or after a user message — never between an
    assistant tool-call message and its tool results.
    """
    for index in range(min(latest_start, len(messages)) - 1, 0, -1):
        message = messages[index]
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "tool":
            return index
        if role == "assistant" and not message.get("tool_calls"):
            return index
        if role == "user":
            return index
    return None


def compact_messages(
    messages: list[dict[str, Any]],
    *,
    window_tokens: int | None = None,
    compact_at: float | None = None,
    keep_recent: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compact ``messages`` when they pass the compaction threshold.

    Returns ``(messages, report)``. The report records whether anything was
    done, which stage ran, and token counts before/after. The system message
    (index 0) is never removed; the recent tail is never summarised.
    """
    window = window_tokens if window_tokens is not None else context_window_tokens()
    fraction = compact_at if compact_at is not None else compact_at_fraction()
    recent = keep_recent if keep_recent is not None else keep_recent_messages()
    threshold = int(window * fraction)
    tokens_before = estimate_message_tokens(messages)
    report: dict[str, Any] = {
        "compacted": False,
        "stage": "none",
        "tokens_before": tokens_before,
        "tokens_after": tokens_before,
        "threshold_tokens": threshold,
        "pruned": 0,
        "summarised": 0,
    }
    if tokens_before <= threshold or len(messages) <= 1:
        return list(messages), report

    # Stage 1: prune old tool results.
    pruned_messages, pruned = prune_tool_results(messages)
    report["pruned"] = pruned
    tokens_after_prune = estimate_message_tokens(pruned_messages)
    if tokens_after_prune <= threshold:
        report.update({
            "compacted": True, "stage": "pruned",
            "tokens_after": tokens_after_prune,
        })
        return pruned_messages, report

    # Stage 2: summarise the old portion, keeping the recent tail intact.
    cut = _safe_cut(pruned_messages, len(pruned_messages) - recent)
    if cut is None or cut < 1:
        report.update({
            "compacted": pruned > 0, "stage": "pruned-only",
            "tokens_after": tokens_after_prune,
        })
        return pruned_messages, report
    prefix = pruned_messages[1:cut + 1]
    summary = summarise_messages(prefix)
    compacted = [
        pruned_messages[0],
        {"role": "user", "content": summary},
        *pruned_messages[cut + 1:],
    ]
    report.update({
        "compacted": True, "stage": "summarised",
        "tokens_after": estimate_message_tokens(compacted),
        "summarised": len(prefix),
    })
    return compacted, report
