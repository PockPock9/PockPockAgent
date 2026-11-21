"""Code-first verifier for Plan-and-Sequence done-conditions (P2).

The verifier checks a step's done-condition against the real state — files
on disk and the recorded step result — never against the model's claim
that it succeeded. It runs no model calls and executes no shell commands;
it only reads files and the step result the runner recorded.

``verify_done_condition`` never raises for bad input: any malformed
condition, path, or step result is reported as ``passed=False`` with a
``detail`` explaining why.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import DoneCondition

__all__ = ["verify_done_condition"]


def _coerce_condition(condition: Any) -> dict[str, Any] | None:
    """Normalise a dict or :class:`DoneCondition` to a plain dict.

    Returns ``None`` when the condition is not a dict or a DoneCondition.
    """
    if isinstance(condition, DoneCondition):
        return condition.model_dump(mode="json")
    if isinstance(condition, dict):
        return condition
    return None


def _fail(detail: str, evidence: str = "") -> dict[str, Any]:
    return {"passed": False, "evidence": evidence, "detail": detail}


def _resolve_inside(workspace: Path, path: str) -> Path | None:
    """Resolve ``path`` against ``workspace``; ``None`` if it escapes.

    Mirrors the workspace rule in ``projects.agent_tools.workspace``:
    the resolved path must stay inside the resolved workspace root, so
    ``..`` segments, absolute paths outside the workspace, and symlinks
    pointing outside are all rejected.
    """
    try:
        root = workspace.resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    try:
        candidate = Path(path)
        target = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        target.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return target


def _tool_calls(step_result: dict | None) -> list | None:
    """The recorded tool calls, or ``None`` when the shape is unusable."""
    if not isinstance(step_result, dict):
        return None
    calls = step_result.get("tool_calls", [])
    if not isinstance(calls, list):
        return None
    return calls


def _values(step_result: dict | None) -> dict | None:
    if not isinstance(step_result, dict):
        return None
    values = step_result.get("values", {})
    if not isinstance(values, dict):
        return None
    return values


def verify_done_condition(
    condition: Any,
    *,
    workspace: Path | None,
    step_result: dict | None,
    artifact_dir: Path | None = None,
) -> dict:
    """Check one done-condition against files and the recorded step result.

    File conditions look in ``workspace`` and then in ``artifact_dir``, the run's task folder where the
    artifact tools save files. With a folder open the two differ, and a step that saved its file with
    save_text_artifact could never pass a check against the open folder alone.

    Returns ``{"passed": bool, "evidence": str, "detail": str}``. Never
    raises for bad input.
    """
    try:
        roots = [root for root in (workspace, artifact_dir) if root is not None]
        if not roots:
            return _verify(condition, workspace=None, step_result=step_result)
        result: dict = {}
        for root in dict.fromkeys(Path(item).resolve() for item in roots):
            result = _verify(condition, workspace=root, step_result=step_result)
            if result.get("passed"):
                return result
        return result
    except Exception as exc:  # Defensive: the verifier must never raise.
        return _fail(f"verifier error: {exc}")


def _verify(condition: Any, *, workspace: Path | None, step_result: dict | None) -> dict:
    cond = _coerce_condition(condition)
    if cond is None:
        return _fail("invalid done-condition: expected a dict or DoneCondition")
    cond_type = cond.get("type")
    if not isinstance(cond_type, str) or not cond_type:
        return _fail("invalid done-condition: missing type")

    if cond_type in ("file_exists", "file_contains"):
        path = cond.get("path")
        if not isinstance(path, str) or not path.strip():
            return _fail(f"done-condition '{cond_type}' requires a path")
        if workspace is None:
            return _fail("no workspace")
        target = _resolve_inside(Path(workspace), path)
        if target is None:
            return _fail(f"path escapes the workspace: {path}")
        if cond_type == "file_exists":
            if target.is_file():
                return {
                    "passed": True,
                    "evidence": f"file exists: {path}",
                    "detail": f"file exists: {path}",
                }
            return _fail(f"file does not exist: {path}")
        # file_contains
        pattern = cond.get("pattern")
        if not isinstance(pattern, str) or pattern == "":
            return _fail("done-condition 'file_contains' requires a pattern")
        if not target.is_file():
            return _fail(f"file does not exist: {path}")
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return _fail(f"could not read file: {path}: {exc}")
        for line in text.splitlines():
            if pattern in line:
                return {
                    "passed": True,
                    "evidence": line[:200],
                    "detail": f"file contains pattern: {path}",
                }
        return _fail(f"file does not contain pattern: {path}")

    if cond_type == "command_exit_0":
        calls = _tool_calls(step_result)
        if calls is None:
            return _fail("invalid step result: tool_calls must be a list")
        exit_codes = [
            call.get("exit_code")
            for call in calls
            if isinstance(call, dict) and call.get("exit_code") is not None
        ]
        if not exit_codes:
            return _fail("no command result recorded")
        if any(not isinstance(code, int) or isinstance(code, bool) or code != 0 for code in exit_codes):
            return _fail(
                "command failed: "
                + ", ".join(str(code) for code in exit_codes if code != 0)
            )
        return {
            "passed": True,
            "evidence": "all recorded commands exited 0",
            "detail": "all recorded commands exited 0",
        }

    if cond_type == "value_equals":
        field = cond.get("field")
        expected = cond.get("expected")
        if not isinstance(field, str) or not field:
            return _fail("done-condition 'value_equals' requires a field")
        if expected is None:
            return _fail("done-condition 'value_equals' requires an expected value")
        values = _values(step_result)
        if values is None:
            return _fail("invalid step result: values must be a dict")
        actual = values.get(field)
        if actual is None:
            return _fail(f"value missing for field: {field}")
        if str(actual) == str(expected):
            return {
                "passed": True,
                "evidence": f"{field} == {expected}",
                "detail": f"{field} == {expected}",
            }
        return _fail(f"value mismatch for field '{field}': got {actual!r}, expected {expected!r}")

    if cond_type == "no_error":
        calls = _tool_calls(step_result)
        if calls is None:
            return _fail("invalid step result: tool_calls must be a list")
        errors = step_result.get("errors", []) if isinstance(step_result, dict) else []
        if not isinstance(errors, list):
            return _fail("invalid step result: errors must be a list")
        if errors:
            return _fail(f"errors recorded: {'; '.join(str(e) for e in errors)[:200]}")
        failed = [
            call.get("tool", "?")
            for call in calls
            if isinstance(call, dict) and not call.get("ok", False)
        ]
        if failed:
            return _fail(f"tool call(s) failed: {', '.join(str(name) for name in failed)}")
        return {
            "passed": True,
            "evidence": "no errors recorded",
            "detail": "no errors recorded",
        }

    return _fail(f"unknown done-condition type: {cond_type}")
