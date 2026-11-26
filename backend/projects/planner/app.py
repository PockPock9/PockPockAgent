"""Planning and tool-capable model selection service."""

import json
import os
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "projects"))
from internal_auth import require_internal_token

import aiohttp
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from planner.critic import review_plan
from planner.contracts import normalized_plan_steps, normalized_subtask_plan, normalized_task_brief
from planner.routing import choose_candidate
from projects.agent_tools import registered_tool_contracts
from projects.model_router import ChatCompletionRequest, ModelProviderError, OllamaChatCompletionAdapter
from projects.plan_sequence.contracts import SEQUENCE_CONTRACT_VERSION, repair_artifact_tools, repair_folder_writes, repair_read_tools, validate_sequence_plan
from projects.plan_sequence.routing import choose_executor_model, choose_planner_model
from projects.model_router.cloud import OpenAICompatibleAdapter, RoutingChatCompletionProvider

app = FastAPI(title="PockPock Planner", docs_url=None, redoc_url=None, openapi_url=None)
OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
# Cloud models ("<provider>/<model>") go through the gateway's local endpoint, which holds the keys.
GATEWAY_URL = os.environ.get("POCKPOCK_GATEWAY_URL", "http://127.0.0.1:8766").rstrip("/")
MODEL_CLIENT = RoutingChatCompletionProvider(
    OllamaChatCompletionAdapter(OLLAMA_URL),
    OpenAICompatibleAdapter(f"{GATEWAY_URL}/cloud/v1", os.environ.get("POCKPOCK_INTERNAL_TOKEN", "")),
)
LARGE_MODEL_BILLIONS = 20.0


async def _request_model_json(
    model: str,
    messages: list[dict[str, str]],
    *,
    timeout: aiohttp.ClientTimeout,
    role: str,
    temperature: float = 0.1,
    schema: dict | None = None,
) -> dict:
    # Streamed, so the read timeout is the longest silence, not the whole answer: a slow model that
    # keeps writing is never cut off, while one that stops is. A single non-streamed request used to
    # end at about 111 seconds on a CPU-only computer, before a small model finished its plan.
    request = ChatCompletionRequest(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
        json_schema=schema,
        context_window=8192,
        think=False,
    )
    try:
        parts = [token async for token in MODEL_CLIENT.stream_tokens(request, timeout=timeout)]
    except ModelProviderError as err:
        status = f" (HTTP {err.status_code})" if err.status_code is not None else ""
        raise HTTPException(status_code=502, detail=f"The {role} model failed{status}.") from err
    content = "".join(parts)
    if not content.strip():
        raise ValueError(f"{role.capitalize()} model returned no JSON content")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError(f"{role.capitalize()} model returned an invalid object")
    return parsed


#: The shape of a /plan reply. Sent as Ollama's ``format`` so decoding is constrained to it: a small
#: model can no longer return prose, a truncated object or a plan that is not a list. Loose on
#: purpose (no length limits, extra keys allowed): the content is still checked by
#: normalized_plan_steps / normalized_task_brief, and too strict a grammar hurts small models.
PLAN_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "plan": {"type": "array", "items": {"type": "string"}},
        "execution_prompt": {"type": "string"},
        "reason": {"type": "string"},
        "task_brief": {"type": "object"},
        "delegation_plan": {"type": "object"},
        "step_details": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
    },
    "required": ["plan", "execution_prompt", "reason", "task_brief"],
}


async def _plan_json(model: str, prompt: str, *, timeout: aiohttp.ClientTimeout) -> tuple[dict, list[str]]:
    """The planner's reply and its steps. An unusable reply (not JSON, or no steps) gets one retry
    that says what was wrong; a timeout or model error is not retried (it would only take as long)."""
    messages = [{"role": "user", "content": prompt}]
    try:
        parsed = await _request_model_json(model, messages, timeout=timeout, role="planner", schema=PLAN_SCHEMA)
        steps = normalized_plan_steps(parsed.get("plan"))
        if not steps:
            raise ValueError("the plan list was empty")
        return parsed, steps
    except (ValueError, TypeError) as err:
        problem = str(err)[:300]
    retry = messages + [{"role": "user", "content": (
        f"Your previous reply could not be used: {problem}. Reply again with only the JSON object described above, "
        "with plan as a list of 3-10 short step strings."
    )}]
    parsed = await _request_model_json(model, retry, timeout=timeout, role="planner", schema=PLAN_SCHEMA)
    steps = normalized_plan_steps(parsed.get("plan"))
    if not steps:
        raise ValueError("Planner returned no usable plan steps")
    return parsed, steps


