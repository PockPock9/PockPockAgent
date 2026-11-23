"""Cloud model providers behind the shared chat-completion contract.

Cloud models are named ``<provider>/<model id>`` (for example ``nim/meta/llama-3.3-70b-instruct``).
The desktop app owns the API keys (encrypted on disk) and pushes the connected providers to the
gateway, which keeps them in memory only. Every provider speaks the OpenAI chat-completions API.
A cloud model is used only when it is chosen by name; automatic routing never selects one.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import re
from typing import Any, AsyncIterator, Mapping, Sequence
from urllib.parse import urlsplit

import aiohttp

from .client import ChatCompletionProvider, ChatCompletionRequest, ModelProviderError

# Provider id -> hosts its API may be served from. A pushed base URL outside this list is refused,
# so a mistaken or hostile configuration cannot make the gateway send a key somewhere else.
PROVIDER_HOSTS: dict[str, tuple[str, ...]] = {
    "nim": ("integrate.api.nvidia.com",),
    "openai": ("api.openai.com",),
    "anthropic": ("api.anthropic.com",),
    "alibaba": ("dashscope-intl.aliyuncs.com", "dashscope.aliyuncs.com", "dashscope-us.aliyuncs.com"),
}
PROVIDER_LABELS = {"nim": "NVIDIA NIM", "openai": "OpenAI", "anthropic": "Claude (Anthropic)", "alibaba": "Alibaba Cloud Model Studio"}
CLOUD_MODEL = re.compile(r"^(nim|openai|anthropic|alibaba)/([A-Za-z0-9][A-Za-z0-9._:/-]{0,87})$")
# OpenAI's reasoning models (o-series, GPT-5 and later) take max_completion_tokens and only the default temperature.
_OPENAI_REASONING = re.compile(r"^(o\d|gpt-[5-9])")


def adapt_body(provider_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Fit an OpenAI-style chat body to what the provider accepts. Returns a new dict.

    Claude is reached through Anthropic's OpenAI-compatible endpoint
    (https://api.anthropic.com/v1/chat/completions). Checked against its documentation on 2026-11-22:
    current Claude models refuse ``temperature`` below 1 and any ``top_p`` (400), some refuse a forced
    tool call (``tool_choice`` "required" or a named function), and ``response_format`` is accepted only
    as ``json_schema`` with ``strict: true``. Those fields are dropped or relaxed so a request written
    for any provider still works; ``n`` must be 1.
    """
    out = dict(body)
    if provider_id == "anthropic":
        out.pop("temperature", None)
        out.pop("top_p", None)
        if "tool_choice" in out and out["tool_choice"] not in ("auto", "none"):
            out["tool_choice"] = "auto"
        response_format = out.get("response_format")
        if response_format is not None and not (isinstance(response_format, Mapping) and response_format.get("type") == "json_schema" and isinstance(response_format.get("json_schema"), Mapping) and response_format["json_schema"].get("strict") is True):
            out.pop("response_format", None)
        out.pop("n", None)
    elif provider_id == "openai" and _OPENAI_REASONING.match(str(out.get("model") or "")):
        if "max_tokens" in out:
            out.setdefault("max_completion_tokens", out.pop("max_tokens"))
        out.pop("temperature", None)
        out.pop("top_p", None)
    return out
MAX_MODELS_PER_PROVIDER = 60


def split_cloud_model(name: str | None) -> tuple[str, str] | None:
    """``("nim", "meta/llama-3.3-70b-instruct")`` for a cloud model name, otherwise ``None``."""
    match = CLOUD_MODEL.fullmatch(name or "")
    return (match.group(1), match.group(2)) if match else None


def is_cloud_model(name: str | None) -> bool:
    return split_cloud_model(name) is not None


@dataclass(frozen=True)
class CloudProvider:
    id: str
    base_url: str
    api_key: str = field(repr=False)
    models: tuple[dict[str, Any], ...] = ()

    @property
    def label(self) -> str:
        return PROVIDER_LABELS.get(self.id, self.id)


