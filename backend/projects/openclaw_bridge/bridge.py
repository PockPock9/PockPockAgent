"""Run OpenClaw agent turns on this PC through the local OpenClaw gateway.

OpenClaw runs natively on Windows with no sandbox. Each turn is one ``gateway_turn.mjs``
helper process that speaks the gateway WebSocket protocol: it streams the reply, reports tool
activity, and relays approval requests. The user's message travels to the helper on stdin, never
on a command line.

Permissions are enforced inside OpenClaw by the ``pockpock-permissions`` plugin. Before each turn
this module records the mode PockPock selected for the session in a small state file the plugin
reads. A session with no record is treated as ``ask``.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

SESSION_PREFIX = "pockpock-"
SESSION_ID = re.compile(r"^pockpock-[A-Za-z0-9][A-Za-z0-9_-]{0,69}$")
AGENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
APPROVAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")
PERMISSION_MODES = ("ask", "auto", "full")
APPROVAL_DECISIONS = ("allow-once", "allow-task", "deny")
MAX_MESSAGE_CHARS = 16_000
DEFAULT_TIMEOUT_SECONDS = 1800  # long enough for a large, partly CPU-run model
STATUS_TTL_SECONDS = 15.0
STATUS_TIMEOUT_SECONDS = 30
MAX_EVENT_BYTES = 1024 * 1024
MAX_TRACKED_SESSIONS = 300
ABORT_GRACE_SECONDS = 8
HELPER_PATH = Path(__file__).with_name("gateway_turn.mjs")
TERMINAL_EVENTS = frozenset({"final", "error", "status_result"})


class OpenClawError(Exception):
    """A turn or status check failed in a way the user can act on."""

    def __init__(self, code: str, message: str, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class OpenClawConfig:
    agent: str = "main"
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    node: str = "node"
    enabled: bool = True

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "OpenClawConfig":
        env = os.environ if environ is None else environ
        agent = env.get("POCKPOCK_OPENCLAW_AGENT", "main").strip() or "main"
        if not AGENT_ID.fullmatch(agent):
            raise ValueError("POCKPOCK_OPENCLAW_AGENT must be a simple name")
        try:
            timeout = int(env.get("POCKPOCK_OPENCLAW_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
        except ValueError as err:
            raise ValueError("POCKPOCK_OPENCLAW_TIMEOUT_SECONDS must be an integer") from err
        timeout = max(30, min(timeout, 3600))
        node = env.get("POCKPOCK_OPENCLAW_NODE", "node").strip() or "node"
        enabled = env.get("POCKPOCK_OPENCLAW_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
        return cls(agent=agent, timeout_seconds=timeout, node=node, enabled=enabled)


def validate_session_id(session_id: str) -> str:
    """Only PockPock-prefixed sessions are accepted so the permission plugin always applies."""
    value = (session_id or "").strip()
    if not SESSION_ID.fullmatch(value):
        raise OpenClawError("invalid_session", "The conversation id is not valid for OpenClaw.", 400)
    return value


def validate_message(message: str) -> str:
    value = (message or "").strip()
    if not value:
        raise OpenClawError("empty_message", "Enter a message for OpenClaw.", 400)
    if len(value) > MAX_MESSAGE_CHARS:
        raise OpenClawError(
            "message_too_long",
            f"OpenClaw messages are limited to {MAX_MESSAGE_CHARS:,} characters including attached documents.",
            413,
        )
    if "\x00" in value:
        raise OpenClawError("invalid_message", "The message contains an unsupported character.", 400)
    return value


def validate_mode(mode: str) -> str:
    value = (mode or "").strip().lower()
    if value not in PERMISSION_MODES:
        raise OpenClawError("invalid_mode", "Choose Ask first, Auto-approve safe, or Full access.", 400)
    return value


def validate_model(model: str | None) -> str:
    """An empty value means OpenClaw's default model. The helper checks the name against OpenClaw's list."""
    value = (model or "").strip()
    if value and not MODEL_ID.fullmatch(value):
        raise OpenClawError("invalid_model", "That model name is not valid.", 400)
    return value


def session_key(agent: str, session_id: str) -> str:
    return f"agent:{agent}:explicit:{session_id}"


def openclaw_state_dir(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    configured = env.get("OPENCLAW_STATE_DIR", "").strip()
    return Path(configured) if configured else Path.home() / ".openclaw"


class PermissionState:
    """The per-session permission modes the OpenClaw plugin reads on every tool call."""

    def __init__(self, path: Path | None = None):
        self.path = path or openclaw_state_dir() / "pockpock" / "permissions.json"
        self._lock = threading.Lock()

    def read(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        sessions = data.get("sessions") if isinstance(data, dict) else None
        if not isinstance(sessions, dict):
            return {}
        return {str(key): str(value) for key, value in sessions.items() if value in PERMISSION_MODES}

    def set(self, key: str, mode: str) -> None:
        """Record ``mode`` for ``key``. Raises ``OSError`` when the file cannot be written."""
        with self._lock:
            sessions = self.read()
            sessions.pop(key, None)
            sessions[key] = mode
            while len(sessions) > MAX_TRACKED_SESSIONS:
                sessions.pop(next(iter(sessions)))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
            temporary.write_text(json.dumps({"version": 1, "sessions": sessions}, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)


def _spawn_helper(command: list[str]) -> subprocess.Popen:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


class OpenClawTurn:
    """One running helper process. Events are read on a background thread."""

    def __init__(self, process: Any, on_close: Callable[[], None]):
        self._process = process
        self._on_close = on_close
        self._events: "queue.Queue[dict[str, Any] | None]" = queue.Queue()
        self._write_lock = threading.Lock()
        self._pending: set[str] = set()
        self._pending_lock = threading.Lock()
        self._closed = False
        self._close_lock = threading.Lock()
        self._reader = threading.Thread(target=self._read, name="openclaw-turn", daemon=True)

    def start(self, request: dict[str, Any]) -> None:
        self._send(request)
        self._reader.start()

    def _send(self, payload: dict[str, Any]) -> bool:
        line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            try:
                self._process.stdin.write(line)
                self._process.stdin.flush()
                return True
            except (OSError, ValueError):
                return False

    def _read(self) -> None:
        terminal = False
        try:
            for raw in self._process.stdout:
                if len(raw) > MAX_EVENT_BYTES:
                    continue
                try:
                    event = json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                    continue
                kind = event["type"]
                if kind == "approval" and isinstance(event.get("id"), str):
                    with self._pending_lock:
                        self._pending.add(event["id"])
                elif kind == "approval_resolved":
                    with self._pending_lock:
                        self._pending.discard(str(event.get("id")))
                self._events.put(event)
                if kind in TERMINAL_EVENTS:
                    terminal = True
                    break
        except (OSError, ValueError):
            pass
        finally:
            if not terminal:
                self._events.put({
                    "type": "error",
                    "code": "bridge_failed",
                    "message": "The OpenClaw helper stopped before the turn finished. Check that Node.js and OpenClaw are installed.",
                })
            self._events.put(None)
            self.close()

    def next_event(self, timeout: float) -> dict[str, Any] | None | bool:
        """Return the next event, ``None`` when the turn is over, or ``False`` on timeout."""
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return False

    def pending_approvals(self) -> set[str]:
        with self._pending_lock:
            return set(self._pending)

    def resolve(self, approval_id: str, decision: str) -> bool:
        with self._pending_lock:
            if approval_id not in self._pending:
                return False
        return self._send({"type": "approval", "id": approval_id, "decision": decision})

    def abort(self) -> None:
        """Ask the helper to stop the agent run, then make sure the process ends."""
        self._send({"type": "abort"})
        try:
            self._process.wait(timeout=ABORT_GRACE_SECONDS)
        except Exception:
            pass
        self.close()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            if self._process.poll() is None:
                try:
                    self._process.wait(timeout=2)
                except Exception:
                    self._process.kill()
        except OSError:
            pass
        self._on_close()


class OpenClawBridge:
    """Configuration, status, and single-turn execution for the local OpenClaw gateway."""

    def __init__(
        self,
        config: OpenClawConfig | None = None,
        spawn: Callable[[list[str]], Any] | None = None,
        which: Callable[[str], str | None] = shutil.which,
        permissions: PermissionState | None = None,
        helper_path: Path = HELPER_PATH,
    ):
        self.config = config or OpenClawConfig()
        self._spawn = spawn or _spawn_helper
        self._which = which
        self.permissions = permissions or PermissionState()
        self._helper_path = helper_path
        self._turn_lock = threading.Lock()
        self._active: OpenClawTurn | None = None
        self._status_lock = threading.Lock()
        self._status_cache: tuple[float, dict[str, Any]] | None = None
        # Per-turn skill and MCP-server selection (tool_selection.py); set by the gateway.
        self.tool_selector: Any = None

    def select_tools(self, session_id: str, message: str) -> dict[str, Any] | None:
        """The tool overlay for one turn, or None when there is no selector or it failed."""
        if self.tool_selector is None:
            return None
        try:
            return self.tool_selector.select(validate_session_id(session_id), message)
        except Exception:  # noqa: BLE001 - a turn never fails because of tool selection
            return None

    def _command(self) -> list[str]:
        return [self._which(self.config.node) or self.config.node, str(self._helper_path)]

    def available(self) -> tuple[bool, str]:
        if not self.config.enabled:
            return False, "OpenClaw integration is turned off (POCKPOCK_OPENCLAW_ENABLED=0)."
        if not self._which(self.config.node):
            return False, "Node.js was not found. Install Node.js 24 or newer to use OpenClaw mode."
        if not self._helper_path.is_file():
            return False, "The OpenClaw helper script is missing from this PockPock installation."
        return True, ""

    def status(self, force: bool = False) -> dict[str, Any]:
        base = {"enabled": self.config.enabled, "agent": self.config.agent, "modes": list(PERMISSION_MODES)}
        ok, reason = self.available()
        if not ok:
            return {**base, "available": False, "ready": False, "plugin": False, "model": "", "models": [], "detail": reason}
        with self._status_lock:
            now = time.monotonic()
            if not force and self._status_cache and now - self._status_cache[0] < STATUS_TTL_SECONDS:
                return self._status_cache[1]
            result = {**base, "available": True, **self._probe()}
            self._status_cache = (now, result)
            return result

    def _probe(self) -> dict[str, Any]:
        offline = {"ready": False, "plugin": False, "model": "", "models": []}
        try:
            process = self._spawn(self._command())
        except OSError:
            return {**offline, "detail": "Node.js could not be started."}
        turn = OpenClawTurn(process, lambda: None)
        turn.start({"type": "start", "statusOnly": True})
        deadline = time.monotonic() + STATUS_TIMEOUT_SECONDS
        try:
            while time.monotonic() < deadline:
                event = turn.next_event(1.0)
                if event is False:
                    continue
                if event is None:
                    break
                if event.get("type") == "status_result":
                    plugin = event.get("plugin") is True
                    model = str(event.get("model") or "").removeprefix("ollama/").removeprefix("pockpock-cloud/")
                    detail = "Ready" if plugin else (
                        "OpenClaw is running, but the PockPock permission plugin is not loaded. Only Full access can run until it is installed."
                    )
                    listed = event.get("models")
                    models = [str(item) for item in listed if isinstance(item, str)][:60] if isinstance(listed, list) else []
                    return {"ready": True, "plugin": plugin, "model": model, "models": models, "detail": detail}
                if event.get("type") == "error":
                    return {**offline, "detail": str(event.get("message") or "The OpenClaw gateway is not reachable.")}
            return {**offline, "detail": "The OpenClaw gateway did not answer. Start it with: openclaw gateway start"}
        finally:
            turn.close()

    def start_turn(self, session_id: str, message: str, mode: str, model: str | None = None, selection: dict[str, Any] | None = None) -> OpenClawTurn:
        """Start one turn. Only one runs at a time; the caller must drain or abort it."""
        session = validate_session_id(session_id)
        text = validate_message(message)
        permission = validate_mode(mode)
        chosen_model = validate_model(model)
        ok, reason = self.available()
        if not ok:
            raise OpenClawError("unavailable", reason, 503)
        if not self._turn_lock.acquire(blocking=False):
            raise OpenClawError("busy", "OpenClaw is still working on another message. Wait for it to finish or stop it.", 409)
        release = self._release_once()
        try:
            try:
                self.permissions.set(session_key(self.config.agent, session), permission)
            except OSError as err:
                # Without the record the plugin falls back to "ask", which is safe but not what
                # the user selected, so stop instead of running under a different mode.
                raise OpenClawError("permission_state", "PockPock could not save the permission mode for OpenClaw, so the turn was not started.", 500) from err
            try:
                process = self._spawn(self._command())
            except OSError as err:
                raise OpenClawError("unavailable", "Node.js could not be started for the OpenClaw helper.", 503) from err
            turn = OpenClawTurn(process, release)
            self._active = turn
            turn.start({
                "type": "start",
                "sessionId": session,
                "message": text,
                "mode": permission,
                "model": chosen_model,
                "agent": self.config.agent,
                "timeoutSeconds": self.config.timeout_seconds,
                # The session's tool overlay; null clears one left by an earlier turn. Absent when no
                # selection ran, so OpenClaw's session is left as it is.
                **({"toolOverrides": selection.get("toolOverrides")} if selection is not None else {}),
            })
            return turn
        except BaseException:
            release()
            raise

    def _release_once(self) -> Callable[[], None]:
        """Return a callback that frees the turn slot exactly once, however often it is called."""
        guard = threading.Lock()
        released = False

        def release() -> None:
            nonlocal released
            with guard:
                if released:
                    return
                released = True
            self._active = None
            self._turn_lock.release()

        return release

    def resolve_approval(self, approval_id: str, decision: str) -> None:
        if decision not in APPROVAL_DECISIONS:
            raise OpenClawError("invalid_decision", "The decision must be allow-once, allow-task or deny.", 400)
        if not APPROVAL_ID.fullmatch(approval_id or ""):
            raise OpenClawError("invalid_approval", "The approval id is not valid.", 400)
        turn = self._active
        if turn is None or not turn.resolve(approval_id, decision):
            raise OpenClawError("approval_not_found", "That approval is no longer waiting. It may have timed out or the turn ended.", 404)

    def cancel_active(self) -> None:
        turn = self._active
        if turn is not None:
            turn.abort()
