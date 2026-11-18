import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from projects.plan_sequence.capsule import (
    build_capsule,
    capsule_to_text,
    capsule_token_estimate,
)
from projects.plan_sequence.contracts import (
    MAX_CAPSULE_TOKENS,
    CapsuleEntry,
    StateCapsule,
)


def _entry(key, kind, value, source_step=None):
    return {"key": key, "kind": kind, "value": value, "source_step": source_step}


_LONG_SUMMARY = "s" * 200  # ~50 tokens per entry


class BuildCapsuleTests(unittest.TestCase):
    def test_accepts_dicts_and_entries(self):
        from_dicts = build_capsule([_entry("a", "path", "/tmp/a.md", "step-1")])
        from_models = build_capsule(
            [CapsuleEntry(key="a", kind="path", value="/tmp/a.md", source_step="step-1")]
        )
        self.assertEqual(from_dicts.entries, from_models.entries)

    def test_accepts_existing_capsule(self):
        original = StateCapsule(entries=[
            CapsuleEntry(key="a", kind="path", value="/tmp/a.md", source_step="step-1"),
        ])
        rebuilt = build_capsule(original)
        self.assertEqual(rebuilt.entries, original.entries)
        self.assertFalse(rebuilt.dropped_pointers)

    def test_trims_summaries_before_pointers_and_stays_within_budget(self):
        entries = [
            _entry("invoice-file", "path", "/tmp/invoices.md", "step-1"),
            _entry("invoice-ids", "id", "msg-1,msg-2,msg-3", "step-1"),
        ] + [
            _entry(f"note-{index}", "summary", _LONG_SUMMARY, "step-2")
            for index in range(10)
        ]
        capsule = build_capsule(entries)
        self.assertLessEqual(capsule.estimated_tokens(), MAX_CAPSULE_TOKENS)
        kinds = [entry.kind for entry in capsule.entries]
        self.assertIn("path", kinds)
        self.assertIn("id", kinds)
        # Pointers survived; at least one summary was trimmed to fit.
        self.assertLess(kinds.count("summary"), 10)
        self.assertFalse(capsule.dropped_pointers)

    def test_trims_values_after_summaries(self):
        entries = (
            [_entry("out", "path", "/tmp/out.md", "step-1")]
            + [_entry(f"v-{index}", "value", _LONG_SUMMARY, "step-1") for index in range(4)]
            + [_entry(f"s-{index}", "summary", _LONG_SUMMARY, "step-1") for index in range(4)]
        )
        capsule = build_capsule(entries, max_tokens=200)
        kinds = [entry.kind for entry in capsule.entries]
        self.assertIn("path", kinds)
        # All summaries go before any value is touched.
        self.assertNotIn("summary", kinds)
        self.assertLessEqual(capsule.estimated_tokens(), 200)

    def test_pointers_dropped_only_as_last_resort_and_noted(self):
        entries = [
            _entry(f"out-{index}", "path", "/tmp/" + "p" * 195, "step-1")
            for index in range(3)
        ]
        capsule = build_capsule(entries, max_tokens=60)
        self.assertLessEqual(capsule.estimated_tokens(), 60)
        self.assertEqual(len(capsule.entries), 1)
        self.assertTrue(capsule.dropped_pointers)

    def test_no_trim_needed_keeps_everything(self):
        entries = [
            _entry("a", "path", "/tmp/a.md", "step-1"),
            _entry("b", "summary", "short note", "step-1"),
        ]
        capsule = build_capsule(entries)
        self.assertEqual(len(capsule.entries), 2)
        self.assertFalse(capsule.dropped_pointers)

    def test_enforces_24_entry_cap(self):
        entries = [_entry(f"k{index}", "value", "x", "step-1") for index in range(1, 31)]
        capsule = build_capsule(entries)
        self.assertEqual(len(capsule.entries), 24)
        # Oldest entries are dropped; newest survive.
        self.assertEqual(capsule.entries[0].key, "k7")
        self.assertEqual(capsule.entries[-1].key, "k30")

    def test_invalid_entry_rejected(self):
        with self.assertRaisesRegex(ValueError, "Invalid capsule entry"):
            build_capsule([{"key": "a", "kind": "not-a-kind", "value": "x"}])


class CapsuleTextTests(unittest.TestCase):
    def test_to_text_round_trips_entries(self):
        entries = [
            CapsuleEntry(key="a", kind="path", value="/tmp/a.md", source_step="step-1"),
            CapsuleEntry(key="b", kind="id", value="msg-1", source_step="step-1"),
            CapsuleEntry(key="c", kind="summary", value="done", source_step="step-2"),
            CapsuleEntry(key="d", kind="value", value="42"),
        ]
        capsule = StateCapsule(entries=entries)
        lines = capsule.to_text().splitlines()
        self.assertEqual(len(lines), 4)
        round_tripped = dict(line.split(": ", 1) for line in lines)
        self.assertEqual(
            round_tripped,
            {"a": "/tmp/a.md", "b": "msg-1", "c": "done", "d": "42"},
        )

    def test_to_text_groups_by_source_step(self):
        entries = [
            CapsuleEntry(key="a", kind="path", value="/tmp/a.md", source_step="step-2"),
            CapsuleEntry(key="b", kind="id", value="msg-1", source_step="step-1"),
            CapsuleEntry(key="c", kind="summary", value="done", source_step="step-2"),
        ]
        text = StateCapsule(entries=entries).to_text()
        # Entries are grouped by source step in order of first appearance:
        # the step-2 entries are adjacent, in their original relative order,
        # ahead of the step-1 group.
        self.assertEqual(text, "a: /tmp/a.md\nc: done\nb: msg-1")

    def test_capsule_to_text_matches_to_text(self):
        capsule = StateCapsule(entries=[
            CapsuleEntry(key="a", kind="path", value="/tmp/a.md", source_step="step-1"),
        ])
        self.assertEqual(capsule_to_text(capsule), capsule.to_text())
        self.assertEqual(capsule_to_text(capsule), "a: /tmp/a.md")

    def test_empty_capsule_text_is_empty(self):
        self.assertEqual(StateCapsule().to_text(), "")


class TokenEstimateTests(unittest.TestCase):
    def test_estimate_functions_return_positive_ints(self):
        text = "invoice-file: /tmp/invoices.md\ntotal: 42"
        capsule = StateCapsule(entries=[
            CapsuleEntry(key="invoice-file", kind="path", value="/tmp/invoices.md"),
            CapsuleEntry(key="total", kind="value", value="42"),
        ])
        for estimate in (capsule.estimated_tokens(), capsule_token_estimate(text)):
            self.assertIsInstance(estimate, int)
            self.assertGreater(estimate, 0)
        self.assertEqual(capsule_token_estimate(text), capsule.estimated_tokens())
        self.assertEqual(capsule_token_estimate(""), 1)

    def test_estimated_tokens_grows_with_text(self):
        short = StateCapsule(entries=[
            CapsuleEntry(key="a", kind="value", value="x"),
        ])
        long = StateCapsule(entries=[
            CapsuleEntry(key="a", kind="value", value="x" * 200),
        ])
        self.assertLess(short.estimated_tokens(), long.estimated_tokens())


if __name__ == "__main__":
    unittest.main()
