import os
import unittest
from unittest.mock import patch

import aiohttp

from projects.model_router import ChatCompletionRequest, ModelProviderError, OllamaChatCompletionAdapter, resolve_think
from projects.model_router.client import DEFAULT_CONTEXT_WINDOW_TOKENS, DEFAULT_KEEP_ALIVE


class FakeResponse:
    def __init__(self, *, status=200, result=None, text="", content=None):
        self.status = status
        self.result = result or {}
        self.response_text = text
        self.content = content or FakeContent([])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def json(self):
        return self.result

    async def text(self):
        return self.response_text


class FakeContent:
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


class FakeSession:
    response = FakeResponse()
    calls = []

    def __init__(self, *, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def post(self, url, *, json):
        self.calls.append((url, json, self.timeout))
        return self.response


class OllamaChatCompletionAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeSession.calls = []
        FakeSession.response = FakeResponse()
        self.adapter = OllamaChatCompletionAdapter("http://127.0.0.1:11434/")
        self.timeout = aiohttp.ClientTimeout(total=10)
        # These tests check the context PockPock asks for; a machine-wide Ollama default
        # (OLLAMA_CONTEXT_LENGTH, set by Setup) would replace it for a model that is not loaded.
        environment = patch.dict(os.environ, {"OLLAMA_CONTEXT_LENGTH": ""})
        environment.start()
        self.addCleanup(environment.stop)

    async def test_native_json_request_preserves_context_settings_and_normalizes_response(self):
        FakeSession.response = FakeResponse(result={
            "message": {"role": "assistant", "content": '{"steps": []}'},
            "done_reason": "stop",
        })
        with patch("projects.model_router.client.aiohttp.ClientSession", FakeSession):
            result = await self.adapter.complete(
                ChatCompletionRequest(
                    model="local-model",
                    messages=[{"role": "user", "content": "Plan this"}],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                    context_window=8192,
                    think=False,
                ),
                timeout=self.timeout,
            )

        url, payload, timeout = FakeSession.calls[0]
        self.assertEqual(url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(payload["format"], "json")
        self.assertIs(payload["think"], False)
        self.assertEqual(payload["options"], {"temperature": 0.1, "num_ctx": 8192})
        self.assertIs(timeout, self.timeout)
        self.assertEqual(result["choices"][0]["message"]["content"], '{"steps": []}')
        self.assertEqual(result["choices"][0]["finish_reason"], "stop")

    async def test_tool_request_uses_openai_compatible_endpoint(self):
        FakeSession.response = FakeResponse(result={"choices": [{"message": {"content": "ok"}}]})
        with patch("projects.model_router.client.aiohttp.ClientSession", FakeSession):
            result = await self.adapter.complete(
                ChatCompletionRequest(
                    model="local-model",
                    messages=[{"role": "user", "content": "Use a tool"}],
                    tools=[{"type": "function", "function": {"name": "read"}}],
                    max_tokens=8192,
                ),
                timeout=self.timeout,
            )

        url, payload, _ = FakeSession.calls[0]
        self.assertEqual(url, "http://127.0.0.1:11434/v1/chat/completions")
        self.assertEqual(payload["tools"][0]["function"]["name"], "read")
        self.assertEqual(payload["max_tokens"], 8192)
        self.assertEqual(result["choices"][0]["message"]["content"], "ok")

    async def test_tool_request_passes_think_false_to_openai_compatible_endpoint(self):
        # Issue #86: a thinking model returns no tool calls unless think is off.
        FakeSession.response = FakeResponse(result={"choices": [{"message": {"content": "ok"}}]})
        with patch("projects.model_router.client.aiohttp.ClientSession", FakeSession):
            await self.adapter.complete(
                ChatCompletionRequest(
                    model="qwen3.5:2b",
                    messages=[{"role": "user", "content": "Use a tool"}],
                    tools=[{"type": "function", "function": {"name": "read"}}],
                    think=False,
                ),
                timeout=self.timeout,
            )

        _, payload, _ = FakeSession.calls[0]
        self.assertIs(payload["think"], False)

    async def test_openai_compatible_request_omits_think_when_unset(self):
        FakeSession.response = FakeResponse(result={"choices": [{"message": {"content": "ok"}}]})
        with patch("projects.model_router.client.aiohttp.ClientSession", FakeSession):
            await self.adapter.complete(
                ChatCompletionRequest(
                    model="local-model",
                    messages=[{"role": "user", "content": "Use a tool"}],
                    tools=[{"type": "function", "function": {"name": "read"}}],
                ),
                timeout=self.timeout,
            )

        _, payload, _ = FakeSession.calls[0]
        self.assertNotIn("think", payload)


    async def test_streaming_uses_shared_adapter_and_preserves_extra_local_options(self):
        FakeSession.response = FakeResponse(content=FakeContent([
            b'{"message":{"content":"Hello"}}\n',
            b'{"message":{"content":" world"}}\n',
            b'{"done":true}\n',
        ]))
        with patch("projects.model_router.client.aiohttp.ClientSession", FakeSession):
            tokens = [
                token async for token in self.adapter.stream_tokens(
                    ChatCompletionRequest(
                        model="local-model",
                        messages=[{"role": "user", "content": "hello"}],
                        temperature=0.4,
                        top_p=0.8,
                        options={"repeat_penalty": 1.1},
                    ),
                    timeout=self.timeout,
                )
            ]

        url, payload, _ = FakeSession.calls[0]
        self.assertEqual(url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(payload["options"], {
            "repeat_penalty": 1.1,
            "temperature": 0.4,
            "top_p": 0.8,
            # Requests that do not set a window get the 16K default, so
            # ordinary turns are not truncated by Ollama's 4K default.
            "num_ctx": DEFAULT_CONTEXT_WINDOW_TOKENS,
        })
        self.assertEqual(payload["keep_alive"], DEFAULT_KEEP_ALIVE)
        self.assertTrue(payload["stream"])
        self.assertEqual(tokens, ["Hello", " world"])

    async def test_native_request_sets_default_keep_alive_and_context(self):
        FakeSession.response = FakeResponse(result={
            "message": {"role": "assistant", "content": "hi"},
            "done_reason": "stop",
        })
        with patch("projects.model_router.client.aiohttp.ClientSession", FakeSession):
            await self.adapter.complete(
                ChatCompletionRequest(
                    model="local-model",
                    messages=[{"role": "user", "content": "hello"}],
                ),
                timeout=self.timeout,
            )

        _, payload, _ = FakeSession.calls[0]
        self.assertEqual(payload["keep_alive"], "30m")
        self.assertEqual(payload["options"]["num_ctx"], 16_384)

    async def test_native_request_prefers_explicit_keep_alive_and_context(self):
        FakeSession.response = FakeResponse(result={
            "message": {"role": "assistant", "content": "hi"},
            "done_reason": "stop",
        })
        with patch("projects.model_router.client.aiohttp.ClientSession", FakeSession):
            await self.adapter.complete(
                ChatCompletionRequest(
                    model="local-model",
                    messages=[{"role": "user", "content": "hello"}],
                    context_window=8192,
                    keep_alive="5m",
                ),
                timeout=self.timeout,
            )

        _, payload, _ = FakeSession.calls[0]
        self.assertEqual(payload["keep_alive"], "5m")
        self.assertEqual(payload["options"]["num_ctx"], 8192)

    async def test_keep_alive_and_context_defaults_are_env_overridable(self):
        FakeSession.response = FakeResponse(result={
            "message": {"role": "assistant", "content": "hi"},
            "done_reason": "stop",
        })
        with (
            patch.dict(os.environ, {"POCKPOCK_OLLAMA_KEEP_ALIVE": "1h", "POCKPOCK_NUM_CTX": "8192"}),
            patch("projects.model_router.client.aiohttp.ClientSession", FakeSession),
        ):
            await self.adapter.complete(
                ChatCompletionRequest(
                    model="local-model",
                    messages=[{"role": "user", "content": "hello"}],
                ),
                timeout=self.timeout,
            )

        _, payload, _ = FakeSession.calls[0]
        self.assertEqual(payload["keep_alive"], "1h")
        self.assertEqual(payload["options"]["num_ctx"], 8192)

    async def test_invalid_num_ctx_env_falls_back_to_default(self):
        FakeSession.response = FakeResponse(result={
            "message": {"role": "assistant", "content": "hi"},
            "done_reason": "stop",
        })
        with (
            patch.dict(os.environ, {"POCKPOCK_NUM_CTX": "not-a-number"}),
            patch("projects.model_router.client.aiohttp.ClientSession", FakeSession),
        ):
            await self.adapter.complete(
                ChatCompletionRequest(
                    model="local-model",
                    messages=[{"role": "user", "content": "hello"}],
                ),
                timeout=self.timeout,
            )

        _, payload, _ = FakeSession.calls[0]
        self.assertEqual(payload["options"]["num_ctx"], DEFAULT_CONTEXT_WINDOW_TOKENS)

    async def test_tool_request_sets_keep_alive_and_context_options(self):
        # The OpenAI-compatible tool path previously sent neither, so agent
        # turns ran on Ollama's 4K default and unloaded after 5 idle minutes.
        FakeSession.response = FakeResponse(result={"choices": [{"message": {"content": "ok"}}]})
        with patch("projects.model_router.client.aiohttp.ClientSession", FakeSession):
            await self.adapter.complete(
                ChatCompletionRequest(
                    model="local-model",
                    messages=[{"role": "user", "content": "Use a tool"}],
                    tools=[{"type": "function", "function": {"name": "read"}}],
                ),
                timeout=self.timeout,
            )

        url, payload, _ = FakeSession.calls[0]
        self.assertEqual(url, "http://127.0.0.1:11434/v1/chat/completions")
        self.assertEqual(payload["keep_alive"], "30m")
        self.assertEqual(payload["options"]["num_ctx"], 16_384)

    async def test_provider_http_failure_is_explicit(self):
        FakeSession.response = FakeResponse(status=503, text="temporarily unavailable")
        with patch("projects.model_router.client.aiohttp.ClientSession", FakeSession):
            with self.assertRaisesRegex(ModelProviderError, "HTTP 503"):
                await self.adapter.complete(
                    ChatCompletionRequest(
                        model="local-model",
                        messages=[{"role": "user", "content": "hello"}],
                    ),
                    timeout=self.timeout,
                )


class ResolveThinkTests(unittest.TestCase):
    def test_qwen35_models_disable_thinking(self):
        for model in ("qwen3.5:2b", "qwen3.5:9b", "qwen3.5-9b-text:latest", "qwen3:8b"):
            self.assertIs(resolve_think(model), False, model)

    def test_other_models_keep_their_default(self):
        for model in ("qwen2.5:14b", "llama3.1:8b", "mistral-nemo:12b", None):
            self.assertIsNone(resolve_think(model), model)

    def test_tool_and_json_turns_disable_thinking_for_any_model(self):
        self.assertIs(resolve_think("qwen2.5:14b", tools=True), False)
        self.assertIs(resolve_think("llama3.1:8b", json_output=True), False)

    def test_explicit_reasoning_keeps_thinking_on(self):
        self.assertIsNone(resolve_think("qwen3.5:2b", explicit_reasoning=True))
        self.assertIsNone(resolve_think("qwen3.5:2b", tools=True, explicit_reasoning=True))


if __name__ == "__main__":
    unittest.main()
