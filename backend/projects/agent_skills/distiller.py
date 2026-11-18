"""Distiller: turn a completed run record into skill/workflow/tip candidates.

Given a run record — task, trajectory (ordered steps with tool calls and
outcomes), outcome (``success`` / ``partial`` / ``failure``) and an optional
verifier verdict — the distiller drafts:

(a) a candidate skill (SKILL.md) when the run succeeded and its steps look
    reusable,
(b) an AWM-style workflow: the trajectory abstracted into generic steps
    (concrete filenames/values stripped, decision points kept),
(c) 1–3 reasoning tips in the 3-field format, including FAILURE tips
    ("don't do X, it fails because...") whenever the trajectory shows a
    failed step, a retry, or a verifier rejection.

Two backends:

* :class:`StubDistiller` — deterministic, rule-based, offline. Used by
  unit tests and by the lifecycle demo; also the fallback when the model
  call fails or returns unusable output. Its output is deliberately
  mechanical (it extracts, it does not invent).
* :class:`OllamaDistiller` — the small local model (default
  ``qwen3.5:2b``, override with ``POCKPOCK_DISTILL_MODEL``) with
  ``think: false`` (a thinking trace would eat the generation, see issue
  #86), asked for a strict JSON draft. Output is validated with the same
  schema checks as the stub; anything invalid falls back to the stub.

Distillation only ever *drafts candidates* into the inbox. Nothing it
produces is retrievable until it passes the promotion gate.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..agent_tools.tool_retriever import _http_json
from .inbox import Candidate
from .memory import normalize_task_tag
from .skills import Skill, slugify, validate_skill

#: Default distillation model (small, local). Override with POCKPOCK_DISTILL_MODEL.
DEFAULT_DISTILL_MODEL = "qwen3.5:2b"

#: Ollama base URL (same default as the rest of the backend).
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"

#: Cap on trajectory text sent to the model, so a long run cannot blow the
#: small model's context.
MAX_TRAJECTORY_CHARS = 12_000


@dataclass
class RunRecord:
    """A completed run, as the distiller consumes it.

    ``trajectory`` is a list of step dicts, each with at least ``step``
    (free text) and optionally ``tool``, ``outcome`` (``ok``/``error``)
    and ``detail``. ``verifier_verdict`` is the external verifier's
    verdict where available (``pass``/``fail`` + note) — the distiller
    trusts it over the run's self-reported outcome.
    """

    run_id: str
    task: str
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    outcome: str = "success"  # success | partial | failure
    verifier_verdict: dict[str, Any] | None = None

    @property
    def succeeded(self) -> bool:
        if self.verifier_verdict is not None:
            return str(self.verifier_verdict.get("verdict", "")).lower() == "pass"
        return self.outcome in {"success", "partial"}

    def failed_steps(self) -> list[dict[str, Any]]:
        return [
            step for step in self.trajectory
            if str(step.get("outcome", "")).lower() in {"error", "failed", "fail"}
        ]


def _abstract_step(step: dict[str, Any]) -> str:
    """Strip concrete values from one trajectory step into a generic instruction."""
    text = str(step.get("step", "") or step.get("detail", "") or "").strip()
    # Replace quoted literals, paths and numbers with placeholders.
    text = re.sub(r"'[^']{1,40}'", "<value>", text)
    text = re.sub(r'"[^"]{1,40}"', "<value>", text)
    text = re.sub(r"[\w./-]+\.(py|js|ts|md|csv|xlsx|docx|json|html)", "<file>", text)
    text = re.sub(r"\b\d+(\.\d+)?\b", "<n>", text)
    return text or "(no description recorded)"


def _trajectory_text(record: RunRecord) -> str:
    lines = []
    for i, step in enumerate(record.trajectory, 1):
        tool = step.get("tool", "")
        outcome = step.get("outcome", "")
        lines.append(f"{i}. [{tool}] {step.get('step', '')} -> {outcome}".strip())
        if step.get("detail"):
            lines.append(f"   detail: {step['detail']}")
    return "\n".join(lines)[:MAX_TRAJECTORY_CHARS]


# ---------------------------------------------------------------------------
# Stub distiller (deterministic, offline)
# ---------------------------------------------------------------------------


class StubDistiller:
    """Rule-based distillation: extracts, never invents. Offline-safe."""

    def distill(self, record: RunRecord) -> list[Candidate]:
        candidates: list[Candidate] = []
        tag = normalize_task_tag(record.task)
        name = slugify(record.task) or "task"
        # Only successful steps go into the reusable procedure: a failed
        # step is material for a FAILURE tip, not for the skill itself.
        ok_steps = [
            step for step in record.trajectory
            if str(step.get("outcome", "")).lower() not in {"error", "failed", "fail"}
        ]
        steps = [_abstract_step(step) for step in ok_steps]
        failed = record.failed_steps()

        if record.succeeded and steps:
            body_lines = [
                f"# {record.task}",
                "",
                "## When to use",
                "",
                f"Use this skill when the task is: {record.task}",
                "",
                "## Procedure",
                "",
            ]
            for i, step in enumerate(steps, 1):
                body_lines.append(f"{i}. {step}")
            body_lines += [
                "",
                "## Notes",
                "",
                f"Distilled from run `{record.run_id}` (outcome: {record.outcome}).",
            ]
            if record.verifier_verdict:
                body_lines.append(
                    f"Verifier verdict: {record.verifier_verdict.get('verdict')} — "
                    f"{record.verifier_verdict.get('note', '')}"
                )
            skill = Skill(
                name=name,
                description=f"Reusable procedure for: {record.task}"[:200],
                version="0.1.0",
                body="\n".join(body_lines),
                verification={"type": "manual"},
                tags=[tag],
                source_run_id=record.run_id,
            )
            problems = validate_skill(skill)
            if not problems:
                candidates.append(Candidate(
                    kind="skill", payload=skill.to_markdown(), name=skill.name,
                    source_run_id=record.run_id, verification=skill.verification,
                ))

            workflow = "\n".join(
                [f"## Workflow: {record.task}", ""]
                + [f"{i}. {step}" for i, step in enumerate(steps, 1)]
            )
            candidates.append(Candidate(
                kind="workflow", payload=workflow, name=name,
                source_run_id=record.run_id, verification={"type": "manual"},
            ))

        tips: list[dict[str, Any]] = []
        if record.succeeded and steps:
            tips.append({
                "title": f"Follow the distilled steps for: {record.task}",
                "description": "The run succeeded by following a repeatable sequence of steps.",
                "content": (
                    "Do the steps in order: " + "; ".join(steps[:5]) + ". "
                    "Skipping a step or reordering them risks the same failure "
                    "modes seen in other runs."
                ),
                "kind": "success",
                "action": "follow the distilled steps in order",
                "task_tag": tag,
                "confidence": 0.6,
            })
        for step in failed[:2]:
            tool = step.get("tool", "a tool")
            tips.append({
                "title": f"Don't repeat the failed {tool} step as-is",
                "description": f"The {tool} step failed during run {record.run_id}.",
                "content": (
                    f"Don't call {tool} with the same arguments again — it fails because: "
                    f"{step.get('detail', 'the step returned an error')}. "
                    "Change the input or use the alternative step from the distilled workflow first."
                ),
                "kind": "failure",
                "action": f"repeat the failed {tool} step unchanged",
                "task_tag": tag,
                "confidence": 0.7,
            })
        for tip in tips[:3]:
            candidates.append(Candidate(
                kind="tip", payload=json.dumps(tip), name=tip["title"],
                source_run_id=record.run_id, verification={"type": "manual"},
            ))
        return candidates


# ---------------------------------------------------------------------------
# Ollama distiller (small local model, think:false)
# ---------------------------------------------------------------------------

_DISTILL_SYSTEM = (
    "You distill agent run trajectories into reusable knowledge. "
    "Reply with strict JSON only, no other text. Schema: "
    '{"skill": {"name": "kebab-case", "description": "one line", "body": "markdown procedure"}, '
    '"workflow": "numbered abstracted steps as markdown", '
    '"tips": [{"title": "...", "description": "...", "content": "...", '
    '"kind": "success"|"failure", "action": "short action phrase", "confidence": 0.0-1.0}]}. '
    "Include failure tips for any step that errored. Abstract concrete filenames and values. "
    "If the run failed, omit the skill and workflow and return only failure tips."
)


def _parse_model_draft(text: str) -> dict[str, Any] | None:
    """Extract a JSON draft from model output (tolerates surrounding text)."""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class OllamaDistiller:
    """Distill with the small local model; falls back to the stub on any failure."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: float = 300.0,
        fallback: StubDistiller | None = None,
    ):
        self.base_url = (base_url or os.environ.get("POCKPOCK_OLLAMA_URL", DEFAULT_OLLAMA_URL)).rstrip("/")
        self.model = model or os.environ.get("POCKPOCK_DISTILL_MODEL", DEFAULT_DISTILL_MODEL)
        self.timeout_s = timeout_s
        self.fallback = fallback or StubDistiller()

    def _chat(self, prompt: str) -> str:
        result = _http_json(
            f"{self.base_url}/api/chat",
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": _DISTILL_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                # Distillation is a text task: thinking on burns the
                # generation on a trace and can return empty content (#86).
                "think": False,
            },
            timeout=self.timeout_s,
        )
        message = (result or {}).get("message") or {}
        return str(message.get("content", "") or "")

    def distill(self, record: RunRecord) -> list[Candidate]:
        prompt = (
            f"Task: {record.task}\nOutcome: {record.outcome}\n"
            f"Verifier verdict: {json.dumps(record.verifier_verdict or {})}\n"
            f"Trajectory:\n{_trajectory_text(record)}"
        )
        try:
            draft = _parse_model_draft(self._chat(prompt))
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            draft = None
        if not draft:
            return self.fallback.distill(record)
        return _candidates_from_draft(record, draft) or self.fallback.distill(record)