def _valid_base_url(provider_id: str, base_url: str, extra_hosts: Sequence[str]) -> str:
    parts = urlsplit(base_url)
    host = (parts.hostname or "").lower()
    allowed = {*PROVIDER_HOSTS.get(provider_id, ()), *extra_hosts}
    local_test = host in {"127.0.0.1", "localhost"} and host in extra_hosts
    if host not in allowed or (parts.scheme != "https" and not local_test) or parts.username or parts.password:
        raise ValueError(f"The address for {provider_id} is not one of its known API addresses.")
    return base_url.rstrip("/")


class CloudRegistry:
    """The connected cloud providers and the models chosen for the pickers. Keys stay in memory."""

    def __init__(self, *, extra_hosts: Sequence[str] = ()):
        self._providers: dict[str, CloudProvider] = {}
        self._extra_hosts = tuple(host.lower() for host in extra_hosts)
        self.proxy_token = ""

    def replace(self, providers: Sequence[Mapping[str, Any]], *, proxy_token: str = "") -> None:
        """Replace everything with a pushed configuration. Raises ``ValueError`` on bad input."""
        parsed: dict[str, CloudProvider] = {}
        for item in providers:
            provider_id = str(item.get("id") or "")
            if provider_id not in PROVIDER_HOSTS:
                raise ValueError("Unknown cloud provider.")
            api_key = str(item.get("api_key") or "").strip()
            if not api_key or len(api_key) > 400 or any(char.isspace() for char in api_key):
                raise ValueError(f"The API key for {provider_id} is missing or not valid.")
            models = []
            for model in list(item.get("models") or [])[:MAX_MODELS_PER_PROVIDER]:
                model_id = str(model.get("id") if isinstance(model, Mapping) else model)
                if not is_cloud_model(f"{provider_id}/{model_id}"):
                    continue
                context = model.get("context_window") if isinstance(model, Mapping) else None
                models.append({"id": model_id, "context_window": context if isinstance(context, int) and context > 0 else None})
            parsed[provider_id] = CloudProvider(
                id=provider_id,
                base_url=_valid_base_url(provider_id, str(item.get("base_url") or ""), self._extra_hosts),
                api_key=api_key,
                models=tuple(models),
            )
        self._providers = parsed
        self.proxy_token = proxy_token if 20 <= len(proxy_token) <= 200 else ""

    def models(self) -> list[dict[str, Any]]:
        """The models to offer, without keys: ``name``, ``provider``, ``provider_label``, ``context_window``."""
        return [
            {"name": f"{provider.id}/{model['id']}", "provider": provider.id, "provider_label": provider.label, "context_window": model["context_window"]}
            for provider in self._providers.values() for model in provider.models
        ]

    def has(self, name: str | None) -> bool:
        return any(item["name"] == name for item in self.models())

    def profile(self, name: str) -> dict[str, Any] | None:
        """A planner model profile for a chosen cloud model. Cloud models are treated as tool-capable."""
        for item in self.models():
            if item["name"] == name:
                return {"name": name, "capabilities": ["completion", "tools"], "context_window": item["context_window"], "parameter_billions": None, "avg_latency_ms": None, "cloud": True}
        return None

    def resolve(self, name: str) -> tuple[CloudProvider, str]:
        parts = split_cloud_model(name)
        provider = self._providers.get(parts[0]) if parts else None
        if not parts or provider is None:
            raise ModelProviderError("That cloud provider is not connected. Connect it on the Cloud page.", status_code=409)
        if not any(model["id"] == parts[1] for model in provider.models):
            raise ModelProviderError("That cloud model is not switched on. Choose it on the Cloud page.", status_code=409)
        return provider, parts[1]


