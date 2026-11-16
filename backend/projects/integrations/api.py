"""Browser-facing routes for integrations. Accepted only from this PC."""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .service import IntegrationError, IntegrationService


class TogglePayload(BaseModel):
    enabled: bool


class ConnectPayload(BaseModel):
    """Optional connect-form fields for external connectors.

    ``credential`` is accepted only to verify and store it; it is never
    returned in any response.
    """

    account: str | None = None
    auth_method: str | None = None
    credential: str | None = None


def create_router(service: IntegrationService, require_local: Callable[[Request], None]) -> APIRouter:
    def local_only(request: Request) -> None:
        require_local(request)

    router = APIRouter(prefix="/api/integrations", dependencies=[Depends(local_only)])

    async def run(coro):
        try:
            return await coro
        except IntegrationError as err:
            raise HTTPException(status_code=err.status_code, detail=str(err)) from err

    @router.get("")
    async def list_integrations():
        # Wrapped (like GET /api/extensions) so the desktop page reads
        # `data.integrations` instead of a bare list.
        return {"integrations": await run(service.list_integrations())}

    @router.get("/{integration_id}")
    async def get_integration(integration_id: str):
        return await run(service.get(integration_id))

    @router.post("/{integration_id}/toggle")
    async def toggle_integration(integration_id: str, payload: TogglePayload):
        return await run(service.set_enabled(integration_id, payload.enabled))

    @router.post("/{integration_id}/connect")
    async def connect_integration(integration_id: str, payload: ConnectPayload | None = None):
        return await run(
            service.connect(
                integration_id,
                account=payload.account if payload else None,
                auth_method=payload.auth_method if payload else None,
                credential=payload.credential if payload else None,
            )
        )

    @router.post("/{integration_id}/disconnect")
    async def disconnect_integration(integration_id: str):
        return await run(service.disconnect(integration_id))

    return router
