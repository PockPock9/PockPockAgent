import asyncio
import json
import os
import socket
import threading
import time
import unittest
from unittest.mock import patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from fastapi import FastAPI
import uvicorn

from projects.model_router import ChatCompletionRequest, ModelProviderError
from projects.model_router.cloud import (
    adapt_body,
    CloudRegistry,
    OpenAICompatibleAdapter,
    RegistryCloudProvider,
    RoutingChatCompletionProvider,
    is_cloud_model,
    split_cloud_model,
)
from projects.model_router.cloud_api import create_cloud_router

TIMEOUT = aiohttp.ClientTimeout(total=10)


class NamesTest(unittest.TestCase):
    def test_cloud_names_carry_a_known_provider_prefix(self):
        self.assertEqual(split_cloud_model("nim/meta/llama-3.3-70b-instruct"), ("nim", "meta/llama-3.3-70b-instruct"))
        self.assertEqual(split_cloud_model("anthropic/claude-sonnet-5-5"), ("anthropic", "claude-sonnet-5-5"))
        self.assertTrue(is_cloud_model("alibaba/qwen-max"))
        for local in ("qwen3.5:9b", "hf.co/user/model:Q4", "ollama/qwen3.5:9b", "nim/", "nim/ bad", "", None):
            self.assertFalse(is_cloud_model(local), local)


class AdaptBodyTest(unittest.TestCase):
    def test_claude_drops_what_its_openai_endpoint_refuses(self):
        body = {"model": "claude-opus-5-5", "messages": [], "temperature": 0.2, "top_p": 0.9, "n": 1, "tool_choice": {"type": "function", "function": {"name": "x"}}, "response_format": {"type": "json_object"}, "max_tokens": 100}
        self.assertEqual(adapt_body("anthropic", body), {"model": "claude-opus-5-5", "messages": [], "tool_choice": "auto", "max_tokens": 100})
        strict = {"type": "json_schema", "json_schema": {"name": "x", "strict": True, "schema": {"type": "object"}}}
        self.assertEqual(adapt_body("anthropic", {"response_format": strict, "tool_choice": "none"}), {"response_format": strict, "tool_choice": "none"})
        self.assertIn("temperature", body, "the caller's body is not changed")

    def test_openai_reasoning_models_get_their_parameter_names(self):
        self.assertEqual(adapt_body("openai", {"model": "gpt-5.1", "max_tokens": 50, "temperature": 0.2}), {"model": "gpt-5.1", "max_completion_tokens": 50})
        self.assertEqual(adapt_body("openai", {"model": "o4-mini", "top_p": 0.5}), {"model": "o4-mini"})
        self.assertEqual(adapt_body("openai", {"model": "gpt-4.1", "max_tokens": 50, "temperature": 0.2}), {"model": "gpt-4.1", "max_tokens": 50, "temperature": 0.2})
        self.assertEqual(adapt_body("nim", {"model": "x", "temperature": 0.2}), {"model": "x", "temperature": 0.2})


class RegistryTest(unittest.TestCase):
    def test_keys_go_only_to_the_providers_own_addresses(self):
        registry = CloudRegistry()
        good = {"id": "nim", "base_url": "https://integrate.api.nvidia.com/v1", "api_key": "nvapi-abc", "models": [{"id": "meta/llama-3.3-70b-instruct", "context_window": 131072}]}
        registry.replace([good], proxy_token="p" * 32)
        self.assertEqual(registry.models(), [{"name": "nim/meta/llama-3.3-70b-instruct", "provider": "nim", "provider_label": "NVIDIA NIM", "context_window": 131072}])
        self.assertNotIn("nvapi-abc", json.dumps(registry.models()))
        for bad_url in ("https://evil.example/v1", "http://integrate.api.nvidia.com/v1", "https://user:pw@integrate.api.nvidia.com/v1", "https://api.anthropic.com/v1", "http://127.0.0.1:9/v1"):
            with self.assertRaises(ValueError, msg=bad_url):
                registry.replace([{**good, "base_url": bad_url}])
        with self.assertRaises(ValueError):
            registry.replace([{**good, "id": "other"}])
        with self.assertRaises(ValueError):
            registry.replace([{**good, "api_key": "has space"}])
        # A failed replace keeps the earlier configuration.
        self.assertTrue(registry.has("nim/meta/llama-3.3-70b-instruct"))

    def test_only_connected_and_chosen_models_resolve(self):
        registry = CloudRegistry()
        registry.replace([{"id": "anthropic", "base_url": "https://api.anthropic.com/v1", "api_key": "sk-ant-1", "models": ["qwen/qwen3-coder", {"id": "bad id"}]}])
        provider, model = registry.resolve("anthropic/qwen/qwen3-coder")
        self.assertEqual((provider.id, model), ("anthropic", "qwen/qwen3-coder"))
        self.assertEqual(len(registry.models()), 1)
        self.assertIn("tools", registry.profile("anthropic/qwen/qwen3-coder")["capabilities"])
        self.assertIsNone(registry.profile("anthropic/other/model"))
        for name in ("anthropic/other/model", "nim/meta/llama-3.3-70b-instruct", "qwen3.5:9b"):
            with self.assertRaises(ModelProviderError):
                registry.resolve(name)
        self.assertNotIn("sk-ant-1", repr(provider))


