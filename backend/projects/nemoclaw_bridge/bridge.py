"""Run single NemoClaw (OpenClaw) agent turns in a WSL sandbox from the Windows gateway.

The gateway runs on Windows; NemoClaw runs inside a WSL distribution. Each turn is one
``nemoclaw <sandbox> agent --json`` invocation through ``wsl.exe --exec``. User text never
becomes shell text: the bash script is a fixed constant and every variable value travels in an
environment variable forwarded with ``WSLENV``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
MAX_MESSAGE_CHARS = 16_000
DEFAULT_TIMEOUT_SECONDS = 300
STATUS_TTL_SECONDS = 20.0
STATUS_TIMEOUT_SECONDS = 45
MAX_OUTPUT_BYTES = 4 * 1024 * 1024

# Fixed script: values are read from NC_* environment variables, never interpolated by Python.
TURN_SCRIPT = (
    'export PATH="$HOME/.local/bin:$PATH"; '
    'exec nemoclaw "$NC_SANDBOX" agent --agent "$NC_AGENT" --session-id "$NC_SESSION" '
    '--timeout "$NC_TIMEOUT" --json -m "$NC_MESSAGE"'
)
STATUS_SCRIPT = 'export PATH="$HOME/.local/bin:$PATH"; exec nemoclaw "$NC_SANDBOX" status'


class NemoClawError(Exception):
    """A turn or status check failed in a way the user can act on."""

    def __init__(self, code: str, message: str, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class NemoClawConfig:
    distro: str = ""
    sandbox: str = "pockpock"
    agent: str = "main"
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    enabled: bool = True

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "NemoClawConfig":
        env = os.environ if environ is None else environ
        distro = env.get("POCKPOCK_NEMOCLAW_DISTRO", "").strip()
        sandbox = env.get("POCKPOCK_NEMOCLAW_SANDBOX", "pockpock").strip() or "pockpock"
        agent = env.get("POCKPOCK_NEMOCLAW_AGENT", "main").strip() or "main"
        for label, value in (("POCKPOCK_NEMOCLAW_SANDBOX", sandbox), ("POCKPOCK_NEMOCLAW_AGENT", agent)):
            if not TOKEN.fullmatch(value):
                raise ValueError(f"{label} must be a simple name")
        if distro and not TOKEN.fullmatch(distro):
            raise ValueError("POCKPOCK_NEMOCLAW_DISTRO must be a simple WSL distribution name")
        try:
            timeout = int(env.get("POCKPOCK_NEMOCLAW_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
        except ValueError as err:
            raise ValueError("POCKPOCK_NEMOCLAW_TIMEOUT_SECONDS must be an integer") from err
        timeout = max(30, min(timeout, 900))
        enabled = env.get("POCKPOCK_NEMOCLAW_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
        return cls(distro=distro, sandbox=sandbox, agent=agent, timeout_seconds=timeout, enabled=enabled)


@dataclass(frozen=True)
class TurnResult:
    text: str
    model: str
    status: str
    duration_ms: int
    truncated: bool = False


def validate_session_id(value: str) -> str:
    session = value.strip()
    if not SESSION_ID.fullmatch(session):
        raise NemoClawError("invalid_session", "Invalid NemoClaw session id.", 422)
    return session


def validate_message(value: str) -> str:
    message = value.strip()
    if not message:
        raise NemoClawError("empty_message", "Type a message for the NemoClaw agent.", 422)
    if len(message) > MAX_MESSAGE_CHARS:
        raise NemoClawError(
            "message_too_long",
            f"NemoClaw messages are limited to {MAX_MESSAGE_CHARS:,} characters.",
            413,
        )
    if "\x00" in message:
        raise NemoClawError("invalid_message", "The message contains an unsupported character.", 422)
    return message


def build_command(config: NemoClawConfig, script: str) -> list[str]:
    command = ["wsl.exe"]
    if config.distro:
        command += ["-d", config.distro]
    return command + ["--exec", "/bin/bash", "-c", script]


def build_environment(values: dict[str, str], base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    forwarded = [item for item in env.get("WSLENV", "").split(":") if item]
    for key, value in values.items():
        env[key] = value
        forwarded = [item for item in forwarded if item.split("/", 1)[0] != key]
        forwarded.append(f"{key}/u")
    env["WSLENV"] = ":".join(forwarded)
    return env


def parse_turn_output(stdout: str, duration_ms: int) -> TurnResult:
    """Parse ``nemoclaw <sandbox> agent --json`` output into reply text."""
    start = stdout.find("{")
    if start < 0:
        raise NemoClawError("bad_output", "NemoClaw returned no JSON result.")
    try:
        data, _ = json.JSONDecoder().raw_decode(stdout[start:])
    except json.JSONDecodeError as err:
        raise NemoClawError("bad_output", "NemoClaw returned an unreadable result.") from err
    if not isinstance(data, dict):
        raise NemoClawError("bad_output", "NemoClaw returned an unexpected result.")
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    payloads = result.get("payloads") if isinstance(result.get("payloads"), list) else []
    text = "\n\n".join(
        str(item.get("text")).strip()
        for item in payloads
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item.get("text").strip()
    )
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    agent_meta = meta.get("agentMeta") if isinstance(meta.get("agentMeta"), dict) else {}
    model = str(agent_meta.get("model") or "")
    status = str(data.get("status") or "unknown")
    if status != "ok":
        raise NemoClawError("turn_failed", text or str(data.get("summary") or "The NemoClaw agent turn failed."))
    if not text:
        raise NemoClawError("empty_reply", "The NemoClaw agent finished without a reply.")
    truncated = "output token limit" in text.lower()
    reported = meta.get("durationMs")
    return TurnResult(
        text=text,
        model=model,
        status=status,
        duration_ms=int(reported) if isinstance(reported, (int, float)) else duration_ms,
        truncated=truncated,
    )


def parse_status_output(stdout: str) -> dict[str, Any]:
    """Extract the fields PockPock needs from ``nemoclaw <sandbox> status`` text."""
    plain = re.sub(r"\x1b\[[0-9;]*m", "", stdout)

    def field(name: str) -> str:
        match = re.search(rf"^\s*{re.escape(name)}:\s*(.+?)\s*$", plain, flags=re.MULTILINE)
        return match.group(1) if match else ""

    phase = field("Phase")
    inference = field("Inference")
    return {
        "phase": phase,
        "model": field("Model"),
        "provider": field("Provider"),
        "agent_version": field("Agent"),
        "inference_healthy": inference.lower().startswith("healthy"),
        "ready": phase.lower() == "ready" and inference.lower().startswith("healthy"),
    }


Runner = Callable[[list[str], dict[str, str], int], tuple[int, str, str]]


class NemoClawBridge:
    """Process-local bridge with a cached status check and one active turn at a time."""

    def __init__(self, config: NemoClawConfig, runner: Runner | None = None, clock: Callable[[], float] = time.monotonic):
        self.config = config
        self._runner = runner
        self._clock = clock
        self._status_cache: tuple[float, dict[str, Any]] | None = None
        self._status_lock = threading.Lock()
        self._turn_lock = threading.Lock()
        self._active: subprocess.Popen[bytes] | None = None

    def _run(self, command: list[str], env: dict[str, str], timeout: int) -> tuple[int, str, str]:
        if self._runner is not None:
            return self._runner(command, env, timeout)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
        self._active = process
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as err:
            process.kill()
            process.communicate()
            raise NemoClawError("timeout", "The NemoClaw agent did not answer in time.", 504) from err
        finally:
            self._active = None
        return process.returncode, stdout[:MAX_OUTPUT_BYTES].decode("utf-8", "replace"), stderr[:MAX_OUTPUT_BYTES].decode("utf-8", "replace")

    def cancel_active(self) -> None:
        process = self._active
        if process is not None and process.poll() is None:
            process.kill()

    def available(self) -> bool:
        return self.config.enabled and (self._runner is not None or shutil.which("wsl.exe") is not None)

    def status(self, force: bool = False, probe: bool = True) -> dict[str, Any]:
        """Report sandbox health.

        ``nemoclaw status`` tests inference, which loads the model into memory. With
        ``probe=False`` only a recent cached result is returned, so merely opening the page
        does not load a model; the sandbox is checked when NemoClaw is actually selected.
        """
        base = {"enabled": self.config.enabled, "sandbox": self.config.sandbox, "distro": self.config.distro or "default"}
        if not self.config.enabled:
            return {**base, "available": False, "ready": False, "detail": "NemoClaw integration is turned off."}
        if not self.available():
            return {**base, "available": False, "ready": False, "detail": "WSL is not installed on this PC."}
        with self._status_lock:
            now = self._clock()
            if not force and self._status_cache and now - self._status_cache[0] < STATUS_TTL_SECONDS:
                return self._status_cache[1]
            if not probe:
                return {**base, "available": True, "ready": False, "checked": False, "detail": "Not checked yet. Select NemoClaw to check the sandbox."}
            env = build_environment({"NC_SANDBOX": self.config.sandbox})
            try:
                code, stdout, _ = self._run(build_command(self.config, STATUS_SCRIPT), env, STATUS_TIMEOUT_SECONDS)
            except NemoClawError:
                code, stdout = -1, ""
            except OSError:
                code, stdout = -1, ""
            parsed = parse_status_output(stdout) if stdout else {"ready": False}
            if parsed.get("ready"):
                detail = "Ready"
            elif code == -1:
                detail = "NemoClaw did not respond. Start Docker Desktop and check WSL."
            elif parsed.get("phase"):
                detail = f"Sandbox is {parsed['phase']}; inference {'healthy' if parsed.get('inference_healthy') else 'unavailable'}."
            else:
                detail = f"Sandbox '{self.config.sandbox}' was not found. Run NemoClaw onboarding in WSL."
            result = {**base, "available": True, "checked": True, **parsed, "detail": detail}
            self._status_cache = (now, result)
            return result

    def run_turn(self, session_id: str, message: str) -> TurnResult:
        if not self.available():
            raise NemoClawError("unavailable", "NemoClaw is not available on this PC.", 503)
        session = validate_session_id(session_id)
        text = validate_message(message)
        if not self._turn_lock.acquire(blocking=False):
            raise NemoClawError("busy", "The NemoClaw agent is already working on another message.", 409)
        try:
            env = build_environment({
                "NC_SANDBOX": self.config.sandbox,
                "NC_AGENT": self.config.agent,
                "NC_SESSION": session,
                "NC_TIMEOUT": str(self.config.timeout_seconds),
                "NC_MESSAGE": text,
            })
            started = self._clock()
            try:
                code, stdout, _stderr = self._run(
                    build_command(self.config, TURN_SCRIPT),
                    env,
                    self.config.timeout_seconds + 45,
                )
            except OSError as err:
                raise NemoClawError("unavailable", "Could not start WSL to reach NemoClaw.", 503) from err
            duration_ms = round((self._clock() - started) * 1000)
            if code != 0 and "{" not in stdout:
                self._status_cache = None
                raise NemoClawError(
                    "turn_failed",
                    "The NemoClaw agent did not answer. Check `nemoclaw "
                    f"{self.config.sandbox} status` in WSL and make sure Docker Desktop is running.",
                )
            return parse_turn_output(stdout, duration_ms)
        finally:
            self._turn_lock.release()
