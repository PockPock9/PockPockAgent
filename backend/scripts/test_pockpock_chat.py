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


class ChatFallbackTests(unittest.TestCase):
    MODELS = [
        {"name": "nomic-embed-text-v2-moe:latest", "details": {"family": "nomic-bert-moe", "families": ["nomic-bert-moe"]}},
        {"name": "qwen3.5:27b", "details": {"family": "qwen35", "families": ["qwen35"]}},
        {"name": "qwen3.5:9b", "details": {"family": "qwen35", "families": ["qwen35"]}},
        {"name": "bge-m3:latest", "details": {"family": "bert", "families": ["bert"]}},
    ]

    def test_embedding_models_are_never_chat_fallbacks(self):
        # R&D validation 2026-11-21: with the router model missing, auto routing chose the newest
        # model in Ollama's list, an embedding model, and every chat failed before falling back.
        from unittest.mock import patch

        with patch.object(pockpock_server, "disabled_models", return_value=set()):
            self.assertEqual(pockpock_server.fallback_chat_models(self.MODELS, set(), set()), ["qwen3.5:27b", "qwen3.5:9b"])
            # A model already in memory comes first, so no other model is loaded next to it.
            self.assertEqual(pockpock_server.fallback_chat_models(self.MODELS, {"qwen3.5:9b"}, set())[0], "qwen3.5:9b")
            self.assertEqual(pockpock_server.fallback_chat_models(self.MODELS, set(), {"qwen3.5:27b"}), ["qwen3.5:9b"])
        self.assertTrue(pockpock_server.is_embedding_model(self.MODELS[0]))
        self.assertTrue(pockpock_server.is_embedding_model(self.MODELS[3]))
        self.assertFalse(pockpock_server.is_embedding_model(self.MODELS[2]))


class RequestValidationTests(unittest.TestCase):
    def test_an_empty_message_is_refused(self):
        # Issue #55: empty, whitespace-only and missing content were answered with HTTP 200.
        for message in ({"role": "user", "content": ""}, {"role": "user", "content": "   "}, {"role": "user"}):
            with self.assertRaises(pockpock_server.HTTPException) as ctx:
                pockpock_server.safe_messages([message])
            self.assertEqual(ctx.exception.status_code, 422)
        # Earlier history and image-only messages are still accepted.
        kept = pockpock_server.safe_messages([
            {"role": "user", "content": ""}, {"role": "assistant", "content": "ok"}, {"role": "user", "content": "next"},
        ])
        self.assertEqual(len(kept), 3)
        self.assertEqual(len(pockpock_server.safe_messages([{"role": "user", "content": "", "images": ["aGk="]}])), 1)

    def test_a_blank_plan_task_is_a_validation_error(self):
        # Issue #73: a whitespace-only task surfaced as a 502 from the planner.
        with self.assertRaises(ValueError):
            pockpock_server.AgentPlanPayload(task="   ")
        self.assertEqual(pockpock_server.AgentPlanPayload(task="Plan it").task, "Plan it")

    def test_nemoclaw_refuses_a_bogus_session_before_the_stream(self):
        # Issue #75: a malformed session id opened a stream and failed later.
        import asyncio

        from projects.nemoclaw_bridge.api import NemoClawChatPayload, create_router

        route = next(r for r in create_router(None, lambda request: None).routes if r.path == "/api/nemoclaw/chat")
        with self.assertRaises(pockpock_server.HTTPException) as ctx:
            asyncio.run(route.endpoint(NemoClawChatPayload(session_id="bogus-123", message="hi")))
        self.assertEqual(ctx.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
