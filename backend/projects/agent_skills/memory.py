"""Reasoning memory (ReasoningBank-style) + semantic fact store.

Two SQLite tables, local only — no graph DB, no external service:

* ``reasoning_tips`` — distilled reasoning strategies in the 3-field
  ReasoningBank format (title / description / content), including
  FAILURE tips ("don't do X, it fails because..."). Every tip carries a
  confidence, a source run id, a task tag, and an expiry/pruning rule.
  Only ``active`` tips are ever retrieved into a run.
* ``facts`` — user/project facts (subject / predicate / value) with the
  same invalidate-don't-overwrite rule as the tips: a new value for the
  same (subject, predicate) marks the old row ``invalidated`` (never
  silently overwritten), so history stays auditable.
* ``pruning_log`` — every pruning/invalidation decision, with its reason,
  so memory loss is always explainable.

Retrieval is BM25 over the tip text (stdlib only, same implementation as
Tool-RAG); dense embeddings are deliberately not added here — tips are
short and keyword retrieval is enough at this scale.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from ..agent_tools.tool_retriever import BM25Index, tokenize

#: Tips whose confidence falls below this are pruned by maintenance.
MIN_CONFIDENCE = 0.2

#: Default time-to-live for a tip/fact that is never used (days).
DEFAULT_TTL_DAYS = 90

#: Statuses a tip or fact can hold. Only ``active`` is retrievable.
STATUSES = ("active", "invalidated", "pruned")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:24]


def normalize_task_tag(text: str) -> str:
    """Normalise a task description into a short, comparable tag."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    stop = {"the", "a", "an", "to", "of", "in", "on", "for", "and", "with", "my", "please"}
    kept = [word for word in words if word not in stop][:6]
    return "-".join(kept) or "general"


@dataclass
class ReasoningTip:
    """One distilled reasoning tip (title / description / content)."""

    id: str = ""
    title: str = ""
    description: str = ""
    content: str = ""
    # "success" (do this, it works) or "failure" (don't do this, it fails).
    kind: str = "success"
    # Short action phrase the tip is about, e.g. "retry with backoff".
    # Contradiction detection compares (task_tag, action, kind).
    action: str = ""
    task_tag: str = ""
    confidence: float = 0.5
    source_run_id: str = ""
    status: str = "active"
    use_count: int = 0
    created_at: str = ""
    last_used_at: str = ""
    expires_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "content": self.content,
            "kind": self.kind,
            "action": self.action,
            "task_tag": self.task_tag,
            "confidence": self.confidence,
            "source_run_id": self.source_run_id,
            "status": self.status,
            "use_count": self.use_count,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "expires_at": self.expires_at,
        }


@dataclass
class Fact:
    """One semantic fact about the user/project."""

    id: str = ""
    subject: str = ""
    predicate: str = ""
    value: str = ""
    confidence: float = 0.5
    source_run_id: str = ""
    status: str = "active"
    created_at: str = ""
    expires_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "predicate": self.predicate,
            "value": self.value,
            "confidence": self.confidence,
            "source_run_id": self.source_run_id,
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


@dataclass
class PruningDecision:
    item_type: str  # "tip" | "fact" | "skill"
    item_id: str
    decision: str  # "invalidated" | "pruned"
    reason: str
    decided_at: str = ""


