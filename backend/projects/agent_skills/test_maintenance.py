"""Tests for maintenance: contradictions and pruning."""

import tempfile
import unittest
from pathlib import Path

from projects.agent_skills.maintenance import (
    detect_contradictions,
    prune_stale,
    run_maintenance,
)
from projects.agent_skills.memory import Fact, ReasoningMemory, ReasoningTip, connect_sqlite


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.memory = ReasoningMemory(connect_sqlite(Path(self.tmp.name) / "m.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def _tip(self, **kwargs):
        defaults = dict(
            title="Retry with backoff",
            description="d",
            content="Wait before retrying.",
            kind="success",
            action="retry with backoff",
            task_tag="api-call",
            confidence=0.8,
        )
        defaults.update(kwargs)
        return self.memory.add_tip(ReasoningTip(**defaults))

    def test_contradiction_invalidates_lower_confidence(self):
        winner = self._tip(confidence=0.9)
        loser = self._tip(
            kind="failure",
            title="Don't retry with backoff",
            content="Don't retry with backoff, it fails because it is too slow.",
            confidence=0.4,
        )
        decisions = detect_contradictions(self.memory)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].item_id, loser.id)
        self.assertEqual(self.memory.get_tip(loser.id).status, "invalidated")
        self.assertEqual(self.memory.get_tip(winner.id).status, "active")
        # The loser is gone from retrieval.
        self.assertEqual(
            [t.id for t in self.memory.retrieve_tips("retry with backoff")],
            [winner.id],
        )

    def test_no_contradiction_when_kinds_agree(self):
        self._tip()
        self._tip(title="Retry with backoff twice", action="retry with backoff")
        self.assertEqual(detect_contradictions(self.memory), [])

    def test_no_contradiction_across_tasks(self):
        self._tip()
        self._tip(kind="failure", task_tag="other-task")
        self.assertEqual(detect_contradictions(self.memory), [])

    def test_prune_low_confidence_tip(self):
        tip = self._tip(confidence=0.1)
        report = prune_stale(self.memory)
        self.assertEqual(len(report.pruned_tips), 1)
        self.assertEqual(self.memory.get_tip(tip.id).status, "pruned")

    def test_prune_expired_unused_tip(self):
        tip = self._tip(expires_at="2020-01-01T00:00:00+00:00")
        report = prune_stale(self.memory, now="2026-11-17T00:00:00+00:00")
        self.assertEqual(len(report.pruned_tips), 1)
        self.assertEqual(self.memory.get_tip(tip.id).status, "pruned")

    def test_used_expired_tip_still_pruned_but_logged(self):
        # Expiry applies even to used tips; the log explains why.
        tip = self._tip(expires_at="2020-01-01T00:00:00+00:00")
        self.memory.mark_tip_used(tip.id)
        report = prune_stale(self.memory, now="2026-11-17T00:00:00+00:00")
        self.assertEqual(len(report.pruned_tips), 1)

    def test_prune_expired_fact(self):
        fact = self.memory.add_fact(Fact(
            subject="x", predicate="y", value="z", expires_at="2020-01-01T00:00:00+00:00",
        ))
        report = prune_stale(self.memory, now="2026-11-17T00:00:00+00:00")
        self.assertEqual(len(report.pruned_facts), 1)
        self.assertEqual(self.memory.get_facts(status="pruned")[0].id, fact.id)

    def test_run_maintenance_combines_both(self):
        self._tip(confidence=0.9)
        self._tip(kind="failure", title="Don't retry with backoff",
                  content="Don't retry with backoff.", confidence=0.4)
        self._tip(title="Stale tip", action="old action", confidence=0.1, task_tag="other")
        report = run_maintenance(self.memory)
        self.assertEqual(len(report.contradictions), 1)
        self.assertEqual(len(report.pruned_tips), 1)
        self.assertEqual(report.total, 2)


if __name__ == "__main__":
    unittest.main()
