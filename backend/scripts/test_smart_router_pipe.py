import unittest
from unittest.mock import AsyncMock

from scripts.smart_router_pipe import Pipe


class FakeModelClient:
    def __init__(self):
        self.requests = []

    async def stream_tokens(self, request, *, timeout):
        self.requests.append((request, timeout))
        yield "local response"


class SmartRouterPipeTests(unittest.IsolatedAsyncioTestCase):
    async def test_injected_model_client_streams_the_routed_request(self):
        client = FakeModelClient()
        pipe = Pipe(model_client=client)
        pipe._queue_dashboard_event = lambda event: None
        pipe._complete_dashboard_event = AsyncMock()
        pipe._dashboard_override = AsyncMock(return_value=None)
        pipe._heuristic_check = lambda _text, _messages: {
            "category": "quick",
            "reason": "test route",
            "confidence": 1.0,
            "complexity": 1,
            "model": "quick-local-model",
        }
        pipe.valves.show_telemetry_hud = False

        output = [
            item async for item in pipe.pipe(
                {"messages": [{"role": "user", "content": "hello"}]}
            )
        ]

        self.assertEqual(output, ["local response"])
        self.assertEqual(len(client.requests), 1)
        request, timeout = client.requests[0]
        self.assertEqual(request.model, "quick-local-model")
        self.assertEqual(request.messages[-1]["content"], "hello")
        self.assertEqual(timeout.total, 400)
        pipe._complete_dashboard_event.assert_awaited()


if __name__ == "__main__":
    unittest.main()