MAX_STEP_DETAILS = 5
MAX_STEP_DETAIL_CHARS = 160


def normalized_step_details(raw: object, steps: list[str]) -> list[list[str]]:
    """The planner's small actions under each step (owner request 2026-11-26: "each step should have
    many small points of what the agent is going to do"), aligned with the steps: one list per step,
    at most five short strings each; anything missing or malformed becomes an empty list."""
    rows = raw if isinstance(raw, list) else []
    details: list[list[str]] = []
    for index in range(len(steps)):
        row = rows[index] if index < len(rows) and isinstance(rows[index], list) else []
        items = []
        for item in row:
            if isinstance(item, str) and item.strip():
                text = " ".join(item.split())
                items.append(text if len(text) <= MAX_STEP_DETAIL_CHARS else text[: MAX_STEP_DETAIL_CHARS - 1] + "…")
            if len(items) >= MAX_STEP_DETAILS:
                break
        details.append(items)
    return details


def with_step_details(execution_prompt: str, steps: list[str], details: list[list[str]]) -> str:
    """Adds the planned actions to the run's instructions, so the agent follows the same small steps."""
    if not any(details):
        return execution_prompt
    lines = []
    for index, (step, actions) in enumerate(zip(steps, details), start=1):
        lines.append(f"{index}. {step}")
        lines.extend(f"   - {action}" for action in actions)
    return execution_prompt + "\n\nPlanned actions for each step (follow them in order):\n" + "\n".join(lines)


#: Longest silence allowed while a planner call streams. Ollama sends nothing while it reads the
#: prompt, which takes a few minutes for a small model on a CPU, so this is generous.
PLANNER_IDLE_SECONDS = 240


