"""Offers the connector tools to OpenClaw as one MCP server, ``pockpock-connectors``.

The server entry points at the gateway's own ``/mcp/connectors`` endpoint and carries PockPock's
local tool token, never an app credential. It exists only while at least one app is connected.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

SERVER_NAME = "pockpock-connectors"
logger = logging.getLogger("pockpock.connectors")
_lock = threading.Lock()


def desired_server(port: int, tool_token: str) -> dict[str, Any]:
    return {"url": f"http://127.0.0.1:{port}/mcp/connectors", "transport": "streamable-http", "headers": {"Authorization": f"Bearer {tool_token}"}}


def sync(run: Callable[[dict[str, Any]], dict[str, Any]], *, connected: bool, port: int, tool_token: str) -> str:
    """Add, update or remove the server through OpenClaw's gateway. ``run`` is ``GatewayConfig.run``.

    Returns ``set``, ``removed`` or ``unchanged``. OpenClaw is changed only when something differs,
    so starting PockPock does not rewrite its configuration every time.
    """
    with _lock:
        existing = (run({"op": "mcp_list"}).get("servers") or {}).get(SERVER_NAME)
        if not connected or not tool_token:
            if existing is None:
                return "unchanged"
            run({"op": "mcp_remove", "name": SERVER_NAME})
            return "removed"
        wanted = desired_server(port, tool_token)
        if isinstance(existing, dict) and existing.get("url") == wanted["url"] and (existing.get("headers") or {}) == wanted["headers"] and existing.get("enabled") is not False:
            return "unchanged"
        run({"op": "mcp_set", "name": SERVER_NAME, "server": wanted, "replace": existing is not None})
        return "set"


def sync_in_background(run: Callable[[dict[str, Any]], dict[str, Any]], *, connected: bool, port: int, tool_token: str) -> threading.Thread:
    """The same, without making the caller wait for OpenClaw. Failures are logged, not raised."""

    def work() -> None:
        try:
            outcome = sync(run, connected=connected, port=port, tool_token=tool_token)
            if outcome != "unchanged":
                logger.info("OpenClaw connector tools: %s", outcome)
        except Exception as err:  # OpenClaw not installed or not running: connectors still work elsewhere
            logger.warning("OpenClaw connector tools were not updated: %s", err)

    thread = threading.Thread(target=work, name="connectors-openclaw", daemon=True)
    thread.start()
    return thread
