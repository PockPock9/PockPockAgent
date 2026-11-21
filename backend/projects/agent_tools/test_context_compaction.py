"""Tests for context compaction (tool-RAG Phase 2)."""

import unittest

from projects.agent_tools.context_compaction import (
    compact_messages,
    estimate_message_tokens,
    prune_tool_results,
    summarise_messages,
    truncate_tool_output,
)


def _tool_call(name: str) -> dict:
    return {"id": "call-" + name, "function": {"name": name, "arguments": "{}"}}


def _exchange(tool: str, result: str, call_id: str = "c1") -> list[dict]:
    return [
        {"role": "assistant", "content": "", "tool_calls": [_tool_call(tool)]},
        {"role": "tool", "tool_call_id": call_id, "content": result},
    ]


class TruncateTests(unittest.TestCase):
    def test_short_output_is_unchanged(self):
        self.assertEqual(truncate_tool_output("small result"), "small result")

    def test_long_output_keeps_head_and_tail_with_marker(self):
        text = "".join(f"line {i:05d}\n" for i in range(5000))
        truncated = truncate_tool_output(text)
        self.assertLess(len(truncated), len(text))
        self.assertTrue(truncated.startswith("line 00000"))
        self.assertTrue(truncated.rstrip().endswith(f"line {4999:05d}"))
        self.assertIn("truncated", truncated)
        self.assertIn(str(len(text)), truncated)

    def test_pointer_names_where_the_full_content_lives(self):
        text = "x" * 60_000
        truncated = truncate_tool_output(text, pointer="the saved artifact at notes.md")
        self.assertIn("notes.md", truncated)

    def test_no_pointer_means_no_storage_claim(self):
        truncated = truncate_tool_output("y" * 60_000)
        self.assertNotIn("full content is in", truncated)


class PruneTests(unittest.TestCase):
    def test_keeps_the_most_recent_tool_results_intact(self):
        messages = [{"role": "system", "content": "sys"}]
        for name in ("a", "b", "c", "d", "e"):
            messages += _exchange("search_project", f"start-{name} " + "x" * 2000 + f" end-{name}", call_id=name)
        pruned, count = prune_tool_results(messages, keep_last=3)
        self.assertEqual(count, 2)
        tool_contents = [m["content"] for m in pruned if m["role"] == "tool"]
        for name, content in zip("ab", tool_contents[:2]):
            self.assertTrue(content.startswith("[tool result pruned to save context: 2014 chars"))
            self.assertIn("call the same tool again", content)
            # The start and end survive (R&D validation: a file's last line was invented once dropped).
            self.assertIn(f"start-{name}", content)
            self.assertIn(f"end-{name}", content)
            self.assertLess(len(content), 800)
        self.assertEqual([c[-5:] for c in tool_contents[2:]], ["end-c", "end-d", "end-e"])
        # The assistant call record survives pruning.
        self.assertEqual(
            [c["function"]["name"] for m in pruned if m.get("tool_calls") for c in m["tool_calls"]],
            ["search_project"] * 5,
        )

    def test_short_results_are_kept_whole(self):
        messages = [{"role": "system", "content": "sys"}]
        for name in ("a", "b", "c", "d"):
            messages += _exchange("search_project", f"result-{name}", call_id=name)
        pruned, count = prune_tool_results(messages, keep_last=1)
        self.assertEqual(count, 0)
        self.assertEqual(pruned, messages)

    def test_nothing_to_prune_returns_the_same_messages(self):
        messages = [{"role": "system", "content": "s"}, *_exchange("save_text_artifact", "ok")]
        pruned, count = prune_tool_results(messages, keep_last=3)
        self.assertEqual(count, 0)
        self.assertEqual(pruned, messages)


class SummariseTests(unittest.TestCase):
    def test_summary_lists_tools_files_and_errors(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "Fix the bug in cart.py and save a report."},
            *_exchange("read_project_file", "content of cart.py"),
            *_exchange("propose_project_edit", '{"error": {"code": "x", "message": "nope"}}'),
        ]
        summary = summarise_messages(messages)
        self.assertIn("read_project_file", summary)
        self.assertIn("propose_project_edit", summary)
        self.assertIn("cart.py", summary)
        self.assertIn("Fix the bug in cart.py", summary)
        self.assertIn("Open items", summary)
        self.assertIn("1 tool call(s) returned errors", summary)


class CompactTests(unittest.TestCase):
    def _long_history(self) -> list[dict]:
        messages: list[dict] = [
            {"role": "system", "content": "You are the agent."},
            {"role": "user", "content": "Analyse the attached sales.csv and save a report."},
        ]
        for i in range(8):
            messages += _exchange("search_project", "x" * 2000, call_id=f"c{i}")
        messages.append({"role": "assistant", "content": "Working on the report now."})
        messages.append({"role": "user", "content": "Also add the totals table."})
        return messages

    def test_under_threshold_is_untouched(self):
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}]
        compacted, report = compact_messages(messages)
        self.assertEqual(compacted, messages)
        self.assertFalse(report["compacted"])

    def test_over_threshold_prunes_first_then_summarises(self):
        messages = self._long_history()
        compacted, report = compact_messages(
            messages, window_tokens=2000, compact_at=0.75, keep_recent=6
        )
        self.assertTrue(report["compacted"])
        self.assertEqual(report["stage"], "summarised")
        self.assertLess(report["tokens_after"], report["tokens_before"])
        # System prompt survives; the summary replaces the old portion.
        self.assertEqual(compacted[0]["role"], "system")
        self.assertIn("Context compacted", compacted[1]["content"])
        self.assertIn("search_project", compacted[1]["content"])
        # The recent tail is intact: the last user request is still verbatim.
        self.assertEqual(compacted[-1]["content"], "Also add the totals table.")
        self.assertEqual(compacted[-2]["content"], "Working on the report now.")
        # No tool message in the tail is left without its assistant call,
        # and no assistant tool-call message is left without its result.
        for index, message in enumerate(compacted):
            if message.get("role") == "tool":
                self.assertTrue(
                    any(m.get("tool_calls") for m in compacted[:index]),
                    "tool result without a preceding call",
                )

    def test_prune_only_stage_when_nothing_can_be_summarised(self):
        # A history whose every message is "recent" (keep_recent covers it
        # all): there is no old portion to summarise, so pruning is all
        # that can be done — and it must still help.
        messages: list[dict] = [{"role": "system", "content": "s"}]
        for i in range(5):
            messages += _exchange("search_project", "z" * 2000, call_id=f"c{i}")
        compacted, report = compact_messages(
            messages, window_tokens=1000, compact_at=0.75, keep_recent=20
        )
        self.assertTrue(report["compacted"])
        self.assertEqual(report["stage"], "pruned-only")
        self.assertLess(report["tokens_after"], report["tokens_before"])
        self.assertGreater(report["pruned"], 0)

    def test_env_override_changes_the_threshold(self):
        import os

        messages = self._long_history()
        _, small = compact_messages(messages, window_tokens=1000, compact_at=0.75)
        os.environ["POCKPOCK_CONTEXT_WINDOW_TOKENS"] = "1000000"
        try:
            _, huge = compact_messages(messages)
        finally:
            del os.environ["POCKPOCK_CONTEXT_WINDOW_TOKENS"]
        self.assertTrue(small["compacted"])
        self.assertFalse(huge["compacted"])

    def test_estimate_tokens_scales_with_content(self):
        short = [{"role": "user", "content": "hi"}]
        long = [{"role": "user", "content": "x" * 4000}]
        self.assertLess(estimate_message_tokens(short), estimate_message_tokens(long))


if __name__ == "__main__":
    unittest.main()