def _env_seconds(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if 30 <= value <= 3600 else default


def planning_timeout(profiles: list[dict], model: str) -> aiohttp.ClientTimeout:
    """Time for one planner/critic call: 10 minutes, 15 for large models that run partly on the CPU.

    ``sock_read`` is the longest silence while the reply streams. Override with
    POCKPOCK_PLANNER_TIMEOUT_SECONDS and POCKPOCK_PLANNER_IDLE_SECONDS.
    """
    size = next((item.get("parameter_billions") for item in profiles if item.get("name") == model), None)
    large = isinstance(size, (int, float)) and size >= LARGE_MODEL_BILLIONS
    total = _env_seconds("POCKPOCK_PLANNER_TIMEOUT_SECONDS", 900 if large else 600)
    idle = min(total, _env_seconds("POCKPOCK_PLANNER_IDLE_SECONDS", PLANNER_IDLE_SECONDS))
    return aiohttp.ClientTimeout(total=total, sock_read=idle)


class PlanRequest(BaseModel):
    task: str = Field(min_length=1, max_length=8_000)
    capable_models: list[str] = Field(min_length=1, max_length=64)
    model_profiles: list[dict] = Field(default_factory=list, max_length=64)
    preferred_model: str | None = Field(default=None, max_length=120)
    default_model: str = Field(min_length=1, max_length=120)
    workspace_path: str | None = Field(default=None, max_length=1024)
    permission_mode: str = Field(default="auto-review", pattern=r"^(default|auto-review|full-access)$")

    @field_validator("task")
    @classmethod
    def task_has_text(cls, value: str) -> str:
        # A task of only spaces became "" later and surfaced as a 502 (issue #73).
        if not value.strip():
            raise ValueError("Describe the task to plan.")
        return value


class SequencePlanRequest(BaseModel):
    """Request for POST /plan-sequence: same shapes as PlanRequest, plus planner_model."""

    task: str = Field(min_length=1, max_length=8_000)
    capable_models: list[str] = Field(min_length=1, max_length=64)
    model_profiles: list[dict] = Field(default_factory=list, max_length=64)
    preferred_model: str | None = Field(default=None, max_length=120)
    default_model: str = Field(min_length=1, max_length=120)
    workspace_path: str | None = Field(default=None, max_length=1024)
    permission_mode: str = Field(default="auto-review", pattern=r"^(default|auto-review|full-access)$")
    planner_model: str | None = Field(default=None, max_length=120)
    # The model the user chose for the steps (the composer's model); used when it is available.
    executor_model: str | None = Field(default=None, max_length=120)

    @field_validator("task")
    @classmethod
    def task_has_text(cls, value: str) -> str:
        # A task of only spaces became "" later and surfaced as a 502 (issue #73).
        if not value.strip():
            raise ValueError("Describe the task to plan.")
        return value


def build_execution_prompt(task: str, plan: list[str], model_prompt: object) -> str:
    prompt = ""
    if isinstance(model_prompt, str):
        prompt = re.sub(r"^\s*```[^\n]*\n?|\n?```\s*$", "", model_prompt.strip())

    if len(re.findall(r"\b[\w'-]+\b", prompt)) < 40:
        model_guidance = prompt
        reviewed_steps = "\n".join(f"{index}. {step}" for index, step in enumerate(plan, start=1))
        prompt = (
            f"Complete only the following user request: {task}\n\n"
            f"Reviewed plan:\n{reviewed_steps}\n\n"
            "Use only capabilities allowed by the task brief. Do not invent extra work, files, downloads, or interactions. "
            "Execute the reviewed steps in order. Verify every success check using available tools. If a step or check "
            "cannot be completed, stop and report the exact limitation. In the final response, state only what you "
            "actually did and observed."
        )
        if model_guidance:
            prompt += f"\n\nSupplementary planner guidance: {model_guidance}"

    return (
        f"Original user request: {task}\n\nComplete only the requested outcome with the minimum required capabilities. "
        "Do not invent file deliverables or workspace changes. If files are created or changed, name them; report validation only if performed.\n\n"
        f"Detailed execution prompt:\n{prompt}"
    )[:4_000]


def build_sequence_plan_prompt(task: str, tool_names: list[str], workspace_path: str | None, permission_mode: str) -> str:
    """Ask the planner model for a validated sequence plan (Plan-and-Sequence P3)."""
    tools = ", ".join(tool_names)
    return (
        "Break the user's request into a validated sequence plan for a small local model to execute one subtask at a time. "
        "Return JSON only, with this shape: "
        '{"contract_version": 1, "task": "<the request>", "steps": [{"id": "find-invoices", "goal": "<one sentence>", '
        '"tools_allowed": ["<tool>"], "budget_tokens": 4000, "budget_seconds": 300, '
        '"done_condition": {"type": "file_exists", "path": "summary.md"}, "inputs": ["task"]}]}. '
        "Rules: 2-15 sequential steps, in execution order: as few as the task needs (5-15 for a larger task). Each step id is lowercase letters, digits, dashes or underscores "
        "(max 32 characters) and unique. Each goal is one sentence (max 280 characters) stating only what that step achieves. "
        "Each tools_allowed lists 1-3 tools, drawn only from this list: "
        f"{tools}. "
        "Use no other tool names: the plan is validated and rejected if a step names a tool that does not exist. "
        "To create a .txt, .md, .csv, .json or .html file use save_text_artifact; create_office_document makes only "
        ".docx, .xlsx and .pptx files. Those two save into the task's own output folder. "
        + (
            "A folder is open: to create or change a file in that folder (for example when the request says 'in this folder'), "
            "use propose_project_patch with the path relative to it; the change is shown to the user for approval. "
            if workspace_path else ""
        )
        + "Each step's model sees only a short summary of earlier steps, not their full output, so a step that writes "
        "something based on what an earlier step read must also list that reading tool (for example read_project_file) "
        "to read the source again. "
        "Prefer file_contains with a word the result must contain over file_exists, so an empty or placeholder file fails. "
        "Each budget_tokens is 500-16000 and each budget_seconds is 30-900. "
        "Each done_condition is one typed, code-checkable condition, never prose: "
        "file_exists needs path; file_contains needs path and pattern; command_exit_0 needs no fields; "
        "value_equals needs field and expected; no_error needs no fields. "
        "A plan with an uncheckable done-condition is invalid and rejected. "
        'Each inputs lists earlier step ids, or "task" for the original request; never a later step and never an unknown id. '
        "Keep each step small enough for a small model: one clear goal, at most 3 tools, a short output. "
        f"Workspace: {workspace_path or 'a new temporary task workspace'}. "
        f"Permission: {permission_mode}. User request: {task}"
    )


def build_sequence_plan_fixup_prompt(error: str, previous_plan: dict, tool_names: list[str]) -> str:
    """Ask the planner model to repair a plan that failed validation (one bounded attempt)."""
    tools = ", ".join(tool_names)
    previous = json.dumps(previous_plan)[:12_000]
    return (
        "Your previous sequence plan was rejected by validation. Fix it and return the complete corrected plan as JSON only. "
        f"Validation error: {error[:2_000]} "
        "The plan must have 2-15 sequential steps; every tools_allowed entry must come from this list: "
        f"{tools}; every done_condition must be a typed, code-checkable condition "
        "(file_exists needs path; file_contains needs path and pattern; command_exit_0 needs no fields; "
        "value_equals needs field and expected; no_error needs no fields); "
        'every inputs entry must be "task" or an earlier step id. '
        f"Previous plan: {previous}"
    )


#: A planner timeout is a re-plan trigger, not a fatal error. Planner calls stream (see
#: _request_model_json), so this now means the model went silent or ran past planning_timeout,
#: not the old fixed ~111-second limit. The 502 detail says so explicitly.
PLANNER_TIMEOUT_DETAIL = (
    "Planner timed out while writing the sequence plan; "
    "treat this as a re-plan trigger, not a fatal error, and retry planning."
)


def _is_timeout_failure(exc: BaseException | None) -> bool:
    """Whether an error chain is a timeout: a TimeoutError anywhere in the
    chain, or timeout wording from the provider (aiohttp reports timeouts as
    ``Connection timeout to host ...`` or a bare ``asyncio.TimeoutError``,
    which ``_request_model_json`` wraps as a 502 HTTPException)."""
    seen: set[int] = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, TimeoutError):
            return True
        if "timed out" in str(current).lower() or "timeout" in str(current).lower():
            return True
        current = current.__cause__ or current.__context__
    return False


