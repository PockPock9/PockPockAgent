"""Provider-neutral chat-completion requests with a local Ollama adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any, AsyncIterator, Mapping, Protocol, Sequence

import aiohttp


class ModelProviderError(RuntimeError):
    """A provider failed or returned an unusable completion."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


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
        options = dict(request.options or {})
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.top_p is not None:
            options["top_p"] = request.top_p
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        if request.context_window is not None:
            options["num_ctx"] = request.context_window
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [dict(message) for message in request.messages],
            "stream": stream,
            "options": options,
        }
        if request.response_format and request.response_format.get("type") == "json_object":
            payload["format"] = "json"
        return payload
