"""Sequence plan schema and validation (Plan-and-Sequence P0).

A :class:`SequencePlan` is the planner's output for one task: 2-15 sequential
steps, each with a pinned tool subset, a token/time budget, a typed
done-condition, and pointers into the state capsule. Plans are validated
before anything executes; an invalid plan is rejected, never run.

Validation rules (see the Plan-and-Sequence design page):

* 2-15 steps (5-15 for larger tasks), unique step ids.
* Every step's ``tools_allowed`` names a tool registered in
  ``projects.agent_tools`` (or in the explicit ``allowed_tools`` set).
* Every step's ``inputs`` is either the literal ``"task"`` (the original
  request is always available) or the id of an *earlier* step, meaning
  "whatever that step put in the state capsule". Steps declare no output
  keys, so a step id is the only static handle on an earlier step's
  capsule entries; an input naming anything else is dangling.
* Every done-condition carries exactly the fields its type needs.
"""

from __future__ import annotations

import re

from typing import Annotated, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from projects.agent_tools.artifacts import TEXT_ARTIFACT_EXTENSIONS
from projects.agent_tools.registry import registered_tool_contracts
from projects.agent_tools.tool_retriever import estimate_tokens

# ---------------------------------------------------------------------------
# Frozen bounds (Plan-and-Sequence design; do not change without a P1 gate)
# ---------------------------------------------------------------------------

# 2, not 5: a small task such as "write two files" plans naturally in 3-4 steps, and a
# 5-step minimum rejected those plans with a 502 (live validation 2026-11-21).
MIN_STEPS = 2
MAX_STEPS = 15
MAX_CAPSULE_TOKENS = 400
MAX_STEP_RETRIES = 2
MAX_TOOLS_PER_STEP = 3
SEQUENCE_CONTRACT_VERSION = 1

#: The original request is always available to every step under this key.
TASK_INPUT_KEY = "task"
#: A step whose only tool is this is carried out by the OpenClaw agent (shell, browser, apps, skills, MCP)
#: instead of the step model; its done-condition is still verified in code. Not an agent tool: the runner
#: hands the step to its ``delegate``. The planner offers it only when OpenClaw is available.
OPENCLAW_STEP_TOOL = "openclaw_agent"


def _present(value: str | None) -> bool:
    """Whether an optional string field carries a non-blank value."""
    return isinstance(value, str) and bool(value.strip())


class DoneCondition(BaseModel):
    """A typed, code-checkable completion condition for one step."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["file_exists", "file_contains", "command_exit_0", "value_equals", "no_error"]
    path: str | None = None
    pattern: str | None = None
    field: str | None = None
    expected: str | None = None

    @model_validator(mode="after")
    def validate_fields_for_type(self):
        required: dict[str, tuple[str, ...]] = {
            "file_exists": ("path",),
            "file_contains": ("path", "pattern"),
            "command_exit_0": (),
            "value_equals": ("field", "expected"),
            "no_error": (),
        }
        forbidden: dict[str, tuple[str, ...]] = {
            "file_exists": ("pattern", "field", "expected"),
            "file_contains": ("field", "expected"),
            "command_exit_0": ("path", "pattern", "field", "expected"),
            "value_equals": ("path", "pattern"),
            "no_error": ("path", "pattern", "field", "expected"),
        }
        missing = [name for name in required[self.type] if not _present(getattr(self, name))]
        if missing:
            raise ValueError(
                f"Done condition '{self.type}' requires field(s): {', '.join(missing)}"
            )
        extra = [name for name in forbidden[self.type] if _present(getattr(self, name))]
        if extra:
            raise ValueError(
                f"Done condition '{self.type}' forbids field(s): {', '.join(extra)}"
            )
        return self


class SequenceStep(BaseModel):
    """One sequential subtask: a single goal, pinned tools, a budget, a check."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    goal: str = Field(min_length=1, max_length=280)
    tools_allowed: list[str] = Field(min_length=1, max_length=MAX_TOOLS_PER_STEP)
    budget_tokens: int = Field(default=4000, ge=500, le=16000)
    budget_seconds: int = Field(default=300, ge=30, le=900)
    done_condition: DoneCondition
    inputs: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        default_factory=list, max_length=10
    )

    @model_validator(mode="after")
    def validate_tools_unique(self):
        if len(set(self.tools_allowed)) != len(self.tools_allowed):
            raise ValueError(f"Step '{self.id}': tools_allowed must be unique")
        return self


