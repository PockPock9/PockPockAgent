import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import research_watch as watch

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def source(name, checked_minutes_ago=None, error_minutes_ago=None, watched=True):
    return {
        "task_id": name * 32, "source_id": name * 64, "workspace_key": "k" * 64, "title": name, "url": f"https://{name}.example",
        "last_checked_at": (NOW - timedelta(minutes=checked_minutes_ago)).isoformat() if checked_minutes_ago is not None else None,
        "watch": {"watched": watched, "error_at": (NOW - timedelta(minutes=error_minutes_ago)).isoformat() if error_minutes_ago is not None else None},
    }


class IntervalTests(unittest.TestCase):
    def test_default_and_bounds(self):
        with mock.patch.dict(os.environ, {"POCKPOCK_SOURCE_WATCH_MINUTES": ""}):
            self.assertEqual(watch.watch_interval_minutes(), 360)
        for raw, expected in (("1", 15), ("90", 90), ("999999", 10080), ("soon", 360)):
            with mock.patch.dict(os.environ, {"POCKPOCK_SOURCE_WATCH_MINUTES": raw}):
                self.assertEqual(watch.watch_interval_minutes(), expected, raw)

    def test_the_switch_turns_background_checks_off(self):
        with mock.patch.dict(os.environ, {"POCKPOCK_SOURCE_WATCH": "0"}):
            self.assertFalse(watch.watching_enabled())
        with mock.patch.dict(os.environ, {"POCKPOCK_SOURCE_WATCH": "1"}):
            self.assertTrue(watch.watching_enabled())


class DueTests(unittest.TestCase):
    def test_only_watched_sources_past_their_interval_are_due_oldest_first(self):
        sources = [source("a", 30), source("b", 400), source("c", 1000), source("d", 1000, watched=False), source("e", None)]
        self.assertEqual([item["title"] for item in watch.due_sources(sources, NOW, 360)], ["e", "c", "b"])

    def test_a_failed_check_waits_a_full_interval_too(self):
        failed_recently = source("a", 1000, error_minutes_ago=10)
        self.assertEqual(watch.due_sources([failed_recently], NOW, 360), [])
        self.assertEqual(watch.next_check_at(failed_recently, 360), NOW - timedelta(minutes=10) + timedelta(minutes=360))


class CheckTests(unittest.TestCase):
    def run_check(self, sources, outcomes, research_enabled=True, limit=3):
        recorded = []
        refreshed = []

        async def list_sources():
            return sources

        async def refresh(task_id, source_id, workspace_key):
            refreshed.append(task_id[0])
            outcome = outcomes[task_id[0]]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        async def record(task_id, source_id, workspace_key, **kwargs):
            recorded.append((task_id[0], kwargs))

        counts = asyncio.run(watch.check_due_sources(list_sources=list_sources, refresh=refresh, record=record,
                                                     research_enabled=research_enabled, interval_minutes=360, now=NOW, limit=limit))
        return counts, refreshed, recorded

    def test_changes_failures_and_unchanged_pages_are_recorded(self):
        class Detail(Exception):
            detail = "The page   did not load."

        sources = [source("a", 400), source("b", 500), source("c", 600)]
        outcomes = {"a": {"changed": True, "previous": {"snapshot_id": 1}}, "b": {"changed": False, "previous": {}}, "c": Detail()}
        counts, refreshed, recorded = self.run_check(sources, outcomes)
        self.assertEqual(counts, {"changed": 1, "unchanged": 1, "failed": 1})
        self.assertEqual(refreshed, ["c", "b", "a"])
        self.assertIn(("a", {"result": "changed"}), recorded)
        self.assertIn(("b", {"result": "ok"}), recorded)
        self.assertIn(("c", {"error": "The page did not load."}), recorded)

    def test_a_first_snapshot_is_not_a_change(self):
        counts, _, recorded = self.run_check([source("a", 400)], {"a": {"changed": True, "previous": None}})
        self.assertEqual(counts["changed"], 0)
        self.assertEqual(recorded, [("a", {"result": "ok"})])

    def test_nothing_is_fetched_while_research_is_off(self):
        counts, refreshed, recorded = self.run_check([source("a", 400)], {"a": {}}, research_enabled=False)
        self.assertEqual((counts, refreshed, recorded), ({"changed": 0, "unchanged": 0, "failed": 0}, [], []))

    def test_at_most_limit_checks_per_tick(self):
        sources = [source(name, 400 + index) for index, name in enumerate("abcde")]
        _, refreshed, _ = self.run_check(sources, {name: {"changed": False} for name in "abcde"}, limit=2)
        self.assertEqual(refreshed, ["e", "d"])


if __name__ == "__main__":
    unittest.main()
