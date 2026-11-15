"""Local-only telemetry sidecar for the Smart Router."""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from pockpock_paths import app_data_dir


HOST = "127.0.0.1"
PORT = int(os.environ.get("LOCAL_AI_DASHBOARD_PORT", "8765"))
OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DATA_DIR = app_data_dir("LocalAIObservability")
DB_PATH = Path(os.environ.get("LOCAL_AI_DASHBOARD_DB", DATA_DIR / "traces.sqlite3"))
PAGE_PATH = Path(__file__).with_name("observability_dashboard.html")
DB_LOCK = threading.Lock()


def connect_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_db():
    with connect_db() as connection:
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


def ollama_json(path):
    with urlopen(f"{OLLAMA_URL}{path}", timeout=0.4) as response:
        return json.loads(response.read().decode("utf-8"))


def installed_models():
    try:
        result = ollama_json("/api/tags")
        return result.get("models", [])
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None


def save_event(data):
    event_type = data.get("event")
    if event_type not in {
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
    }:
        raise ValueError("Unsupported event type")

    def text(key, limit=240):
        value = data.get(key, "")
        return value[:limit] if isinstance(value, str) else ""

    def number(key, maximum=2**31 - 1):
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0, min(int(value), maximum))
        return None

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
    with DB_LOCK, connect_db() as connection:
        connection.execute(
            """INSERT INTO events (
                created_at, request_id, call_id, event, model, automatic_model,
                role, status, category, source, reason, error, confidence,
                complexity, duration_ms, prompt_chars
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )


def current_override():
    with connect_db() as connection:
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

    with connect_db() as connection:
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


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "LocalAIRouterDashboard/1.0"

    def log_message(self, fmt, *args):
        print(f"[dashboard] {self.address_string()} {fmt % args}")

    def send_json(self, status, value):
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self, max_bytes=16384):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > max_bytes:
            raise ValueError("Invalid request body size")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        if self.path == "/":
            try:
                body = PAGE_PATH.read_bytes()
            except OSError as err:
                self.send_json(500, {"error": f"Dashboard UI unavailable: {err}"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            self.send_json(200, dashboard_state())
        elif self.path == "/api/override":
            self.send_json(200, {"model": current_override()})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        try:
            data = self.read_json()
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            if self.path == "/api/events":
                save_event(data)
                self.send_json(202, {"ok": True})
            elif self.path == "/api/override":
                model = data.get("model", "")
                if not isinstance(model, str) or len(model) > 120:
                    raise ValueError("Invalid model name")
                if model:
                    models = installed_models()
                    if models is None:
                        self.send_json(503, {"error": "Ollama is not responding"})
                        return
                    if model not in {item.get("name") for item in models}:
                        self.send_json(400, {"error": "Choose an installed Ollama model"})
                        return
                with DB_LOCK, connect_db() as connection:
                    if model:
                        connection.execute(
                            """INSERT INTO settings (key, value) VALUES ('model_override', ?)
                            ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                            (model,),
                        )
                    else:
                        connection.execute(
                            "DELETE FROM settings WHERE key = 'model_override'"
                        )
                save_event({
                    "event": "route_decision",
                    "model": model,
                    "source": "override_changed",
                    "reason": "Manual model override enabled" if model else "Automatic routing restored",
                })
                self.send_json(200, {"model": model})
            else:
                self.send_json(404, {"error": "Not found"})
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as err:
            self.send_json(400, {"error": str(err)})
        except (OSError, sqlite3.Error) as err:
            self.send_json(500, {"error": f"Local storage error: {err}"})


def main():
    initialize_db()
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    print(f"Local AI observability dashboard: http://{HOST}:{PORT}")
    print(f"Trace database: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