class SequencePlan(BaseModel):
    """A validated plan: 2-15 sequential steps for one task."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = SEQUENCE_CONTRACT_VERSION
    task: str = Field(min_length=1, max_length=8000)
    steps: list[SequenceStep] = Field(min_length=MIN_STEPS, max_length=MAX_STEPS)
    planner_model: str | None = None
    executor_model: str | None = None

    @model_validator(mode="after")
    def validate_step_ids_unique(self):
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError(f"Duplicate step id: '{step.id}'")
            seen.add(step.id)
        return self


class CapsuleEntry(BaseModel):
    """One pointer in the state capsule: a path, id, summary, or value."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64)
    kind: Literal["path", "id", "summary", "value"]
    value: str = Field(min_length=1, max_length=200)
    source_step: str | None = None


def _entries_to_text(entries: Sequence[CapsuleEntry]) -> str:
    """Render entries as ``key: value`` lines, grouped by source step.

    Entries with no source step come first; then one group per source step,
    in order of first appearance. No headers: every line is an entry, so the
    text round-trips back to the entry list.
    """
    groups: dict[str | None, list[CapsuleEntry]] = {}
    order: list[str | None] = []
    for entry in entries:
        if entry.source_step not in groups:
            groups[entry.source_step] = []
            order.append(entry.source_step)
        groups[entry.source_step].append(entry)
    ordered = [key for key in order if key is None] + [key for key in order if key is not None]
    return "\n".join(
        f"{entry.key}: {entry.value}" for key in ordered for entry in groups[key]
    )


class StateCapsule(BaseModel):
    """The ≤400-token state passed between steps: pointers, not payloads."""

    model_config = ConfigDict(extra="forbid")

    entries: list[CapsuleEntry] = Field(default_factory=list, max_length=24)
    # True when trimming had to drop a "path"/"id" pointer to fit the token
    # budget (set by capsule.build_capsule; never set by direct construction).
    dropped_pointers: bool = False

    def to_text(self) -> str:
        """One ``key: value`` line per entry, grouped by source step."""
        return _entries_to_text(self.entries)

    def estimated_tokens(self) -> int:
        """Token estimate for the rendered capsule text."""
        return estimate_tokens(self.to_text())


class StepResult(BaseModel):
    """The outcome of running one step (recorded by the runner, P2+)."""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    status: Literal["passed", "failed", "needs_replan"]
    attempts: int = Field(ge=1)
    prompt_tokens: int = 0
    evidence: str = ""
    error: str | None = None


class SequenceRunResult(BaseModel):
    """The outcome of running a whole sequence plan (recorded by the runner)."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    status: Literal["completed", "failed", "needs_replan"]
    steps: list[StepResult] = Field(default_factory=list)
    capsule: StateCapsule = Field(default_factory=StateCapsule)
    total_prompt_tokens: int = 0


# Which artifact tool can write a file of each kind. save_text_artifact writes the text and code files
# in TEXT_ARTIFACT_EXTENSIONS; create_office_document writes .docx/.pdf/.xlsx/.pptx.
_TEXT_EXTENSIONS = TEXT_ARTIFACT_EXTENSIONS
_OFFICE_EXTENSIONS = {".docx", ".pdf", ".xlsx", ".pptx"}


def repair_artifact_tools(raw: object) -> object:
    """Give a step that must produce a file the artifact tool that can write that kind of file.

    Live validation (2026-11-21, qwen3.5:9b planner) pinned create_office_document to a step whose
    done-condition was ``notes.md``; that tool writes only Office files, so the step could never pass
    and the run ended needing a replan. Only the two artifact tools are swapped, so a step never
    gains a capability it did not have.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("steps"), list):
        return raw
    for step in raw["steps"]:
        if not isinstance(step, dict) or not isinstance(step.get("tools_allowed"), list):
            continue
        condition = step.get("done_condition") if isinstance(step.get("done_condition"), dict) else {}
        path = str(condition.get("path") or "").lower()
        extension = path[path.rfind("."):] if "." in path else ""
        tools = step["tools_allowed"]
        if extension in _TEXT_EXTENSIONS and "create_office_document" in tools and "save_text_artifact" not in tools:
            step["tools_allowed"] = ["save_text_artifact" if tool == "create_office_document" else tool for tool in tools]
        elif extension in _OFFICE_EXTENSIONS and "create_office_document" not in tools and _TEXT_WRITERS & set(tools):
            # Only create_office_document writes Word, PDF, Excel and PowerPoint files. A "convert to PDF" step
            # given propose_project_patch failed three times with "file does not exist: resume.pdf" (scenario
            # run 2026-11-28): the text writers swap for it.
            swapped, kept = False, []
            for tool in tools:
                if tool in _TEXT_WRITERS:
                    if not swapped:
                        kept.append("create_office_document")
                        swapped = True
                else:
                    kept.append(tool)
            step["tools_allowed"] = kept
    return raw


