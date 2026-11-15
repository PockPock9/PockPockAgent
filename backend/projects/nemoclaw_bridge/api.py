"""Browser-facing NemoClaw routes. Agent turns are accepted only from this PC."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .bridge import MAX_MESSAGE_CHARS, NemoClawBridge, NemoClawError

HEARTBEAT_SECONDS = 10
logger = logging.getLogger("pockpock.nemoclaw")


class NemoClawChatPayload(BaseModel):
    session_id: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS + 2000)


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_router(bridge: NemoClawBridge, require_local: Callable[[Request], None]) -> APIRouter:
    """Build the router. ``require_local`` is the gateway's same-PC request check."""

    def local_only(request: Request) -> None:
        require_local(request)

    router = APIRouter(prefix="/api/nemoclaw", dependencies=[Depends(local_only)])

    @router.get("/status")
    async def nemoclaw_status(refresh: int = 0, probe: int = 1):
        return await asyncio.to_thread(bridge.status, bool(refresh), bool(probe) or bool(refresh))

    @router.post("/chat")
    async def nemoclaw_chat(payload: NemoClawChatPayload):
        async def stream():
            started = time.monotonic()
            turn = asyncio.create_task(asyncio.to_thread(bridge.run_turn, payload.session_id, payload.message))
            try:
                yield _sse({
                    "type": "decision",
                    "model": f"NemoClaw · {bridge.config.sandbox}",
                    "category": "nemoclaw",
                    "source": "nemoclaw",
                    "reason": "Sent to the sandboxed NemoClaw agent in WSL",
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
