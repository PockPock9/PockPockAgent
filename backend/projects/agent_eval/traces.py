"""LoRA distillation hooks: export verified traces as SFT data.

Successful, *verified* harness runs are the raw material for distilling
the small executor (report §2.7): fine-tuning teaches format, style
and tool use reliably, and rarely teaches new reasoning — which is
exactly what a small local executor needs. The export therefore keeps
only **format / tool-use** traces:

* Only attempts that **passed verification** are exported. A failed or
  unverified run is not training data.
* Only attempts with **at least one tool call** are exported. A
  no-tool pass teaches nothing about tool use.
* The transcript is the executor loop only — system prompt, user task,
  assistant tool calls, tool results. It contains **no planner
  reasoning** by construction: the harness never runs the planner, and
  no thinking trace is recorded. Never train the executor on planner
  reasoning; that is the planner's job and the executor must stay
  short-output and format-tight.
* Tool results are capped in length so one huge file dump does not
  dominate a training example.

Output is one JSON object per line (SFT chat format)::

    {"schema_version": 1, "task_id": "...", "model": "qwen3.5:2b",
     "quantisation": "Q4_K_M", "seed": 0, "verified": true,
     "messages": [{"role": "system", ...}, {"role": "user", ...},
                  {"role": "assistant", "tool_calls": [...]},
                  {"role": "tool", "content": "..."}],
     "outcome": {"steps": 2, "tokens": 512, "wall_seconds": 41.2}}

No training happens here and no training dependency is added — see
``docs/features/lora-distillation-recipe.md`` for the recipe
(Unsloth/TRL, executor-only) that consumes this file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

TRACE_SCHEMA_VERSION = 1
MAX_TOOL_CONTENT_CHARS = 4_000


def _normalise_tool_calls(calls: Any) -> list[dict[str, Any]]:
    """Normalise assistant tool calls to OpenAI chat shape."""
    normalised: list[dict[str, Any]] = []
    if not isinstance(calls, list):
        return normalised
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            continue
        if "function" in call and isinstance(call["function"], dict):
            normalised.append({
                "id": call.get("id", f"call_{index}"),
                "type": "function",
                "function": {
                    "name": call["function"].get("name", ""),
                    "arguments": call["function"].get("arguments", "{}"),
                },
            })
        elif isinstance(call.get("name"), str):
            normalised.append({
                "id": f"call_{index}",
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call.get("arguments") or {}),
                },
            })
    return normalised


def normalise_transcript(transcript: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Clean one executor transcript into SFT chat messages."""
    messages: list[dict[str, Any]] = []
    for message in transcript:
        role = message.get("role")
        if role == "assistant":
            entry: dict[str, Any] = {"role": "assistant"}
            content = message.get("content")
            if isinstance(content, str) and content:
                entry["content"] = content
            calls = _normalise_tool_calls(message.get("tool_calls"))
            if calls:
                entry["tool_calls"] = calls
            if "content" in entry or "tool_calls" in entry:
                messages.append(entry)
        elif role == "tool":
            content = message.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content)
            messages.append({
                "role": "tool",
                "tool_call_id": str(message.get("tool_call_id", "")),
                "name": str(message.get("name", "")),
                "content": content[:MAX_TOOL_CONTENT_CHARS],
            })
        elif role in {"system", "user"}:
            content = message.get("content", "")
            if isinstance(content, str) and content:
                messages.append({"role": role, "content": content})
    return messages


def trace_record(
    *,
    task_id: str,
    model: str,
    quantisation: str,
    seed: int,
    transcript: Sequence[Mapping[str, Any]],
    outcome: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Build one SFT record, or ``None`` when the trace is unusable.

    Unusable means: no tool calls (nothing to distil about tool use),
    or a transcript without a user message (malformed run).
    """
    messages = normalise_transcript(transcript)
    has_tool_call = any("tool_calls" in message for message in messages)
    has_user = any(message["role"] == "user" for message in messages)
    if not has_tool_call or not has_user:
        return None
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "task_id": task_id,
        "model": model,
        "quantisation": quantisation,
        "seed": seed,
        "verified": True,
        "messages": messages,
        "outcome": {
            "steps": outcome.get("steps"),
            "tokens": outcome.get("tokens"),
            "wall_seconds": outcome.get("wall_seconds"),
        },
    }


def export_traces_from_report(report: Any, out_path: str | Path) -> dict[str, int]:
    """Export verified passing attempts from a live :class:`RunReport`.

    Takes the in-memory report, because transcripts live on the
    ``ExecutorResult`` objects and are deliberately *not* written to
    ``report.json`` (tool results would bloat it with file contents).
    Export traces in the same process as the harness run, right after
    it finishes — a ``report.json`` alone cannot regenerate them.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    attempts = exported = 0
    with out_path.open("w", encoding="utf-8") as handle:
        for task in report.tasks:
            for attempt in task.attempts:
                attempts += 1
                if not attempt.passed:
                    continue
                record = trace_record(
                    task_id=task.task_id,
                    model=report.config.model,
                    quantisation=report.config.quantisation,
                    seed=attempt.seed,
                    transcript=attempt.executor.transcript,
                    outcome={
                        "steps": attempt.executor.steps,
                        "tokens": attempt.executor.tokens,
                        "wall_seconds": round(attempt.executor.wall_seconds, 3),
                    },
                )
                if record is None:
                    continue
                handle.write(json.dumps(record) + "\n")
                exported += 1
    return {"attempts": attempts, "exported": exported, "skipped": attempts - exported}
