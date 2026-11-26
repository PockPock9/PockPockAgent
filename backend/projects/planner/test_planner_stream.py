import asyncio
import unittest
from unittest import mock

import aiohttp

import app


class StreamingPlannerCallTests(unittest.TestCase):
    """Planner calls stream, so a slow model that keeps writing is not cut off (the ~111 s bug)."""

    def test_streamed_tokens_are_joined_into_json(self):
        seen = {}

        async def stream_tokens(request, *, timeout):
            seen["timeout"] = timeout
            seen["think"] = request.think
            seen["format"] = request.response_format
            for token in ('{"plan": ', '["Read", ', '"Save"]}'):
                await asyncio.sleep(0)
                yield token

        with mock.patch.object(app.MODEL_CLIENT, "stream_tokens", stream_tokens):
            timeout = app.planning_timeout([], "qwen3.5:9b")
            parsed = asyncio.run(app._request_model_json("qwen3.5:9b", [{"role": "user", "content": "plan"}], timeout=timeout, role="planner"))
        self.assertEqual(parsed, {"plan": ["Read", "Save"]})
        self.assertIs(seen["think"], False)
        self.assertEqual(seen["format"], {"type": "json_object"})
        # The read timeout is the longest silence, and the whole call may take much longer.
        self.assertEqual((seen["timeout"].sock_read, seen["timeout"].total), (240, 600))

    def test_plan_json_sends_the_schema_and_retries_an_unusable_reply_once(self):
        calls = []

        async def fake(model, messages, *, timeout, role, temperature=0.1, schema=None):
            calls.append((messages, schema))
            if len(calls) == 1:
                raise ValueError("Expecting value: line 1 column 1")
            return {"plan": ["Read the file", "Write the summary"], "execution_prompt": "x", "reason": "y", "task_brief": {}}

        with mock.patch.object(app, "_request_model_json", fake):
            parsed, steps = asyncio.run(app._plan_json("m", "Plan it", timeout=aiohttp.ClientTimeout(total=5)))
        self.assertEqual(steps, ["Read the file", "Write the summary"])
        self.assertEqual(len(calls), 2)
        self.assertIs(calls[0][1], app.PLAN_SCHEMA)
        self.assertIn("could not be used: Expecting value", calls[1][0][-1]["content"])

    def test_plan_json_gives_up_after_one_retry_and_never_retries_a_model_failure(self):
        calls = []

        async def empty_plan(model, messages, *, timeout, role, temperature=0.1, schema=None):
            calls.append(1)
            return {"plan": []}

        with mock.patch.object(app, "_request_model_json", empty_plan):
            with self.assertRaises(ValueError):
                asyncio.run(app._plan_json("m", "Plan it", timeout=aiohttp.ClientTimeout(total=5)))
        self.assertEqual(len(calls), 2)

        calls.clear()

        async def model_down(model, messages, *, timeout, role, temperature=0.1, schema=None):
            calls.append(1)
            raise app.HTTPException(status_code=502, detail="The planner model failed.")

        with mock.patch.object(app, "_request_model_json", model_down):
            with self.assertRaises(app.HTTPException):
                asyncio.run(app._plan_json("m", "Plan it", timeout=aiohttp.ClientTimeout(total=5)))
        self.assertEqual(len(calls), 1)

    def test_empty_reply_is_an_error(self):
        async def stream_tokens(request, *, timeout):
            if False:
                yield ""

        with mock.patch.object(app.MODEL_CLIENT, "stream_tokens", stream_tokens):
            with self.assertRaises(ValueError):
                asyncio.run(app._request_model_json("m", [], timeout=aiohttp.ClientTimeout(total=5), role="planner"))

    def test_timeouts_can_be_configured(self):
        with mock.patch.dict("os.environ", {"POCKPOCK_PLANNER_TIMEOUT_SECONDS": "1200", "POCKPOCK_PLANNER_IDLE_SECONDS": "400"}):
            timeout = app.planning_timeout([], "m")
        self.assertEqual((timeout.total, timeout.sock_read), (1200, 400))
        with mock.patch.dict("os.environ", {"POCKPOCK_PLANNER_TIMEOUT_SECONDS": "5"}):
            self.assertEqual(app.planning_timeout([], "m").total, 600)


if __name__ == "__main__":
    unittest.main()