_TEXT_WRITERS = {"save_text_artifact", "propose_project_patch", "propose_project_edit"}


def _office_step(step: dict) -> bool:
    condition = step.get("done_condition") if isinstance(step.get("done_condition"), dict) else {}
    path = str(condition.get("path") or "").lower()
    return "." in path and path[path.rfind("."):] in _OFFICE_EXTENSIONS


_READ_TOOLS = ("read_project_file", "read_selected_file", "scrape_public_page", "search_project")
_WRITE_TOOLS = {"save_text_artifact", "create_office_document", "propose_project_patch", "propose_project_edit"}


def repair_read_tools(raw: object) -> object:
    """Let a step that writes after earlier steps read something read it again.

    Live validation (2026-11-22): a planner pinned read_project_file to step 1 and save_text_artifact
    alone to step 2, so step 2 (told to re-read files rather than trust the short state summary) could
    not, and wrote "[extract from notes.md]" placeholders. The step gets the reading tool the nearest
    earlier step used, within the 3-tool limit; it gains no tool the plan did not already use.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("steps"), list):
        return raw
    seen_reads: list[str] = []
    for step in raw["steps"]:
        if not isinstance(step, dict) or not isinstance(step.get("tools_allowed"), list):
            continue
        tools = step["tools_allowed"]
        writes = any(tool in _WRITE_TOOLS for tool in tools)
        reads = [tool for tool in tools if tool in _READ_TOOLS]
        if writes and not reads and seen_reads and len(tools) < MAX_TOOLS_PER_STEP:
            step["tools_allowed"] = [*tools, seen_reads[-1]]
        for tool in reads:
            if tool in seen_reads:
                seen_reads.remove(tool)
            seen_reads.append(tool)
    return raw


_IN_FOLDER = re.compile(
    r"\b(in|into|to|inside)\s+(this|the|my|that|our)\s+(open\s+)?(folder|directory|project|repo|repository|workspace)\b",
    re.IGNORECASE,
)


_WEB_TOOLS = {"browse_public_page", "scrape_public_page", "search_public_site", "browser_action"}
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
_FILE_SUFFIXES = {
    "md", "txt", "html", "htm", "css", "js", "mjs", "ts", "tsx", "json", "csv", "py", "pdf", "docx", "xlsx", "pptx",
    "png", "jpg", "jpeg", "gif", "webp", "svg", "xml", "yaml", "yml", "ini", "toml", "log", "sh", "ps1",
}
_HOST = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+([a-z]{2,24}))\b", re.IGNORECASE)


def names_a_website(task: str) -> bool:
    """Whether the request names a website: a URL or a host name (not a file name such as notes.md)."""
    return any(match.group(2).lower() not in _FILE_SUFFIXES for match in _HOST.finditer(task or ""))


_FORMAT_WORDS = (
    (".pdf", re.compile(r"\bpdf\b", re.I)),
    (".docx", re.compile(r"\b(?:word|docx)\b", re.I)),
    (".xlsx", re.compile(r"\b(?:excel|xlsx|spreadsheet|workbook)\b", re.I)),
    (".pptx", re.compile(r"\b(?:powerpoint|pptx|slides?|slide deck|presentation)\b", re.I)),
)
_FOLDER_READ_TOOLS = {"read_project_file", "search_project", "list_project_files"}


def _step_path(step: dict) -> str:
    condition = step.get("done_condition") if isinstance(step.get("done_condition"), dict) else {}
    return condition.get("path") if isinstance(condition.get("path"), str) else ""


def repair_requested_formats(raw: object, *, task: str) -> object:
    """Make the document steps produce the formats the request asks for.

    Asked for "a PDF report from sales.csv", a planner wrote a step for sales_report.docx; the run passed
    and no PDF existed (scenario run 2026-11-28). A requested format that no step produces takes over a
    document step whose format was not asked for.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("steps"), list):
        return raw
    requested = [ext for ext, pattern in _FORMAT_WORDS if pattern.search(task)]
    if not requested:
        return raw
    office_steps = [s for s in raw["steps"] if isinstance(s, dict) and _step_path(s).lower().endswith(tuple(_OFFICE_EXTENSIONS))]
    produced = {_step_path(s).lower()[_step_path(s).rfind("."):] for s in office_steps}
    for ext in requested:
        if ext in produced:
            continue
        spare = next((s for s in office_steps if _step_path(s).lower()[_step_path(s).rfind("."):] not in requested), None)
        if spare is None:
            continue
        old_path = _step_path(spare)
        new_path = old_path[:old_path.rfind(".")] + ext
        spare["done_condition"]["path"] = new_path
        if isinstance(spare.get("goal"), str):
            spare["goal"] = spare["goal"].replace(old_path, new_path)
        produced.discard(old_path.lower()[old_path.rfind("."):])
        produced.add(ext)
    return raw


