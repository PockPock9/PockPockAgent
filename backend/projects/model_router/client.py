"""Provider-neutral chat-completion requests with a local Ollama adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from typing import Any, AsyncIterator, Mapping, Protocol, Sequence

import aiohttp


class ModelProviderError(RuntimeError):
    """A provider failed or returned an unusable completion."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


# Model families whose Ollama builds think by default. With thinking on, the
# reply is a long reasoning trace and the visible content can come back empty
# to callers that only forward ``content`` (GitHub issue #86). The gateway
# therefore sends ``think: false`` for these models unless a turn explicitly
# needs reasoning.
THINKING_MODEL_PREFIXES = ("qwen3.5", "qwen3:")


def model_thinks_by_default(model: str | None) -> bool:
    """True when ``model`` is a thinking-by-default local model."""
    name = (model or "").lower()
    return any(name.startswith(prefix) or f"/{prefix}" in name for prefix in THINKING_MODEL_PREFIXES)


#: How long Ollama keeps a model resident after its last use, sent as
#: ``keep_alive`` on every local request. Ollama's own default is 5
#: minutes, which unloads the model between agent turns and pays a reload
#: on the next one; 30 minutes keeps it resident across a working
#: session. Override with ``POCKPOCK_OLLAMA_KEEP_ALIVE`` (e.g. ``5m``,
#: ``1h``, ``0`` to unload immediately).
DEFAULT_KEEP_ALIVE = "30m"

#: Context window (``num_ctx``) sent when a request does not set one.
#: Ollama defaults to 4K on cards under 24 GB, which is too small for
#: agent loops; 16K fits ordinary agent turns while keeping KV-cache
#: VRAM in check (about 3 GB for a 14B model — raising this much higher
#: on a 12 GB card can force partial CPU offload). The agent loop's
#: compaction budget is separate; see context_compaction.py. Override
#: with ``POCKPOCK_NUM_CTX``.
DEFAULT_CONTEXT_WINDOW_TOKENS = 16_384


def ollama_keep_alive() -> str:
    """Keep-alive sent on local requests (env-overridable)."""
    return os.environ.get("POCKPOCK_OLLAMA_KEEP_ALIVE", "").strip() or DEFAULT_KEEP_ALIVE


def default_context_window() -> int:
    """Context window sent when a request does not set one (env-overridable)."""
    try:
        return int(os.environ.get("POCKPOCK_NUM_CTX", "").strip() or DEFAULT_CONTEXT_WINDOW_TOKENS)
    except ValueError:
        return DEFAULT_CONTEXT_WINDOW_TOKENS


def resolve_num_ctx(request: "ChatCompletionRequest") -> int:
    """Context window for one request: explicit field, then caller option, then default."""
    if request.context_window is not None:
        return request.context_window
    num_ctx = (request.options or {}).get("num_ctx")
    if isinstance(num_ctx, int) and num_ctx > 0:
        return num_ctx
    return default_context_window()


def resolve_think(
    model: str | None,
    *,
    tools: bool = False,
    json_output: bool = False,
    explicit_reasoning: bool = False,
) -> bool | None:
    """Decide the Ollama ``think`` flag for one model call.

    Returns ``False`` for tool-call and structured-JSON turns (thinking
    tokens slow those turns and can break schema adherence) and for
    thinking-by-default models in ordinary chat, where the trace otherwise
    eats the reply. Returns ``None`` — leave the model default — for
    explicit hard-reasoning turns and for models that do not think by
    default, so thinking stays available where the code asks for it.
    """
    if explicit_reasoning:
        return None
    if tools or json_output or model_thinks_by_default(model):
        return False
    return None


@dataclass(frozen=True)
class ChatCompletionRequest:
    model: str
    messages: Sequence[Mapping[str, Any]]
    tools: Sequence[Mapping[str, Any]] | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    response_format: Mapping[str, Any] | None = None
    context_window: int | None = None
    options: Mapping[str, Any] | None = None
    # Ollama's reasoning switch; None leaves the model default. Structured JSON calls turn it off
    # because thinking tokens on a large, partly CPU-offloaded model can take minutes.
    # Callers should use resolve_think() so thinking-by-default models (Qwen 3.5,
    # issue #86) get think=False on ordinary turns instead of returning empty replies.
    think: bool | None = None
    # Ollama keep-alive for this request (e.g. "30m"); None uses
    # ollama_keep_alive(). Sent on both Ollama endpoints so the model
    # stays resident between turns of one session.
    keep_alive: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(message) for message in self.messages],
        }
        for name in ("tools", "temperature", "top_p", "max_tokens", "response_format"):
            value = getattr(self, name)
            if value is not None:
                payload[name] = value
        return payload


