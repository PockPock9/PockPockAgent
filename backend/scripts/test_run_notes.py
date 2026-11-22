import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import pockpock_server as gateway
from projects.agent_core.executor import note_message


class RunNoteTests(unittest.TestCase):
    """Agent Studio: a note added while a PockPock Agent run works is queued for its next step."""

    RUN = "a" * 32

    def setUp(self):
        self.patches = [patch.object(gateway, "require_local_agent_request", lambda request: None)]
        for item in self.patches:
            item.start()
        gateway.AGENT_RUN_NOTES.clear()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        gateway.AGENT_RUN_NOTES.clear()
        gateway.AGENT_RUN_CANCEL_EVENTS.pop(self.RUN, None)

    def add(self, text, run=None):
        return asyncio.run(gateway.add_agent_run_note(run or self.RUN, gateway.AgentRunNotePayload(text=text), None))

    def test_a_note_is_queued_only_while_the_run_is_active(self):
        with self.assertRaises(HTTPException) as caught:
            self.add("Use British spelling")
        self.assertEqual(caught.exception.status_code, 404)
        gateway.AGENT_RUN_CANCEL_EVENTS[self.RUN] = asyncio.Event()
        self.assertEqual(self.add("  Use British spelling  "), {"accepted": True, "queued": 1})
        self.assertEqual(gateway.AGENT_RUN_NOTES[self.RUN], ["Use British spelling"])

    def test_pending_notes_are_bounded(self):
        gateway.AGENT_RUN_CANCEL_EVENTS[self.RUN] = asyncio.Event()
        for index in range(gateway.MAX_PENDING_RUN_NOTES):
            self.add(f"note {index}")
        with self.assertRaises(HTTPException) as caught:
            self.add("one too many")
        self.assertEqual(caught.exception.status_code, 429)

    def test_the_model_sees_the_note_as_the_users_words_within_the_plan(self):
        text = note_message("  Skip the images folder  ")
        self.assertTrue(text.endswith("Skip the images folder"))
        self.assertIn("within the approved plan and permissions", text)


if __name__ == "__main__":
    unittest.main()
