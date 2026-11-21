import asyncio
import json
import unittest
from unittest.mock import patch

import agent_run_store


def sse(event):
    return f"data: {json.dumps(event)}\n\n"


class TrackAgentStreamTests(unittest.TestCase):
    def test_closing_the_client_stream_closes_the_run_stream(self):
        # Issue #41: when the client went away, the run's own generator was never closed, so its
        # cleanup (which marks the run finished) never ran and the run stayed "running".
        cleaned = []

        async def run_stream():
            try:
                yield sse({"type": "approval_requested"})
                await asyncio.sleep(3600)  # waiting for an approval that never comes
                yield sse({"type": "done"})
            finally:
                cleaned.append(True)

        async def scenario():
            with patch.object(agent_run_store, "store_agent_event", return_value=True):
                tracked = agent_run_store.track_agent_stream("a" * 32, run_stream(), lambda event: sse(event))
                first = await tracked.__anext__()
                self.assertIn("approval_requested", first)
                pending = asyncio.ensure_future(tracked.__anext__())
                await asyncio.sleep(0)
                pending.cancel()  # the server cancels the response task on disconnect
                with self.assertRaises(asyncio.CancelledError):
                    await pending
                await tracked.aclose()

        asyncio.run(scenario())
        self.assertEqual(cleaned, [True])

    def test_an_abandoned_stream_closes_the_run_stream(self):
        cleaned = []

        async def run_stream():
            try:
                yield sse({"type": "token", "content": "a"})
                yield sse({"type": "token", "content": "b"})
            finally:
                cleaned.append(True)

        async def scenario():
            with patch.object(agent_run_store, "store_agent_event", return_value=True):
                tracked = agent_run_store.track_agent_stream("b" * 32, run_stream(), lambda event: sse(event))
                await tracked.__anext__()
                await tracked.aclose()  # the client stopped reading after the first event
                # Checked here, while the loop runs: asyncio.run would close leftover generators itself.
                self.assertEqual(cleaned, [True])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
