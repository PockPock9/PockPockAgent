"""Browser-facing NemoClaw routes. Agent turns are accepted only from this PC."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .bridge import MAX_MESSAGE_CHARS, NemoClawBridge, NemoClawError, sandbox_place, validate_message, validate_session_id

HEARTBEAT_SECONDS = 10
logger = logging.getLogger("pockpock.nemoclaw")


class NemoClawChatPayload(BaseModel):
    session_id: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS + 2000)


class NemoClawModelPayload(BaseModel):
    # Empty: back to the sandbox's local model. Otherwise a connected cloud model, "<provider>/<model>".
    model: str = Field(default="", max_length=100)


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_router(
    bridge: NemoClawBridge,
    require_local: Callable[[Request], None],
    cloud_models: Callable[[], list[str]] = lambda: [],
    cloud_token: Callable[[], str] = lambda: "",
) -> APIRouter:
    """Build the router. ``require_local`` is the gateway's same-PC request check; ``cloud_models``
    lists the connected cloud model names and ``cloud_token`` gives the local cloud endpoint's token."""

    def local_only(request: Request) -> None:
        require_local(request)

    router = APIRouter(prefix="/api/nemoclaw", dependencies=[Depends(local_only)])

    @router.get("/status")
    async def nemoclaw_status(refresh: int = 0, probe: int = 1):
        return await asyncio.to_thread(bridge.status, bool(refresh), bool(probe) or bool(refresh))

    @router.get("/model")
    async def nemoclaw_model():
        try:
            return {**await asyncio.to_thread(bridge.route), "cloud_models": cloud_models()}
        except NemoClawError as err:
            raise HTTPException(status_code=err.status_code, detail=str(err)) from err

    @router.put("/model")
    async def set_nemoclaw_model(payload: NemoClawModelPayload):
        if payload.model and payload.model not in cloud_models():
            raise HTTPException(status_code=409, detail="That cloud model is not connected. Choose it on the Cloud page.")
        try:
            return {**await asyncio.to_thread(lambda: bridge.set_model(payload.model, token=cloud_token())), "cloud_models": cloud_models()}
        except NemoClawError as err:
            raise HTTPException(status_code=err.status_code, detail=str(err)) from err

    @router.post("/chat")
    async def nemoclaw_chat(payload: NemoClawChatPayload):
        # Refuse a malformed session id or an empty message before the stream starts, as OpenClaw
        # does, instead of opening a turn that can only fail later (issue #75).
        try:
            validate_session_id(payload.session_id)
            validate_message(payload.message)
        except NemoClawError as err:
            raise HTTPException(status_code=err.status_code, detail=str(err)) from err

        async def stream():
            started = time.monotonic()
            turn = asyncio.create_task(asyncio.to_thread(bridge.run_turn, payload.session_id, payload.message))
            try:
                yield _sse({
                    "type": "decision",
                    "model": f"NemoClaw · {bridge.config.sandbox}",
                    "category": "nemoclaw",
                    "source": "nemoclaw",
                    "reason": f"Sent to the sandboxed NemoClaw agent {sandbox_place()}",
                })
                while True:
                    done, _ = await asyncio.wait({turn}, timeout=HEARTBEAT_SECONDS)
                    if done:
                        break
                    yield _sse({"type": "status", "message": "NemoClaw agent is working"})
                result = turn.result()
                label = f"NemoClaw · {result.model}" if result.model else f"NemoClaw · {bridge.config.sandbox}"
                yield _sse({"type": "decision", "model": label, "category": "nemoclaw", "source": "nemoclaw"})
                yield _sse({"type": "token", "content": result.text})
                yield _sse({
                    "type": "done",
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "truncated": result.truncated,
                })
            except NemoClawError as err:
                yield _sse({"type": "error", "code": err.code, "message": str(err)})
            except asyncio.CancelledError:
                bridge.cancel_active()
                turn.cancel()
                raise
            except Exception:
                logger.exception("NemoClaw bridge request failed")
                yield _sse({"type": "error", "code": "bridge_failed", "message": "The NemoClaw bridge failed. Check the PockPock AI server logs."})

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

    return router