async def _request_sequence_plan_json(model: str, messages: list[dict[str, str]], timeout: aiohttp.ClientTimeout) -> dict:
    """One planner JSON call for a sequence plan, with timeout surfaced as a re-plan trigger."""
    try:
        return await _request_model_json(model, messages, timeout=timeout, role="planner")
    except HTTPException as err:
        if _is_timeout_failure(err):
            raise HTTPException(status_code=502, detail=PLANNER_TIMEOUT_DETAIL) from err
        raise
    except (aiohttp.ClientError, TimeoutError) as err:
        raise HTTPException(status_code=502, detail=PLANNER_TIMEOUT_DETAIL) from err


@app.get("/health")
async def health():
    return {"ok": True, "service": "planner"}


@app.post("/plan", dependencies=[Depends(require_internal_token)])
async def plan(payload: PlanRequest):
    task = payload.task.strip()
    candidates = list(dict.fromkeys(payload.capable_models))
    if not candidates:
        raise HTTPException(status_code=503, detail="No enabled local model supports agent tool calls.")
    if payload.model_profiles:
        selected, route_reason = choose_candidate(payload.model_profiles, task=task, preferred=payload.preferred_model, fallback=payload.default_model)
    else:
        preferred = payload.preferred_model if payload.preferred_model in candidates else None
        coding_task = bool(re.search(r"\b(code|coding|program|app|application|website|web\s+app|game|bug|fix|feature|project|workspace|script|software|build|implement|edit|refactor)\b", task, re.IGNORECASE))
        selected = preferred or next((name for name in candidates if coding_task and re.search(r"coder|code|agent", name, re.IGNORECASE)), None)
        selected = selected or (payload.default_model if payload.default_model in candidates else candidates[0])
        route_reason = "Selected an enabled local tool-capable model compatible with the request."
    prompt = (
        "Convert the user's request into a clear plan for a local autonomous agent and a detailed execution prompt. "
        "Do not answer with instructions or claim work is already done. Use only capabilities available to the agent: "
        "bounded public web research on user-supplied hosts, read-only browser observations and user-requested browser "
        "interactions, attached-file analysis, task-output files, optional local image generation, workspace-scoped code "
        "edits, and validation. There is no general shell tool. Preserve the user's requested scope: do not invent extra "
        "work, files, downloads, or workspace deliverables, and do not require saving results unless the user asks for a "
        "saved file or it is necessary to deliver the requested outcome. Read-only research and browsing findings belong "
        "in the final response by default. browse_public_page automatically saves its screenshot as an image artifact; "
        "its visible_text is observation data, not a document artifact. Select tools by intent: use scrape_public_page "
        "for text from one exact URL, search_public_site for multi-page research and source citations, and browser_read "
        "only when the user explicitly requests visual inspection, a screenshot, or browser interaction. Browser "
        "observations are not research source records. Choose required_capabilities from the plan: scrape_public_page "
        "and search_public_site require public_research; browse_public_page requires browser_read; browser_action "
        "requires browser_action. Opening the supplied URL and capturing a screenshot use browse_public_page; "
        "do not add browser_action unless the user requests an interaction such as clicking, typing, selecting, or scrolling. "
        "When the user explicitly asks to open or show a browser/window, use a visible isolated Chromium window; ordinary research, "
        "page inspection, and unattended checks stay headless. An explicit headless/background request overrides visible intent. "
        "For a single-page visual inspection with a brief summary, browser_read is sufficient; do not also add public_research unless the user asks for multi-page research or citations. "
        "For text-only public research, required_capabilities must be exactly "
        "[public_research]. Do not include workspace_read, workspace_write, or project_validation unless the user "
        "explicitly requests changes to a code or project workspace, or asks to read, review or summarize files in the open "
        "workspace folder (that needs workspace_read only). Choose the minimum capabilities necessary to "
        "complete the user's request; generic agent instructions are not user requirements. Do not add browser "
        "capabilities to text-only research. Do not invent retrieval limits; "
        "report only limits returned by the selected tool, or state that none were reported. Choose artifact_creation "
        "only for a separately saved file or document the user requested, not for a chat response or browser screenshot. "
        "Choose local_image_generation only for requested original artwork, not a browser screenshot. "
        "When the user asks to build, create, write, or fix an app, game, website, script, or other code, write the "
        "source files directly in the task workspace (required_capabilities include workspace_read and workspace_write); "
        "do not search for, download, scrape, or clone existing code unless the user explicitly asks for that. "
        "For greetings and plain questions that need no tools, return an empty required_capabilities list. "
        "Success checks must be verifiable with the agent's own tools, such as a named file existing in the workspace "
        "or a file containing a required feature; never use checks that need a person to run, play, or view the result, "
        "such as 'the game runs successfully'. "
        "Preserve the requested outcome. Return JSON with plan (3-10 short steps), step_details (one list per plan step, in the same "
        "order, of 2-4 short concrete actions the agent will take in that step, each naming the tool or command it will use "
        "and what it works on, for example 'Write index.html with the header, menu and contact sections'), execution_prompt (at least 40 words of imperative "
        "instructions that include verification), and reason (one short sentence). Do not return an empty prompt or "
        "generic tutorial. Put code deliverables in the task workspace. Also return task_brief containing desired_outcome, "
        "constraints, assumptions, required_capabilities (choose only from workspace_read, workspace_write, "
        "project_validation, public_research, browser_read, browser_action, attachment_read, artifact_creation, "
        "local_image_generation), milestones "
        "(objects with id, title, completion_check), deliverables, success_checks, requires_clarification, and "
        "clarifying_questions. Return success_checks as plain strings, not objects. Keep checks observable and specific. Also return delegation_plan with subtasks only when the task has independent, separable work; each subtask needs id, role, purpose, expected_result, depends_on (only IDs listed earlier), allowed_tools (from the known tools), max_tool_calls, and max_duration_seconds. Use at most 16 subtasks; otherwise return an empty subtasks list. Do not create delegates for sequential steps that need shared context or conflicting workspace edits. Mark requires_clarification true and ask concise "
        "questions when a missing detail materially changes the work; give each question as an object with question and options "
        "(2-3 short answers the user can pick). Do not return or recommend any permission level; "
        "the user's selected permission is authoritative. "
        f"Workspace: {payload.workspace_path or 'a new temporary task workspace'}. "
        f"Permission: {payload.permission_mode}. User request: {task}"
    )
    timeout = planning_timeout(payload.model_profiles, selected)
    try:
        parsed, plan_steps = await _plan_json(selected, prompt, timeout=timeout)
        task_brief = normalized_task_brief(
            parsed.get("task_brief"),
            original_request=task,
            plan=plan_steps,
            permission_level=payload.permission_mode,
            has_workspace=bool(payload.workspace_path),
        )
        async def generate_critic_json(messages: list[dict[str, str]]) -> dict:
            return await _request_model_json(selected, messages, timeout=timeout, role="critic", temperature=0)

        reviewed = await review_plan(
            task=task,
            task_brief=task_brief,
            plan=plan_steps,
            success_checks=task_brief["success_checks"],
            generate_json=generate_critic_json,
        )
        # The actions belong to the steps as planned; a reviewer that rewrote the steps makes them stale.
        step_details = normalized_step_details(parsed.get("step_details"), plan_steps) if reviewed["plan"] == plan_steps else [[] for _ in reviewed["plan"]]
        plan_steps = reviewed["plan"]
        task_brief = normalized_task_brief(
            {**task_brief, "success_checks": reviewed["success_checks"]},
            original_request=task,
            plan=plan_steps,
            permission_level=payload.permission_mode,
            has_workspace=bool(payload.workspace_path),
        )
        execution_prompt = with_step_details(build_execution_prompt(task, plan_steps, parsed.get("execution_prompt")), plan_steps, step_details)
        delegation_plan = normalized_subtask_plan(parsed.get("delegation_plan"))
        return {
            "contract_version": 1,
            "task_brief": task_brief,
            "plan": plan_steps,
            "step_details": step_details,
            "critic_review": reviewed["critic_review"],
            "execution_prompt": execution_prompt,
            "selected_model": selected,
            "reason": route_reason,
            "delegation_plan": delegation_plan,
        }
    except HTTPException:
        raise
    except (aiohttp.ClientError, TimeoutError, ValueError, TypeError) as err:
        raise HTTPException(status_code=502, detail=f"Planner service could not produce a usable plan: {err}") from err


