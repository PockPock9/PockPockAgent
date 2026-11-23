"""The hub: the saved servers, their running state, and the MCP messages clients send them."""

from __future__ import annotations

import os
import threading
from typing import Any

from .store import ServerSpec, ServerStore, spec_from
from .upstream import Upstream, UpstreamError, make_upstream

# Protocol versions a client may ask for. The hub answers in the version the client asked for when it
# knows it; it does not change messages between versions, which differ only in fields it passes on.
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
CALL_TIMEOUT_SECONDS = 600
REQUEST_TIMEOUT_SECONDS = 60


class HubError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class Hub:
    def __init__(self, store: ServerStore | None = None, *, port: int | None = None):
        self.store = store or ServerStore()
        self.port = port or int(os.environ.get("POCKPOCK_MCP_HUB_PORT", "8776"))
        self._lock = threading.Lock()
        self._upstreams: dict[str, Upstream] = {}
        self._specs: dict[str, ServerSpec] = self.store.load()

    # ----- management (gateway) -----

    def token(self) -> str:
        return self.store.token()

    def client_entry(self, name: str) -> dict[str, Any]:
        """How a client on this PC reaches a server: an OpenClaw ``mcp.servers`` entry."""
        if name not in self._specs:
            raise HubError("not_found", "Local MCP has no server with that name.", 404)
        return {"url": f"http://127.0.0.1:{self.port}/mcp/{name}", "transport": "streamable-http", "headers": {"Authorization": f"Bearer {self.token()}"}}

    def describe(self, name: str) -> dict[str, Any]:
        spec = self._specs[name]
        upstream = self._upstreams.get(name)
        status = upstream.status() if upstream else {"state": "stopped", "detail": "", "tools": None, "started_at": None, "calls": 0, "failures": 0}
        if not spec.enabled:
            status = {**status, "state": "off"}
        if name in self.store.unreadable:
            status = {**status, "state": "error", "detail": "Its saved keys cannot be read on this PC. Connect it again."}
        return {
            "name": name, "transport": spec.transport, "target": spec.target(), "source": spec.source, "enabled": spec.enabled,
            "env_keys": sorted(spec.env), "has_headers": bool(spec.headers), **status,
        }

    def list(self) -> list[dict[str, Any]]:
        return [self.describe(name) for name in sorted(self._specs)]

    def put(self, name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Adds or replaces a server. A running server whose launch settings changed is restarted on next use."""
        try:
            spec = spec_from(name, data)
        except ValueError as err:
            raise HubError("invalid", str(err)) from err
        with self._lock:
            self.store.save(spec)
            previous = self._specs.get(name)
            self._specs[name] = spec
            upstream = self._upstreams.get(name)
            if upstream and (previous is None or not previous.same_launch(spec) or not spec.enabled):
                upstream.stop()
                del self._upstreams[name]
            elif upstream:
                upstream.spec = spec
        return self.describe(name)

    def remove(self, name: str) -> bool:
        with self._lock:
            upstream = self._upstreams.pop(name, None)
            self._specs.pop(name, None)
            removed = self.store.remove(name)
        if upstream:
            upstream.stop()
        return removed

    def set_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        spec = self._specs.get(name)
        if spec is None:
            raise HubError("not_found", "Local MCP has no server with that name.", 404)
        data = {"transport": spec.transport, "command": spec.command, "args": list(spec.args), "env": spec.env, "url": spec.url, "headers": spec.headers, "source": spec.source, "enabled": enabled}
        return self.put(name, data)

    def restart(self, name: str) -> dict[str, Any]:
        """Stops the server and starts it again now, so the page shows whether it starts."""
        upstream = self._upstream(name, start=False)
        upstream.stop()
        with self._lock:
            self._upstreams.pop(name, None)
        try:
            self._upstream(name).ensure_started()
        except UpstreamError:
            pass  # the state and detail say why
        return self.describe(name)

    def logs(self, name: str) -> list[str]:
        if name not in self._specs:
            raise HubError("not_found", "Local MCP has no server with that name.", 404)
        upstream = self._upstreams.get(name)
        return list(upstream.log) if upstream else []

    def stop_all(self) -> None:
        with self._lock:
            upstreams, self._upstreams = list(self._upstreams.values()), {}
        for upstream in upstreams:
            upstream.stop()

    # ----- MCP (clients) -----

    def _upstream(self, name: str, *, start: bool = True) -> Upstream:
        with self._lock:
            spec = self._specs.get(name)
            if spec is None:
                raise HubError("not_found", "Local MCP has no server with that name.", 404)
            if not spec.enabled and start:
                raise HubError("off", f"The MCP server {name} is switched off in PockPock.", 409)
            if name in self.store.unreadable and start:
                raise HubError("unreadable", f"The saved keys of {name} cannot be read on this PC. Connect it again in PockPock.", 409)
            upstream = self._upstreams.get(name)
            if upstream is None:
                upstream = self._upstreams[name] = make_upstream(spec)
            return upstream

    def handle(self, name: str, message: dict[str, Any]) -> dict[str, Any] | None:
        """One JSON-RPC message from a client. Returns the reply, or None for a notification."""
        method, request_id, params = message["method"], message.get("id"), message.get("params")
        if "id" not in message:
            return None  # initialized, cancelled, progress: nothing to pass on (the hub has its own ids)
        try:
            upstream = self._upstream(name)
            if method == "initialize":
                result = dict(upstream.ensure_started())
                wanted = str((params or {}).get("protocolVersion") or "") if isinstance(params, dict) else ""
                result["protocolVersion"] = wanted if wanted in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
                # The hub answers in single JSON replies and cannot send change notifications.
                capabilities = dict(result.get("capabilities") or {})
                for key in ("tools", "prompts", "resources"):
                    if isinstance(capabilities.get(key), dict):
                        capabilities[key] = {**capabilities[key], "listChanged": False, **({"subscribe": False} if key == "resources" else {})}
                result["capabilities"] = capabilities
                return {"jsonrpc": "2.0", "id": request_id, "result": result}
            if method == "ping":
                return {"jsonrpc": "2.0", "id": request_id, "result": {}}
            timeout = CALL_TIMEOUT_SECONDS if method == "tools/call" else REQUEST_TIMEOUT_SECONDS
            return {"jsonrpc": "2.0", "id": request_id, "result": upstream.request(method, params, timeout)}
        except HubError as err:
            if method == "tools/call" and err.code != "not_found":
                return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": str(err)}], "isError": True}}
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32002 if err.code == "not_found" else -32603, "message": str(err)}}
        except UpstreamError as err:
            if err.rpc_code is not None:
                error: dict[str, Any] = {"code": err.rpc_code, "message": str(err)}
                if err.data is not None:
                    error["data"] = err.data
                return {"jsonrpc": "2.0", "id": request_id, "error": error}
            if method == "tools/call":
                # The model can read a failed call and act on it; a protocol error would end the turn.
                return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": f"The MCP server {name} could not run the tool: {err}"}], "isError": True}}
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": f"The MCP server {name} could not answer: {err}"}}