def _fake_provider(seen: list):
    async def chat(request: web.Request):
        body = await request.json()
        seen.append({"auth": request.headers.get("Authorization"), "body": body, "title": request.headers.get("X-Title")})
        if body["model"] == "broken":
            return web.json_response({"error": {"message": "Invalid API key"}}, status=401)
        if body.get("stream"):
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            for token in ("Hel", "lo"):
                await response.write(f'data: {json.dumps({"choices": [{"delta": {"content": token}}]})}\n\n'.encode())
            await response.write(b": keep-alive\n\ndata: [DONE]\n\n")
            return response
        return web.json_response({"choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi"}, "finish_reason": "stop"}]})

    app = web.Application()
    app.router.add_post("/v1/chat/completions", chat)
    return app


class AdapterTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seen: list = []
        self.server = TestServer(_fake_provider(self.seen))
        await self.server.start_server()
        self.base = f"http://127.0.0.1:{self.server.port}/v1"
        self.registry = CloudRegistry(extra_hosts=["127.0.0.1"])
        self.registry.replace([{"id": "anthropic", "base_url": self.base, "api_key": "sk-test", "models": ["vendor/model-a", "broken"]}], proxy_token="t" * 32)

    async def asyncTearDown(self):
        await self.server.close()

    async def test_complete_sends_the_upstream_model_and_key(self):
        provider = RegistryCloudProvider(self.registry)
        request = ChatCompletionRequest(model="anthropic/vendor/model-a", messages=[{"role": "user", "content": "hi", "images": ["QUJD"]}], temperature=0.2, think=False, context_window=4096)
        result = await provider.complete(request, timeout=TIMEOUT)
        self.assertEqual(result["choices"][0]["message"]["content"], "Hi")
        sent = self.seen[0]
        self.assertEqual(sent["auth"], "Bearer sk-test")
        self.assertEqual(sent["body"]["model"], "vendor/model-a")
        self.assertEqual(sent["body"]["messages"][0]["content"][1]["image_url"]["url"], "data:image/png;base64,QUJD")
        self.assertNotIn("think", sent["body"])
        self.assertNotIn("options", sent["body"])
        # Current Claude models refuse a temperature below 1, so it is not sent to Anthropic.
        self.assertNotIn("temperature", sent["body"])

    async def test_stream_yields_tokens_and_errors_are_explained(self):
        provider = RegistryCloudProvider(self.registry)
        tokens = [token async for token in provider.stream_tokens(ChatCompletionRequest(model="anthropic/vendor/model-a", messages=[{"role": "user", "content": "hi"}]), timeout=TIMEOUT)]
        self.assertEqual(tokens, ["Hel", "lo"])
        with self.assertRaises(ModelProviderError) as caught:
            await provider.complete(ChatCompletionRequest(model="anthropic/broken", messages=[{"role": "user", "content": "hi"}]), timeout=TIMEOUT)
        self.assertEqual(caught.exception.status_code, 401)
        self.assertIn("Check the API key", str(caught.exception))
        self.assertNotIn("sk-test", str(caught.exception))

    async def test_routing_keeps_local_names_local(self):
        class Local:
            async def complete(self, request, *, timeout):
                return {"choices": [{"message": {"content": f"local:{request.model}"}}]}

        routed = RoutingChatCompletionProvider(Local(), RegistryCloudProvider(self.registry))
        local = await routed.complete(ChatCompletionRequest(model="qwen3.5:9b", messages=[]), timeout=TIMEOUT)
        self.assertEqual(local["choices"][0]["message"]["content"], "local:qwen3.5:9b")
        cloud = await routed.complete(ChatCompletionRequest(model="anthropic/vendor/model-a", messages=[{"role": "user", "content": "x"}]), timeout=TIMEOUT)
        self.assertEqual(cloud["choices"][0]["message"]["content"], "Hi")

    async def test_local_endpoint_needs_a_token_and_hides_the_key(self):
        app = FastAPI()
        app.include_router(create_cloud_router(self.registry))
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(0.05)
            url = f"http://127.0.0.1:{port}"
            with patch.dict(os.environ, {"POCKPOCK_INTERNAL_TOKEN": "internal-token-value"}):
                async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                    body = {"model": "anthropic/vendor/model-a", "messages": [{"role": "user", "content": "hi"}]}
                    async with session.post(f"{url}/cloud/v1/chat/completions", json=body) as response:
                        self.assertEqual(response.status, 401)
                    async with session.post(f"{url}/cloud/v1/chat/completions", json=body, headers={"Authorization": "Bearer wrong"}) as response:
                        self.assertEqual(response.status, 401)
                    headers = {"Authorization": f"Bearer {'t' * 32}"}
                    async with session.post(f"{url}/cloud/v1/chat/completions", json=body, headers=headers) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual((await response.json())["choices"][0]["message"]["content"], "Hi")
                    self.assertEqual(self.seen[-1]["auth"], "Bearer sk-test")
                    self.assertEqual(self.seen[-1]["body"]["model"], "vendor/model-a")
                    # OpenClaw's own request body is fitted to Claude too.
                    async with session.post(f"{url}/cloud/v1/chat/completions", json={**body, "temperature": 0.1, "top_p": 0.9, "tool_choice": "required", "tools": []}, headers=headers) as response:
                        self.assertEqual(response.status, 200)
                    self.assertEqual({key: self.seen[-1]["body"].get(key) for key in ("temperature", "top_p", "tool_choice")}, {"temperature": None, "top_p": None, "tool_choice": "auto"})
                    async with session.post(f"{url}/cloud/v1/chat/completions", json={**body, "stream": True}, headers={"Authorization": "Bearer internal-token-value"}) as response:
                        text = await response.text()
                        self.assertIn('"content": "Hel"', text)
                        self.assertIn("[DONE]", text)
                    async with session.post(f"{url}/cloud/v1/chat/completions", json={**body, "model": "nim/not/connected"}, headers=headers) as response:
                        self.assertEqual(response.status, 409)
                    async with session.post(f"{url}/cloud/v1/chat/completions", json={**body, "model": "anthropic/broken"}, headers=headers) as response:
                        self.assertEqual(response.status, 401)
                    async with session.get(f"{url}/cloud/v1/models", headers=headers) as response:
                        self.assertEqual([item["id"] for item in (await response.json())["data"]], ["anthropic/vendor/model-a", "anthropic/broken"])
                    async with session.get(f"{url}/api/cloud/models") as response:
                        listing = await response.text()
                        self.assertIn("anthropic/vendor/model-a", listing)
                        self.assertNotIn("sk-test", listing)
                    push = {"providers": [], "proxy_token": ""}
                    async with session.put(f"{url}/api/cloud/config", json=push) as response:
                        self.assertEqual(response.status, 401)
                    async with session.put(f"{url}/api/cloud/config", json=push, headers={"X-PockPock-Internal-Token": "internal-token-value"}) as response:
                        self.assertEqual(response.status, 200)
                    self.assertEqual(self.registry.models(), [])
        finally:
            server.should_exit = True
            deadline = time.time() + 5
            while thread.is_alive() and time.time() < deadline:
                await asyncio.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
