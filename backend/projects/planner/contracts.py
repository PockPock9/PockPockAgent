"""Versioned planner output contracts for structured agent task briefs."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskMilestone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=160)
    completion_check: str = Field(min_length=1, max_length=320)


class TaskPlanVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, le=20)
    status: Literal["proposed", "approved"]
    plan: list[str] = Field(min_length=1, max_length=10)
    success_checks: list[str] = Field(min_length=1, max_length=12)
    rationale: str = Field(default="", max_length=240)
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


ALLOWED_DELEGATE_TOOLS = {
    "list_project_files", "search_project", "read_project_file", "propose_project_edit",
    "propose_project_patch", "validate_project", "search_public_site", "scrape_public_page",
    "read_selected_file", "save_text_artifact", "create_office_document", "generate_local_image",
    "browse_public_page", "browser_action",
}


class ProposedSubtask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    role: str = Field(min_length=1, max_length=80)
    purpose: str = Field(min_length=1, max_length=400)
    expected_result: str = Field(min_length=1, max_length=400)
    depends_on: list[str] = Field(default_factory=list, max_length=15)
    allowed_tools: list[str] = Field(min_length=1, max_length=14)
    max_tool_calls: int = Field(default=8, ge=1, le=20)
    max_duration_seconds: int = Field(default=300, ge=30, le=900)

    @model_validator(mode="after")
    def validate_allowed_tools(self):
        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            raise ValueError("Allowed tools must be unique")
        unknown = set(self.allowed_tools) - ALLOWED_DELEGATE_TOOLS
        if unknown:
            raise ValueError(f"Unsupported delegate tool(s): {', '.join(sorted(unknown))}")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("Subtask dependencies must be unique")
        return self


class SubtaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = 1
    subtasks: list[ProposedSubtask] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_graph(self):
        seen: set[str] = set()
        for subtask in self.subtasks:
            if subtask.id in seen:
                raise ValueError("Subtask IDs must be unique")
            if any(dependency not in seen for dependency in subtask.depends_on):
                raise ValueError("Dependencies must reference earlier subtasks in topological order")
            seen.add(subtask.id)
        return self


def normalized_subtask_plan(raw: object) -> dict:
    """Validate the coordinator proposal and apply the fixed operational bounds."""
    source = raw if isinstance(raw, dict) else {"subtasks": []}
    return SubtaskPlan.model_validate(source).model_dump(mode="json")


def _as_list(value: object) -> object:
    return [value] if isinstance(value, str) else value


def _normalized_text_items(value: object) -> object:
    if not isinstance(value, list):
        return value
    fields = ("check", "criterion", "description", "title", "text", "completion_check", "expected_result")
    normalized = []
    for item in value:
        if isinstance(item, dict):
            item = next(
                (item[field] for field in fields if isinstance(item.get(field), str) and item[field].strip()),
                item,
            )
        normalized.append(item)
    return normalized


def _normalized_required_capabilities(value: object, original_request: str) -> object:
    aliases = {
        "list_project_files": "workspace_read",
        "search_project": "workspace_read",
        "read_project_file": "workspace_read",
        "propose_project_edit": "workspace_write",
        "propose_project_patch": "workspace_write",
        "validate_project": "project_validation",
        "search_public_site": "public_research",
        "scrape_public_page": "public_research",
        "browse_public_page": "browser_read",
        "read_selected_file": "attachment_read",
        "save_text_artifact": "artifact_creation",
        "create_office_document": "artifact_creation",
        "generate_local_image": "local_image_generation",
    }
    if not isinstance(value, list):
        return value
    normalized = []
    for item in value:
        capability = aliases.get(item, item) if isinstance(item, str) else item
        if capability not in normalized:
            normalized.append(capability)
    if "browser_action" in normalized and not re.search(
        r"\b(click|tap|press|type|enter|fill|select|choose|scroll|hover|submit|send|download|navigate to)\b",
        original_request,
        re.IGNORECASE,
    ):
        normalized.remove("browser_action")
    if "browser_read" in normalized and "public_research" in normalized and not re.search(
        r"\b(search|research|compare|citation|cite|sources?)\b|across\s+(?:multiple|several)\s+pages",
        original_request,
        re.IGNORECASE,
    ):
        normalized.remove("public_research")
    # Deterministic guards: the planner model sometimes asks for web access on requests that never mention
    # the web (a greeting, "build a game") and forgets write access for code deliverables. Both make the
    # agent fail, because tools are filtered by these capabilities.
    if not _WEB_CUE.search(original_request):
        for capability in ("public_research", "browser_read", "browser_action"):
            if capability in normalized:
                normalized.remove(capability)
    if _BUILD_INTENT.search(original_request):
        # project_validation is a static syntax/reference check (commands run only under Full access); the
        # server asks for it after file edits, so a build task without it cannot finish.
        for capability in ("workspace_read", "workspace_write", "project_validation"):
            if capability not in normalized:
                normalized.append(capability)
    # A request for a saved file or document needs the artifact tools, or the run has nothing to save
    # with (issue #92: "Save a text artifact named probe-result.md" planned no capabilities at all).
    # Research reports are built by the gateway from validated sources, so they are left alone.
    if _ARTIFACT_INTENT.search(original_request) and not {"artifact_creation", "workspace_write", "public_research"} & set(normalized):
        normalized.append("artifact_creation")
    return normalized


_WEB_CUE = re.compile(
    r"https?://|\bwww\.|\b[a-z0-9-]+\.(?:com|org|net|io|dev|ai|edu|gov|co|app)\b"
    r"|\b(web|website|websites|site|sites|page|pages|browser|browse|online|internet|url|link|links|search|research"
    r"|look\s+up|scrape|crawl|screenshot|sources?|citations?|cite|news|docs|documentation)\b",
    re.IGNORECASE,
)
_ARTIFACT_INTENT = re.compile(
    r"\b(save|create|make|write|export|generate|produce|draft|prepare)\b[^.?!\n]{0,80}?"
    r"(?:\b(artifact|document|doc|report|spreadsheet|workbook|presentation|slides|deck|memo)\b"
    r"|\.(?:md|txt|docx|xlsx|pptx|csv|pdf|html)\b)",
    re.IGNORECASE,
)
_BUILD_INTENT = re.compile(
    r"\b(build|create|make|write|implement|develop|code|program|scaffold|generate|fix|refactor|edit|update|modify|add)\b"
    r"[^.?!\n]{0,80}?\b(app|apps|application|webapp|web\s+app|website|site|page|game|games|script|scripts|program|component"
    r"|file|files|project|tool|cli|api|server|bot|extension|function|class|module|library|html|css|javascript|typescript"
    r"|python|code|feature|bug|test|tests)\b",
    re.IGNORECASE,
)


def normalized_plan_steps(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    steps = []
    for item in raw:
        if isinstance(item, str):
            step = item
        elif isinstance(item, dict):
            step = next(
                (item[key] for key in ("action", "step", "title", "description") if isinstance(item.get(key), str)),
                "",
            )
        else:
            continue
        step = step.strip()
        if step:
            steps.append(step[:320])
        if len(steps) == 10:
            break
    return steps


class TaskBrief(BaseModel):
    """A compact, inspectable statement of the requested outcome and how to verify it."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = 1
    original_request: str = Field(min_length=1, max_length=8_000)
    desired_outcome: str = Field(min_length=1, max_length=1_000)
    constraints: list[str] = Field(default_factory=list, max_length=12)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    required_capabilities: list[Literal[
        "workspace_read", "workspace_write", "project_validation", "public_research",
        "browser_read", "browser_action", "attachment_read", "artifact_creation",
        "local_image_generation",
    ]] = Field(default_factory=list, max_length=9)
    permission_level: Literal["default", "auto-review", "full-access"]
    milestones: list[TaskMilestone] = Field(min_length=1, max_length=10)
    deliverables: list[str] = Field(default_factory=list, max_length=12)
    success_checks: list[str] = Field(min_length=1, max_length=12)
    requires_clarification: bool = False
    clarifying_questions: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def clarification_has_questions(self):
        if self.requires_clarification and not self.clarifying_questions:
            raise ValueError("A task marked for clarification must include at least one question")
        if not self.requires_clarification and self.clarifying_questions:
            raise ValueError("Clarifying questions require requires_clarification=true")
        return self


