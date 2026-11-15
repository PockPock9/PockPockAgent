import sys
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import agent_run_store
from projects.agent_tools.research_contracts import make_source_record

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import frog_ai_server as gateway


@contextmanager
def isolated_store():
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
                connection.close()


class ResearchCollectionStoreTests(unittest.TestCase):
    def setUp(self):
        self.source = make_source_record(
            url="https://example.com/research",
            provider="named_host_fetcher",
            retrieved_at=datetime.now(timezone.utc),
            title="Research page",
        )
        self.task_id = "1" * 32
        self.workspace_key = "a" * 64

    def test_saves_bounded_snapshots_and_retains_only_changed_versions(self):
        with isolated_store():
            agent_run_store.initialize_agent_store()
            agent_run_store.create_agent_run(self.task_id, None, "agent", "research")

            first = agent_run_store.add_research_collection_source(
                self.task_id,
                self.workspace_key,
                self.source.model_dump(mode="json"),
                "first version",
                False,
            )
            self.assertEqual(first["sources"][0]["version_count"], 1)

            unchanged = agent_run_store.add_research_collection_snapshot(
                self.task_id,
                self.source.source_id,
                self.workspace_key,
                self.source.model_dump(mode="json"),
                "first version",
                False,
            )
            self.assertFalse(unchanged["changed"])
            changed = agent_run_store.add_research_collection_snapshot(
                self.task_id,
                self.source.source_id,
                self.workspace_key,
                self.source.model_dump(mode="json"),
                "second version",
                True,
            )
            self.assertTrue(changed["changed"])
            self.assertEqual(changed["previous"]["text"], "first version")
            self.assertEqual(changed["current"]["text"], "second version")

            saved = agent_run_store.get_research_collection(self.task_id, self.workspace_key)
            versions = saved["sources"][0]["versions"]
            self.assertEqual(len(versions), 2)
            self.assertEqual(versions[1]["snapshot_id"], changed["current"]["snapshot_id"])
            snapshot = agent_run_store.get_research_snapshot(
                self.task_id,
                self.source.source_id,
                versions[0]["snapshot_id"],
                self.workspace_key,
            )
            self.assertEqual(snapshot["text"], "first version")
            self.assertTrue(versions[1]["truncated"])

    def test_enforces_byte_limit_and_isolates_workspace_scope(self):
        with isolated_store():
            agent_run_store.initialize_agent_store()
            agent_run_store.create_agent_run(self.task_id, None, "agent", "research")
            with self.assertRaisesRegex(ValueError, "200 KB"):
                agent_run_store.add_research_collection_source(
                    self.task_id,
                    self.workspace_key,
                    self.source.model_dump(mode="json"),
                    "x" * (agent_run_store.MAX_RESEARCH_SNAPSHOT_BYTES + 1),
                    False,
                )
            self.assertIsNone(agent_run_store.get_research_collection(self.task_id, self.workspace_key))
            agent_run_store.add_research_collection_source(
                self.task_id,
                self.workspace_key,
                self.source.model_dump(mode="json"),
                "saved text",
                False,
            )
            with self.assertRaises(agent_run_store.ResearchCollectionScopeError):
                agent_run_store.get_research_collection(self.task_id, "b" * 64)

            other_task = "2" * 32
            agent_run_store.create_agent_run(other_task, None, "agent", "other research")
            self.assertIsNone(agent_run_store.get_research_collection(other_task, self.workspace_key))
            agent_run_store.add_research_collection_source(
                other_task,
                self.workspace_key,
                self.source.model_dump(mode="json"),
                "other task text",
                False,
            )
            other = agent_run_store.get_research_collection(other_task, self.workspace_key)
            self.assertEqual(other["sources"][0]["latest"]["byte_count"], len("other task text".encode("utf-8")))

    def test_gateway_truncates_at_utf8_boundary(self):
        text, truncated = gateway._bounded_research_text("🙂" * 60_000)
        self.assertTrue(truncated)
        self.assertEqual(len(text.encode("utf-8")), agent_run_store.MAX_RESEARCH_SNAPSHOT_BYTES)

    def test_notes_persist_and_collection_deletion_removes_all_versions(self):
        with isolated_store():
            agent_run_store.initialize_agent_store()
            agent_run_store.create_agent_run(self.task_id, None, "agent", "research")
            agent_run_store.add_research_collection_source(
                self.task_id,
                self.workspace_key,
                self.source.model_dump(mode="json"),
                "saved text",
                False,
            )
            updated = agent_run_store.update_research_collection_note(
                self.task_id,
                self.source.source_id,
                self.workspace_key,
                "Review this source later.",
            )
            self.assertEqual(updated["notes"], "Review this source later.")
            self.assertEqual(len(updated["versions"]), 1)
            self.assertTrue(agent_run_store.delete_research_collection(self.task_id, self.workspace_key))
            self.assertIsNone(agent_run_store.get_research_collection(self.task_id, self.workspace_key))
            with agent_run_store.telemetry.connect_db() as connection:
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM research_collection_snapshots WHERE task_id=?",
                    (self.task_id,),
                ).fetchone()[0], 0)

    def test_gateway_only_fetches_on_save_or_manual_refresh_and_returns_differences(self):
        task_id = "3" * 32
        with isolated_store(), tempfile.TemporaryDirectory() as workspace:
            agent_run_store.initialize_agent_store()
            agent_run_store.create_agent_run(task_id, None, "agent", "research")
            workspace_key = gateway._workspace_collection_key(workspace)
            agent_run_store.store_agent_event(task_id, 1, {
                "type": "research_sources",
                "task_id": task_id,
                "workspace_key": workspace_key,
                "sources": [self.source.model_dump(mode="json")],
            })
            gateway.AGENT_TASK_WORKSPACES[task_id] = Path(workspace)
            self.addCleanup(gateway.AGENT_TASK_WORKSPACES.pop, task_id, None)

            async def run_endpoints():
                from unittest.mock import AsyncMock

                fetch_page = AsyncMock(side_effect=[
                    {"url": self.source.canonical_url, "title": "Research page", "text": "first saved page"},
                    {"url": self.source.canonical_url, "title": "Updated research page", "text": "updated saved page"},
                ])
                with patch.object(gateway, "require_local_agent_request"), \
                     patch.object(gateway, "require_research_provider"), \
                     patch.object(gateway, "scrape_public_page", fetch_page):
                    payload = gateway.ResearchCollectionSavePayload(
                        source_id=self.source.source_id,
                        notes="Check this claim",
                    )
                    saved = await gateway.save_agent_research_source(task_id, payload, None)
                    self.assertEqual(saved["collection"]["sources"][0]["notes"], "Check this claim")
                    collection = await gateway.read_agent_research_collection(task_id, None)
                    self.assertEqual(collection["collection"]["sources"][0]["version_count"], 1)
                    self.assertEqual(fetch_page.await_count, 1)

                    refreshed = await gateway.refresh_agent_research_source(
                        task_id,
                        self.source.source_id,
                        None,
                    )
                    self.assertTrue(refreshed["changed"])
                    self.assertEqual(refreshed["previous"]["text"], "first saved page")
                    self.assertEqual(refreshed["current"]["text"], "updated saved page")
                    self.assertEqual(fetch_page.await_count, 2)

            asyncio.run(run_endpoints())


if __name__ == "__main__":
    unittest.main()
