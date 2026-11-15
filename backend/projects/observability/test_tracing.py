import unittest

from projects.observability import PromptFreeTraceAdapter


class PromptFreeTraceAdapterTests(unittest.TestCase):
    def test_forwards_operational_metadata(self):
        events = []
        adapter = PromptFreeTraceAdapter(events.append)

        adapter.emit({
            "event": "model_call_completed",
            "model": "local-model",
            "duration_ms": 125,
        })

        self.assertEqual(events, [{
            "event": "model_call_completed",
            "model": "local-model",
            "duration_ms": 125,
        }])

    def test_rejects_prompt_content_fields(self):
        adapter = PromptFreeTraceAdapter(lambda _: self.fail("unsafe event was persisted"))

        with self.assertRaisesRegex(ValueError, "Prompt-free trace"):
            adapter.emit({"event": "request_received", "metadata": {"task": "private request"}})


if __name__ == "__main__":
    unittest.main()
