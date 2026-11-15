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
from pydantic import BaseModel, Field

from planner.critic import review_plan
from planner.contracts import normalized_plan_steps, normalized_subtask_plan, normalized_task_brief
from planner.routing import choose_candidate
from projects.model_router import ChatCompletionRequest, ModelProviderError, OllamaChatCompletionAdapter

app = FastAPI(title="PockPock Planner", docs_url=None, redoc_url=None)
OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
MODEL_CLIENT = OllamaChatCompletionAdapter(OLLAMA_URL)
LARGE_MODEL_BILLIONS = 20.0


async def _request_model_json(
    model: str,
    messages: list[dict[str, str]],
    *,
    timeout: aiohttp.ClientTimeout,
    role: str,
    temperature: float = 0.1,
) -> dict:
    try:
        result = await MODEL_CLIENT.complete(
            ChatCompletionRequest(
                model=model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
                context_window=8192,
                think=False,
            ),
            timeout=timeout,
        )
    except ModelProviderError as err:
        status = f" (HTTP {err.status_code})" if err.status_code is not None else ""
        raise HTTPException(status_code=502, detail=f"The {role} model failed{status}.") from err
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as err:
        raise ValueError(f"{role.capitalize()} model returned an invalid response") from err
    if not isinstance(content, str):
        raise ValueError(f"{role.capitalize()} model returned no JSON content")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError(f"{role.capitalize()} model returned an invalid object")
    return parsed


def planning_timeout(profiles: list[dict], model: str) -> aiohttp.ClientTimeout:
    """Give each planner/critic call more time on large models, which run partly on the CPU on 12 GB GPUs."""
    size = next((item.get("parameter_billions") for item in profiles if item.get("name") == model), None)
    seconds = 300 if isinstance(size, (int, float)) and size >= LARGE_MODEL_BILLIONS else 120
    return aiohttp.ClientTimeout(total=seconds, sock_read=seconds - 10)


class PlanRequest(BaseModel):
    task: str = Field(min_length=1, max_length=8_000)
    capable_models: list[str] = Field(min_length=1, max_length=64)
    model_profiles: list[dict] = Field(default_factory=list, max_length=64)
    preferred_model: str | None = Field(default=None, max_length=120)
    default_model: str = Field(min_length=1, max_length=120)
    workspace_path: str | None = Field(default=None, max_length=1024)
    permission_mode: str = Field(default="auto-review", pattern=r"^(default|auto-review|full-access)$")


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
        "explicitly requests changes to a code or project workspace. Choose the minimum capabilities necessary to "
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
        "Preserve the requested outcome. Return JSON with plan (3-10 short steps), execution_prompt (at least 40 words of imperative "
        "instructions that include verification), and reason (one short sentence). Do not return an empty prompt or "
        "generic tutorial. Put code deliverables in the task workspace. Also return task_brief containing desired_outcome, "
        "constraints, assumptions, required_capabilities (choose only from workspace_read, workspace_write, "
        "project_validation, public_research, browser_read, browser_action, attachment_read, artifact_creation, "
        "local_image_generation), milestones "
        "(objects with id, title, completion_check), deliverables, success_checks, requires_clarification, and "
        "clarifying_questions. Return success_checks as plain strings, not objects. Keep checks observable and specific. Also return delegation_plan with subtasks only when the task has independent, separable work; each subtask needs id, role, purpose, expected_result, depends_on (only IDs listed earlier), allowed_tools (from the known tools), max_tool_calls, and max_duration_seconds. Use at most 16 subtasks; otherwise return an empty subtasks list. Do not create delegates for sequential steps that need shared context or conflicting workspace edits. Mark requires_clarification true and ask concise "
        "questions when a missing detail materially changes the work. Do not return or recommend any permission level; "
        "the user's selected permission is authoritative. "
        f"Workspace: {payload.workspace_path or 'a new temporary task workspace'}. "
        f"Permission: {payload.permission_mode}. User request: {task}"
    )
    timeout = planning_timeout(payload.model_profiles, selected)
    try:
        parsed = await _request_model_json(selected, [{"role": "user", "content": prompt}], timeout=timeout, role="planner")
        plan_steps = normalized_plan_steps(parsed.get("plan"))
        if not plan_steps:
            raise ValueError("Planner returned no usable plan steps")
        task_brief = normalized_task_brief(
            parsed.get("task_brief"),
            original_request=task,
            plan=plan_steps,
            permission_level=payload.permission_mode,
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
        plan_steps = reviewed["plan"]
        task_brief = normalized_task_brief(
            {**task_brief, "success_checks": reviewed["success_checks"]},
            original_request=task,
            plan=plan_steps,
            permission_level=payload.permission_mode,
        )
        execution_prompt = build_execution_prompt(task, plan_steps, parsed.get("execution_prompt"))
        delegation_plan = normalized_subtask_plan(parsed.get("delegation_plan"))
        return {
            "contract_version": 1,
            "task_brief": task_brief,
            "plan": plan_steps,
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
