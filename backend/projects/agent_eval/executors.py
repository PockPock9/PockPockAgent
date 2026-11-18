"""Executors: what actually attempts an eval task.

Two executors, and the difference between them is the whole point of the
harness design — be explicit about which one produced a number:

* :class:`StubExecutor` — deterministic. It runs the task's reference
  solution (``stub_actions``) through the *real* tool implementations
  (``execute_agent_tool`` / ``execute_project_tool``) in a fresh
  workspace. It proves the harness, the tools and the verifiers work,
  and it measures nothing about a model: a stub pass means "this task
  is solvable and verifiable", not "the agent can do it". Stub runs are
  labelled ``executor: "stub"`` in every report and trace.
* :class:`OllamaExecutor` — live. A small agent loop around a local
  Ollama model via the provider-neutral ``ChatCompletionProvider``:
  Tool-RAG selects the schemas (same ``select_tools`` progressive
  disclosure the gateway uses), the model is called with
  ``think: false`` (Qwen 3.5 returns empty replies otherwise — issue
  #86), tool calls are dispatched through the real registry, results
  feed back for the next turn. This loop deliberately bypasses the
  gateway planner: the planner's 111s timeout bug (issue #83 area) and
  the executor zero-tools bug (issue #92) mean a live gateway
  round-trip cannot currently be measured end-to-end, so the harness
  measures the model + tools directly and records that limitation.
  A gateway-backed executor can replace this loop once those bugs are
  fixed, without changing the task or verifier format.

Both executors return an :class:`ExecutorResult` with the same shape:
steps (tool calls), token estimate, wall time, the tool-call transcript
used for LoRA trace export, and any error. Verification is separate
(see ``verifiers.verify_task``) and is what decides pass/fail.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import aiohttp

from projects.agent_tools import (
    AgentToolContext,
    ProjectAgentContext,
    execute_agent_tool,
    execute_project_tool,
    explicit_task_hosts,
    registered_tool_specs,
)
from projects.agent_tools import workspace as workspace_tools
from projects.agent_tools.tool_retriever import ToolRetriever
from projects.model_router import (
    ChatCompletionProvider,
    ChatCompletionRequest,
    ModelProviderError,
    OllamaChatCompletionAdapter,
    resolve_think,
)

#: Tools implemented by the project-tool path (workspace files).
PROJECT_TOOLS = frozenset({
    "list_project_files",
    "search_project",
    "read_project_file",
    "propose_project_edit",
    "propose_project_patch",
    "validate_project",
})

#: The default system prompt the live executor uses. The prompt
#: optimizer varies this text; keep it short and tool-focused so a
#: 2B model spends its context on the task, not the instructions.
DEFAULT_SYSTEM_PROMPT = (
    "You are a local file agent. Complete the user's task by calling the "
    "tools provided. Call one tool per turn. When the task asks you to "
    "save or create a file, do it with the matching tool and then stop. "
    "Do not describe what you will do instead of doing it, and do not "
    "claim the task is done until a tool result confirms it."
)

DEFAULT_MAX_STEPS = 8
DEFAULT_CALL_TIMEOUT_S = 180


def estimate_tokens(text: str) -> int:
    """Rough token estimate (chars / 4), as in the tool retriever."""
    return max(0, len(text) // 4)


@dataclass
class ExecutorResult:
    """What one executor attempt did, before verification."""

    finished: bool
    steps: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens: int = 0
    wall_seconds: float = 0.0
    transcript: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    final_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "finished": self.finished,
            "steps": self.steps,
            "tool_calls": self.tool_calls,
            "tokens": self.tokens,
            "wall_seconds": round(self.wall_seconds, 3),
            "transcript": self.transcript,
            "error": self.error,
            "final_text": self.final_text,
        }


async def dispatch_tool(
    name: str,
    arguments: dict[str, Any],
    agent_context: AgentToolContext,
    project_context: ProjectAgentContext,
) -> dict[str, Any]:
    """Dispatch one tool call through the real registry.

    ``validate_project`` is special-cased to the in-process validator
    (``workspace.validate_project``): the registry's project-tool path
    calls the loopback validator *service*, which needs a running
    service and an internal token the harness does not have. The
    in-process function runs the same syntax/reference checks.

    Project patches (``propose_project_patch`` / ``propose_project_edit``)
    only *stage* a pending diff in the real agent — the gateway applies
    it after the user approves it. The harness auto-applies the staged
    diff inside the attempt's throwaway workspace (the harness is the
    approver here; nothing leaves the temp dir), so a task can complete
    and be verified in one run. The staged ``patch_id`` and the apply
    outcome are recorded in the returned dict.
    """
    if name in PROJECT_TOOLS:
        if name == "validate_project":
            return workspace_tools.validate_project(project_context)
        result = await execute_project_tool(name, arguments, project_context)
        if name in {"propose_project_patch", "propose_project_edit"}:
            patch_id = result.get("patch_id") if isinstance(result, dict) else None
            if isinstance(patch_id, str):
                applied = workspace_tools.apply_project_patch(
                    patch_id, project_context.project_root
                )
                result = {**result, "applied": applied}
        return result
    return await execute_agent_tool(name, arguments, agent_context)


def make_contexts(task: Any, workspace: Path) -> tuple[AgentToolContext, ProjectAgentContext]:
    """Fresh tool contexts rooted at one attempt's workspace."""
    agent_context = AgentToolContext(
        task_id=f"eval-{task.id}",
        allowed_hosts=explicit_task_hosts(task.prompt),
        attachments=dict(task.attachments),
        output_dir=workspace,
        permission_mode="default",
        permitted_tools=frozenset(
            spec["function"]["name"] for spec in registered_tool_specs()
        ),
    )
    project_context = ProjectAgentContext(
        task_id=f"eval-{task.id}",
        project_root=workspace,
        allow_execution=False,
    )
    return agent_context, project_context


