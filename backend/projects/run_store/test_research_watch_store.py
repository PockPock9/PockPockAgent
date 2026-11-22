"""Watching saved research sources (UI-01E): store state, migration, and the gateway routes and
background pass, with the page fetch mocked (no network)."""
import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import agent_run_store
import pockpock_server as gateway
from fastapi import HTTPException
from projects.agent_tools.research_contracts import make_source_record
from contextlib import contextmanager


@contextmanager
def isolated_store():
    """A temporary database. The gateway reads it from worker threads (asyncio.to_thread), so
    connections opened there are closed in their own thread by the store and skipped here."""
    with tempfile.TemporaryDirectory() as directory:
        connections = []
        original_connect = agent_run_store.telemetry.connect_db

        def tracked_connect():
            connection = original_connect()
            connections.append(connection)
            return connection

        try:
            with patch.object(agent_run_store.telemetry, "DB_PATH", Path(directory) / "runs.sqlite3"), patch.object(
                agent_run_store.telemetry, "connect_db", tracked_connect
            ):
                yield
        finally:
            for connection in connections:
                try:
                    connection.close()
                except sqlite3.ProgrammingError:
                    pass


def make_source(name="research"):
    return make_source_record(
        url=f"https://example.com/{name}",
        provider="named_host_fetcher",
        retrieved_at=datetime.now(timezone.utc),
        title=f"{name.title()} page",
    )


class WatchStoreTests(unittest.TestCase):
    task_id = "1" * 32
    workspace_key = "a" * 64

    def save(self, source):
        agent_run_store.add_research_collection_source(
            self.task_id, self.workspace_key, source.model_dump(mode="json"), "first version", False,
        )

    def watch(self, source, **changes):
        return agent_run_store.update_research_source_watch(self.task_id, source.source_id, self.workspace_key, **changes)

    def test_watch_state_follows_turning_on_changes_seen_errors_and_off(self):
        source = make_source()
        with isolated_store():
            agent_run_store.initialize_agent_store()
            agent_run_store.create_agent_run(self.task_id, None, "agent", "research")
            self.save(source)
            state = agent_run_store.get_research_collection_source(self.task_id, source.source_id, self.workspace_key)["watch"]
            self.assertEqual(state, {"watched": False, "changed_at": None, "unseen": False, "error": "", "error_at": None})
            self.assertEqual(agent_run_store.list_watched_research_sources(), [])

            self.assertTrue(self.watch(source, watched=True)["watch"]["watched"])
            listed = agent_run_store.list_watched_research_sources()
            self.assertEqual([(item["task_id"], item["source_id"], item["workspace_key"], item["url"]) for item in listed],
                             [(self.task_id, source.source_id, self.workspace_key, source.canonical_url)])

            changed = self.watch(source, result="changed")["watch"]
            self.assertTrue(changed["unseen"])
            self.assertIsNotNone(changed["changed_at"])
            self.assertFalse(self.watch(source, seen=True)["watch"]["unseen"])

            failed = self.watch(source, error="The page\n did not load.")["watch"]
            self.assertEqual(failed["error"], "The page did not load.")
            self.assertIsNotNone(failed["error_at"])
            self.assertEqual(self.watch(source, result="ok")["watch"]["error"], "")

            self.watch(source, result="changed")
            off = self.watch(source, watched=False)["watch"]
            self.assertEqual((off["watched"], off["unseen"], off["error"]), (False, False, ""))
            self.assertEqual(agent_run_store.list_watched_research_sources(), [])
            # The collection view carries the same state.
            collection = agent_run_store.get_research_collection(self.task_id, self.workspace_key)
            self.assertFalse(collection["sources"][0]["watch"]["watched"])

    def test_unsaved_sources_other_workspaces_and_bad_values_are_refused(self):
        source = make_source()
        with isolated_store():
            agent_run_store.initialize_agent_store()
            agent_run_store.create_agent_run(self.task_id, None, "agent", "research")
            self.assertIsNone(self.watch(source, watched=True))
            self.save(source)
            with self.assertRaises(agent_run_store.ResearchCollectionScopeError):
                agent_run_store.update_research_source_watch(self.task_id, source.source_id, "b" * 64, watched=True)
            for changes in ({"result": "maybe"}, {"error": "  "}, {"watched": "yes"}):
                with self.assertRaises(ValueError):
                    self.watch(source, **changes)

    def test_at_most_fifty_sources_are_watched(self):
        with isolated_store():
            agent_run_store.initialize_agent_store()
            agent_run_store.create_agent_run(self.task_id, None, "agent", "research")
            sources = [make_source(f"page-{index}") for index in range(agent_run_store.MAX_WATCHED_RESEARCH_SOURCES + 1)]
            for source in sources:
                self.save(source)
            for source in sources[:-1]:
                self.watch(source, watched=True)
            with self.assertRaisesRegex(ValueError, "At most 50"):
                self.watch(sources[-1], watched=True)
            self.watch(sources[0], watched=True)  # Already watched: not refused.

    def test_an_older_database_gains_the_watch_columns(self):
        with isolated_store():
            with closing(sqlite3.connect(agent_run_store.telemetry.DB_PATH)) as connection, connection:
                connection.execute("""CREATE TABLE research_collection_sources (
                    task_id TEXT NOT NULL, source_id TEXT NOT NULL, source_json TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    last_checked_at TEXT NOT NULL, PRIMARY KEY (task_id, source_id))""")
                connection.execute("INSERT INTO research_collection_sources VALUES ('t', 's', '{}', '', 'x', 'x', 'x')")
            agent_run_store.initialize_agent_store()
            with closing(sqlite3.connect(agent_run_store.telemetry.DB_PATH)) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(research_collection_sources)")}
                row = connection.execute("SELECT watched, watch_unseen, watch_error FROM research_collection_sources").fetchone()
            self.assertTrue(set(agent_run_store.RESEARCH_WATCH_COLUMNS) <= columns)
            self.assertEqual(row, (0, 0, ""))