_UNVERIFIABLE_CHECK = re.compile(
    r"\b(runs?|running|playable|play|plays|played|playing|launch|launches|launched|loads?|loaded|renders?|rendered"
    r"|displays?|displayed|smooth(?:ly)?|crash(?:es|ing)?|user can|users can|in (?:a|the) browser"
    r"|open(?:s|ed)? (?:it|the [\w-]+)|works? (?:correctly|properly|as expected)|without errors"
    r"|should|can be made|when (?:the user|you|clicking|pressing|tapping)"
    r"|optimi[sz]ed|performance|performant|responsive(?:ness)?|user-friendly|intuitive|efficient(?:ly)?|fast|engaging"
    r"|(?:bird|pipes?|player|character|ball|sprite|enemy|enemies) (?:falls?|moves?|jumps?|flies|flaps?|scrolls?|bounces?))\b",
    re.IGNORECASE,
)


# Environment setup the agent neither controls nor needs: the task workspace is created for it, and a plain
# web app has no libraries to install. Local models skip these when reporting, which fails the run.
_SETUP_CHECK = re.compile(
    r"\b(?:workspace|directory|folder)\b[^.]{0,40}\b(?:exists?|writable|created|set up|ready|initiali[sz]ed)\b"
    r"|\b(?:librar(?:y|ies)|dependenc(?:y|ies)|packages?|modules?|frameworks?|tools?)\b[^.]{0,40}\b(?:installed|available|set up)\b"
    r"|\b(?:environment|project)\b[^.]{0,20}\b(?:is |are )?(?:set up|initiali[sz]ed|configured)\b",
    re.IGNORECASE,
)


