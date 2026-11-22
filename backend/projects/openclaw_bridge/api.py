"""Browser-facing OpenClaw routes. Agent turns and approvals are accepted only from this PC."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .bridge import MAX_MESSAGE_CHARS, OpenClawBridge, OpenClawError

HEARTBEAT_SECONDS = 10.0
logger = logging.getLogger("pockpock.openclaw")


class OpenClawChatPayload(BaseModel):
    session_id: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS + 2000)
    permission_mode: str = Field(default="ask", max_length=16)
    model: str | None = Field(default=None, max_length=100)


class OpenClawApprovalPayload(BaseModel):
    approval_id: str = Field(min_length=1, max_length=128)
    decision: str = Field(min_length=1, max_length=16)


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _label(model: str) -> str:
    return f"OpenClaw · {model}" if model else "OpenClaw"


def create_router(bridge: OpenClawBridge, require_local: Callable[[Request], None]) -> APIRouter:
    """Build the router. ``require_local`` is the gateway's same-PC request check."""

    def local_only(request: Request) -> None:
        require_local(request)

    router = APIRouter(prefix="/api/openclaw", dependencies=[Depends(local_only)])

    @router.get("/status")
    async def openclaw_status(refresh: int = 0):
        return await asyncio.to_thread(bridge.status, bool(refresh))

    @router.post("/approvals")
    async def openclaw_approval(payload: OpenClawApprovalPayload):
        try:
            bridge.resolve_approval(payload.approval_id, payload.decision)
        except OpenClawError as err:
            raise HTTPException(status_code=err.status_code, detail=str(err)) from err
        return {"ok": True}

    @router.post("/chat")
    async def openclaw_chat(payload: OpenClawChatPayload):
        try:
            selection = await asyncio.to_thread(bridge.select_tools, payload.session_id, payload.message)
            turn = bridge.start_turn(payload.session_id, payload.message, payload.permission_mode, payload.model, selection)
        except OpenClawError as err:
            raise HTTPException(status_code=err.status_code, detail=str(err)) from err

        async def stream():
            started = time.monotonic()
            finished = False
            try:
                yield _sse({
                    "type": "decision",
                    "model": _label(""),
                    "category": "openclaw",
                    "source": "openclaw",
                    "reason": "Sent to the OpenClaw agent running on this PC",
                })
                if selection and selection.get("toolOverrides"):
                    yield _sse({
                        "type": "tool_selection",
                        "skills_offered": selection.get("skills_offered"),
                        "skills_total": selection.get("skills_total"),
                        "servers_offered": selection.get("servers_offered"),
                        "servers_total": selection.get("servers_total"),
                        "tokens_saved": selection.get("tokens_saved", 0),
                        "method": selection.get("method", ""),
                    })
                while True:
                    event = await asyncio.to_thread(turn.next_event, HEARTBEAT_SECONDS)
                    if event is False:
                        yield _sse({"type": "status", "message": "OpenClaw agent is working"})
                        continue
                    if event is None:
                        break
                    kind = event.get("type")
                    if kind == "delta":
                        yield _sse({"type": "token", "content": str(event.get("text") or "")})
                    elif kind == "replace":
                        yield _sse({"type": "replace", "content": str(event.get("text") or "")})
                    elif kind == "tool":
                        yield _sse({
                            "type": "tool",
                            "phase": event.get("phase"),
                            "id": event.get("id"),
                            "name": event.get("name"),
                            "title": event.get("title"),
                            "status": event.get("status"),
                            "error": event.get("error"),
                        })
                    elif kind == "approval":
                        yield _sse({
                            "type": "approval",
                            "id": event.get("id"),
                            "title": event.get("title"),
                            "description": event.get("description"),
                            "severity": event.get("severity"),
                            "tool_name": event.get("toolName"),
                        })
                    elif kind == "approval_resolved":
                        yield _sse({"type": "approval_resolved", "id": event.get("id"), "decision": event.get("decision")})
                    elif kind == "approval_error":
                        yield _sse({"type": "approval_error", "id": event.get("id"), "message": event.get("message")})
                    elif kind == "final":
                        finished = True
                        yield _sse({"type": "decision", "model": _label(str(event.get("model") or "")), "category": "openclaw", "source": "openclaw"})
                        yield _sse({"type": "replace", "content": str(event.get("text") or "")})
                        yield _sse({"type": "done", "duration_ms": round((time.monotonic() - started) * 1000)})
                    elif kind == "error":
                        finished = True
                        yield _sse({"type": "error", "code": event.get("code"), "message": event.get("message")})
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("OpenClaw bridge request failed")
                yield _sse({"type": "error", "code": "bridge_failed", "message": "The OpenClaw bridge failed. Check the PockPock AI server logs."})
            finally:
                # Stop or a dropped browser connection must end the agent run, not just the stream.
                if not finished:
                    await asyncio.shield(asyncio.to_thread(turn.abort))

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

    return router