class WatchGatewayTests(unittest.TestCase):
    task_id = "3" * 32

    def test_watch_list_background_check_seen_and_errors(self):
        source = make_source()
        with isolated_store(), tempfile.TemporaryDirectory() as workspace:
            agent_run_store.initialize_agent_store()
            agent_run_store.create_agent_run(self.task_id, None, "agent", "research")
            workspace_key = gateway._workspace_collection_key(workspace)
            agent_run_store.store_agent_event(self.task_id, 1, {
                "type": "research_sources", "task_id": self.task_id, "workspace_key": workspace_key,
                "sources": [source.model_dump(mode="json")],
            })
            gateway.AGENT_TASK_WORKSPACES[self.task_id] = Path(workspace)
            self.addCleanup(gateway.AGENT_TASK_WORKSPACES.pop, self.task_id, None)

            def age_last_check(hours):
                old = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
                with closing(agent_run_store.telemetry.connect_db()) as connection, connection:
                    connection.execute("UPDATE research_collection_sources SET last_checked_at=?, watch_error_at=NULL", (old,))

            async def scenario():
                fetch_page = AsyncMock(side_effect=[
                    {"url": source.canonical_url, "title": "Research page", "text": "first saved page"},
                    {"url": source.canonical_url, "title": "Research page", "text": "the page changed"},
                    gateway.AgentToolError("The page did not load."),
                ])
                with patch.object(gateway, "require_local_agent_request"), \
                     patch.object(gateway, "require_research_provider"), \
                     patch.object(gateway, "research_provider", return_value="named_hosts"), \
                     patch.object(gateway, "scrape_public_page", fetch_page):
                    watch_on = gateway.ResearchSourceWatchPayload(watched=True)
                    with self.assertRaises(HTTPException) as unsaved:
                        await gateway.watch_agent_research_source(self.task_id, source.source_id, watch_on, None)
                    self.assertEqual(unsaved.exception.status_code, 404)

                    await gateway.save_agent_research_source(
                        self.task_id, gateway.ResearchCollectionSavePayload(source_id=source.source_id), None)
                    watched = await gateway.watch_agent_research_source(self.task_id, source.source_id, watch_on, None)
                    self.assertTrue(watched["source"]["watch"]["watched"])

                    listed = await gateway.read_watched_research_sources(None)
                    self.assertTrue(listed["research_enabled"])
                    self.assertEqual(listed["interval_minutes"], 360)
                    self.assertEqual(len(listed["sources"]), 1)
                    self.assertNotIn("workspace_key", listed["sources"][0])
                    self.assertIsNotNone(listed["sources"][0]["next_check_at"])

                    # Just saved: not due, nothing fetched.
                    self.assertEqual(await gateway.check_watched_research_sources(), {"changed": 0, "unchanged": 0, "failed": 0})
                    self.assertEqual(fetch_page.await_count, 1)

                    age_last_check(7)
                    self.assertEqual((await gateway.check_watched_research_sources())["changed"], 1)
                    item = (await gateway.read_watched_research_sources(None))["sources"][0]
                    self.assertTrue(item["watch"]["unseen"])
                    seen = await gateway.mark_watched_research_source_seen(self.task_id, source.source_id, None)
                    self.assertFalse(seen["source"]["watch"]["unseen"])

                    age_last_check(7)
                    self.assertEqual((await gateway.check_watched_research_sources())["failed"], 1)
                    item = (await gateway.read_watched_research_sources(None))["sources"][0]
                    self.assertEqual(item["watch"]["error"], "The page did not load.")
                    # The failed check waits a full interval before it is tried again.
                    self.assertEqual(await gateway.check_watched_research_sources(), {"changed": 0, "unchanged": 0, "failed": 0})
                    self.assertEqual(fetch_page.await_count, 3)

                with patch.object(gateway, "require_local_agent_request"), \
                     patch.object(gateway, "research_provider", return_value="disabled"), \
                     patch.object(gateway, "scrape_public_page", AsyncMock()) as never:
                    age_last_check(7)
                    await gateway.check_watched_research_sources()
                    never.assert_not_awaited()
                    self.assertFalse((await gateway.read_watched_research_sources(None))["research_enabled"])

            asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