def _verifiable_build_checks(checks: list, original_request: str) -> list:
    """For build/edit tasks, replace checks that need a person to run or view the result.

    The agent can read and write workspace files but cannot run a game or look at a page, so a check like
    "the game runs successfully" can never be evidenced and would always fail the completion check.
    Environment-setup checks ("workspace directory exists", "libraries are installed") are dropped.
    """
    if not _BUILD_INTENT.search(original_request):
        return checks
    kept = [
        check for check in checks
        if not (isinstance(check, str) and (_SETUP_CHECK.search(check) or _UNVERIFIABLE_CHECK.search(check)))
    ]
    if len(kept) == len(checks):
        return checks
    for replacement in (
        "The requested source files exist in the task workspace.",
        "The source files implement the requested features.",
    ):
        if replacement not in kept:
            kept.append(replacement)
    return kept[:12]


def normalized_task_brief(
    raw: object,
    *,
    original_request: str,
    plan: list[str],
    permission_level: str,
) -> dict:
    """Validate planner content, preserving user input and preventing permission escalation."""
    source = raw if isinstance(raw, dict) else {}
    milestones = source.get("milestones")
    if not isinstance(milestones, list) or not milestones:
        milestones = [
            {"id": f"step-{index}", "title": step, "completion_check": step}
            for index, step in enumerate(plan[:10], 1)
        ]
    if not milestones:
        milestones = [{"id": "step-1", "title": "Complete the requested work", "completion_check": "The requested outcome is produced and reviewed."}]
    milestones = [
        {**milestone, "id": str(milestone["id"])}
        if isinstance(milestone, dict) and isinstance(milestone.get("id"), int) and not isinstance(milestone["id"], bool)
        else milestone
        for milestone in milestones
    ]
    checks = _normalized_text_items(_as_list(source.get("success_checks")))
    if not isinstance(checks, list) or not checks:
        checks = [milestone["completion_check"] for milestone in milestones if isinstance(milestone, dict) and isinstance(milestone.get("completion_check"), str)]
    if not checks:
        checks = ["Verify the requested result and report actual outputs and validation results."]
    checks = _verifiable_build_checks(checks, original_request)
    brief = {
        "contract_version": 1,
        "original_request": original_request,
        "desired_outcome": source.get("desired_outcome") if isinstance(source.get("desired_outcome"), str) else original_request,
        "constraints": _normalized_text_items(_as_list(source.get("constraints", []))),
        "assumptions": _normalized_text_items(_as_list(source.get("assumptions", []))),
        "required_capabilities": _normalized_required_capabilities(
            _as_list(source.get("required_capabilities", [])),
            original_request,
        ),
        "permission_level": permission_level,
        "milestones": milestones,
        "deliverables": _normalized_text_items(_as_list(source.get("deliverables", []))),
        "success_checks": checks,
        "requires_clarification": source.get("requires_clarification", False),
        "clarifying_questions": _normalized_text_items(_as_list(source.get("clarifying_questions", []))),
    }
    return TaskBrief.model_validate(brief).model_dump(mode="json")
