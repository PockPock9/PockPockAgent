"""Authenticated loopback routes for the transient Chrome companion relay."""

from typing import Any, Awaitable

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from projects.internal_auth import require_internal_token

from .relay import ChromeRelayError, chrome_companion_relay


router = APIRouter(
    prefix="/api/internal/chrome-companion",
    dependencies=[Depends(require_internal_token)],
)


class HostConnect(BaseModel):
    extension_id: str = Field(min_length=32, max_length=32)
    tab_id: int = Field(ge=0, le=2_147_483_647)
    origin: str = Field(min_length=1, max_length=2048)


class HostResult(BaseModel):
    pairing_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    tab_id: int = Field(ge=0, le=2_147_483_647)
    origin: str = Field(min_length=1, max_length=2048)
    result: dict[str, Any]


class RunRequest(BaseModel):
    operation: str = Field(min_length=1, max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)


class PairingReference(BaseModel):
    pairing_id: str = Field(pattern=r"^[a-f0-9]{32}$")


def _raise_http(error: ChromeRelayError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": str(error)},
    ) from error


async def _relay_or_http(awaitable: Awaitable[Any]) -> Any:
    try:
        return await awaitable
    except ChromeRelayError as error:
        _raise_http(error)


@router.post("/host/connect")
async def host_connect(payload: HostConnect):
    return await _relay_or_http(
        chrome_companion_relay.connect(payload.extension_id, payload.tab_id, payload.origin)
    )


@router.get("/host/next")
async def host_next(pairing_id: str = Query(pattern=r"^[a-f0-9]{32}$")):
    command = await _relay_or_http(chrome_companion_relay.next_command(pairing_id))
    return {"command": command}


@router.post("/host/result")
async def host_result(payload: HostResult):
    accepted = await _relay_or_http(
        chrome_companion_relay.complete(
            payload.pairing_id,
            payload.request_id,
            payload.tab_id,
            payload.origin,
            payload.result,
        )
    )
    return {"accepted": accepted}


@router.post("/host/disconnect")
async def host_disconnect(payload: PairingReference):
    disconnected = await _relay_or_http(chrome_companion_relay.disconnect(payload.pairing_id))
    return {"disconnected": disconnected}


@router.post("/runs/{run_id}/request")
async def run_request(
    run_id: str = Path(pattern=r"^[a-f0-9]{32}$"),
    payload: RunRequest = ...,
):
    result = await _relay_or_http(
        chrome_companion_relay.request(run_id, payload.operation, payload.payload)
    )
    return {"result": result}


@router.post("/runs/{run_id}/release")
async def release_run(run_id: str = Path(pattern=r"^[a-f0-9]{32}$")):
    released = await _relay_or_http(chrome_companion_relay.release_run(run_id))
    return {"released": released}