@app.post("/plan-sequence", dependencies=[Depends(require_internal_token)])
async def plan_sequence(payload: SequencePlanRequest):
    """Plan one task as a validated sequence plan (Plan-and-Sequence P3).

    The planner model (strong local model by default) writes 5-15 sequential
    subtasks; the plan is validated before anything executes. On validation
    failure the model gets exactly one fix-up attempt with the error text;
    if it still fails, the request fails with 502 and no invalid plan is
    returned. A planner timeout is a re-plan trigger, not a fatal error.
    """
    task = payload.task.strip()
    installed = set(dict.fromkeys(payload.capable_models))
    profiles = payload.model_profiles or None
    try:
        planner_model, planner_reason = choose_planner_model(
            installed,
            preferred=payload.planner_model or payload.preferred_model,
            fallback=payload.default_model,
            profiles=profiles,
        )
    except ValueError as err:
        raise HTTPException(status_code=503, detail=str(err)) from err
    try:
        if payload.executor_model and payload.executor_model in installed:
            executor_model, executor_reason = payload.executor_model, "Used the model you chose for the steps."
        else:
            executor_model, executor_reason = choose_executor_model(
                installed, step_complexity="standard", profiles=profiles
            )
    except ValueError as err:
        raise HTTPException(status_code=503, detail=str(err)) from err
    tool_names = sorted(registered_tool_contracts())
    prompt = build_sequence_plan_prompt(task, tool_names, payload.workspace_path, payload.permission_mode)
    timeout = planning_timeout(payload.model_profiles, planner_model)
    try:
        raw = await _request_sequence_plan_json(
            planner_model, [{"role": "user", "content": prompt}], timeout
        )
    except ValueError as err:
        # The model returned malformed JSON or a non-object; there is no
        # previous JSON to show it, so no fix-up attempt is possible.
        raise HTTPException(
            status_code=502,
            detail=f"Planner returned unusable JSON for the sequence plan: {err}",
        ) from err
    try:
        validated = validate_sequence_plan(repair_read_tools(repair_folder_writes(repair_artifact_tools(raw), task=task, folder_open=bool(payload.workspace_path), permission_mode=payload.permission_mode)), allowed_tools=set(tool_names))
    except ValueError as err:
        fixup_prompt = build_sequence_plan_fixup_prompt(str(err), raw, tool_names)
        try:
            raw_retry = await _request_sequence_plan_json(
                planner_model, [{"role": "user", "content": fixup_prompt}], timeout
            )
        except ValueError as retry_err:
            raise HTTPException(
                status_code=502,
                detail=f"Planner returned unusable JSON for the sequence plan: {retry_err}",
            ) from retry_err
        try:
            validated = validate_sequence_plan(repair_read_tools(repair_folder_writes(repair_artifact_tools(raw_retry), task=task, folder_open=bool(payload.workspace_path), permission_mode=payload.permission_mode)), allowed_tools=set(tool_names))
        except ValueError as retry_err:
            raise HTTPException(
                status_code=502,
                detail=f"Planner returned an invalid sequence plan after one fix-up attempt: {str(retry_err)[:2_000]}",
            ) from retry_err
    validated["planner_model"] = planner_model
    validated["executor_model"] = executor_model
    return {
        "contract_version": SEQUENCE_CONTRACT_VERSION,
        "sequence_plan": validated,
        "selected_model": planner_model,
        "executor_model": executor_model,
        "reason": planner_reason,
        "executor_reason": executor_reason,
    }