def repair_empty_folder(raw: object, *, folder_has_files: bool | None) -> object:
    """Leave out steps that only read or search the open folder when it has no files.

    In an empty folder a planner added "search for safety guidelines" and "read the found documents"
    steps; they failed three times with "The requested project file does not exist" and the run never
    reached the slides (scenario run 2026-11-28). A plan keeps at least two steps.
    """
    if folder_has_files is not False or not isinstance(raw, dict) or not isinstance(raw.get("steps"), list):
        return raw
    steps = [s for s in raw["steps"] if isinstance(s, dict)]
    reading = {s.get("id") for s in steps if s.get("tools_allowed") and set(s["tools_allowed"]) <= _FOLDER_READ_TOOLS}
    kept = [s for s in steps if s.get("id") not in reading]
    if not reading or len(kept) < MIN_STEPS:
        return raw
    for step in kept:
        if isinstance(step.get("inputs"), list):
            step["inputs"] = [item for item in step["inputs"] if item not in reading] or ["task"]
        # A writer that was also told to re-read the (missing) sources keeps only its writing tools.
        tools = step.get("tools_allowed") or []
        if any(tool not in _FOLDER_READ_TOOLS for tool in tools):
            step["tools_allowed"] = [tool for tool in tools if tool not in ("read_project_file", "search_project")] or tools
    raw["steps"] = kept
    return raw


