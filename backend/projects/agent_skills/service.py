"""Service facade: one object wiring library + memory + inbox + distiller.

The gateway and the CLI scripts talk to this, not to the individual
modules. Defaults resolve under the app data dir
(``<app-data>/PockPock/agent-skills/`` for skill files,
``<app-data>/PockPock/agent-skills.sqlite3`` for candidates, tips, facts
and the pruning log); ``POCKPOCK_SKILLS_DIR`` / ``POCKPOCK_SKILLS_DB``
override them, and tests pass explicit paths.

Skill retrieval into a live run is off by default
(``POCKPOCK_SKILLS_ENABLED``, see :func:`skills_enabled` in
:mod:`projects.agent_skills.skills`) so existing behaviour is unchanged
until the flag is set.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

from .distiller import OllamaDistiller, RunRecord, StubDistiller
from .inbox import Candidate, SkillInbox, VerificationResult
from .maintenance import MaintenanceReport, run_maintenance
from .memory import Fact, ReasoningMemory, ReasoningTip, connect_sqlite
from .skills import SkillLibrary, default_skills_dir, skills_enabled


def default_db_path() -> Path:
    """Default SQLite path (env-overridable)."""
    override = os.environ.get("POCKPOCK_SKILLS_DB", "").strip()
    if override:
        return Path(override).expanduser()
    try:
        from pockpock_paths import app_data_dir  # type: ignore

        return app_data_dir("PockPock") / "agent-skills.sqlite3"
    except Exception:
        return Path.home() / ".local" / "share" / "PockPock" / "agent-skills.sqlite3"


class AgentSkillsService:
    """Facade over the skill library, reasoning memory, inbox and distiller."""

    def __init__(
        self,
        skills_dir: Path | str | None = None,
        db_path: Path | str | None = None,
        *,
        dense_enabled: bool = True,
    ):
        self.skills_dir = Path(skills_dir) if skills_dir is not None else default_skills_dir()
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self.memory = ReasoningMemory(connect_sqlite(self.db_path))
        self.library = SkillLibrary(self.skills_dir, dense_enabled=dense_enabled)
        self.inbox = SkillInbox(connect_sqlite(self.db_path), self.library, self.memory)
        self.inbox.initialize()
        self.memory.initialize()
        self.library.attach_statuses(self.inbox.registry_statuses())

    # -- distill + inbox ------------------------------------------------------
    def distill_run(
        self, record: RunRecord, *, use_model: bool = False
    ) -> list[Candidate]:
        """Distill a run record into inbox candidates (never directly usable)."""
        distiller = OllamaDistiller() if use_model else StubDistiller()
        candidates = distiller.distill(record)
        return [self.inbox.submit(candidate) for candidate in candidates]

    def verify_candidate(self, candidate_id: str) -> VerificationResult:
        return self.inbox.verify(candidate_id)

    def approve_candidate(
        self, candidate_id: str, *, reason: str = "", by: str = "human",
        force: bool = False,
    ) -> Candidate:
        candidate = self.inbox.approve(candidate_id, reason=reason, by=by, force=force)
        self.library.attach_statuses(self.inbox.registry_statuses())
        return candidate

    def reject_candidate(self, candidate_id: str, *, reason: str, by: str = "human") -> Candidate:
        return self.inbox.reject(candidate_id, reason=reason, by=by)

    # -- retrieval for a live run (promoted skills + active tips only) --------
    def retrieve_for_task(
        self, task: str, *, top_k_skills: int = 3, top_k_tips: int = 3
    ) -> dict[str, Any]:
        """What a live run may see for ``task``: promoted skills, active tips, facts."""
        self.library.attach_statuses(self.inbox.registry_statuses())
        records = self.library.retrieve(task, top_k=top_k_skills)
        tips = self.memory.retrieve_tips(task, top_k=top_k_tips)
        for tip in tips:
            self.memory.mark_tip_used(tip.id)
        facts = self.memory.get_facts()
        task_words = {word for word in task.lower().split() if len(word) > 3}
        matching_facts = [
            fact for fact in facts
            if task_words & set(fact.subject.lower().split())
            or task_words & set(fact.value.lower().split())
        ][:5]
        return {
            "skills": [
                {
                    "name": record.skill.name,
                    "description": record.skill.description,
                    "version": record.skill.version,
                    "body": record.skill.body,
                    "score": record.score,
                }
                for record in records
            ],
            "tips": [tip.as_dict() for tip in tips],
            "facts": [fact.as_dict() for fact in matching_facts],
        }

    def context_block_for_task(self, task: str) -> str:
        """A short context block to append to a run's system prompt ('' when empty).

        Promoted skill bodies are truncated: the model gets the procedure,
        not the whole library. Only called when ``POCKPOCK_SKILLS_ENABLED``
        is set; the executor guards the call with the same flag.
        """
        retrieved = self.retrieve_for_task(task)
        parts: list[str] = []
        for skill in retrieved["skills"]:
            parts.append(
                f"Skill '{skill['name']}' (v{skill['version']}): {skill['description']}\n"
                f"{skill['body'][:4000]}"
            )
        for tip in retrieved["tips"]:
            marker = "DO" if tip["kind"] == "success" else "DO NOT"
            parts.append(f"Reasoning tip [{marker}] {tip['title']}: {tip['content']}")
        for fact in retrieved["facts"]:
            parts.append(f"Known fact: {fact['subject']} {fact['predicate']} {fact['value']}")
        if not parts:
            return ""
        return (
            "Relevant skills and memory from past runs (verified, promoted items only):\n"
            + "\n\n".join(parts)
        )

    # -- maintenance ------------------------------------------------------------
    def run_maintenance(self) -> MaintenanceReport:
        return run_maintenance(self.memory, inbox=self.inbox)


__all__ = [
    "AgentSkillsService",
    "Candidate",
    "Fact",
    "ReasoningTip",
    "RunRecord",
    "default_db_path",
    "skills_enabled",
]
