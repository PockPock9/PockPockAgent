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
