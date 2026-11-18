"""Sequence plan schema and validation (Plan-and-Sequence P0).

A :class:`SequencePlan` is the planner's output for one task: 5-15 sequential
steps, each with a pinned tool subset, a token/time budget, a typed
done-condition, and pointers into the state capsule. Plans are validated
before anything executes; an invalid plan is rejected, never run.

Validation rules (see the Plan-and-Sequence design page):

* 5-15 steps, unique step ids.
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

from typing import Annotated, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from projects.agent_tools.registry import registered_tool_contracts
from projects.agent_tools.tool_retriever import estimate_tokens

# ---------------------------------------------------------------------------
# Frozen bounds (Plan-and-Sequence design; do not change without a P1 gate)
# ---------------------------------------------------------------------------

MIN_STEPS = 5
MAX_STEPS = 15
MAX_CAPSULE_TOKENS = 400
MAX_STEP_RETRIES = 2
MAX_TOOLS_PER_STEP = 3
SEQUENCE_CONTRACT_VERSION = 1

#: The original request is always available to every step under this key.
TASK_INPUT_KEY = "task"


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
    """A validated plan: 5-15 sequential steps for one task."""

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


def validate_sequence_plan(raw: object, *, allowed_tools: set[str] | None = None) -> dict:
    """Validate a raw plan dict and return its normalised JSON form.

    ``allowed_tools`` defaults to the registered tool contract names from
    ``projects.agent_tools``. Raises :class:`ValueError` with a specific
    message on any problem: wrong step count, unknown tool, duplicate step
    id, invalid done-condition, or a dangling input.
    """
    if allowed_tools is None:
        allowed_tools = set(registered_tool_contracts())
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