def _candidates_from_draft(record: RunRecord, draft: Mapping[str, Any]) -> list[Candidate]:
    """Validate a model draft into candidates; empty list means 'use the stub'."""
    candidates: list[Candidate] = []
    tag = normalize_task_tag(record.task)
    skill_data = draft.get("skill")
    if isinstance(skill_data, dict) and record.succeeded:
        skill = Skill(
            name=slugify(str(skill_data.get("name", ""))) or slugify(record.task),
            description=str(skill_data.get("description", ""))[:200],
            version="0.1.0",
            body=str(skill_data.get("body", "")),
            verification={"type": "manual"},
            tags=[tag],
            source_run_id=record.run_id,
        )
        if not validate_skill(skill):
            candidates.append(Candidate(
                kind="skill", payload=skill.to_markdown(), name=skill.name,
                source_run_id=record.run_id, verification=skill.verification,
            ))
    workflow = draft.get("workflow")
    if isinstance(workflow, str) and workflow.strip() and record.succeeded:
        candidates.append(Candidate(
            kind="workflow", payload=workflow.strip(),
            name=slugify(record.task), source_run_id=record.run_id,
            verification={"type": "manual"},
        ))
    tips = draft.get("tips")
    if isinstance(tips, list):
        for tip in tips[:3]:
            if not isinstance(tip, dict):
                continue
            title = str(tip.get("title", "")).strip()
            content = str(tip.get("content", "")).strip()
            if not title or not content:
                continue
            kind = str(tip.get("kind", "success")).lower()
            if kind not in {"success", "failure"}:
                kind = "success"
            try:
                confidence = float(tip.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            candidates.append(Candidate(
                kind="tip",
                payload=json.dumps({
                    "title": title,
                    "description": str(tip.get("description", "")),
                    "content": content,
                    "kind": kind,
                    "action": str(tip.get("action", "")).strip().lower(),
                    "task_tag": tag,
                    "confidence": min(1.0, max(0.0, confidence)),
                }),
                name=title, source_run_id=record.run_id,
                verification={"type": "manual"},
            ))
    return candidates