class StubExecutor:
    """Deterministic reference-solution executor (see module docstring)."""

    name = "stub"

    def run(
        self,
        task: Any,
        workspace: Path,
        system_prompt: str,
        *,
        seed: int = 0,
        timeout_s: int = 120,
    ) -> ExecutorResult:
        started = time.monotonic()
        agent_context, project_context = make_contexts(task, workspace)
        tool_calls: list[dict[str, Any]] = []
        transcript: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task.prompt},
        ]

        async def _run() -> None:
            for action in task.stub_actions:
                name = action["tool"]
                arguments = dict(action.get("arguments") or {})
                result = await dispatch_tool(name, arguments, agent_context, project_context)
                tool_calls.append({"tool": name, "arguments": arguments, "result": result})
                transcript.append({
                    "role": "assistant",
                    "tool_calls": [{"name": name, "arguments": arguments}],
                })
                transcript.append({"role": "tool", "name": name, "content": json.dumps(result)})

        try:
            asyncio.run(_run())
        except Exception as err:  # noqa: BLE001 - stub failure is a result, not a crash
            return ExecutorResult(
                finished=False,
                steps=len(tool_calls),
                tool_calls=tool_calls,
                tokens=estimate_tokens(task.prompt + system_prompt),
                wall_seconds=time.monotonic() - started,
                transcript=transcript,
                error=f"{type(err).__name__}: {err}",
            )
        return ExecutorResult(
            finished=True,
            steps=len(tool_calls),
            tool_calls=tool_calls,
            tokens=estimate_tokens(task.prompt + system_prompt),
            wall_seconds=time.monotonic() - started,
            transcript=transcript,
            final_text="Reference solution executed.",
        )


