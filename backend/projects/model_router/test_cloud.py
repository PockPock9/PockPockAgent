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
        self.assertEqual(split_cloud_model("openrouter/deepseek/deepseek-r1:free"), ("openrouter", "deepseek/deepseek-r1:free"))
        self.assertTrue(is_cloud_model("alibaba/qwen-max"))
        for local in ("qwen3.5:9b", "hf.co/user/model:Q4", "ollama/qwen3.5:9b", "nim/", "nim/ bad", "", None):
            self.assertFalse(is_cloud_model(local), local)


class RegistryTest(unittest.TestCase):
    def test_keys_go_only_to_the_providers_own_addresses(self):
        registry = CloudRegistry()
        good = {"id": "nim", "base_url": "https://integrate.api.nvidia.com/v1", "api_key": "nvapi-abc", "models": [{"id": "meta/llama-3.3-70b-instruct", "context_window": 131072}]}
        registry.replace([good], proxy_token="p" * 32)
        self.assertEqual(registry.models(), [{"name": "nim/meta/llama-3.3-70b-instruct", "provider": "nim", "provider_label": "NVIDIA NIM", "context_window": 131072}])
        self.assertNotIn("nvapi-abc", json.dumps(registry.models()))
        for bad_url in ("https://evil.example/v1", "http://integrate.api.nvidia.com/v1", "https://user:pw@integrate.api.nvidia.com/v1", "https://openrouter.ai/api/v1", "http://127.0.0.1:9/v1"):
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
        registry.replace([{"id": "openrouter", "base_url": "https://openrouter.ai/api/v1", "api_key": "sk-or-1", "models": ["qwen/qwen3-coder", {"id": "bad id"}]}])
        provider, model = registry.resolve("openrouter/qwen/qwen3-coder")
        self.assertEqual((provider.id, model), ("openrouter", "qwen/qwen3-coder"))
        self.assertEqual(len(registry.models()), 1)
        self.assertIn("tools", registry.profile("openrouter/qwen/qwen3-coder")["capabilities"])
        self.assertIsNone(registry.profile("openrouter/other/model"))
        for name in ("openrouter/other/model", "nim/meta/llama-3.3-70b-instruct", "qwen3.5:9b"):
            with self.assertRaises(ModelProviderError):
                registry.resolve(name)
        self.assertNotIn("sk-or-1", repr(provider))


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
        self.registry.replace([{"id": "openrouter", "base_url": self.base, "api_key": "sk-test", "models": ["vendor/model-a", "broken"]}], proxy_token="t" * 32)

    async def asyncTearDown(self):
        await self.server.close()

    async def test_complete_sends_the_upstream_model_and_key(self):
        provider = RegistryCloudProvider(self.registry)
        request = ChatCompletionRequest(model="openrouter/vendor/model-a", messages=[{"role": "user", "content": "hi", "images": ["QUJD"]}], temperature=0.2, think=False, context_window=4096)
        result = await provider.complete(request, timeout=TIMEOUT)
        self.assertEqual(result["choices"][0]["message"]["content"], "Hi")
        sent = self.seen[0]
        self.assertEqual(sent["auth"], "Bearer sk-test")
        self.assertEqual(sent["title"], "PockPock Agent")
        self.assertEqual(sent["body"]["model"], "vendor/model-a")
        self.assertEqual(sent["body"]["messages"][0]["content"][1]["image_url"]["url"], "data:image/png;base64,QUJD")
        self.assertNotIn("think", sent["body"])
        self.assertNotIn("options", sent["body"])

    async def test_stream_yields_tokens_and_errors_are_explained(self):
        provider = RegistryCloudProvider(self.registry)
        tokens = [token async for token in provider.stream_tokens(ChatCompletionRequest(model="openrouter/vendor/model-a", messages=[{"role": "user", "content": "hi"}]), timeout=TIMEOUT)]
        self.assertEqual(tokens, ["Hel", "lo"])
        with self.assertRaises(ModelProviderError) as caught:
            await provider.complete(ChatCompletionRequest(model="openrouter/broken", messages=[{"role": "user", "content": "hi"}]), timeout=TIMEOUT)
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
        cloud = await routed.complete(ChatCompletionRequest(model="openrouter/vendor/model-a", messages=[{"role": "user", "content": "x"}]), timeout=TIMEOUT)
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
                    body = {"model": "openrouter/vendor/model-a", "messages": [{"role": "user", "content": "hi"}]}
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
                    async with session.post(f"{url}/cloud/v1/chat/completions", json={**body, "stream": True}, headers={"Authorization": "Bearer internal-token-value"}) as response:
                        text = await response.text()
                        self.assertIn('"content": "Hel"', text)
                        self.assertIn("[DONE]", text)
                    async with session.post(f"{url}/cloud/v1/chat/completions", json={**body, "model": "nim/not/connected"}, headers=headers) as response:
                        self.assertEqual(response.status, 409)
                    async with session.post(f"{url}/cloud/v1/chat/completions", json={**body, "model": "openrouter/broken"}, headers=headers) as response:
                        self.assertEqual(response.status, 401)
                    async with session.get(f"{url}/cloud/v1/models", headers=headers) as response:
                        self.assertEqual([item["id"] for item in (await response.json())["data"]], ["openrouter/vendor/model-a", "openrouter/broken"])
                    async with session.get(f"{url}/api/cloud/models") as response:
                        listing = await response.text()
                        self.assertIn("openrouter/vendor/model-a", listing)
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
