import unittest
from unittest.mock import patch

import aiohttp

from projects.model_router import ChatCompletionRequest, ModelProviderError, OllamaChatCompletionAdapter


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
        })
        self.assertTrue(payload["stream"])
        self.assertEqual(tokens, ["Hello", " world"])

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


if __name__ == "__main__":
    unittest.main()
