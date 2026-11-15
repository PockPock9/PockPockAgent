"""Browser-facing routes for agent extensions. Accepted only from this PC."""

from __future__ import annotations

import asyncio
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .service import ExtensionError, ExtensionService


class InspectPayload(BaseModel):
    url: str = Field(min_length=1, max_length=600)
    prefer: str | None = Field(default=None, max_length=8)


class InstallPayload(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=64)
    skills: list[str] | None = Field(default=None, max_length=60)
    args: list[str] | None = Field(default=None, max_length=40)
    env: dict[str, str] | None = None
    authorization: str | None = Field(default=None, max_length=4000)


class CancelPayload(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=64)


class RemovePayload(BaseModel):
    kind: str = Field(min_length=1, max_length=8)
    name: str = Field(min_length=1, max_length=64)


class TogglePayload(BaseModel):
    kind: str = Field(min_length=1, max_length=8)
    name: str = Field(min_length=1, max_length=64)
    enabled: bool


def create_router(service: ExtensionService, require_local: Callable[[Request], None]) -> APIRouter:
    def local_only(request: Request) -> None:
        require_local(request)

    router = APIRouter(prefix="/api/extensions", dependencies=[Depends(local_only)])

    async def run(function, *args):
        try:
            return await asyncio.to_thread(function, *args)
        except ExtensionError as err:
            raise HTTPException(status_code=err.status_code, detail=str(err)) from err

    @router.get("")
    async def list_extensions():
        return await run(service.list)

    @router.post("/inspect")
    async def inspect_link(payload: InspectPayload):
        return await run(service.inspect, payload.url, payload.prefer)

    @router.post("/install")
    async def install_extension(payload: InstallPayload):
        return await run(service.install, payload.proposal_id, payload.skills, payload.args, payload.env, payload.authorization)

    @router.post("/cancel")
    async def cancel_proposal(payload: CancelPayload):
        await run(service.cancel, payload.proposal_id)
        return {"ok": True}

    @router.post("/remove")
    async def remove_extension(payload: RemovePayload):
        return await run(service.remove, payload.kind, payload.name)

    @router.post("/toggle")
    async def toggle_extension(payload: TogglePayload):
        return await run(service.set_enabled, payload.kind, payload.name, payload.enabled)

    return router
