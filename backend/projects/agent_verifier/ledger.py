"""Durable run ledger (Task/Progress ledger, Magentic-One style).

One SQLite database holds, per run: the plan/task, one row per step with its
state capsule, tool calls, file diffs, and verifier verdicts, plus an
append-only event log (resume, rewind, retry, terminal outcome).

Durability contract (this is what makes resume after a kill possible):
- Every step is written twice: a ``pending`` row is committed *before* the
  executor runs the step, and the outcome row is committed *after* it.
- Every write is its own transaction with ``PRAGMA synchronous=FULL`` on a
  WAL journal, so a committed row survives a process kill.
- Nothing is only held in memory: the harness never trusts in-process state
  over what ``get_run`` / ``get_steps`` return from disk.

This ledger is deliberately separate from the existing run store
(``backend/scripts/agent_run_store.py``): that store owns gateway run
metadata, approvals, and delegation contracts. This ledger owns the
*verifiable execution* record — per-step capsules, diffs, and verdicts —
for runs the verifier harness drives. A run may reference a run-store
``run_id`` (same 32-hex format) but the ledger never duplicates the run
store's tables, and it works standalone for offline/CLI verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:  # package import (backend root on sys.path)
    from agent_verifier.capsule import StateCapsule
except ImportError:  # service-folder import (projects/ on sys.path)
    from capsule import StateCapsule

_RUN_ID_RE = re.compile(r"^[a-f0-9]{32}$")

RUN_STATUSES = {"running", "completed", "failed", "interrupted", "cancelled", "timed_out"}
STEP_STATUSES = {"pending", "running", "success", "failed", "skipped", "rewound"}


class LedgerError(ValueError):
    """Raised for invalid ledger input or a missing run/step."""


def default_db_path() -> Path:
    """Default ledger location: the PockPock local data dir, unless overridden."""
    override = os.environ.get("POCKPOCK_AGENT_VERIFIER_DB")
    if override:
        return Path(override).expanduser()
    try:
        import sys

        scripts = Path(__file__).resolve().parents[2] / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from pockpock_paths import app_data_dir

        return app_data_dir("PockPock") / "agent-verifier-ledger.sqlite3"
    except Exception:
        return Path.home() / ".local" / "share" / "PockPock" / "agent-verifier-ledger.sqlite3"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


class Ledger:
    """SQLite-backed durable ledger. One connection per call; safe to share."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._init_schema(connection)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # sqlite3's own context manager commits or rolls back but leaves the
        # connection open; close it too, so the file is not held (Windows cannot
        # delete or move an open database).
        connection = sqlite3.connect(self.db_path, timeout=10)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _init_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL DEFAULT '',
                task TEXT NOT NULL DEFAULT '',
                requirements_json TEXT NOT NULL DEFAULT '[]',
                plan_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'running',
                limits_json TEXT NOT NULL DEFAULT '{}',
                capsule_json TEXT NOT NULL DEFAULT '{}',
                failure_signature_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS steps (
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                step_index INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                finished_at TEXT,
                tool_calls_json TEXT NOT NULL DEFAULT '[]',
                result_json TEXT,
                error_json TEXT,
                capsule_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (run_id, step_index)
            );
            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                step_index INTEGER NOT NULL,
                tool TEXT NOT NULL,
                arguments_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT '',
                duration_ms INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS file_diffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                step_index INTEGER NOT NULL,
                path TEXT NOT NULL,
                sha256_before TEXT NOT NULL DEFAULT '',
                sha256_after TEXT NOT NULL DEFAULT '',
                diff_hash TEXT NOT NULL DEFAULT '',
                restored INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS verdicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                step_index INTEGER,
                verifier TEXT NOT NULL,
                verdict TEXT NOT NULL,
                evidence_json TEXT NOT NULL DEFAULT '[]',
                failed_check TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_steps_run ON steps(run_id, step_index);
            CREATE INDEX IF NOT EXISTS idx_verdicts_run ON verdicts(run_id, created_at);
            """
        )

    # -- runs ---------------------------------------------------------------

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
            raise LedgerError("run_id must be a 32-character lowercase hex string")

    def create_run(
        self,
        run_id: str,
        *,
        task: str,
        task_type: str = "",
        requirements: list[str] | None = None,
        plan: list[dict] | None = None,
        limits: dict | None = None,
    ) -> dict:
        """Persist a run and its plan before any step executes (write-ahead)."""
        self._validate_run_id(run_id)
        if not isinstance(task, str) or not task.strip():
            raise LedgerError("task must be a non-empty string")
        plan = list(plan or [])
        now = _utcnow()
        capsule = StateCapsule(goal=task.strip(), next_step=plan[0].get("title", "") if plan else "")
        with self._lock, self._connect() as connection:
            if connection.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
                raise LedgerError("This run ID has already been used.")
            connection.execute(
                "INSERT INTO runs(run_id, task_type, task, requirements_json, plan_json, status,"
                " limits_json, capsule_json, created_at, updated_at, started_at)"
                " VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)",
                (
                    run_id, task_type[:40], task.strip()[:8000],
                    _dumps([str(item) for item in (requirements or [])]),
                    _dumps(plan), _dumps(limits or {}), _dumps(capsule.to_dict()),
                    now, now, now,
                ),
            )
            for index, step in enumerate(plan):
                title = step.get("title", "") if isinstance(step, dict) else str(step)
                connection.execute(
                    "INSERT INTO steps(run_id, step_index, title, status, capsule_json)"
                    " VALUES (?, ?, ?, 'pending', ?)",
                    (run_id, index, str(title)[:500], _dumps({})),
                )
            self._insert_event(connection, run_id, "run_created", {"plan_steps": len(plan)})
        return self.get_run(run_id)  # type: ignore[return-value]

    def get_run(self, run_id: str) -> dict | None:
        self._validate_run_id(run_id)
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            return self._run_dict(row) if row else None

    def list_runs(self, *, status: str | None = None, limit: int = 50) -> list[dict]:
        if status is not None and status not in RUN_STATUSES:
            raise LedgerError(f"Unknown run status: {status}")
        with self._lock, self._connect() as connection:
            if status:
                rows = connection.execute(
                    "SELECT * FROM runs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status, max(1, min(limit, 500))),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
                    (max(1, min(limit, 500)),),
                ).fetchall()
            return [self._run_dict(row) for row in rows]

    @staticmethod
    def _run_dict(row: sqlite3.Row) -> dict:
        return {
            "run_id": row["run_id"],
            "task_type": row["task_type"],
            "task": row["task"],
            "requirements": _loads(row["requirements_json"], []),
            "plan": _loads(row["plan_json"], []),
            "status": row["status"],
            "limits": _loads(row["limits_json"], {}),
            "capsule": _loads(row["capsule_json"], {}),
            "failure_signature": _loads(row["failure_signature_json"], None),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    def set_status(self, run_id: str, status: str, *, failure_signature: dict | None = None) -> dict:
        self._validate_run_id(run_id)
        if status not in RUN_STATUSES:
            raise LedgerError(f"Unknown run status: {status}")
        now = _utcnow()
        with self._lock, self._connect() as connection:
            if not connection.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
                raise LedgerError("Run not found")
            finished = now if status in {"completed", "failed", "cancelled", "timed_out"} else None
            connection.execute(
                "UPDATE runs SET status=?, updated_at=?, finished_at=COALESCE(?, finished_at),"
                " failure_signature_json=COALESCE(?, failure_signature_json) WHERE run_id=?",
                (status, now, finished,
                 _dumps(failure_signature) if failure_signature is not None else None, run_id),
            )
            self._insert_event(connection, run_id, "status_changed", {"status": status})
        result = self.get_run(run_id)
        assert result is not None
        return result

    def update_capsule(self, run_id: str, capsule: StateCapsule) -> None:
        self._validate_run_id(run_id)
        with self._lock, self._connect() as connection:
            if not connection.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
                raise LedgerError("Run not found")
            connection.execute(
                "UPDATE runs SET capsule_json=?, updated_at=? WHERE run_id=?",
                (_dumps(capsule.to_dict()), _utcnow(), run_id),
            )

    def replace_plan(self, run_id: str, plan: list[dict]) -> None:
        """Re-planning: persist the new plan and its pending step rows."""
        self._validate_run_id(run_id)
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT plan_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                raise LedgerError("Run not found")
            old_plan = _loads(row["plan_json"], [])
            done = {
                r["step_index"]
                for r in connection.execute(
                    "SELECT step_index FROM steps WHERE run_id=? AND status='success'", (run_id,)
                ).fetchall()
            }
            connection.execute("UPDATE runs SET plan_json=?, updated_at=? WHERE run_id=?", (_dumps(plan), _utcnow(), run_id))
            for index, step in enumerate(plan):
                title = step.get("title", "") if isinstance(step, dict) else str(step)
                if index in done:
                    continue
                connection.execute(
                    "INSERT INTO steps(run_id, step_index, title, status, capsule_json)"
                    " VALUES (?, ?, ?, 'pending', ?) ON CONFLICT(run_id, step_index)"
                    " DO UPDATE SET title=excluded.title",
                    (run_id, index, str(title)[:500], _dumps({})),
                )
            self._insert_event(connection, run_id, "plan_replaced",
                               {"old_steps": len(old_plan), "new_steps": len(plan)})

    # -- steps --------------------------------------------------------------

    def append_step_begin(self, run_id: str, step_index: int, *, title: str = "") -> dict:
        """Write-ahead: record the step as running BEFORE the executor runs it."""
        self._validate_run_id(run_id)
        now = _utcnow()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM steps WHERE run_id=? AND step_index=?", (run_id, step_index)
            ).fetchone()
            if not row:
                raise LedgerError("Step not found")
            if row["status"] in {"success"}:
                raise LedgerError("A successful step cannot be re-run; rewind first")
            attempts = int(row["attempts"]) + 1
            connection.execute(
                "UPDATE steps SET status='running', attempts=?, started_at=?, title=COALESCE(NULLIF(?, ''), title)"
                " WHERE run_id=? AND step_index=?",
                (attempts, now, title[:500], run_id, step_index),
            )
            self._insert_event(connection, run_id, "step_started", {"step_index": step_index, "attempt": attempts})
        result = self.get_step(run_id, step_index)
        assert result is not None
        return result

    def append_step_end(
        self,
        run_id: str,
        step_index: int,
        *,
        status: str,
        result: dict | None = None,
        error: dict | None = None,
        capsule: StateCapsule | None = None,
    ) -> dict:
        """Commit the step outcome AFTER execution. Never called before the step runs."""
        self._validate_run_id(run_id)
        if status not in STEP_STATUSES:
            raise LedgerError(f"Unknown step status: {status}")
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM steps WHERE run_id=? AND step_index=?", (run_id, step_index)
            ).fetchone()
            if not row:
                raise LedgerError("Step not found")
            connection.execute(
                "UPDATE steps SET status=?, finished_at=?, result_json=?, error_json=?, capsule_json=?,"
                " title=title WHERE run_id=? AND step_index=?",
                (
                    status, _utcnow(),
                    _dumps(result) if result is not None else None,
                    _dumps(error) if error is not None else None,
                    _dumps(capsule.to_dict()) if capsule is not None else _dumps({}),
                    run_id, step_index,
                ),
            )
            if capsule is not None:
                connection.execute(
                    "UPDATE runs SET capsule_json=?, updated_at=? WHERE run_id=?",
                    (_dumps(capsule.to_dict()), _utcnow(), run_id),
                )
            self._insert_event(connection, run_id, "step_finished",
                               {"step_index": step_index, "status": status})
        result_row = self.get_step(run_id, step_index)
        assert result_row is not None
        return result_row

    def get_step(self, run_id: str, step_index: int) -> dict | None:
        self._validate_run_id(run_id)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM steps WHERE run_id=? AND step_index=?", (run_id, step_index)
            ).fetchone()
            return self._step_dict(row) if row else None

    def get_steps(self, run_id: str) -> list[dict]:
        self._validate_run_id(run_id)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM steps WHERE run_id=? ORDER BY step_index", (run_id,)
            ).fetchall()
            return [self._step_dict(row) for row in rows]

    @staticmethod
    def _step_dict(row: sqlite3.Row) -> dict:
        return {
            "run_id": row["run_id"],
            "step_index": row["step_index"],
            "title": row["title"],
            "status": row["status"],
            "attempts": row["attempts"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "tool_calls": _loads(row["tool_calls_json"], []),
            "result": _loads(row["result_json"], None),
            "error": _loads(row["error_json"], None),
            "capsule": _loads(row["capsule_json"], {}),
        }

    def next_unfinished_step(self, run_id: str) -> dict | None:
        """First step that is not a success — the resume point. None = plan done."""
        for step in self.get_steps(run_id):
            if step["status"] != "success":
                return step
        return None

    # -- tool calls, diffs, verdicts, events --------------------------------

    def record_tool_call(
        self, run_id: str, step_index: int, *, tool: str, arguments: dict | None = None,
        status: str = "", duration_ms: int | None = None,
    ) -> None:
        self._validate_run_id(run_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO tool_calls(run_id, step_index, tool, arguments_json, status, duration_ms, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, step_index, str(tool)[:120], _dumps(arguments or {}), str(status)[:40], duration_ms, _utcnow()),
            )
            # Keep the step's embedded tool-call list in sync (bounded, latest first).
            row = connection.execute(
                "SELECT tool_calls_json FROM steps WHERE run_id=? AND step_index=?", (run_id, step_index)
            ).fetchone()
            calls = _loads(row["tool_calls_json"], []) if row else []
            calls.append({"tool": tool, "status": status, "duration_ms": duration_ms})
            connection.execute(
                "UPDATE steps SET tool_calls_json=? WHERE run_id=? AND step_index=?",
                (_dumps(calls[-50:]), run_id, step_index),
            )

    def record_file_diff(
        self, run_id: str, step_index: int, *, path: str,
        sha256_before: str = "", sha256_after: str = "",
    ) -> dict:
        self._validate_run_id(run_id)
        diff_hash = hashlib.sha256(f"{sha256_before}\n{sha256_after}\n{path}".encode("utf-8")).hexdigest()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO file_diffs(run_id, step_index, path, sha256_before, sha256_after, diff_hash, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, step_index, str(path)[:500], sha256_before, sha256_after, diff_hash, _utcnow()),
            )
        return {"path": path, "sha256_before": sha256_before, "sha256_after": sha256_after,
                "diff_hash": diff_hash, "restored": False}

    def get_file_diffs(self, run_id: str, *, step_index: int | None = None) -> list[dict]:
        self._validate_run_id(run_id)
        with self._lock, self._connect() as connection:
            if step_index is None:
                rows = connection.execute(
                    "SELECT * FROM file_diffs WHERE run_id=? ORDER BY id", (run_id,)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM file_diffs WHERE run_id=? AND step_index=? ORDER BY id",
                    (run_id, step_index),
                ).fetchall()
            return [
                {"path": r["path"], "step_index": r["step_index"], "sha256_before": r["sha256_before"],
                 "sha256_after": r["sha256_after"], "diff_hash": r["diff_hash"],
                 "restored": bool(r["restored"])}
                for r in rows
            ]

    def record_verdict(
        self, run_id: str, *, verifier: str, verdict: str,
        evidence: list | None = None, failed_check: str | None = None,
        step_index: int | None = None,
    ) -> None:
        self._validate_run_id(run_id)
        if verdict not in {"pass", "fail", "error", "skipped"}:
            raise LedgerError(f"Unknown verdict: {verdict}")
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO verdicts(run_id, step_index, verifier, verdict, evidence_json, failed_check, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, step_index, str(verifier)[:80], verdict,
                 _dumps(evidence or []), (failed_check or "")[:500], _utcnow()),
            )

    def get_verdicts(self, run_id: str) -> list[dict]:
        self._validate_run_id(run_id)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM verdicts WHERE run_id=? ORDER BY id", (run_id,)
            ).fetchall()
            return [
                {"verifier": r["verifier"], "verdict": r["verdict"],
                 "evidence": _loads(r["evidence_json"], []),
                 "failed_check": r["failed_check"], "step_index": r["step_index"],
                 "created_at": r["created_at"]}
                for r in rows
            ]

    def record_event(self, run_id: str, event_type: str, payload: dict | None = None) -> None:
        self._validate_run_id(run_id)
        with self._lock, self._connect() as connection:
            self._insert_event(connection, run_id, event_type, payload or {})

    def get_events(self, run_id: str) -> list[dict]:
        self._validate_run_id(run_id)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY id", (run_id,)
            ).fetchall()
            return [{"event_type": r["event_type"], "payload": _loads(r["payload_json"], {}),
                     "created_at": r["created_at"]} for r in rows]

    @staticmethod
    def _insert_event(connection: sqlite3.Connection, run_id: str, event_type: str, payload: dict) -> None:
        connection.execute(
            "INSERT INTO events(run_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (run_id, str(event_type)[:80], _dumps(payload), _utcnow()),
        )

    # -- rewind ----------------------------------------------------------------

    def rewind(self, run_id: str, step_index: int) -> dict:
        """Rewind to step N: truncate ledger past N and flag what was not restored.

        Step rows, tool calls, and verdicts after N are deleted; the step at N
        itself returns to ``pending`` so it re-runs. File diffs after N are
        *kept* and marked unrestored: this implementation does not snapshot
        whole files, so it cannot restore file contents by itself — it records
        exactly which files were changed past N (path + before/after hashes)
        so the operator (or a future snapshot restore) knows what to undo.
        Returns the rewind summary, including the unrestored file list.
        """
        self._validate_run_id(run_id)
        with self._lock, self._connect() as connection:
            if not connection.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
                raise LedgerError("Run not found")
            if step_index < 0:
                raise LedgerError("step_index must be >= 0")
            unrestored = [
                {"path": r["path"], "step_index": r["step_index"],
                 "sha256_before": r["sha256_before"], "sha256_after": r["sha256_after"],
                 "diff_hash": r["diff_hash"]}
                for r in connection.execute(
                    "SELECT * FROM file_diffs WHERE run_id=? AND step_index>? ORDER BY id",
                    (run_id, step_index),
                ).fetchall()
            ]
            connection.execute("DELETE FROM steps WHERE run_id=? AND step_index>?", (run_id, step_index))
            connection.execute("DELETE FROM tool_calls WHERE run_id=? AND step_index>?", (run_id, step_index))
            connection.execute("DELETE FROM verdicts WHERE run_id=? AND step_index IS NOT NULL AND step_index>?",
                               (run_id, step_index))
            connection.execute(
                "UPDATE steps SET status='pending', finished_at=NULL, result_json=NULL, error_json=NULL"
                " WHERE run_id=? AND step_index=?", (run_id, step_index),
            )
            # Re-create the step row if the plan was longer than the stored rows.
            row = connection.execute(
                "SELECT plan_json FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            plan = _loads(row["plan_json"], [])
            if step_index < len(plan) and not connection.execute(
                "SELECT 1 FROM steps WHERE run_id=? AND step_index=?", (run_id, step_index)
            ).fetchone():
                title = plan[step_index].get("title", "") if isinstance(plan[step_index], dict) else str(plan[step_index])
                connection.execute(
                    "INSERT INTO steps(run_id, step_index, title, status, capsule_json) VALUES (?, ?, ?, 'pending', ?)",
                    (run_id, step_index, str(title)[:500], _dumps({})),
                )
            connection.execute(
                "UPDATE runs SET status='running', updated_at=?, finished_at=NULL WHERE run_id=?",
                (_utcnow(), run_id),
            )
            self._insert_event(connection, run_id, "rewound", {
                "step_index": step_index,
                "unrestored_files": [item["path"] for item in unrestored],
                "file_restore": "not_restored" if unrestored else "nothing_to_restore",
            })
        return {
            "run_id": run_id, "rewound_to_step": step_index,
            "unrestored_files": unrestored,
            "file_restore": "not_restored — file contents were not snapshotted; re-run from step N "
                            "or restore the listed files from version control" if unrestored
                            else "nothing_to_restore",
        }
