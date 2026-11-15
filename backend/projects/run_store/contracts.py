"""Typed parent/child run metadata and result contracts."""

from datetime import datetime
import json
import re
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DelegationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    subtask_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    role: str = Field(min_length=1, max_length=80)
    dependency_ids: list[str] = Field(default_factory=list, max_length=16)
    context_scope: list[Literal["approved_task", "dependency_results"]] = Field(min_length=1, max_length=2)
    workspace_scope: Literal["isolated_task_workspace", "reviewable_patch"]
    artifact_scope: list[str] = Field(default_factory=list, max_length=50)
    allowed_tools: list[str] = Field(min_length=1, max_length=14)
    max_tool_calls: int = Field(default=20, ge=1, le=20)
    max_duration_seconds: int = Field(default=900, ge=30, le=900)
    permission_level: Literal["default", "auto-review", "full-access"] = "default"
    deadline_at: datetime

    @model_validator(mode="after")
    def validate_dependencies(self):
        if len(set(self.dependency_ids)) != len(self.dependency_ids):
            raise ValueError("Dependency run IDs must be unique")
        if any(not re.fullmatch(r"[a-f0-9]{32}", item) for item in self.dependency_ids):
            raise ValueError("Dependency run IDs must be valid 32-character hexadecimal IDs")
        if self.parent_run_id in self.dependency_ids:
            raise ValueError("A parent run cannot be a dependency of its child")
        if len(set(self.context_scope)) != len(self.context_scope):
            raise ValueError("Context scopes must be unique")
        if "approved_task" not in self.context_scope:
            raise ValueError("A delegate must receive its approved subtask instructions")
        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            raise ValueError("Allowed tools must be unique")
        if self.artifact_scope:
            raise ValueError("Artifact access is unavailable until an artifact is explicitly assigned in the approved plan")
        return self


class DelegationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = 1
    status: Literal["completed", "partial", "failed", "cancelled", "timed_out"]
    summary: str = Field(min_length=1, max_length=4000)
    evidence: list[str] = Field(default_factory=list, max_length=50)
    artifact_ids: list[str] = Field(default_factory=list, max_length=50)
    incomplete_checks: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_result_bounds(self):
        if any(len(item) > 500 for item in self.evidence):
            raise ValueError("Delegation evidence items must be at most 500 characters")
        if any(len(item) > 255 for item in self.artifact_ids):
            raise ValueError("Delegation artifact IDs must be at most 255 characters")
        if any(len(item) > 320 for item in self.incomplete_checks):
            raise ValueError("Delegation incomplete checks must be at most 320 characters")
        return self


def delegate_task_prompt(subtask: dict) -> str:
    if not isinstance(subtask, dict):
        raise ValueError("An approved subtask is required")
    purpose = subtask.get("purpose")
    expected_result = subtask.get("expected_result")
    if not isinstance(purpose, str) or not purpose.strip() or not isinstance(expected_result, str) or not expected_result.strip():
        raise ValueError("The approved subtask must include its purpose and expected result")
    return f"{purpose.strip()}\n\nExpected result: {expected_result.strip()}"


def build_delegate_context(
    contract: DelegationContract,
    *,
    approved_subtask: dict,
    dependency_results: dict[str, dict],
) -> dict:
    """Build the minimum child context from its approved subtask and dependencies."""
    if not isinstance(approved_subtask, dict):
        raise ValueError("An approved subtask is required")
    if approved_subtask.get("id") != contract.subtask_id or approved_subtask.get("role") != contract.role:
        raise ValueError("The approved subtask does not match the delegation contract")
    context: dict = {"subtask_id": contract.subtask_id, "role": contract.role, "allowed_tools": list(contract.allowed_tools)}
    if "approved_task" in contract.context_scope:
        context["approved_task"] = delegate_task_prompt(approved_subtask)
    if "dependency_results" in contract.context_scope:
        context["dependency_results"] = {
            run_id: deepcopy(dependency_results[run_id])
            for run_id in contract.dependency_ids
            if run_id in dependency_results
        }
    if context.get("approved_task") is None:
        raise ValueError("The delegate context is missing its approved subtask instructions")
    return context


def bounded_dependency_results(dependency_results: dict[str, dict], *, max_chars: int = 5_000) -> dict[str, dict]:
    """Keep only typed, bounded result fields and cap the serialized child context."""
    bounded: dict[str, dict] = {}
    for run_id, raw in dependency_results.items():
        if not isinstance(raw, dict):
            raise ValueError("A dependency result must be an object")
        try:
            result = DelegationResult.model_validate(raw)
        except ValueError as err:
            raise ValueError(f"An approved dependency result is invalid: {err}") from err
        bounded[run_id] = {
            "status": result.status,
            "summary": result.summary[:240],
            "evidence": [item[:120] for item in result.evidence[:2]],
            "artifact_ids": [item[:128] for item in result.artifact_ids[:5]],
            "incomplete_checks": [item[:120] for item in result.incomplete_checks[:2]],
        }
    while bounded and len(json.dumps(bounded, ensure_ascii=False)) > max_chars:
        largest = max(bounded, key=lambda key: len(bounded[key]["summary"]))
        summary = bounded[largest]["summary"]
        if len(summary) > 24:
            bounded[largest]["summary"] = summary[:max(24, len(summary) - 64)]
            continue
        optional_fields = ("evidence", "incomplete_checks", "artifact_ids")
        for field_name in optional_fields:
            if bounded[largest][field_name]:
                bounded[largest][field_name].pop()
                break
        else:
            raise ValueError("Approved dependency results exceed the child context size limit")
    return bounded


def restrict_delegate_tools(contract: DelegationContract, tool_specs: list[dict]) -> list[dict]:
    """Return only approved model-callable tool schemas for a child run."""
    allowed = set(contract.allowed_tools)
    return [
        spec for spec in tool_specs
        if isinstance(spec, dict)
        and isinstance(spec.get("function"), dict)
        and spec["function"].get("name") in allowed
    ]