def _openai_tool_calls(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Tool calls from an OpenAI-compatible chat completion response."""
    calls: list[dict[str, Any]] = []
    try:
        message = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return calls
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(function.get("name"), str) and isinstance(arguments, dict):
            calls.append({"name": function["name"], "arguments": arguments})
    return calls


def _response_text(response: Mapping[str, Any]) -> str:
    try:
        return str(response["choices"][0]["message"].get("content") or "")
    except (KeyError, IndexError, TypeError):
        return ""


def _response_tokens(response: Mapping[str, Any], messages: Sequence[Mapping[str, Any]]) -> int:
    usage = response.get("usage") if isinstance(response, dict) else None
    if isinstance(usage, dict) and isinstance(usage.get("total_tokens"), int):
        return usage["total_tokens"]
    return sum(estimate_tokens(json.dumps(message)) for message in messages)


class OllamaExecutor:
    """Live agent loop against a local Ollama model (see module docstring)."""

    name = "ollama"

    def __init__(
        self,
        provider: ChatCompletionProvider | None = None,
        *,
        model: str,
        max_steps: int = DEFAULT_MAX_STEPS,
        call_timeout_s: int = DEFAULT_CALL_TIMEOUT_S,
        temperature: float = 0.0,
        base_url: str = "http://127.0.0.1:11434",
    ) -> None:
        self.provider = provider or OllamaChatCompletionAdapter(base_url)
        self.model = model
        self.max_steps = max_steps
        self.call_timeout_s = call_timeout_s
        self.temperature = temperature

    def run(
        self,
        task: Any,
        workspace: Path,
        system_prompt: str,
        *,
        seed: int = 0,
        timeout_s: int = 120,
    ) -> ExecutorResult:
        started = time.monotonic()
        agent_context, project_context = make_contexts(task, workspace)
        specs = registered_tool_specs()
        selected_specs, _retrieval = ToolRetriever().select_tools(task.prompt, specs, top_k=8)
        tools = selected_specs or specs
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task.prompt},
        ]
        transcript: list[dict[str, Any]] = [dict(message) for message in messages]
        tool_calls: list[dict[str, Any]] = []
        tokens = 0
        error: str | None = None
        final_text = ""

        async def _run() -> None:
            nonlocal tokens, error, final_text
            for _step in range(self.max_steps):
                request = ChatCompletionRequest(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    temperature=self.temperature,
                    think=resolve_think(self.model, tools=True),
                    options={"seed": seed},
                )
                try:
                    response = await self.provider.complete(
                        request,
                        timeout=aiohttp.ClientTimeout(total=self.call_timeout_s),
                    )
                except (ModelProviderError, aiohttp.ClientError, asyncio.TimeoutError) as err:
                    error = f"{type(err).__name__}: {err}"
                    return
                tokens += _response_tokens(response, messages)
                calls = _openai_tool_calls(response)
                text = _response_text(response)
                if calls:
                    assistant_message: dict[str, Any] = {
                        "role": "assistant",
                        "content": text,
                        "tool_calls": [
                            {
                                "id": f"call_{len(tool_calls) + index}",
                                "type": "function",
                                "function": {
                                    "name": call["name"],
                                    "arguments": json.dumps(call["arguments"]),
                                },
                            }
                            for index, call in enumerate(calls)
                        ],
                    }
                else:
                    assistant_message = {"role": "assistant", "content": text}
                messages.append(assistant_message)
                transcript.append(dict(assistant_message))
                if not calls:
                    final_text = text
                    return
                for call in calls:
                    name = call["name"]
                    arguments = call["arguments"]
                    try:
                        result = await asyncio.wait_for(
                            dispatch_tool(name, arguments, agent_context, project_context),
                            timeout=timeout_s,
                        )
                        result_text = json.dumps(result)
                    except Exception as err:  # noqa: BLE001 - tool errors feed back to the model
                        result_text = json.dumps({"error": f"{type(err).__name__}: {err}"})
                        result = {"error": result_text}
                    tool_calls.append({"tool": name, "arguments": arguments, "result": result})
                    tool_message = {
                        "role": "tool",
                        "tool_call_id": f"call_{len(tool_calls) - 1}",
                        "name": name,
                        "content": result_text,
                    }
                    messages.append(tool_message)
                    transcript.append(dict(tool_message))
            error = f"Stopped after {self.max_steps} tool steps without finishing"
            final_text = _response_text({})  # no final answer within the step budget

        try:
            asyncio.run(_run())
        except Exception as err:  # noqa: BLE001 - executor failure is a result
            error = f"{type(err).__name__}: {err}"
        return ExecutorResult(
            finished=error is None,
            steps=len(tool_calls),
            tool_calls=tool_calls,
            tokens=tokens,
            wall_seconds=time.monotonic() - started,
            transcript=transcript,
            error=error,
            final_text=final_text,
        )
