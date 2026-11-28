"""OpenClaw as the worker for one Plan-in-steps step (the ``openclaw_agent`` step tool).

PockPock plans and checks; OpenClaw does the steps the step model's tools cannot (shell commands, installs,
builds, the browser, apps). For such a step the sequence runner calls the delegate made here, which:
- starts an OpenClaw turn in the run's folder, in one session per run (so OpenClaw's long prompt stays cached
  in Ollama from step to step), with the run's permission (Full access -> full, Auto-review -> auto);
- relays OpenClaw's tool lines, command details and approvals to the app as ``openclaw_*`` events, and stops
  the step's clock while an approval waits for the user;
- returns a step result for the code check: one entry per OpenClaw action, the last command's exit code
  (an earlier failed attempt that OpenClaw then fixed does not count), and an error only when the turn failed.

The runner then verifies the step's done-condition in code as for any step, never on OpenClaw's word.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any, Callable

from .bridge import OpenClawBridge, OpenClawError

PERMISSION = {"full-access": "full", "auto-review": "auto"}
BUSY_RETRIES = 10
BUSY_WAIT_SECONDS = 2.0


def openclaw_model(executor_model: str | None) -> str | None:
    """The run's local executor model, so one model serves both. OpenClaw's helper knows local models by their
    bare Ollama name ("qwen3.5:9b"; "ollama/qwen3.5:9b" was refused, live run 2026-11-28); a cloud executor
    ("<provider>/<model>") uses OpenClaw's default model."""
    from projects.model_router.cloud import is_cloud_model

    if not executor_model or is_cloud_model(executor_model):
        return None
    return executor_model


def make_openclaw_delegate(
    bridge: OpenClawBridge,
    *,
    run_id: str,
    folder: Path,
    permission_mode: str,
    executor_model: str | None,
    emit: Callable[[dict], None],
) -> Callable | None:
    """The runner's ``delegate``, or None when OpenClaw cannot run steps (not installed, or Default permission)."""
    mode = PERMISSION.get(permission_mode)
    if mode is None or not bridge.available()[0]:
        return None
    session = f"pockpock-steps-{run_id[:16]}"

    async def delegate(*, step: dict, prompt: str, run_id: str, attempt: int, waiting) -> dict[str, Any]:
        step_id = str(step.get("id", ""))
        turn = None
        for wait in range(BUSY_RETRIES + 1):
            try:
                turn = await asyncio.to_thread(bridge.start_turn, session, prompt, mode, openclaw_model(executor_model), None, str(folder))
                break
            except OpenClawError as err:
                # The previous turn (this step's last attempt) may still be closing its process, or the user's
                # own OpenClaw chat is running: wait a little before giving up.
                if err.code != "busy" or wait == BUSY_RETRIES:
                    return {"tool_calls": [], "values": {}, "errors": [f"OpenClaw could not start: {err}"]}
                await asyncio.sleep(BUSY_WAIT_SECONDS)
        calls: dict[str, dict] = {}
        order: list[str] = []
        errors: list[str] = []
        reply = ""
        waits = contextlib.ExitStack()
        pending: set[str] = set()
        emit({"type": "openclaw_step", "step_id": step_id, "attempt": attempt, "message": "OpenClaw is doing this step"})
        try:
            while True:
                event = await asyncio.to_thread(turn.next_event, 1.0)
                if event is False:
                    continue
                if event is None:
                    break
                kind = event.get("type")
                if kind == "tool":
                    call_id = str(event.get("id") or len(order))
                    if call_id not in calls:
                        calls[call_id] = {"tool": f"openclaw:{event.get('name') or 'tool'}", "ok": True, "output": str(event.get("title") or "")[:300]}
                        order.append(call_id)
                    if event.get("phase") != "start" and event.get("status") not in (None, "completed"):
                        # A failed action is kept in the record but does not fail the step by itself:
                        # OpenClaw often retries and fixes it. The code check decides.
                        calls[call_id]["output"] += f" ({event.get('status')}: {str(event.get('error') or '')[:200]})"
                    emit({"type": "openclaw_tool", **{k: event.get(k) for k in ("phase", "id", "name", "title", "status", "error")}})
                elif kind == "tool_detail":
                    call_id = str(event.get("id") or "")
                    if call_id in calls and isinstance(event.get("exitCode"), int):
                        calls[call_id]["exit_code"] = event["exitCode"]
                    emit({"type": "openclaw_tool_detail", **{k: event.get(k) for k in ("id", "name", "command", "input", "output", "exitCode", "durationMs", "cwd", "diff", "failed") if event.get(k) is not None}})
                elif kind == "approval":
                    approval_id = str(event.get("id"))
                    if approval_id not in pending:
                        pending.add(approval_id)
                        waits.enter_context(waiting())
                    emit({"type": "openclaw_approval", "id": approval_id, "title": event.get("title"), "description": event.get("description"),
                          "severity": event.get("severity"), "tool_name": event.get("toolName"), "untrusted": event.get("untrusted") is True})
                elif kind == "approval_resolved":
                    pending.discard(str(event.get("id")))
                    if not pending:
                        waits.close()
                        waits = contextlib.ExitStack()
                    emit({"type": "openclaw_approval_resolved", "id": event.get("id"), "decision": event.get("decision")})
                elif kind in ("delta",):
                    reply += str(event.get("text") or "")
                elif kind in ("replace", "final"):
                    reply = str(event.get("text") or reply)
                elif kind == "error":
                    errors.append(f"OpenClaw: {str(event.get('message') or 'the turn failed')[:300]}")
        except asyncio.CancelledError:
            await asyncio.to_thread(turn.abort)
            raise
        finally:
            waits.close()
            # Release OpenClaw before the runner's next attempt or step starts a turn.
            await asyncio.to_thread(turn.close)
        # Only the last command's exit code counts for a "command exits 0" check.
        with_codes = [call_id for call_id in order if "exit_code" in calls[call_id]]
        for call_id in with_codes[:-1]:
            calls[call_id].pop("exit_code")
        tool_calls = [calls[call_id] for call_id in order]
        tool_calls.append({"tool": "openclaw_agent", "ok": not errors, "output": reply.strip()[:2000]})
        return {"tool_calls": tool_calls, "values": {}, "errors": errors}

    return delegate
