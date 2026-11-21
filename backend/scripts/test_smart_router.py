import unittest
from unittest.mock import AsyncMock

from scripts.smart_router import Pipe


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

    async def test_default_router_model_is_an_installed_small_model(self):
        # Issue #91: the old default qwen2.5:1.5b is not installed; qwen3.5:2b is.
        self.assertEqual(Pipe.Valves().router_model, "qwen3.5:2b")

    async def test_quick_model_defaults_to_small_installed_model(self):
        # Local-AI efficiency plan: simple/triage turns run on the small
        # model (qwen3.5:2b, installed) instead of qwen2.5:7b, while
        # reasoning/planning stays on the larger configured models.
        self.assertEqual(Pipe.Valves().quick_model, "qwen3.5:2b")

    async def test_algorithm_questions_route_to_the_code_model(self):
        # Issue #56: "time complexity" questions were sent to the quick model.
        pipe = Pipe()
        for question in ("What is the time complexity of binary search and why?", "Explain big-O of quicksort"):
            decision = pipe._heuristic_check(question, [{"role": "user", "content": question}])
            self.assertEqual((decision["category"], decision["model"]), ("code", pipe.valves.code_model), question)
        decision = pipe._heuristic_check("What is the capital of France?", [{"role": "user", "content": "What is the capital of France?"}])
        self.assertEqual(decision["category"], "quick")

    async def test_heuristic_routes_greeting_to_small_model(self):
        pipe = Pipe()
        decision = pipe._heuristic_check(
            "hello", [{"role": "user", "content": "hello"}]
        )
        self.assertEqual(decision["category"], "quick")
        self.assertEqual(decision["model"], "qwen3.5:2b")

    async def test_heuristic_routes_short_factual_question_to_small_model(self):
        pipe = Pipe()
        decision = pipe._heuristic_check(
            "What is the capital of France?",
            [{"role": "user", "content": "What is the capital of France?"}],
        )
        self.assertEqual(decision["category"], "quick")
        self.assertEqual(decision["model"], "qwen3.5:2b")

    async def test_resolve_routed_model_falls_back_when_small_model_missing(self):
        pipe = Pipe()
        # Small model installed: used as routed.
        self.assertEqual(
            pipe.resolve_routed_model("qwen3.5:2b", {"qwen3.5:2b", "qwen2.5:14b"}),
            "qwen3.5:2b",
        )
        # Small model not installed: fall back to the general model.
        self.assertEqual(
            pipe.resolve_routed_model("qwen3.5:2b", {"qwen2.5:14b"}),
            "qwen2.5:14b",
        )
        # Any other routed model is returned unchanged.
        self.assertEqual(
            pipe.resolve_routed_model("qwen2.5-coder:7b", {"qwen2.5:14b"}),
            "qwen2.5-coder:7b",
        )

    async def test_pipe_routes_quick_turn_to_small_model(self):
        request = await self._run_pipe({
            "category": "quick",
            "reason": "test route",
            "confidence": 1.0,
            "complexity": 1,
            "model": Pipe.Valves().quick_model,
        })
        self.assertEqual(request.model, "qwen3.5:2b")

    async def _run_pipe(self, decision):
        client = FakeModelClient()
        pipe = Pipe(model_client=client)
        pipe._queue_dashboard_event = lambda event: None
        pipe._complete_dashboard_event = AsyncMock()
        pipe._dashboard_override = AsyncMock(return_value=None)
        pipe._heuristic_check = lambda _text, _messages: decision
        pipe.valves.show_telemetry_hud = False
        output = [
            item async for item in pipe.pipe(
                {"messages": [{"role": "user", "content": "hello"}]}
            )
        ]
        self.assertEqual(output, ["local response"])
        return client.requests[0][0]

    async def test_qwen35_chat_request_disables_thinking(self):
        request = await self._run_pipe({
            "category": "quick",
            "reason": "test route",
            "confidence": 1.0,
            "complexity": 1,
            "model": "qwen3.5:2b",
        })
        self.assertIs(request.think, False)

    async def test_reasoning_turn_keeps_thinking_on(self):
        request = await self._run_pipe({
            "category": "reasoning",
            "reason": "test route",
            "confidence": 1.0,
            "complexity": 8,
            "model": "qwen3.5:2b",
        })
        self.assertIsNone(request.think)


if __name__ == "__main__":
    unittest.main()
