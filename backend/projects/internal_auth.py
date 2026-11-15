"""Shared authentication for loopback-only internal service calls."""

import hmac
import os

from fastapi import Header, HTTPException


async def require_internal_token(token: str | None = Header(default=None, alias="X-PockPock-Internal-Token")) -> None:
    expected = os.environ.get("POCKPOCK_INTERNAL_TOKEN", "")
    if not expected or not token or not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=401, detail="Internal service authentication failed")