def _openai_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Ollama-style ``images`` (base64 strings) become OpenAI image parts."""
    converted = []
    for message in messages:
        item = dict(message)
        images = item.pop("images", None)
        if images and isinstance(item.get("content"), str):
            item["content"] = [
                {"type": "text", "text": item["content"]},
                *({"type": "image_url", "image_url": {"url": image if str(image).startswith("data:") else f"data:image/png;base64,{image}"}} for image in images),
            ]
        converted.append(item)
    return converted


def _error_detail(status: int, body: str) -> str:
    detail = body
    try:
        parsed = json.loads(body)
        error = parsed.get("error") if isinstance(parsed, dict) else None
        detail = str((error.get("message") if isinstance(error, dict) else error) or parsed.get("message") or body)
    except (ValueError, AttributeError):
        pass
    hint = {401: " Check the API key on the Cloud page.", 402: " The account has no credit left.", 403: " The key is not allowed to use this model.", 429: " The provider's rate limit or quota was reached."}.get(status, "")
    return f"Cloud model request failed (HTTP {status}): {detail.strip()[:240]}{hint}"


class OpenAICompatibleAdapter:
    """Chat completions against one OpenAI-compatible endpoint."""

    def __init__(self, base_url: str, api_key: str, *, headers: Mapping[str, str] | None = None, provider_id: str = ""):
        self.base_url = base_url.rstrip("/")
        self.provider_id = provider_id
        self._headers = {"Authorization": f"Bearer {api_key}", **(headers or {})}

    def _payload(self, request: ChatCompletionRequest, *, model: str | None, stream: bool) -> dict[str, Any]:
        payload = request.to_payload()
        payload["messages"] = _openai_messages(request.messages)
        if model:
            payload["model"] = model
        if stream:
            payload["stream"] = True
        return adapt_body(self.provider_id, payload)

    async def complete(self, request: ChatCompletionRequest, *, timeout: aiohttp.ClientTimeout, model: str | None = None) -> dict[str, Any]:
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self.base_url}/chat/completions", json=self._payload(request, model=model, stream=False), headers=self._headers) as response:
                    if response.status >= 400:
                        raise ModelProviderError(_error_detail(response.status, await response.text()), status_code=response.status)
                    result = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise ModelProviderError(f"Cloud model request failed: {err or type(err).__name__}") from err
        if not isinstance(result, dict) or not isinstance(result.get("choices"), list) or not result["choices"]:
            raise ModelProviderError("The cloud model returned an invalid completion response")
        return result

    async def stream_tokens(self, request: ChatCompletionRequest, *, timeout: aiohttp.ClientTimeout, model: str | None = None) -> AsyncIterator[str]:
        if request.tools is not None:
            raise ModelProviderError("Streaming tool calls are not supported by this adapter")
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self.base_url}/chat/completions", json=self._payload(request, model=model, stream=True), headers=self._headers) as response:
                    if response.status >= 400:
                        raise ModelProviderError(_error_detail(response.status, await response.text()), status_code=response.status)
                    async for raw in response.content:
                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            token = chunk["choices"][0].get("delta", {}).get("content")
                        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                            continue
                        if isinstance(token, str) and token:
                            yield token
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ModelProviderError(f"Cloud model request failed: {err or type(err).__name__}") from err


class RegistryCloudProvider:
    """Sends a cloud-named request to its provider, using the key held in the registry."""

    def __init__(self, registry: CloudRegistry):
        self.registry = registry

    def _adapter(self, name: str) -> tuple[OpenAICompatibleAdapter, str]:
        provider, model = self.registry.resolve(name)
        return OpenAICompatibleAdapter(provider.base_url, provider.api_key, provider_id=provider.id), model

    async def complete(self, request: ChatCompletionRequest, *, timeout: aiohttp.ClientTimeout) -> dict[str, Any]:
        adapter, model = self._adapter(request.model)
        return await adapter.complete(request, timeout=timeout, model=model)

    async def stream_tokens(self, request: ChatCompletionRequest, *, timeout: aiohttp.ClientTimeout) -> AsyncIterator[str]:
        adapter, model = self._adapter(request.model)
        async for token in adapter.stream_tokens(request, timeout=timeout, model=model):
            yield token


class RoutingChatCompletionProvider:
    """Local models go to the local provider; ``<provider>/<model>`` cloud names go to the cloud one."""

    def __init__(self, local: ChatCompletionProvider, cloud: ChatCompletionProvider):
        self.local = local
        self.cloud = cloud

    def _pick(self, request: ChatCompletionRequest) -> ChatCompletionProvider:
        return self.cloud if is_cloud_model(request.model) else self.local

    async def complete(self, request: ChatCompletionRequest, *, timeout: aiohttp.ClientTimeout) -> dict[str, Any]:
        return await self._pick(request).complete(request, timeout=timeout)

    async def stream_tokens(self, request: ChatCompletionRequest, *, timeout: aiohttp.ClientTimeout) -> AsyncIterator[str]:
        async for token in self._pick(request).stream_tokens(request, timeout=timeout):
            yield token
