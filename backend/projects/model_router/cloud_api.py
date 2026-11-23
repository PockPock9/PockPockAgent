"""Gateway routes for cloud models.

- ``PUT /api/cloud/config`` (internal token): the desktop app pushes the connected providers and keys.
- ``GET /api/cloud/models``: the chosen cloud models, without keys, for the pickers.
- ``/cloud/v1``: a local OpenAI-compatible endpoint for OpenClaw, NemoClaw and the planner. They send
  ``<provider>/<model>`` names with a local token; the gateway adds the real key. So API keys are
  never written into OpenClaw's or NemoClaw's configuration.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
from typing import Any

import aiohttp
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from projects.internal_auth import require_internal_token

from .client import ModelProviderError
from .cloud import CloudRegistry, adapt_body

MAX_PROXY_BODY = 8 * 1024 * 1024
PROXY_TIMEOUT = aiohttp.ClientTimeout(total=1800, sock_connect=20, sock_read=600)


class CloudModelPayload(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    context_window: int | None = Field(default=None, ge=1, le=10_000_000)


class CloudProviderPayload(BaseModel):
    id: str = Field(min_length=1, max_length=20)
    base_url: str = Field(min_length=8, max_length=200)
    api_key: str = Field(min_length=1, max_length=400)
    models: list[CloudModelPayload] = Field(default_factory=list, max_length=200)


class CloudConfigPayload(BaseModel):
    providers: list[CloudProviderPayload] = Field(default_factory=list, max_length=8)
    proxy_token: str = Field(default="", max_length=200)


def create_cloud_router(registry: CloudRegistry) -> APIRouter:
    router = APIRouter()

    def require_proxy_token(authorization: str | None = Header(default=None)) -> None:
        given = (authorization or "").removeprefix("Bearer ").strip()
        accepted = [token for token in (registry.proxy_token, os.environ.get("POCKPOCK_INTERNAL_TOKEN", "")) if token]
        if not given or not any(hmac.compare_digest(given, token) for token in accepted):
            raise HTTPException(status_code=401, detail="The local cloud endpoint needs PockPock's token.")

    @router.put("/api/cloud/config", dependencies=[Depends(require_internal_token)])
    async def set_cloud_config(payload: CloudConfigPayload):
        try:
            registry.replace([provider.model_dump() for provider in payload.providers], proxy_token=payload.proxy_token)
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err)) from err
        return {"ok": True, "models": len(registry.models())}

    @router.get("/api/cloud/models")
    async def cloud_models():
        return {"models": registry.models()}

    @router.get("/cloud/v1/models", dependencies=[Depends(require_proxy_token)])
    async def proxy_models():
        return {"object": "list", "data": [{"id": item["name"], "object": "model", "created": int(time.time()), "owned_by": item["provider"]} for item in registry.models()]}

    @router.post("/cloud/v1/chat/completions", dependencies=[Depends(require_proxy_token)])
    async def proxy_chat(request: Request):
        raw = await request.body()
        if len(raw) > MAX_PROXY_BODY:
            raise HTTPException(status_code=413, detail="The request is too large.")
        try:
            body: Any = json.loads(raw)
        except ValueError as err:
            raise HTTPException(status_code=400, detail="The request is not valid JSON.") from err
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="The request is not valid JSON.")
        try:
            provider, model = registry.resolve(str(body.get("model") or ""))
        except ModelProviderError as err:
            return JSONResponse(status_code=err.status_code or 409, content={"error": {"message": str(err), "type": "invalid_request_error"}})
        body = adapt_body(provider.id, {**body, "model": model})
        headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}
        url = f"{provider.base_url}/chat/completions"

        session = aiohttp.ClientSession(timeout=PROXY_TIMEOUT)
        try:
            upstream = await session.post(url, json=body, headers=headers)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            await session.close()
            return JSONResponse(status_code=502, content={"error": {"message": f"{provider.label} could not be reached: {err or type(err).__name__}", "type": "upstream_error"}})

        if body.get("stream") is not True or upstream.status >= 400:
            try:
                content = await upstream.read()
            finally:
                upstream.release()
                await session.close()
            return StreamingResponse(iter([content]), status_code=upstream.status, media_type=upstream.headers.get("Content-Type", "application/json"))

        async def relay():
            try:
                async for chunk in upstream.content.iter_any():
                    yield chunk
            except (aiohttp.ClientError, asyncio.TimeoutError):
                yield b'data: {"error":{"message":"The cloud provider closed the connection."}}\n\n'
            finally:
                upstream.release()
                await session.close()

        return StreamingResponse(relay(), status_code=200, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return router
