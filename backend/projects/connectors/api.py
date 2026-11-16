"""Gateway routes for connectors.

- ``GET /api/connectors``: the catalog and what is connected (no credentials).
- ``POST /api/connectors/verify`` (internal token): check a credential with the app; nothing is stored.
- ``PUT /api/connectors/config`` (internal token): the desktop app pushes the connected apps.
- ``POST /mcp/connectors``: a Model Context Protocol endpoint (streamable HTTP, JSON answers) that
  offers the connected apps' tools to an agent. It needs the local tool token.
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Any, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from projects.internal_auth import require_internal_token

from .clients import ConnectorError
from .service import ConnectorService

logger = logging.getLogger("pockpock.connectors")
MCP_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_MCP_BODY = 2 * 1024 * 1024


class VerifyPayload(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    credentials: dict[str, str] = Field(default_factory=dict)


class ConnectedPayload(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    account: str = Field(default="", max_length=120)
    credentials: dict[str, str] = Field(default_factory=dict)


class ConfigPayload(BaseModel):
    connected: list[ConnectedPayload] = Field(default_factory=list, max_length=20)
    tool_token: str = Field(default="", max_length=200)


def _rpc_result(request_id: Any, result: Any) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def _rpc_error(request_id: Any, code: int, message: str, status: int = 200) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}, status_code=status)


def create_connectors_router(service: ConnectorService, on_change: Callable[[ConnectorService], None] | None = None) -> APIRouter:
    """``on_change`` runs after every configuration push (for example to register the tools with OpenClaw)."""
    router = APIRouter()

    def require_tool_token(authorization: str | None = Header(default=None)) -> None:
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not service.tool_token or not given or not hmac.compare_digest(given, service.tool_token):
            raise HTTPException(status_code=401, detail="The connector tools need PockPock's local token.")

    @router.get("/api/connectors")
    async def list_connectors():
        return {"connectors": service.listing()}

    @router.post("/api/connectors/verify", dependencies=[Depends(require_internal_token)])
    async def verify_connector(payload: VerifyPayload):
        try:
            return await service.verify(payload.id, payload.credentials)
        except ConnectorError as err:
            raise HTTPException(status_code=err.status_code, detail=str(err)) from err

    @router.put("/api/connectors/config", dependencies=[Depends(require_internal_token)])
    async def set_connectors_config(payload: ConfigPayload):
        try:
            service.replace([item.model_dump() for item in payload.connected], tool_token=payload.tool_token)
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err)) from err
        if on_change is not None:
            try:
                on_change(service)
            except Exception:  # registration with an agent is best effort; the connection itself stands
                logger.exception("Connector tools could not be registered with the agent")
        return {"ok": True, "connected": service.connected_ids(), "tools": len(service.tools())}

    @router.get("/mcp/connectors")
    async def mcp_get():
        # This server only answers requests; it has no server-to-client stream.
        return Response(status_code=405, headers={"Allow": "POST"})

    @router.post("/mcp/connectors", dependencies=[Depends(require_tool_token)])
    async def mcp_post(request: Request):
        raw = await request.body()
        if len(raw) > MAX_MCP_BODY:
            return _rpc_error(None, -32600, "The request is too large.", 413)
        try:
            message = json.loads(raw)
        except ValueError:
            return _rpc_error(None, -32700, "The request is not valid JSON.", 400)
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return _rpc_error(None, -32600, "Not a JSON-RPC 2.0 request.", 400)
        method, request_id, params = message["method"], message.get("id"), message.get("params") or {}
        if "id" not in message:  # a notification, such as notifications/initialized
            return Response(status_code=202)
        if method == "initialize":
            wanted = str(params.get("protocolVersion") or "") if isinstance(params, dict) else ""
            return _rpc_result(request_id, {
                "protocolVersion": wanted if wanted in MCP_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "pockpock-connectors", "title": "PockPock connectors", "version": "1.0.0"},
                "instructions": "Tools for the apps the user connected in PockPock. Tools that send, post or create something change the outside world: do so only when the user asked for it.",
            })
        if method == "ping":
            return _rpc_result(request_id, {})
        if method == "tools/list":
            return _rpc_result(request_id, {"tools": service.tools()})
        if method == "tools/call":
            if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                return _rpc_error(request_id, -32602, "tools/call needs a tool name.")
            arguments = params.get("arguments")
            try:
                result = await service.call(params["name"], arguments if isinstance(arguments, dict) else {})
            except ConnectorError as err:
                if err.code == "unknown":
                    return _rpc_error(request_id, -32602, str(err))
                # A failed call is a tool result the model can read and act on, not a protocol error.
                return _rpc_result(request_id, {"content": [{"type": "text", "text": str(err)}], "isError": True})
            except Exception:
                logger.exception("Connector tool %s failed", params["name"])
                return _rpc_result(request_id, {"content": [{"type": "text", "text": "The tool failed unexpectedly. Try again."}], "isError": True})
            return _rpc_result(request_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "structuredContent": result, "isError": False})
        return _rpc_error(request_id, -32601, f"Method not found: {method}")

    return router
