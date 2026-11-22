"""Prompt-free request telemetry for the Smart Router: SQLite storage and the summaries
shown by the desktop app. Stores routing decisions and timings, never prompts or replies."""

import json
from contextlib import closing
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from pockpock_paths import app_data_dir


OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DATA_DIR = app_data_dir("LocalAIObservability")
DB_PATH = Path(os.environ.get("LOCAL_AI_DASHBOARD_DB", DATA_DIR / "traces.sqlite3"))
DB_LOCK = threading.Lock()


_SCHEMA_READY = False


def _open():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def connect_db():
    """Open the database, creating its tables the first time in this process.

    The gateway also initializes the schema at startup; doing it here as well means code that
    runs outside that startup (tests, scripts, a fresh install's first request) never meets a
    missing table.
    """
    if not _SCHEMA_READY:
        initialize_db()
    return _open()


def initialize_db():
    global _SCHEMA_READY
    # closing(): sqlite3 connections used as context managers commit but stay open, which keeps
    # the file locked on Windows.
    with closing(_open()) as connection, connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                request_id TEXT NOT NULL DEFAULT '',
                call_id TEXT NOT NULL DEFAULT '',
                event TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                automatic_model TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                confidence REAL,
                complexity INTEGER,
                duration_ms INTEGER,
                prompt_chars INTEGER
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )"""
        )
    _SCHEMA_READY = True


def ollama_json(path):
    with urlopen(f"{OLLAMA_URL}{path}", timeout=0.4) as response:
        return json.loads(response.read().decode("utf-8"))


def installed_models():
    try:
        result = ollama_json("/api/tags")
        return result.get("models", [])
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None


def is_embedding_model(item):
    """An embedding-only model (nomic-embed-text, bge, ...): it answers no chat request.

    Ollama lists them with the chat models; /api/tags reports a BERT-family architecture for them.
    """
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    families = [str(name).lower() for name in (details.get("families") or [details.get("family") or ""])]
    return "embed" in str(item.get("name") or "").lower() or any("bert" in name for name in families)


SUPPORTED_EVENTS = frozenset({
    "request_received",
    "route_decision",
    "model_call_started",
    "model_call_completed",
    "model_management",
    "router_state",
    "agent_task_started",
    "agent_task_completed",
    "agent_tool_started",
    "agent_tool_completed",
    # Agent diagnostics recorded by the executor (issue #50). save_event stores only fixed columns,
    # so these keep the same prompt-free footprint.
    "build_review",
    "context_compaction",
    "skill_retrieval",
    "tool_retrieval",
    "tool_search_hydration",
})


def save_event(data):
    event_type = data.get("event")
    if event_type not in SUPPORTED_EVENTS:
        raise ValueError("Unsupported event type")

    def text(key, limit=240):
        value = data.get(key, "")
        return value[:limit] if isinstance(value, str) else ""

    def number(key, maximum=2**31 - 1):
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0, min(int(value), maximum))
        return None

    if event_type == "context_compaction" and not data.get("reason"):
        # The table has no columns for these, and without them a compaction row says nothing about what was
        # done (R&D validation 2026-11-21). The stage goes in status, the numbers in reason.
        data = {
            **data,
            "status": data.get("stage") if isinstance(data.get("stage"), str) else "",
            "reason": (
                f"{data.get('tokens_before')} -> {data.get('tokens_after')} estimated tokens "
                f"(threshold {data.get('threshold_tokens')}); pruned {data.get('pruned')}, "
                f"summarised {data.get('summarised')}"
            ),
        }

    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        confidence = None
    else:
        confidence = max(0.0, min(float(confidence), 1.0))

    values = (
        datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        text("request_id", 64),
        text("call_id", 64),
        event_type,
        text("model", 120),
        text("automatic_model", 120),
        text("role", 32),
        text("status", 16),
        text("category", 32),
        text("source", 32),
        text("reason"),
        text("error"),
        confidence,
        number("complexity", 10),
        number("duration_ms"),
        number("prompt_chars"),
    )
    with DB_LOCK, closing(connect_db()) as connection, connection:
        connection.execute(
            """INSERT INTO events (
                created_at, request_id, call_id, event, model, automatic_model,
                role, status, category, source, reason, error, confidence,
                complexity, duration_ms, prompt_chars
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )


