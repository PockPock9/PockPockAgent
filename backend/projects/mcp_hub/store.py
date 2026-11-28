"""The hub's saved servers: ``<PockPock data>/mcp-hub/servers.json``.

One entry per server: how to start it (``stdio``: command, arguments, environment) or reach it
(``streamable-http``: address, headers), whether it is switched on, and where it came from.
Environment values and headers are sealed with ``protect.seal`` before they are written; nothing
else in the file is secret. The file also holds the hub's client token, which clients (OpenClaw,
later PockPock Agent) send to reach ``/mcp/<name>``. It is a local token, not a
third-party key.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import protect

SERVER_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")
HEADER_KEY = re.compile(r"^[A-Za-z0-9-]{1,100}$")
TRANSPORTS = ("stdio", "streamable-http")
MAX_ARGS = 40
MAX_ARG_CHARS = 500
MAX_SECRET_CHARS = 4000
MAX_SERVERS = 100


class StoreError(ValueError):
    """A server definition is not valid; the message is safe to show."""


@dataclass(frozen=True)
class ServerSpec:
    name: str
    transport: str
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict, repr=False)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict, repr=False)
    enabled: bool = True
    source: str = ""

    def target(self) -> str:
        """What the server runs or where it is, without secrets: shown in the app and used for tool retrieval."""
        return self.url if self.transport != "stdio" else " ".join([self.command, *self.args]).strip()

    def same_launch(self, other: "ServerSpec") -> bool:
        return (self.transport, self.command, self.args, self.env, self.url, self.headers) == (other.transport, other.command, other.args, other.env, other.url, other.headers)


def spec_from(name: str, data: dict[str, Any]) -> ServerSpec:
    """Validates a definition sent by the gateway. Raises ``StoreError``."""
    if not SERVER_NAME.fullmatch(name or ""):
        raise StoreError("The server name is not valid (lower-case letters, digits and dashes, up to 40).")
    transport = str(data.get("transport") or "stdio")
    if transport not in TRANSPORTS:
        raise StoreError("Only stdio and streamable-http servers can run in Local MCP.")
    source = str(data.get("source") or "")[:500]
    enabled = data.get("enabled") is not False
    if transport == "stdio":
        command = str(data.get("command") or "")
        if not command or len(command) > 200 or any(char in command for char in "\x00\r\n"):
            raise StoreError("The command is not valid.")
        args = data.get("args") or []
        if not isinstance(args, list) or len(args) > MAX_ARGS or any(not isinstance(arg, str) or not arg or len(arg) > MAX_ARG_CHARS or "\x00" in arg for arg in args):
            raise StoreError("The arguments are not valid.")
        env = data.get("env") or {}
        if not isinstance(env, dict) or any(not ENV_KEY.fullmatch(str(key)) or not isinstance(value, str) or len(value) > MAX_SECRET_CHARS or "\x00" in value for key, value in env.items()):
            raise StoreError("The environment settings are not valid.")
        return ServerSpec(name=name, transport=transport, command=command, args=tuple(args), env=dict(env), enabled=enabled, source=source)
    url = str(data.get("url") or "")
    if not re.fullmatch(r"https?://[^\s]{1,1000}", url):
        raise StoreError("The server address is not valid.")
    headers = data.get("headers") or {}
    if not isinstance(headers, dict) or any(not HEADER_KEY.fullmatch(str(key)) or not isinstance(value, str) or len(value) > MAX_SECRET_CHARS or any(ord(char) < 32 for char in value) for key, value in headers.items()):
        raise StoreError("The headers are not valid.")
    return ServerSpec(name=name, transport=transport, url=url, headers=dict(headers), enabled=enabled, source=source)


def default_dir() -> Path:
    override = os.environ.get("POCKPOCK_MCP_HUB_DIR")
    if override:
        return Path(override)
    from pockpock_paths import app_data_dir  # backend/scripts, on sys.path in app.py

    return app_data_dir("PockPock") / "mcp-hub"


class ServerStore:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or default_dir()
        self.file = self.directory / "servers.json"
        self._lock = threading.Lock()
        # Secrets that could not be read (a file copied from another PC): the server is listed but not started.
        self.unreadable: set[str] = set()

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temp = self.file.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, self.file)

    def token(self) -> str:
        with self._lock:
            data = self._read()
            token = data.get("token")
            if isinstance(token, str) and len(token) >= 32:
                return token
            data["token"] = secrets.token_urlsafe(32)
            self._write(data)
            return data["token"]

    def load(self) -> dict[str, ServerSpec]:
        with self._lock:
            servers = self._read().get("servers") or {}
        result: dict[str, ServerSpec] = {}
        self.unreadable = set()
        for name, entry in servers.items() if isinstance(servers, dict) else ():
            if not isinstance(entry, dict):
                continue
            try:
                env = {key: protect.unseal(value) for key, value in (entry.get("env") or {}).items()}
                headers = {key: protect.unseal(value) for key, value in (entry.get("headers") or {}).items()}
            except (ValueError, TypeError):
                self.unreadable.add(name)
                env, headers = {}, {}
            try:
                result[name] = spec_from(name, {**entry, "env": env, "headers": headers})
            except StoreError:
                continue
        return result

    def save(self, spec: ServerSpec) -> None:
        with self._lock:
            data = self._read()
            servers = data.setdefault("servers", {})
            if spec.name not in servers and len(servers) >= MAX_SERVERS:
                raise StoreError(f"Local MCP holds at most {MAX_SERVERS} servers.")
            entry: dict[str, Any] = {"transport": spec.transport, "enabled": spec.enabled, "source": spec.source, "updated_at": int(time.time())}
            if spec.transport == "stdio":
                entry.update(command=spec.command, args=list(spec.args), env={key: protect.seal(value) for key, value in spec.env.items()})
            else:
                entry.update(url=spec.url, headers={key: protect.seal(value) for key, value in spec.headers.items()})
            servers[spec.name] = entry
            self._write(data)
        self.unreadable.discard(spec.name)

    def remove(self, name: str) -> bool:
        with self._lock:
            data = self._read()
            removed = (data.get("servers") or {}).pop(name, None) is not None
            if removed:
                self._write(data)
        self.unreadable.discard(name)
        return removed