def repair_plan_mistakes(raw: object, *, task: str, folder_open: bool, permission_mode: str, image_available: bool = True) -> object:
    """Fix the plan mistakes a small planner makes that guarantee a failed step (live runs 2026-11-27,
    qwen3.5:9b planning: 0 of 4 tasks finished, every failure from the plan):

    - Web tools (browse, scrape, search, browser) are dropped when the request names no website: they
      may only fetch hosts named in the request, so a "research competitors" step could never work.
    - The image generator is dropped from a step whose result is not an image ("write summary.md" was
      given generate_local_image).
    - A step left with no tool that must produce a text file gets the file-writing tool (into the open
      folder when one is open and the permission allows it, else the task folder).
    - A step that only reads cannot change a file, so a "contains <text>" check on it becomes "file
      exists" (a read of resume.txt was checked for an invented name, "John Doe").
    - Inputs that name no earlier step are dropped instead of rejecting the plan.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("steps"), list):
        return raw
    web_allowed = names_a_website(task)
    write_tool = "propose_project_patch" if folder_open and permission_mode != "default" else "save_text_artifact"
    seen_ids: list[str] = []
    for step in raw["steps"]:
        if not isinstance(step, dict):
            continue
        tools = [tool for tool in step.get("tools_allowed") or [] if isinstance(tool, str)]
        condition = step.get("done_condition") if isinstance(step.get("done_condition"), dict) else {}
        path = condition.get("path") if isinstance(condition.get("path"), str) else ""
        makes_image = path.lower().endswith(_IMAGE_SUFFIXES)
        if not web_allowed:
            tools = [tool for tool in tools if tool not in _WEB_TOOLS]
        if not makes_image or not image_available:
            tools = [tool for tool in tools if tool != "generate_local_image"]
        if makes_image and not image_available and not tools:
            # No image engine runs: an image-only step could never pass, so it is left out.
            step["_drop"] = True
            continue
        # Only a step left with no tool at all (its web or image tools removed) is given the writer: a step
        # that lists or reads files to confirm one exists keeps its tools.
        if not tools and condition.get("type") in ("file_exists", "file_contains") and path and not makes_image:
            tools = [write_tool]
        writes = any(tool in _WRITE_TOOLS for tool in tools)
        if not writes and condition.get("type") == "file_contains" and path:
            step["done_condition"] = {**condition, "type": "file_exists", "pattern": None}
        if not tools:
            tools = ["list_project_files"] if folder_open else [write_tool]
        step["tools_allowed"] = list(dict.fromkeys(tools))[:MAX_TOOLS_PER_STEP]
        if isinstance(step.get("inputs"), list):
            step["inputs"] = [item for item in step["inputs"] if item == "task" or item in seen_ids] or ["task"]
        if isinstance(step.get("id"), str):
            seen_ids.append(step["id"])
    dropped = {step.get("id") for step in raw["steps"] if isinstance(step, dict) and step.get("_drop")}
    if dropped and len(dropped) < len(raw["steps"]):
        raw["steps"] = [step for step in raw["steps"] if not (isinstance(step, dict) and step.get("_drop"))]
        for step in raw["steps"]:
            if isinstance(step, dict) and isinstance(step.get("inputs"), list):
                step["inputs"] = [item for item in step["inputs"] if item not in dropped] or ["task"]
    else:
        for step in raw["steps"]:
            if isinstance(step, dict):
                step.pop("_drop", None)
    return raw


def repair_folder_writes(raw: object, *, task: str, folder_open: bool, permission_mode: str) -> object:
    """Write into the open folder when one is open (and the permission allows changing it).

    save_text_artifact writes into the task's own output folder. Live validation (2026-11-22): asked to
    "write summary.md in this folder", the planner chose it anyway, so the file landed elsewhere. With a
    folder open and the request naming it, such a step uses propose_project_patch instead, which writes
    into the folder and, in Auto-review, shows the change for approval. Default mode cannot change the
    folder, so nothing is swapped there.
    """
    # The app sends the folder only when the user chose "Work in <folder>", so that choice decides: before
    # 2026-11-27 the request also had to say "in this folder", and a website asked for without those words
    # was saved in the task folder while the checking steps read the open folder (runs 2026-11-27).
    if not folder_open or permission_mode == "default":
        return raw
    if not isinstance(raw, dict) or not isinstance(raw.get("steps"), list):
        return raw
    for step in raw["steps"]:
        if isinstance(step, dict) and isinstance(step.get("tools_allowed"), list) and "save_text_artifact" in step["tools_allowed"] and not _office_step(step):
            step["tools_allowed"] = ["propose_project_patch" if tool == "save_text_artifact" else tool for tool in step["tools_allowed"]]
    return raw


def validate_sequence_plan(raw: object, *, allowed_tools: set[str] | None = None) -> dict:
    """Validate a raw plan dict and return its normalised JSON form.

    ``allowed_tools`` defaults to the registered tool contract names from
    ``projects.agent_tools``. Raises :class:`ValueError` with a specific
    message on any problem: wrong step count, unknown tool, duplicate step
    id, invalid done-condition, or a dangling input.
    """
    if allowed_tools is None:
        allowed_tools = set(registered_tool_contracts()) | {OPENCLAW_STEP_TOOL}
    if isinstance(raw, dict) and isinstance(raw.get("steps"), list):
        for step in raw["steps"]:
            # OpenClaw does the whole step with its own tools, so it is the step's only tool.
            if isinstance(step, dict) and isinstance(step.get("tools_allowed"), list) and OPENCLAW_STEP_TOOL in step["tools_allowed"]:
                step["tools_allowed"] = [OPENCLAW_STEP_TOOL]
    try:
        plan = SequencePlan.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid sequence plan: {exc}") from exc
    for step in plan.steps:
        unknown = sorted(set(step.tools_allowed) - allowed_tools)
        if unknown:
            raise ValueError(
                f"Step '{step.id}' uses unknown tool(s): {', '.join(unknown)}"
            )
    seen_ids: set[str] = set()
    for step in plan.steps:
        for input_key in step.inputs:
            if input_key != TASK_INPUT_KEY and input_key not in seen_ids:
                raise ValueError(
                    f"Step '{step.id}' has dangling input '{input_key}': "
                    "it is not 'task' and does not match any earlier step id"
                )
        seen_ids.add(step.id)
    return plan.model_dump(mode="json")
