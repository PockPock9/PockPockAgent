"""Bounded, dependency-aware scheduling helpers for local delegate runs."""

import asyncio
from copy import deepcopy
import os
import re
from typing import Any, Awaitable, Callable
import uuid

from projects.planner.contracts import ProposedSubtask, SubtaskPlan
from projects.run_store.contracts import DelegationContract, delegate_task_prompt


DEFAULT_DELEGATE_CONCURRENCY = 3
MAX_DELEGATE_CONCURRENCY = 16
_DELEGATE_RUN_NAMESPACE = uuid.UUID("f52c8fd0-84b8-4bc7-a6d1-1f3a899250c8")


def configured_delegate_concurrency(value: str | None = None) -> int:
    raw = os.environ.get("POCKPOCK_MAX_DELEGATE_CONCURRENCY") if value is None else value
    if raw is None:
        return DEFAULT_DELEGATE_CONCURRENCY
    try:
        limit = int(raw)
    except (TypeError, ValueError) as err:
        raise ValueError("POCKPOCK_MAX_DELEGATE_CONCURRENCY must be an integer.") from err
    if not 1 <= limit <= MAX_DELEGATE_CONCURRENCY:
        raise ValueError(f"Delegate concurrency must be between 1 and {MAX_DELEGATE_CONCURRENCY}.")
    return limit


def stable_delegate_run_id(parent_run_id: str, subtask_id: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", parent_run_id):
        raise ValueError("A valid parent run ID is required.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", subtask_id):
        raise ValueError("A valid subtask ID is required.")
    return uuid.uuid5(_DELEGATE_RUN_NAMESPACE, f"{parent_run_id}:{subtask_id}").hex


async def run_subtask_plan(
    plan: SubtaskPlan,
    execute: Callable[[ProposedSubtask, dict[str, Any]], Awaitable[Any]],
    *,
    max_concurrency: int | None = None,
    cancel_event: asyncio.Event,
) -> dict[str, Any]:
    """Run only dependency-ready subtasks and stop active work on cancellation/errors."""
    limit = configured_delegate_concurrency() if max_concurrency is None else max_concurrency
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_DELEGATE_CONCURRENCY:
        raise ValueError(f"Delegate concurrency must be between 1 and {MAX_DELEGATE_CONCURRENCY}.")

    pending = {subtask.id: subtask for subtask in plan.subtasks}
    running: dict[asyncio.Task, ProposedSubtask] = {}
    results: dict[str, Any] = {}

    async def cancel_running() -> None:
        tasks = list(running)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        running.clear()

    try:
        while pending or running:
            if cancel_event.is_set():
                raise asyncio.CancelledError

            capacity = limit - len(running)
            ready = [
                subtask for subtask in plan.subtasks
                if subtask.id in pending and set(subtask.depends_on).issubset(results)
            ][:capacity]
            for subtask in ready:
                dependencies = {
                    dependency_id: deepcopy(results[dependency_id])
                    for dependency_id in subtask.depends_on
                }
                task = asyncio.create_task(execute(subtask, dependencies))
                running[task] = subtask
                del pending[subtask.id]

            if not running:
                if pending:
                    raise ValueError("The approved subtask graph cannot make progress.")
                break

            cancel_waiter = asyncio.create_task(cancel_event.wait())
            try:
                done, _ = await asyncio.wait(
                    [*running, cancel_waiter],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_waiter in done and cancel_event.is_set():
                    raise asyncio.CancelledError
                for task in done:
                    if task is cancel_waiter:
                        continue
                    subtask = running.pop(task)
                    results[subtask.id] = task.result()
            finally:
                cancel_waiter.cancel()
                await asyncio.gather(cancel_waiter, return_exceptions=True)
    except BaseException:
        await cancel_running()
        raise
    return results


def create_or_load_delegate_run(
    parent_run_id: str,
    conversation_id: str | None,
    subtask: ProposedSubtask,
    *,
    dependency_run_ids: list[str],
    permission_level: str,
    deadline_at: str,
) -> tuple[bool, dict[str, Any], list[dict[str, Any]]]:
    """Create one deterministic child run or return its durable state on retry."""
    import agent_run_store

    subtask_data = subtask.model_dump(mode="json")
    run_id = stable_delegate_run_id(parent_run_id, subtask.id)
    context_scope = ["approved_task"]
    if subtask.depends_on:
        context_scope.append("dependency_results")
    contract = DelegationContract(
        parent_run_id=parent_run_id,
        subtask_id=subtask.id,
        role=subtask.role,
        dependency_ids=dependency_run_ids,
        context_scope=context_scope,
        workspace_scope="isolated_task_workspace",
        artifact_scope=[],
        allowed_tools=subtask.allowed_tools,
        max_tool_calls=subtask.max_tool_calls,
        max_duration_seconds=subtask.max_duration_seconds,
        permission_level=permission_level,
        deadline_at=deadline_at,
    )
    task = delegate_task_prompt(subtask_data)
    created = True
    try:
        agent_run_store.create_agent_run(
            run_id,
            conversation_id,
            "delegate",
            task,
            contract.model_dump(mode="json"),
            permission_level,
        )
    except agent_run_store.RunAlreadyExists:
        created = False

    run, events = agent_run_store.get_run_events(run_id, 0, 1000)
    if run is None:
        raise RuntimeError("The delegate run was not available after creation or retry.")
    delegation = run.get("delegation") or {}
    if (
        run.get("conversation_id") != conversation_id
        or run.get("task_type") != "delegate"
        or run.get("title") != task[:160]
        or delegation.get("parent_run_id") != parent_run_id
        or delegation.get("subtask_id") != subtask.id
        or delegation.get("role") != subtask.role
        or delegation.get("dependency_ids") != dependency_run_ids
        or delegation.get("context_scope") != context_scope
        or delegation.get("workspace_scope") != "isolated_task_workspace"
        or delegation.get("artifact_scope") != []
        or delegation.get("allowed_tools") != subtask.allowed_tools
        or delegation.get("max_tool_calls") != subtask.max_tool_calls
        or delegation.get("max_duration_seconds") != subtask.max_duration_seconds
        or delegation.get("permission_level") != permission_level
    ):
        raise agent_run_store.InvalidRunRelationship(
            "The stable delegate run ID is already bound to a different subtask contract."
        )
    return created, run, events


def existing_delegate_result(run: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Project an existing child state into the typed scheduler result without rerunning it."""
    for item in reversed(events):
        event = item.get("event", {}) if isinstance(item, dict) else {}
        result = event.get("result") if isinstance(event, dict) else None
        if event.get("type") == "delegate_result" and isinstance(result, dict):
            return result
    status_map = {
        "completed": "completed",
        "partial": "partial",
        "cancelled": "cancelled",
        "timed_out": "timed_out",
        "failed": "failed",
        "interrupted": "failed",
    }
    status = status_map.get(str(run.get("status")), "partial")
    summary = "This delegate run already exists; it was not started again."
    for item in reversed(events):
        event = item.get("event", {}) if isinstance(item, dict) else {}
        if not isinstance(event, dict):
            continue
        if event.get("type") == "token" and isinstance(event.get("content"), str):
            summary = event["content"][:4000] or summary
            break
        if event.get("type") == "error" and isinstance(event.get("message"), str):
            summary = event["message"][:4000]
            break
    return {
        "contract_version": 1,
        "status": status,
        "summary": summary,
        "evidence": [],
        "artifact_ids": [],
        "incomplete_checks": [] if status == "completed" else ["Existing delegate run was not dispatched again."],
    }
