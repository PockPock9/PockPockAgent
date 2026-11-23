"""The gateway's side of Local MCP (``projects/mcp_hub``): add, remove and check the servers it runs.

Calls go to ``POCKPOCK_MCP_HUB_URL`` (``http://127.0.0.1:8776``) with the internal service token.
Server definitions, including environment values and headers, travel only over this loopback call.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

HUB_UNAVAILABLE = "Local MCP is not running. Start it on the Services page, then try again."


class HubClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or os.environ.get("POCKPOCK_MCP_HUB_URL") or "http://127.0.0.1:8776").rstrip("/")

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 20) -> dict[str, Any]:
        from .service import ExtensionError  # the service module imports this one

        request = urllib.request.Request(self.base_url + path, data=None if body is None else json.dumps(body).encode("utf-8"), method=method, headers={
            "Content-Type": "application/json",
            "X-PockPock-Internal-Token": os.environ.get("POCKPOCK_INTERNAL_TOKEN", ""),
        })
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as err:
            try:
                detail = json.loads(err.read() or b"{}").get("detail")
            except ValueError:
                detail = None
            message = detail if isinstance(detail, str) else f"Local MCP refused the request (HTTP {err.code})."
            raise ExtensionError("hub_refused" if err.code != 404 else "not_found", message, err.code if err.code in {400, 404, 409, 422} else 502) from err
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise ExtensionError("hub_unavailable", HUB_UNAVAILABLE, 503) from err
        try:
            parsed = json.loads(raw or b"{}")
        except ValueError:
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _name(name: str) -> str:
        return urllib.parse.quote(name, safe="")

    def servers(self) -> list[dict[str, Any]]:
        return list(self._call("GET", "/servers").get("servers") or [])

    def put(self, name: str, definition: dict[str, Any]) -> dict[str, Any]:
        """Saves the server; returns ``{"server": status, "client": OpenClaw entry}``."""
        return self._call("PUT", f"/servers/{self._name(name)}", definition)

    def remove(self, name: str) -> bool:
        return bool(self._call("DELETE", f"/servers/{self._name(name)}").get("removed"))

    def set_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        return self._call("POST", f"/servers/{self._name(name)}/enabled", {"enabled": enabled}).get("server") or {}

    def restart(self, name: str) -> dict[str, Any]:
        # Starting an npx or uvx server for the first time downloads it.
        return self._call("POST", f"/servers/{self._name(name)}/restart", timeout=200).get("server") or {}

    def log(self, name: str) -> list[str]:
        return [str(line) for line in self._call("GET", f"/servers/{self._name(name)}/log").get("lines") or []]

    def client(self, name: str) -> dict[str, Any]:
        return self._call("GET", f"/servers/{self._name(name)}/client").get("client") or {}
