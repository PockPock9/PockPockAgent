"""Bounded in-memory relay between the local gateway and one paired Chrome tab."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import re
import time
import uuid
from typing import Any
from urllib.parse import urlsplit


PAIRING_TTL_SECONDS = 60
MAX_RELAY_MESSAGE_BYTES = 48_000
RELAY_POLL_SECONDS = 20
_EXTENSION_ID = re.compile(r"^[a-p]{32}$")
_RUN_ID = re.compile(r"^[a-f0-9]{32}$")
_PAIRING_ID = re.compile(r"^[a-f0-9]{32}$")
_REQUEST_ID = re.compile(r"^[a-f0-9]{32}$")
_SUPPORTED_OPERATIONS = {"ping"}


class ChromeRelayError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass
class PendingRequest:
    run_id: str
    future: asyncio.Future[dict[str, Any]]


@dataclass
class Pairing:
    pairing_id: str
    extension_id: str
    tab_id: int
    origin: str
    last_seen: float
    owner_run_id: str | None = None
    commands: asyncio.Queue[dict[str, Any] | None] = field(
        default_factory=lambda: asyncio.Queue(maxsize=1)
    )
    pending: dict[str, PendingRequest] = field(default_factory=dict)
    request_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    closed: bool = False


def normalize_origin(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ChromeRelayError(422, "invalid_origin", "A valid HTTP or HTTPS origin is required.")
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as err:
        raise ChromeRelayError(422, "invalid_origin", "A valid HTTP or HTTPS origin is required.") from err
    if (
        scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ChromeRelayError(422, "invalid_origin", "Only an exact HTTP or HTTPS origin can be paired.")
    host = hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if port is not None and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    return f"{scheme}://{host}"


def _encoded_size(value: object) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError, UnicodeEncodeError) as err:
        raise ChromeRelayError(422, "invalid_message", "Relay messages must contain valid JSON values.") from err


class ChromeCompanionRelay:
    """Owns transient pairing, run ownership, and request/response queues."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pairing: Pairing | None = None

    async def connect(self, extension_id: object, tab_id: object, origin: object) -> dict[str, Any]:
        if not isinstance(extension_id, str) or not _EXTENSION_ID.fullmatch(extension_id):
            raise ChromeRelayError(422, "invalid_extension", "The registered Chrome extension ID is invalid.")
        if isinstance(tab_id, bool) or not isinstance(tab_id, int) or not 0 <= tab_id <= 2_147_483_647:
            raise ChromeRelayError(422, "invalid_tab", "A valid Chrome tab ID is required.")
        normalized_origin = normalize_origin(origin)
        async with self._lock:
            self._expire_stale_locked()
            if self._pairing is not None:
                raise ChromeRelayError(409, "tab_already_paired", "Another Chrome tab is already paired.")
            pairing = Pairing(
                pairing_id=uuid.uuid4().hex,
                extension_id=extension_id,
                tab_id=tab_id,
                origin=normalized_origin,
                last_seen=time.monotonic(),
            )
            self._pairing = pairing
            return {
                "pairing_id": pairing.pairing_id,
                "tab_id": pairing.tab_id,
                "origin": pairing.origin,
            }

    async def next_command(self, pairing_id: object) -> dict[str, Any] | None:
        async with self._lock:
            pairing = self._require_pairing_locked(pairing_id)
            pairing.last_seen = time.monotonic()
        try:
            command = await asyncio.wait_for(
                pairing.commands.get(),
                timeout=RELAY_POLL_SECONDS,
            )
        except asyncio.TimeoutError:
            async with self._lock:
                if self._pairing is pairing and not pairing.closed:
                    pairing.last_seen = time.monotonic()
            return None
        if command is None:
            raise ChromeRelayError(410, "pairing_closed", "The Chrome pairing was disconnected.")
        async with self._lock:
            if self._pairing is not pairing or pairing.closed:
                raise ChromeRelayError(410, "pairing_closed", "The Chrome pairing was disconnected.")
            if command["request_id"] not in pairing.pending:
                return None
            pairing.last_seen = time.monotonic()
        return command

    async def request(
        self,
        run_id: object,
        operation: object,
        payload: object,
        *,
        timeout: float = 25,
    ) -> dict[str, Any]:
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ChromeRelayError(422, "invalid_run", "A valid agent run ID is required.")
        if not isinstance(operation, str) or operation not in _SUPPORTED_OPERATIONS:
            raise ChromeRelayError(422, "unsupported_operation", "The Chrome relay operation is not supported.")
        if not isinstance(payload, dict) or _encoded_size(payload) > MAX_RELAY_MESSAGE_BYTES:
            raise ChromeRelayError(413, "message_too_large", "The Chrome relay request exceeds its size limit.")

        async with self._lock:
            pairing = self._require_pairing_locked()
        async with pairing.request_lock:
            async with self._lock:
                if self._pairing is not pairing or pairing.closed:
                    raise ChromeRelayError(410, "pairing_closed", "The Chrome pairing was disconnected.")
                if pairing.owner_run_id is None:
                    pairing.owner_run_id = run_id
                elif pairing.owner_run_id != run_id:
                    raise ChromeRelayError(409, "pairing_owned", "The paired Chrome tab belongs to another active run.")
                request_id = uuid.uuid4().hex
                future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
                pairing.pending[request_id] = PendingRequest(run_id=run_id, future=future)
                command = {
                    "pairing_id": pairing.pairing_id,
                    "request_id": request_id,
                    "run_id": run_id,
                    "tab_id": pairing.tab_id,
                    "origin": pairing.origin,
                    "operation": operation,
                    "payload": payload,
                }
                pairing.commands.put_nowait(command)
            try:
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError as err:
                raise ChromeRelayError(504, "relay_timeout", "The paired Chrome tab did not respond in time.") from err
            finally:
                async with self._lock:
                    pending = pairing.pending.pop(request_id, None)
                    if pending and not pending.future.done():
                        pending.future.cancel()

    async def complete(
        self,
        pairing_id: object,
        request_id: object,
        tab_id: object,
        origin: object,
        result: object,
    ) -> bool:
        if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
            raise ChromeRelayError(422, "invalid_request", "A valid relay request ID is required.")
        if isinstance(tab_id, bool) or not isinstance(tab_id, int):
            raise ChromeRelayError(422, "invalid_tab", "A valid Chrome tab ID is required.")
        normalized_origin = normalize_origin(origin)
        if not isinstance(result, dict):
            raise ChromeRelayError(422, "invalid_result", "The Chrome relay result must be a JSON object.")
        if _encoded_size(result) > MAX_RELAY_MESSAGE_BYTES:
            raise ChromeRelayError(413, "message_too_large", "The Chrome relay result exceeds its size limit.")
        async with self._lock:
            pairing = self._require_pairing_locked(pairing_id)
            if tab_id != pairing.tab_id or normalized_origin != pairing.origin:
                raise ChromeRelayError(409, "tab_scope_mismatch", "The relay response does not match the paired tab.")
            pending = pairing.pending.get(request_id)
            if pending is None:
                return False
            if not pending.future.done():
                pending.future.set_result(result)
            pairing.last_seen = time.monotonic()
            return True

    async def release_run(self, run_id: object) -> bool:
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ChromeRelayError(422, "invalid_run", "A valid agent run ID is required.")
        async with self._lock:
            pairing = self._require_pairing_locked()
            if pairing.owner_run_id != run_id:
                return False
            if any(not item.future.done() for item in pairing.pending.values()):
                raise ChromeRelayError(409, "run_busy", "The paired Chrome tab still has a pending request.")
            pairing.owner_run_id = None
            return True

    async def disconnect(self, pairing_id: object) -> bool:
        async with self._lock:
            pairing = self._pairing
            if pairing is None or pairing.pairing_id != pairing_id:
                return False
            self._close_locked(pairing)
            return True

    def _require_pairing_locked(self, pairing_id: object | None = None) -> Pairing:
        pairing = self._pairing
        if pairing is None or pairing.closed or (pairing_id is not None and pairing.pairing_id != pairing_id):
            raise ChromeRelayError(404, "pairing_not_found", "No matching Chrome tab is paired.")
        if time.monotonic() - pairing.last_seen > PAIRING_TTL_SECONDS:
            self._close_locked(pairing)
            raise ChromeRelayError(410, "pairing_expired", "The Chrome pairing expired; reconnect the tab.")
        return pairing

    def _expire_stale_locked(self) -> None:
        pairing = self._pairing
        if pairing and time.monotonic() - pairing.last_seen > PAIRING_TTL_SECONDS:
            self._close_locked(pairing)

    def _close_locked(self, pairing: Pairing) -> None:
        pairing.closed = True
        if self._pairing is pairing:
            self._pairing = None
        for pending in pairing.pending.values():
            if not pending.future.done():
                pending.future.set_exception(
                    ChromeRelayError(410, "pairing_closed", "The Chrome pairing was disconnected.")
                )
        pairing.pending.clear()
        try:
            pairing.commands.put_nowait(None)
        except asyncio.QueueFull:
            pass


chrome_companion_relay = ChromeCompanionRelay()
