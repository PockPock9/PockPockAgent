import unittest

import pockpock_server


class PrepareChatMessagesTests(unittest.TestCase):
    def test_merges_preferences_and_directive_into_one_system_message(self):
        messages, report = pockpock_server.prepare_chat_messages(
            [{"role": "user", "content": "hello"}],
            "You are a quick-response engine.",
            ["Prefer short answers."],
        )
        self.assertFalse(report["compacted"])
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(
            messages[0]["content"],
            "Optional saved user style preferences (apply only where relevant; do not change the task, "
            "permissions, or safety):\n- Prefer short answers.\n\n"
            "You are a quick-response engine.",
        )
        self.assertEqual(messages[1], {"role": "user", "content": "hello"})

    def test_directive_only_when_no_preferences(self):
        messages, report = pockpock_server.prepare_chat_messages(
            [{"role": "user", "content": "hello"}],
            "You are a quick-response engine.",
            [],
        )
        self.assertFalse(report["compacted"])
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0], {"role": "system", "content": "You are a quick-response engine."})

    def test_no_system_message_when_nothing_to_say(self):
        messages, report = pockpock_server.prepare_chat_messages(
            [{"role": "user", "content": "hello"}],
            "",
            [],
        )
        self.assertFalse(report["compacted"])
        self.assertEqual(messages, [{"role": "user", "content": "hello"}])

    def test_client_system_message_is_kept_and_history_is_not_compacted(self):
        history = [
            {"role": "system", "content": "Client system prompt."},
            {"role": "user", "content": "x" * 200_000},
            {"role": "assistant", "content": "y" * 200_000},
        ]
        messages, report = pockpock_server.prepare_chat_messages(
            history,
            "You are a quick-response engine.",
            ["Prefer short answers."],
        )
        # Preferences go in front; the client's system message is never
        # summarised away, so no compaction runs on this shape.
        self.assertFalse(report["compacted"])
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Prefer short answers.", messages[0]["content"])
        self.assertEqual(messages[1], {"role": "system", "content": "Client system prompt."})
        self.assertEqual(messages[2:], history[1:])

    def test_long_history_is_compacted_and_system_message_survives(self):
        history = [{"role": "user", "content": "old turn " + "x" * 40_000} for _ in range(3)]
        history += [
            {"role": "user", "content": "recent question"},
            {"role": "assistant", "content": "recent answer"},
            {"role": "user", "content": "follow-up"},
            {"role": "assistant", "content": "follow-up answer"},
            {"role": "user", "content": "latest question"},
            {"role": "assistant", "content": "latest answer"},
        ]
        messages, report = pockpock_server.prepare_chat_messages(
            history,
            "You are a quick-response engine.",
            [],
        )
        self.assertTrue(report["compacted"])
        self.assertEqual(report["stage"], "summarised")
        # The merged system message is never removed.
        self.assertEqual(messages[0], {"role": "system", "content": "You are a quick-response engine."})
        # The recent tail survives verbatim.
        self.assertEqual(messages[-6:], history[-6:])
        self.assertLess(len(messages), len(history) + 1)


if __name__ == "__main__":
    unittest.main()
