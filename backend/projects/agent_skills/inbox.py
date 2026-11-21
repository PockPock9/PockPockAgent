"""Promotion gate: the skill inbox.

This is the hard part of the skill/memory system, built first. A candidate
is NOT usable until it passes its verification test or a human approves it:

* Distillation produces *candidates*, never library entries. Candidates
  live in the ``skill_candidates`` SQLite table with status ``pending``.
* Each candidate ships with a verification test (a script, a small Python
  snippet, or ``manual``). :func:`run_verification` executes it in a fresh
  temp directory with a timeout; exit code 0 (or no exception) passes.
  A script runs via ``subprocess`` with a minimal environment — no
  network access is granted by the harness, and the command is taken from
  the candidate itself, so only run verification for candidates from a
  trusted source (own runs, or human-reviewed inbox entries).
* ``approve`` promotes a candidate: verified candidates (test passed, or
  ``manual`` type) move into the skill library with status ``promoted``
  and their reasoning tips become ``active``. An unverified candidate
  cannot be approved unless the reviewer explicitly passes
  ``force=True`` — and that override is recorded in the decision log.
* ``reject`` marks the candidate rejected with a reason; rejected
  candidates are never retrieved and never promoted.

Unverified candidates must never be retrieved into a live run. Retrieval
(see :mod:`projects.agent_skills.skills` and
:mod:`projects.agent_skills.service`) only ever sees ``promoted`` skills
and ``active`` tips, so the gate cannot be bypassed by a retrieval bug.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from .memory import PruningDecision, ReasoningMemory, ReasoningTip, _new_id, _now
from .skills import Skill, SkillLibrary, validate_skill

#: Candidate statuses.
CANDIDATE_STATUSES = ("pending", "approved", "rejected")

#: Default verification timeout (seconds).
DEFAULT_VERIFICATION_TIMEOUT_S = 120


@dataclass
class VerificationResult:
    passed: bool
    method: str  # "script" | "python" | "manual" | "error"
    detail: str = ""
    duration_ms: float = 0.0


@dataclass
class Candidate:
    """One distilled candidate awaiting the promotion gate."""

    id: str = ""
    kind: str = "skill"  # "skill" | "workflow" | "tip"
    # For kind == "skill": the full SKILL.md text. For "workflow": the
    # abstracted steps as markdown. For "tip": a JSON ReasoningTip dict.
    payload: str = ""
    name: str = ""  # skill name, workflow title, or tip title
    source_run_id: str = ""
    status: str = "pending"
    verification: dict[str, Any] = field(default_factory=dict)
    verification_result: dict[str, Any] = field(default_factory=dict)
    decision_reason: str = ""
    decided_by: str = ""
    created_at: str = ""
    decided_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "source_run_id": self.source_run_id,
            "status": self.status,
            "verification": self.verification,
            "verification_result": self.verification_result,
            "decision_reason": self.decision_reason,
            "decided_by": self.decided_by,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
        }


def run_verification(
    verification: dict[str, Any],
    *,
    skill_dir: Path | None = None,
    timeout_s: int = DEFAULT_VERIFICATION_TIMEOUT_S,
) -> VerificationResult:
    """Run a candidate's verification test. Returns pass/fail, never raises.

    * ``{"type": "script", "command": [...]}`` — run the command in a
      fresh temp dir (``skill_dir`` is copied in when given, so a skill's
      own ``scripts/`` can be tested). Exit 0 passes.
    * ``{"type": "python", "code": "..."}`` — run the snippet with the
      current interpreter in a fresh temp dir. No exception passes.
    * ``{"type": "manual"}`` — no automated test; a human must approve.
      Reported as passed=False with method "manual" so the gate treats it
      as unverified until a reviewer approves it.
    * empty/unknown — fails closed: not verified.
    """
    import time

    started = time.monotonic()
    vtype = (verification or {}).get("type")
    if vtype == "manual":
        return VerificationResult(False, "manual", "manual verification: human approval required")
    if vtype == "script":
        command = verification.get("command")
        if not isinstance(command, list) or not command or not all(
            isinstance(part, str) for part in command
        ):
            return VerificationResult(False, "error", "script verification needs a command list")
        try:
            with tempfile.TemporaryDirectory(prefix="pockpock-verify-") as tmp:
                if skill_dir is not None and Path(skill_dir).is_dir():
                    import shutil

                    for entry in Path(skill_dir).iterdir():
                        target = Path(tmp) / entry.name
                        if entry.is_dir():
                            shutil.copytree(entry, target)
                        else:
                            shutil.copy2(entry, target)
                env = {"PATH": os.environ.get("PATH", ""), "TMPDIR": tmp}
                result = subprocess.run(
                    command, cwd=tmp, capture_output=True, text=True,
                    timeout=int(verification.get("timeout_s", timeout_s)),
                    env=env, check=False,
                )
            detail = (result.stdout + result.stderr)[-1000:].strip()
            return VerificationResult(
                result.returncode == 0, "script",
                detail or f"exit code {result.returncode}",
                round((time.monotonic() - started) * 1000, 1),
            )
        except (subprocess.TimeoutExpired, OSError) as err:
            return VerificationResult(False, "error", f"verification failed to run: {err}")
    if vtype == "python":
        code = verification.get("code")
        if not isinstance(code, str) or not code.strip():
            return VerificationResult(False, "error", "python verification needs code")
        try:
            with tempfile.TemporaryDirectory(prefix="pockpock-verify-") as tmp:
                result = subprocess.run(
                    [sys.executable, "-c", code], cwd=tmp, capture_output=True,
                    text=True, timeout=int(verification.get("timeout_s", timeout_s)),
                    env={"PATH": os.environ.get("PATH", ""), "TMPDIR": tmp},
                    check=False,
                )
            detail = (result.stdout + result.stderr)[-1000:].strip()
            return VerificationResult(
                result.returncode == 0, "python",
                detail or f"exit code {result.returncode}",
                round((time.monotonic() - started) * 1000, 1),
            )
        except (subprocess.TimeoutExpired, OSError) as err:
            return VerificationResult(False, "error", f"verification failed to run: {err}")
    return VerificationResult(False, "error", f"unknown verification type: {vtype!r}")


class SkillInbox:
    """Pending-candidate queue with approve/reject and the promotion step."""

    def __init__(
        self,
        connect_db: Callable[[], sqlite3.Connection],
        library: SkillLibrary,
        memory: ReasoningMemory,
        lock: threading.Lock | None = None,
    ):
        self._connect_db = connect_db
        self._library = library
        self._memory = memory
        self._lock = lock or threading.Lock()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect_db()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS skill_candidates (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    name TEXT NOT NULL,
                    source_run_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    verification TEXT NOT NULL DEFAULT '{}',
                    verification_result TEXT NOT NULL DEFAULT '{}',
                    decision_reason TEXT NOT NULL DEFAULT '',
                    decided_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    decided_at TEXT NOT NULL DEFAULT ''
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS skill_registry (
                    name TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    source_run_id TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )"""
            )

    # -- enqueue --------------------------------------------------------------
    def submit(self, candidate: Candidate) -> Candidate:
        """Add a distilled candidate to the inbox (always ``pending``)."""
        if candidate.kind not in {"skill", "workflow", "tip"}:
            raise ValueError(f"Unknown candidate kind: {candidate.kind!r}")
        if not (candidate.payload or "").strip():
            raise ValueError("Candidate payload is required")
        self.initialize()
        candidate.id = candidate.id or _new_id()
        candidate.status = "pending"
        candidate.created_at = candidate.created_at or _now()
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO skill_candidates
                   (id, kind, payload, name, source_run_id, status,
                    verification, verification_result, decision_reason,
                    decided_by, created_at, decided_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    candidate.id, candidate.kind, candidate.payload, candidate.name,
                    candidate.source_run_id, candidate.status,
                    json.dumps(candidate.verification),
                    json.dumps(candidate.verification_result),
                    candidate.decision_reason, candidate.decided_by,
                    candidate.created_at, candidate.decided_at,
                ),
            )
        return candidate

    def _row_to_candidate(self, row: sqlite3.Row) -> Candidate:
        return Candidate(
            id=row["id"], kind=row["kind"], payload=row["payload"], name=row["name"],
            source_run_id=row["source_run_id"], status=row["status"],
            verification=json.loads(row["verification"] or "{}"),
            verification_result=json.loads(row["verification_result"] or "{}"),
            decision_reason=row["decision_reason"], decided_by=row["decided_by"],
            created_at=row["created_at"], decided_at=row["decided_at"],
        )

    def get(self, candidate_id: str) -> Candidate | None:
        self.initialize()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM skill_candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
        return self._row_to_candidate(row) if row else None

    def list(self, *, status: str = "pending") -> list[Candidate]:
        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM skill_candidates WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        return [self._row_to_candidate(row) for row in rows]

    # -- verification -----------------------------------------------------------
    def verify(self, candidate_id: str) -> VerificationResult:
        """Run the candidate's verification test and record the result."""
        candidate = self.get(candidate_id)
        if candidate is None:
            raise FileNotFoundError(f"No such candidate: {candidate_id}")
        if candidate.status != "pending":
            raise ValueError(f"Candidate {candidate_id} is already {candidate.status}")
        skill_dir: Path | None = None
        if candidate.kind == "skill":
            try:
                skill_dir = self._library.skill_path(candidate.name).parent
            except ValueError:
                skill_dir = None
        result = run_verification(candidate.verification, skill_dir=skill_dir)
        candidate.verification_result = {
            "passed": result.passed, "method": result.method,
            "detail": result.detail, "duration_ms": result.duration_ms,
        }
        with self._lock, self._connection() as connection:
            connection.execute(
                "UPDATE skill_candidates SET verification_result = ? WHERE id = ?",
                (json.dumps(candidate.verification_result), candidate_id),
            )
        return result

    def _is_verified(self, candidate: Candidate) -> bool:
        return bool((candidate.verification_result or {}).get("passed"))

    # -- decisions --------------------------------------------------------------
    def approve(
        self, candidate_id: str, *, reason: str = "", by: str = "human",
        force: bool = False,
    ) -> Candidate:
        """Promote a candidate into the library / memory.

        Requires a passed verification test, unless ``force=True`` — an
        explicit human override that is recorded in ``decision_reason``.
        A ``manual``-type candidate has no automated test, so approval
        itself is the verification and is always allowed (recorded as
        ``by`` the reviewer).
        """
        candidate = self.get(candidate_id)
        if candidate is None:
            raise FileNotFoundError(f"No such candidate: {candidate_id}")
        if candidate.status != "pending":
            raise ValueError(f"Candidate {candidate_id} is already {candidate.status}")
        verified = self._is_verified(candidate)
        manual = (candidate.verification or {}).get("type") == "manual"
        if not verified and not manual and not force:
            raise ValueError(
                f"Candidate {candidate_id} has not passed verification; "
                "run verify() first or approve with force=True (recorded override)"
            )
        self._promote(candidate)
        now = _now()
        decision_reason = reason or ("approved after verification" if verified else "human approval")
        if force and not verified and not manual:
            decision_reason += " [OVERRIDE: approved without passing verification]"
        with self._lock, self._connection() as connection:
            connection.execute(
                """UPDATE skill_candidates
                   SET status = 'approved', decision_reason = ?, decided_by = ?, decided_at = ?
                   WHERE id = ?""",
                (decision_reason, by, now, candidate_id),
            )
        candidate.status = "approved"
        candidate.decision_reason = decision_reason
        candidate.decided_by = by
        candidate.decided_at = now
        return candidate

    def _promote(self, candidate: Candidate) -> None:
        """Move an approved candidate into the library/memory as usable."""
        self.initialize()
        now = _now()
        if candidate.kind == "skill":
            from .skills import skill_from_markdown

            skill = skill_from_markdown(candidate.payload, status="promoted")
            problems = validate_skill(skill)
            if problems:
                raise ValueError("Cannot promote invalid skill: " + "; ".join(problems))
            path = self._library.skill_path(skill.name)
            if path.exists():
                self._library.update(skill)
            else:
                self._library.create(skill)
            self._set_registry(skill.name, "promoted", skill.confidence, candidate.source_run_id)
            self._library.attach_statuses(self.registry_statuses())
        elif candidate.kind == "workflow":
            # A workflow is stored as a skill whose body is the abstracted
            # steps; the name is prefixed so it stays discoverable.
            from .skills import Skill as _Skill

            skill = _Skill(
                name=f"workflow-{candidate.name}"[:64],
                description=f"Workflow distilled from run {candidate.source_run_id or 'unknown'}: {candidate.name}",
                version="0.1.0",
                body=candidate.payload,
                verification=candidate.verification,
                tags=["workflow"],
                source_run_id=candidate.source_run_id,
                status="promoted",
            )
            problems = validate_skill(skill)
            if problems:
                raise ValueError("Cannot promote invalid workflow: " + "; ".join(problems))
            path = self._library.skill_path(skill.name)
            if path.exists():
                self._library.update(skill)
            else:
                self._library.create(skill)
            self._set_registry(skill.name, "promoted", 0.5, candidate.source_run_id)
            self._library.attach_statuses(self.registry_statuses())
        elif candidate.kind == "tip":
            data = json.loads(candidate.payload)
            tip = ReasoningTip(
                title=data.get("title", candidate.name),
                description=data.get("description", ""),
                content=data.get("content", ""),
                kind=data.get("kind", "success"),
                action=data.get("action", ""),
                task_tag=data.get("task_tag", ""),
                confidence=float(data.get("confidence", 0.5)),
                source_run_id=candidate.source_run_id,
            )
            self._memory.add_tip(tip)
        else:  # pragma: no cover - submit() already validates kind
            raise ValueError(f"Unknown candidate kind: {candidate.kind!r}")

    def reject(self, candidate_id: str, *, reason: str, by: str = "human") -> Candidate:
        """Reject a candidate. Rejected candidates are never promoted or retrieved."""
        candidate = self.get(candidate_id)
        if candidate is None:
            raise FileNotFoundError(f"No such candidate: {candidate_id}")
        if candidate.status != "pending":
            raise ValueError(f"Candidate {candidate_id} is already {candidate.status}")
        if not (reason or "").strip():
            raise ValueError("A rejection needs a reason")
        now = _now()
        with self._lock, self._connection() as connection:
            connection.execute(
                """UPDATE skill_candidates
                   SET status = 'rejected', decision_reason = ?, decided_by = ?, decided_at = ?
                   WHERE id = ?""",
                (reason, by, now, candidate_id),
            )
        candidate.status = "rejected"
        candidate.decision_reason = reason
        candidate.decided_by = by
        candidate.decided_at = now
        return candidate

    # -- registry ---------------------------------------------------------------
    def _set_registry(self, name: str, status: str, confidence: float, source_run_id: str) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO skill_registry (name, status, confidence, source_run_id, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                       status = excluded.status,
                       confidence = excluded.confidence,
                       source_run_id = excluded.source_run_id,
                       updated_at = excluded.updated_at""",
                (name, status, confidence, source_run_id, _now()),
            )

    def registry_statuses(self) -> dict[str, str]:
        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT name, status FROM skill_registry"
            ).fetchall()
        return {row["name"]: row["status"] for row in rows}

    def registry_entries(self) -> list[dict[str, Any]]:
        """Full registry rows (name, status, confidence) for maintenance."""
        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT name, status, confidence, source_run_id FROM skill_registry"
            ).fetchall()
        return [dict(row) for row in rows]

    def set_skill_status(self, name: str, status: str, *, reason: str = "") -> None:
        """Change a promoted skill's lifecycle status (prune/invalidate).

        The decision is logged to the reasoning memory's pruning log so
        memory loss is always explainable.
        """
        if status not in {"draft", "verified", "promoted", "pruned", "invalidated"}:
            raise ValueError(f"Unknown skill status: {status!r}")
        self.initialize()
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO skill_registry (name, status, confidence, source_run_id, updated_at)
                   VALUES (?, ?, 0.5, '', ?)
                   ON CONFLICT(name) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at""",
                (name, status, _now()),
            )
        if status in {"pruned", "invalidated"}:
            self._memory.log_decision(
                PruningDecision(
                    item_type="skill", item_id=name, decision=status,
                    reason=reason or f"skill status changed to {status}",
                )
            )
        self._library.attach_statuses(self.registry_statuses())
