"""Tests for reasoning memory tips and the semantic fact store."""

import tempfile
import unittest
from pathlib import Path

from projects.agent_skills.memory import (
    Fact,
    ReasoningMemory,
    ReasoningTip,
    connect_sqlite,
    normalize_task_tag,
)


class ReasoningMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.memory = ReasoningMemory(connect_sqlite(Path(self.tmp.name) / "m.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def _tip(self, **kwargs):
        defaults = dict(
            title="Retry with backoff",
            description="Retries need a delay.",
            content="Wait before retrying or the server throttles you.",
            kind="success",
            action="retry with backoff",
            task_tag="api-call",
            confidence=0.8,
            source_run_id="run-1",
        )
        defaults.update(kwargs)
        return ReasoningTip(**defaults)

    def test_add_and_retrieve_tip(self):
        tip = self.memory.add_tip(self._tip())
        self.assertTrue(tip.id)
        results = self.memory.retrieve_tips("how do I retry the api call with backoff")
        self.assertEqual([t.id for t in results], [tip.id])

    def test_retrieve_only_active_tips(self):
        tip = self.memory.add_tip(self._tip())
        self.memory.set_tip_status(tip.id, "invalidated", reason="test")
        self.assertEqual(self.memory.retrieve_tips("retry the api call with backoff"), [])

    def test_invalid_tip_rejected(self):
        with self.assertRaises(ValueError):
            self.memory.add_tip(ReasoningTip(title="", content="x"))
        with self.assertRaises(ValueError):
            self.memory.add_tip(self._tip(kind="maybe"))

    def test_mark_used_increments(self):
        tip = self.memory.add_tip(self._tip())
        self.memory.mark_tip_used(tip.id)
        self.memory.mark_tip_used(tip.id)
        self.assertEqual(self.memory.get_tip(tip.id).use_count, 2)

    def test_pruning_log_records_status_change(self):
        tip = self.memory.add_tip(self._tip())
        self.memory.set_tip_status(tip.id, "pruned", reason="stale")
        log = self.memory.pruning_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0].item_id, tip.id)
        self.assertEqual(log[0].decision, "pruned")

    def test_failure_tip_stored(self):
        tip = self.memory.add_tip(self._tip(
            kind="failure",
            title="Don't retry immediately",
            content="Don't retry immediately, it fails because the server throttles.",
            action="retry immediately",
        ))
        self.assertEqual(tip.kind, "failure")
        results = self.memory.retrieve_tips("don't retry immediately after failure")
        self.assertIn(tip.id, [t.id for t in results])

    def test_normalize_task_tag(self):
        self.assertEqual(normalize_task_tag("Please summarise the CSV file"), "summarise-csv-file")


class FactStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.memory = ReasoningMemory(connect_sqlite(Path(self.tmp.name) / "m.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_and_get_fact(self):
        fact = self.memory.add_fact(Fact(subject="project", predicate="language", value="Python"))
        self.assertTrue(fact.id)
        facts = self.memory.get_facts("project")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].value, "Python")

    def test_new_value_invalidates_old_never_overwrites(self):
        first = self.memory.add_fact(Fact(subject="project", predicate="language", value="Python"))
        second = self.memory.add_fact(Fact(subject="project", predicate="language", value="Rust"))
        self.assertIsNotNone(second.superseded_id)
        self.assertEqual(second.superseded_id, first.id)
        # Old row still exists, now invalidated, with its old value intact.
        old = [f for f in self.memory.get_facts("project", status="invalidated")]
        self.assertEqual(len(old), 1)
        self.assertEqual(old[0].value, "Python")
        active = self.memory.get_facts("project")
        self.assertEqual([f.value for f in active], ["Rust"])
        log = self.memory.pruning_log()
        self.assertTrue(any(entry.item_id == first.id for entry in log))

    def test_identical_fact_is_idempotent(self):
        first = self.memory.add_fact(Fact(subject="a", predicate="b", value="c"))
        second = self.memory.add_fact(Fact(subject="a", predicate="b", value="c"))
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(self.memory.get_facts("a")), 1)

    def test_empty_fact_rejected(self):
        with self.assertRaises(ValueError):
            self.memory.add_fact(Fact(subject="", predicate="b", value="c"))


if __name__ == "__main__":
    unittest.main()