class ReasoningMemory:
    """SQLite-backed reasoning tips + facts + pruning log.

    ``connect_db`` is injected (same pattern as ``LocalPreferenceMemory``)
    so the gateway can share its app database and tests can use a temp file.
    """

    def __init__(
        self,
        connect_db: Callable[[], sqlite3.Connection],
        lock: threading.Lock | None = None,
    ):
        self._connect_db = connect_db
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
                """CREATE TABLE IF NOT EXISTS reasoning_tips (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    content TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'success',
                    action TEXT NOT NULL DEFAULT '',
                    task_tag TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    source_run_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    use_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL DEFAULT ''
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS facts (
                    id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    source_run_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL DEFAULT ''
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS pruning_log (
                    id TEXT PRIMARY KEY,
                    item_type TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    decided_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tips_tag ON reasoning_tips(task_tag, status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_facts_sp ON facts(subject, predicate, status)"
            )

    # -- tips ---------------------------------------------------------------
    def add_tip(self, tip: ReasoningTip, *, ttl_days: int = DEFAULT_TTL_DAYS) -> ReasoningTip:
        """Store a tip. Raises ValueError on empty title/content or bad kind."""
        if not (tip.title or "").strip():
            raise ValueError("Tip title is required")
        if not (tip.content or "").strip():
            raise ValueError("Tip content is required")
        if tip.kind not in {"success", "failure"}:
            raise ValueError(f"Unknown tip kind: {tip.kind!r}")
        if not 0.0 <= tip.confidence <= 1.0:
            raise ValueError("Tip confidence must be between 0.0 and 1.0")
        self.initialize()
        now = _now()
        tip.id = tip.id or _new_id()
        tip.created_at = tip.created_at or now
        tip.task_tag = tip.task_tag or normalize_task_tag(tip.title)
        tip.action = (tip.action or "").strip().lower()
        tip.expires_at = tip.expires_at or (
            datetime.now(timezone.utc) + timedelta(days=ttl_days)
        ).isoformat()
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO reasoning_tips
                   (id, title, description, content, kind, action, task_tag,
                    confidence, source_run_id, status, use_count, created_at,
                    last_used_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tip.id, tip.title, tip.description, tip.content, tip.kind,
                    tip.action, tip.task_tag, tip.confidence, tip.source_run_id,
                    tip.status, tip.use_count, tip.created_at, tip.last_used_at,
                    tip.expires_at,
                ),
            )
        return tip

    def _row_to_tip(self, row: sqlite3.Row) -> ReasoningTip:
        return ReasoningTip(**{key: row[key] for key in row.keys()})

    def get_tip(self, tip_id: str) -> ReasoningTip | None:
        self.initialize()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM reasoning_tips WHERE id = ?", (tip_id,)
            ).fetchone()
        return self._row_to_tip(row) if row else None

    def list_tips(self, *, status: str | None = None) -> list[ReasoningTip]:
        self.initialize()
        with self._connection() as connection:
            if status is None:
                rows = connection.execute(
                    "SELECT * FROM reasoning_tips ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM reasoning_tips WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
        return [self._row_to_tip(row) for row in rows]

    def retrieve_tips(
        self, task: str, *, top_k: int = 3, min_score: float = 0.5
    ) -> list[ReasoningTip]:
        """BM25 retrieval over *active* tips only. Never returns pruned/invalidated tips."""
        active = self.list_tips(status="active")
        if not active or not (task or "").strip():
            return []
        docs = [
            " ".join([tip.title, tip.description, tip.content, tip.task_tag, tip.action])
            for tip in active
        ]
        index = BM25Index([tokenize(doc) for doc in docs])
        scores = index.score(tokenize(task))
        best = max(scores) if scores else 0.0
        if best < min_score:
            return []
        ranked = sorted(range(len(active)), key=lambda i: scores[i], reverse=True)
        return [active[i] for i in ranked[:top_k]]

    def mark_tip_used(self, tip_id: str) -> None:
        """Record a retrieval use (feeds the disuse-pruning rule)."""
        self.initialize()
        with self._lock, self._connection() as connection:
            connection.execute(
                """UPDATE reasoning_tips
                   SET use_count = use_count + 1, last_used_at = ?
                   WHERE id = ?""",
                (_now(), tip_id),
            )

    def set_tip_status(self, tip_id: str, status: str, *, reason: str = "") -> bool:
        """Change a tip's status, logging the decision when it leaves ``active``."""
        if status not in STATUSES:
            raise ValueError(f"Unknown status: {status!r}")
        self.initialize()
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "UPDATE reasoning_tips SET status = ? WHERE id = ?", (status, tip_id)
            )
            if cursor.rowcount and status != "active":
                self._log_locked(
                    connection, "tip", tip_id, status,
                    reason or f"status changed to {status}",
                )
        return cursor.rowcount > 0

    # -- facts --------------------------------------------------------------
    def add_fact(self, fact: Fact, *, ttl_days: int = DEFAULT_TTL_DAYS) -> Fact:
        """Store a fact, invalidating (never overwriting) a conflicting active fact.

        A conflict is the same (subject, predicate) with a different value.
        The old row is marked ``invalidated`` with the superseding fact's id
        in the pruning log; the old value stays readable for audit.
        Returns the new fact; ``fact.superseded_id`` is set when a conflict
        was found (attribute added dynamically, not a column).
        """
        if not (fact.subject or "").strip() or not (fact.predicate or "").strip():
            raise ValueError("Fact subject and predicate are required")
        if not (fact.value or "").strip():
            raise ValueError("Fact value is required")
        self.initialize()
        now = _now()
        fact.id = fact.id or _new_id()
        fact.created_at = fact.created_at or now
        fact.expires_at = fact.expires_at or (
            datetime.now(timezone.utc) + timedelta(days=ttl_days)
        ).isoformat()
        superseded_id: str | None = None
        with self._lock, self._connection() as connection:
            existing = connection.execute(
                """SELECT id, value FROM facts
                   WHERE subject = ? AND predicate = ? AND status = 'active'""",
                (fact.subject.strip(), fact.predicate.strip()),
            ).fetchone()
            if existing and existing["value"] != fact.value:
                superseded_id = existing["id"]
                connection.execute(
                    "UPDATE facts SET status = 'invalidated' WHERE id = ?",
                    (superseded_id,),
                )
                self._log_locked(
                    connection, "fact", superseded_id, "invalidated",
                    f"superseded by fact {fact.id} (same subject/predicate, new value)",
                )
            elif existing:
                # Identical fact already active: keep the original, report it.
                fact.id = existing["id"]
                return fact
            connection.execute(
                """INSERT INTO facts
                   (id, subject, predicate, value, confidence, source_run_id,
                    status, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fact.id, fact.subject.strip(), fact.predicate.strip(), fact.value,
                    fact.confidence, fact.source_run_id, fact.status,
                    fact.created_at, fact.expires_at,
                ),
            )
        fact.superseded_id = superseded_id  # type: ignore[attr-defined]
        return fact

    def get_facts(
        self, subject: str | None = None, *, status: str = "active"
    ) -> list[Fact]:
        self.initialize()
        with self._connection() as connection:
            if subject:
                rows = connection.execute(
                    "SELECT * FROM facts WHERE subject = ? AND status = ? ORDER BY created_at DESC",
                    (subject, status),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM facts WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
        return [Fact(**{key: row[key] for key in row.keys()}) for row in rows]

    def set_fact_status(self, fact_id: str, status: str, *, reason: str = "") -> bool:
        if status not in STATUSES:
            raise ValueError(f"Unknown status: {status!r}")
        self.initialize()
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "UPDATE facts SET status = ? WHERE id = ?", (status, fact_id)
            )
            if cursor.rowcount and status != "active":
                self._log_locked(
                    connection, "fact", fact_id, status,
                    reason or f"status changed to {status}",
                )
        return cursor.rowcount > 0

    # -- pruning log ----------------------------------------------------------
    def _log_locked(
        self, connection: sqlite3.Connection, item_type: str, item_id: str,
        decision: str, reason: str,
    ) -> None:
        connection.execute(
            """INSERT INTO pruning_log (id, item_type, item_id, decision, reason, decided_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (_new_id(), item_type, item_id, decision, reason, _now()),
        )

    def log_decision(self, decision: PruningDecision) -> None:
        self.initialize()
        with self._lock, self._connection() as connection:
            self._log_locked(
                connection, decision.item_type, decision.item_id,
                decision.decision, decision.reason,
            )

    def pruning_log(self) -> list[PruningDecision]:
        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM pruning_log ORDER BY decided_at DESC"
            ).fetchall()
        return [
            PruningDecision(
                item_type=row["item_type"], item_id=row["item_id"],
                decision=row["decision"], reason=row["reason"],
                decided_at=row["decided_at"],
            )
            for row in rows
        ]


def connect_sqlite(db_path: Path | str) -> Callable[[], sqlite3.Connection]:
    """Build a ``connect_db`` callable for a SQLite file (row-dict access)."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(str(path), timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    return connect
