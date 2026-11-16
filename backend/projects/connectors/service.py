"""Connected apps in the gateway: credential checks, the in-memory credentials, and tool calls.

The desktop app owns the credentials (encrypted on disk) and pushes the connected ones here, where
they stay in memory only. The agent never sees a credential: it calls a tool by name and gets the
app's answer.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from . import clients
from .catalog import BY_ID, CATALOG, TOOLS, Connector
from .clients import ConnectorError, Http

MAX_RESULT_CHARS = 60_000


def clean_credentials(connector: Connector, values: Mapping[str, Any]) -> dict[str, str]:
    """Keep only the connector's own fields, as trimmed strings. Raises on a missing or oversized value."""
    cleaned: dict[str, str] = {}
    for item in connector.fields:
        if item.only_when and str(values.get(item.only_when[0]) or "") != item.only_when[1]:
            continue
        value = str(values.get(item.key) or "").strip()
        if item.options and value not in {option for option, _ in item.options}:
            raise ConnectorError(f"Choose a value for “{item.label}”.", status_code=400, code="bad_input")
        if not value and item.required:
            raise ConnectorError(f"“{item.label}” is needed.", status_code=400, code="bad_input")
        if len(value) > item.max_length or any(ord(char) < 32 for char in value) or (item.secret and item.key == "token" and any(char.isspace() for char in value)):
            raise ConnectorError(f"“{item.label}” is not valid. Paste it exactly as the app shows it.", status_code=400, code="bad_input")
        cleaned[item.key] = value
    # App passwords are often shown in groups of four with spaces; the spaces are not part of it.
    if connector.id == "email" and "password" in cleaned:
        cleaned["password"] = cleaned["password"].replace(" ", "")
    return cleaned


class ConnectorService:
    def __init__(self, http: Http = clients.http_request):
        self._http = http
        self._connected: dict[str, dict[str, Any]] = {}  # id -> {"credentials": {...}, "account": str}
        self.tool_token = ""

    async def verify(self, connector_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        """Check a credential with the app itself. Returns the account it belongs to; stores nothing."""
        connector = BY_ID.get(connector_id)
        if connector is None:
            raise ConnectorError("Unknown connector.", status_code=404, code="unknown")
        credentials = clean_credentials(connector, values)
        try:
            account = await clients.VERIFY[connector_id](credentials, self._http)
        except ConnectorError as err:
            # The clients word a refusal for a tool call ("reconnect it"); at connect time say what to fix.
            if err.code == "refused" and ("saved credential" in str(err) or "not valid" in str(err)):
                label = next((item.label for item in connector.fields if item.secret), "credential").lower()
                raise ConnectorError(f"{connector.name} did not accept that {label}. Copy it again and check that it is complete and still active.", status_code=409, code="refused") from None
            raise
        return {"id": connector_id, "account": str(account)[:120], "credentials": credentials}

    def replace(self, connected: list[Mapping[str, Any]], *, tool_token: str = "") -> None:
        """Replace every connection with a pushed configuration. Raises ``ValueError`` on bad input."""
        parsed: dict[str, dict[str, Any]] = {}
        for item in connected:
            connector = BY_ID.get(str(item.get("id") or ""))
            if connector is None:
                raise ValueError("Unknown connector.")
            try:
                credentials = clean_credentials(connector, item.get("credentials") or {})
            except ConnectorError as err:
                raise ValueError(str(err)) from err
            parsed[connector.id] = {"credentials": credentials, "account": str(item.get("account") or "")[:120]}
        self._connected = parsed
        self.tool_token = tool_token if 20 <= len(tool_token) <= 200 else ""

    def listing(self) -> list[dict[str, Any]]:
        """The catalog with what is connected. Never includes a credential."""
        return [{**connector.to_dict(), "connected": connector.id in self._connected, "account": self._connected.get(connector.id, {}).get("account", "")} for connector in CATALOG]

    def connected_ids(self) -> list[str]:
        return list(self._connected)

    def tools(self) -> list[dict[str, Any]]:
        """MCP tool definitions of the connected apps."""
        return [
            {"name": tool.name, "title": tool.title, "description": f"{tool.description} ({connector.name}{'; changes something outside this computer' if tool.write else ''})", "inputSchema": tool.input_schema(), "annotations": {"title": tool.title, "readOnlyHint": not tool.write, "destructiveHint": False, "openWorldHint": True}}
            for connector in CATALOG if connector.id in self._connected for tool in connector.tools
        ]

    async def call(self, name: str, arguments: Mapping[str, Any] | None) -> dict[str, Any]:
        entry = TOOLS.get(name)
        if entry is None:
            raise ConnectorError(f"There is no tool named {name}.", status_code=404, code="unknown")
        connector, tool = entry
        connection = self._connected.get(connector.id)
        if connection is None:
            raise ConnectorError(f"{connector.name} is not connected. Connect it on the Connectors page.", status_code=409, code="not_connected")
        args = dict(arguments or {})
        unknown = set(args) - set(tool.properties)
        if unknown:
            raise ConnectorError(f"Unknown input for {name}: {', '.join(sorted(unknown))}.", status_code=400, code="bad_input")
        result = await clients.HANDLERS[name](connection["credentials"], args, self._http)
        text = json.dumps(result, ensure_ascii=False)
        if len(text) > MAX_RESULT_CHARS:
            result = {"truncated": True, "text": text[:MAX_RESULT_CHARS]}
        return result