def current_override():
    with closing(connect_db()) as connection, connection:
        row = connection.execute(
            "SELECT value FROM settings WHERE key = 'model_override'"
        ).fetchone()
    return row["value"] if row else ""


def dashboard_state(models_override=None, running_override=None):
    models = installed_models() if models_override is None else models_override
    running_models = set()
    ollama_error = ""
    if models is None:
        ollama_error = "Ollama is not responding"
        models = []
    elif running_override is not None:
        running_models = {
            item.get("name", "") for item in running_override
        }
    else:
        try:
            running = ollama_json("/api/ps")
            running_models = {
                item.get("name", "") for item in running.get("models", [])
            }
        except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
            ollama_error = "Ollama is responding, but runtime status is unavailable"

    with closing(connect_db()) as connection, connection:
        aggregates = {
            row["model"]: dict(row)
            for row in connection.execute(
                """SELECT model,
                    SUM(CASE WHEN event = 'route_decision' THEN 1 ELSE 0 END) AS decisions,
                    SUM(CASE WHEN event = 'model_call_started' THEN 1 ELSE 0 END) AS calls,
                    SUM(CASE WHEN event = 'model_call_completed' AND status = 'success'
                        THEN 1 ELSE 0 END) AS successes,
                    AVG(CASE WHEN event = 'model_call_completed' AND duration_ms IS NOT NULL
                        THEN duration_ms END) AS avg_ms
                FROM events WHERE model != '' GROUP BY model"""
            )
        }
        events = [
            dict(row)
            for row in connection.execute(
                """SELECT id, created_at, request_id, call_id, event, model,
                    automatic_model, role, status, category, source, reason, error,
                    confidence, complexity, duration_ms, prompt_chars
                FROM events ORDER BY id DESC LIMIT 60"""
            )
        ]
        active = [
            dict(row)
            for row in connection.execute(
                """SELECT started.call_id, started.request_id, started.model, started.role,
                    started.created_at
                FROM events AS started
                WHERE started.event = 'model_call_started'
                    AND started.id > (SELECT COALESCE(MAX(id), 0) - 2000 FROM events)
                    AND NOT EXISTS (
                        SELECT 1 FROM events AS finished
                        WHERE finished.event = 'model_call_completed'
                            AND finished.call_id = started.call_id
                    )
                ORDER BY started.id DESC LIMIT 20"""
            )
        ]
        totals = connection.execute(
            """SELECT
                SUM(CASE WHEN event = 'request_received' THEN 1 ELSE 0 END) AS requests,
                SUM(CASE WHEN event = 'model_call_started' THEN 1 ELSE 0 END) AS calls,
                AVG(CASE WHEN event = 'model_call_completed' AND duration_ms IS NOT NULL
                    THEN duration_ms END) AS avg_ms
            FROM events"""
        ).fetchone()

    inventory = []
    installed_names = set()
    for model in models:
        name = model.get("name", "")
        installed_names.add(name)
        counts = aggregates.get(name, {})
        inventory.append({
            "name": name,
            "size": model.get("size", 0),
            "modified_at": model.get("modified_at", ""),
            "installed": True,
            "running": name in running_models,
            "embedding": is_embedding_model(model),
            "decisions": counts.get("decisions") or 0,
            "calls": counts.get("calls") or 0,
            "successes": counts.get("successes") or 0,
            "avg_ms": round(counts["avg_ms"]) if counts.get("avg_ms") is not None else None,
        })
    for name in sorted(set(aggregates) - installed_names):
        counts = aggregates[name]
        inventory.append({
            "name": name,
            "size": 0,
            "modified_at": "",
            "installed": False,
            "running": False,
            "decisions": counts.get("decisions") or 0,
            "calls": counts.get("calls") or 0,
            "successes": counts.get("successes") or 0,
            "avg_ms": round(counts["avg_ms"]) if counts.get("avg_ms") is not None else None,
        })

    return {
        "connected": not bool(ollama_error),
        "ollama_error": ollama_error,
        "models": inventory,
        "events": events,
        "active": active,
        "override": current_override(),
        "totals": {
            "requests": totals["requests"] or 0,
            "calls": totals["calls"] or 0,
            "avg_ms": round(totals["avg_ms"]) if totals["avg_ms"] is not None else None,
        },
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
