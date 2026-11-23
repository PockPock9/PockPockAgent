"""PockPock Local MCP: runs the MCP servers the user added and offers each one to every agent on this PC.

Local port: 8776 (``POCKPOCK_MCP_HUB_PORT``). Two kinds of caller:

- The gateway manages servers (``/servers``) with ``X-PockPock-Internal-Token``.
- Agents (OpenClaw now) reach a server at ``POST /mcp/<name>`` (streamable HTTP, single JSON replies)
  with ``Authorization: Bearer <hub token>``. The token is in the hub's data folder and in the client
  entry the gateway writes into OpenClaw; it is a local token, never a third-party key.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "scripts", ROOT / "projects", ROOT):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from projects.internal_auth import require_internal_token  # noqa: E402
from projects.mcp_hub.hub import Hub, HubError  # noqa: E402

MAX_BODY = 8 * 1024 * 1024
logger = logging.getLogger("pockpock.mcp_hub")


class ServerBody(BaseModel):
    transport: str = Field(default="stdio", max_length=40)
    command: str = Field(default="", max_length=200)
    args: list[str] = Field(default_factory=list, max_length=40)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = Field(default="", max_length=1000)
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    source: str = Field(default="", max_length=500)

class EnabledBody(BaseModel):
    enabled: bool


def create_app(hub: Hub | None = None) -> FastAPI:
    hub = hub or Hub()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            await asyncio.to_thread(hub.stop_all)

    app = FastAPI(title="PockPock Local MCP", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.hub = hub

    def fail(err: HubError) -> HTTPException:
        return HTTPException(status_code=err.status_code, detail=str(err))

    async def require_client_token(authorization: str | None = Header(default=None)) -> None:
        expected = hub.token()
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not given or not hmac.compare_digest(given, expected):
            raise HTTPException(status_code=401, detail="A valid Local MCP token is required.")

    @app.get("/health")
    async def health():
        return {"ok": True, "service": "mcp-hub"}

    # ----- management -----

    @app.get("/servers", dependencies=[Depends(require_internal_token)])
    async def servers():
        return {"servers": hub.list()}

    @app.put("/servers/{name}", dependencies=[Depends(require_internal_token)])
    async def put_server(name: str, body: ServerBody):
        try:
            return {"server": await asyncio.to_thread(hub.put, name, body.model_dump()), "client": hub.client_entry(name)}
        except HubError as err:
            raise fail(err) from err

    @app.delete("/servers/{name}", dependencies=[Depends(require_internal_token)])
    async def delete_server(name: str):
        return {"removed": await asyncio.to_thread(hub.remove, name)}

    @app.post("/servers/{name}/enabled", dependencies=[Depends(require_internal_token)])
    async def enable_server(name: str, body: EnabledBody):
        try:
            return {"server": await asyncio.to_thread(hub.set_enabled, name, body.enabled)}
        except HubError as err:
            raise fail(err) from err

    @app.post("/servers/{name}/restart", dependencies=[Depends(require_internal_token)])
    async def restart_server(name: str):
        try:
            return {"server": await asyncio.to_thread(hub.restart, name)}
        except HubError as err:
            raise fail(err) from err

    @app.get("/servers/{name}/log", dependencies=[Depends(require_internal_token)])
    async def server_log(name: str):
        try:
            return {"lines": hub.logs(name)}
        except HubError as err:
            raise fail(err) from err

    @app.get("/servers/{name}/client", dependencies=[Depends(require_internal_token)])
    async def server_client(name: str):
        try:
            return {"client": hub.client_entry(name)}
        except HubError as err:
            raise fail(err) from err

    # ----- MCP -----

    def rpc_error(request_id: Any, code: int, message: str, status: int = 200) -> JSONResponse:
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}, status_code=status)

    @app.get("/mcp/{name}")
    async def mcp_get(name: str):
        # Replies come back on the POST; there is no server-to-client stream.
        return Response(status_code=405, headers={"Allow": "POST"})

    @app.delete("/mcp/{name}", dependencies=[Depends(require_client_token)])
    async def mcp_delete(name: str):
        return Response(status_code=204)

    @app.post("/mcp/{name}", dependencies=[Depends(require_client_token)])
    async def mcp_post(name: str, request: Request):
        raw = await request.body()
        if len(raw) > MAX_BODY:
            return rpc_error(None, -32600, "The request is too large.", 413)
        try:
            message = json.loads(raw)
        except ValueError:
            return rpc_error(None, -32700, "The request is not valid JSON.", 400)
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return rpc_error(None, -32600, "Not a single JSON-RPC 2.0 request.", 400)
        reply = await asyncio.to_thread(hub.handle, name, message)
        if reply is None:
            return Response(status_code=202)
        return JSONResponse(reply)

    return app


app = create_app()