class ChatCompletionProvider(Protocol):
    async def complete(
        self,
        request: ChatCompletionRequest,
        *,
        timeout: aiohttp.ClientTimeout,
    ) -> dict[str, Any]:
        """Return a chat-completion response using the shared response shape."""

    def stream_tokens(
        self,
        request: ChatCompletionRequest,
        *,
        timeout: aiohttp.ClientTimeout,
    ) -> AsyncIterator[str]:
        """Yield generated text tokens."""


class OllamaChatCompletionAdapter:
    """Use Ollama's native API for text requests and its OpenAI-compatible API for tools."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def complete(
        self,
        request: ChatCompletionRequest,
        *,
        timeout: aiohttp.ClientTimeout,
    ) -> dict[str, Any]:
        if request.tools is not None:
            return await self._complete_openai_compatible(request, timeout)
        return await self._complete_native(request, timeout)

    async def _complete_openai_compatible(
        self,
        request: ChatCompletionRequest,
        timeout: aiohttp.ClientTimeout,
    ) -> dict[str, Any]:
        payload = request.to_payload()
        # Ollama's OpenAI-compatible endpoint accepts the same ``think`` flag
        # as /api/chat; without it a thinking model burns the turn on a
        # reasoning trace and returns no tool calls (issue #86).
        if request.think is not None:
            payload["think"] = request.think
        # Tool-call turns previously sent neither keep-alive nor a context
        # window, so they ran on Ollama's 4K default and the model unloaded
        # after 5 idle minutes. Send both here, as on the native endpoint.
        payload["keep_alive"] = request.keep_alive or ollama_keep_alive()
        payload["options"] = _request_options(request)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                ) as response:
                    if response.status >= 400:
                        detail = (await response.text())[:240]
                        raise ModelProviderError(
                            f"Local model request failed (HTTP {response.status}): {detail}",
                            status_code=response.status,
                        )
                    result = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ModelProviderError(f"Local model request failed: {err}") from err
        if not isinstance(result, dict):
            raise ModelProviderError("Local model returned an invalid completion response")
        return result

    async def _complete_native(
        self,
        request: ChatCompletionRequest,
        timeout: aiohttp.ClientTimeout,
    ) -> dict[str, Any]:
        payload = self._native_payload(request, stream=False)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self.base_url}/api/chat", json=payload) as response:
                    if response.status >= 400:
                        detail = (await response.text())[:240]
                        raise ModelProviderError(
                            f"Local model request failed (HTTP {response.status}): {detail}",
                            status_code=response.status,
                        )
                    result = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ModelProviderError(f"Local model request failed: {err}") from err

        message = result.get("message") if isinstance(result, dict) else None
        if not isinstance(message, dict):
            raise ModelProviderError("Local model returned an invalid completion response")
        return {
            "choices": [{
                "index": 0,
                "message": dict(message),
                "finish_reason": result.get("done_reason") if isinstance(result, dict) else None,
            }]
        }

    async def stream_tokens(
        self,
        request: ChatCompletionRequest,
        *,
        timeout: aiohttp.ClientTimeout,
    ) -> AsyncIterator[str]:
        if request.tools is not None:
            raise ModelProviderError("Streaming tool calls are not supported by this adapter")
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=self._native_payload(request, stream=True),
                ) as response:
                    if response.status >= 400:
                        detail = (await response.text())[:240]
                        raise ModelProviderError(
                            f"Local model request failed (HTTP {response.status}): {detail}"
                        )
                    async for line in response.content:
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        message = chunk.get("message", {}) if isinstance(chunk, dict) else {}
                        token = message.get("content", "") if isinstance(message, dict) else ""
                        if isinstance(token, str) and token:
                            yield token
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ModelProviderError(f"Local model request failed: {err}") from err

    @staticmethod
    def _native_payload(
        request: ChatCompletionRequest,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [dict(message) for message in request.messages],
            "stream": stream,
            "options": _request_options(request),
            # Keep the model resident between turns of one session instead
            # of Ollama's 5-minute default unload (see DEFAULT_KEEP_ALIVE).
            "keep_alive": request.keep_alive or ollama_keep_alive(),
        }
        if request.response_format and request.response_format.get("type") == "json_object":
            payload["format"] = "json"
        if request.think is not None:
            payload["think"] = request.think
        return payload


def _request_options(request: ChatCompletionRequest) -> dict[str, Any]:
    """Ollama ``options`` for one request: caller options, then the typed fields.

    The context window always lands here: an explicit ``context_window``
    wins, then a caller-supplied ``num_ctx`` option, then the
    ``POCKPOCK_NUM_CTX`` default (16K — Ollama's own 4K default on
    sub-24 GB cards truncates ordinary agent turns).
    """
    options = dict(request.options or {})
    if request.temperature is not None:
        options["temperature"] = request.temperature
    if request.top_p is not None:
        options["top_p"] = request.top_p
    if request.max_tokens is not None:
        options["num_predict"] = request.max_tokens
    options["num_ctx"] = resolve_num_ctx(request)
    return options
