import sys
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import agent_run_store
from projects.run_store.contracts import (
    DelegationContract,
    build_delegate_context,
    delegate_task_prompt,
    restrict_delegate_tools,
)


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


class RunEventContractTests(unittest.TestCase):
    def test_delegate_execution_claim_is_atomic_parent_bound_and_requires_active_run(self):
        with isolated_store():
            agent_run_store.initialize_agent_store()
            parent = "a" * 32
            child = "b" * 32
            agent_run_store.create_agent_run(parent, "conversation", "agent", "parent")
            agent_run_store.store_agent_event(parent, 1, {
                "type": "delegation_plan",
                "status": "approved",
                "subtasks": [{
                    "id": "research",
                    "role": "researcher",
                    "purpose": "Research the topic",
                    "expected_result": "Provide two sources",
                    "allowed_tools": ["search_public_site"],
                }],
            })
            metadata = {
                "parent_run_id": parent,
                "subtask_id": "research",
                "role": "researcher",
                "dependency_ids": [],
                "context_scope": ["approved_task"],
                "workspace_scope": "isolated_task_workspace",
                "artifact_scope": [],
                "allowed_tools": ["search_public_site"],
                "permission_level": "default",
                "deadline_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            }
            agent_run_store.create_agent_run(
                child,
                "conversation",
                "delegate",
                "Research the topic\n\nExpected result: Provide two sources",
                metadata,
            )

            self.assertTrue(agent_run_store.claim_delegate_execution(child, parent))
            self.assertFalse(agent_run_store.claim_delegate_execution(child, parent))
            with self.assertRaises(agent_run_store.InvalidRunRelationship):
                agent_run_store.claim_delegate_execution(child, "c" * 32)

            agent_run_store.store_agent_event(child, 2, {
                "type": "done",
                "status": "success",
            })
            self.assertFalse(agent_run_store.claim_delegate_execution(child, parent))

    def test_existing_run_table_gets_cancellation_columns_in_place(self):
        with isolated_store():
            with agent_run_store.telemetry.connect_db() as connection:
                connection.execute("""CREATE TABLE agent_runs (
                    run_id TEXT PRIMARY KEY, conversation_id TEXT, task_type TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT ''
                )""")
            agent_run_store.initialize_agent_store()
            with agent_run_store.telemetry.connect_db() as connection:
                columns = {row["name"] for row in connection.execute("PRAGMA table_info(agent_runs)")}
            self.assertIn("cancel_requested_at", columns)
            self.assertIn("cancel_reason", columns)
            self.assertIn("parent_run_id", columns)
            self.assertIn("subtask_id", columns)
            self.assertIn("deadline_at", columns)
            self.assertIn("max_tool_calls", columns)
            self.assertIn("max_duration_seconds", columns)
            self.assertIn("permission_level", columns)

    def test_parent_child_contract_persists_and_rejects_cross_conversation_or_bad_dependencies(self):
        from datetime import datetime, timedelta, timezone

        with isolated_store():
            agent_run_store.initialize_agent_store()
            parent = "1" * 32
            child = "2" * 32
            agent_run_store.create_agent_run(parent, "conversation", "agent", "parent", permission_level="auto-review")
            agent_run_store.store_agent_event(parent, 1, {"type": "delegation_plan", "status": "approved", "subtasks": [
                {"id": "research", "role": "researcher", "purpose": "Research the topic",
                 "expected_result": "Provide two sources", "allowed_tools": ["search_public_site", "scrape_public_page"]},
            ]})
            metadata = {
                "parent_run_id": parent, "subtask_id": "research", "role": "researcher", "dependency_ids": [],
                "context_scope": ["approved_task"], "workspace_scope": "isolated_task_workspace",
                "artifact_scope": [],
                "allowed_tools": ["search_public_site"], "permission_level": "default",
                "deadline_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            }
            task = "Research the topic\n\nExpected result: Provide two sources"
            agent_run_store.create_agent_run(child, "conversation", "delegate", task, metadata)
            agent_run_store.store_agent_event(child, 1, {
                "type": "delegate_result", "contract_version": 1, "parent_run_id": parent,
                "result": {"contract_version": 1, "status": "completed", "summary": "Child completed"},
            })
            run, _ = agent_run_store.get_run_events(child, 0, 10)
            self.assertEqual(run["delegation"]["parent_run_id"], parent)
            self.assertEqual(run["delegation"]["role"], "researcher")
            self.assertEqual(run["delegation"]["subtask_id"], "research")
            self.assertEqual(run["delegation"]["permission_level"], "default")
            self.assertEqual(run["delegation"]["allowed_tools"], ["search_public_site"])
            _, events = agent_run_store.get_run_events(child, 0, 10)
            self.assertEqual(events[0]["event"]["type"], "delegate_result")
            self.assertEqual(events[0]["event"]["result"]["summary"], "Child completed")
            with self.assertRaises(agent_run_store.InvalidRunRelationship):
                agent_run_store.create_agent_run("3" * 32, "other", "delegate", "cross", metadata)
            with self.assertRaisesRegex(agent_run_store.InvalidRunRelationship, "approved subtask instructions"):
                agent_run_store.create_agent_run("4" * 32, "conversation", "delegate", "unapproved task", metadata)
            metadata["dependency_ids"] = ["4" * 32]
            with self.assertRaises(agent_run_store.InvalidRunRelationship):
                agent_run_store.create_agent_run("5" * 32, "conversation", "delegate", "bad dep", metadata)
            unapproved_parent = "6" * 32
            agent_run_store.create_agent_run(unapproved_parent, "conversation", "agent", "unapproved parent")
            agent_run_store.store_agent_event(unapproved_parent, 1, {
                "type": "delegation_plan", "status": "proposed",
                "subtasks": [{"id": "research", "role": "researcher", "purpose": "Research the topic",
                              "expected_result": "Provide two sources", "allowed_tools": ["search_public_site"]}],
            })
            metadata["parent_run_id"] = unapproved_parent
            metadata["dependency_ids"] = []
            with self.assertRaisesRegex(agent_run_store.InvalidRunRelationship, "not been approved"):
                agent_run_store.create_agent_run("7" * 32, "conversation", "delegate", task, metadata)

            completed_parent = "8" * 32
            agent_run_store.create_agent_run(completed_parent, "conversation", "agent", "completed parent")
            agent_run_store.store_agent_event(completed_parent, 1, {
                "type": "delegation_plan", "status": "approved",
                "subtasks": [{"id": "research", "role": "researcher", "purpose": "Research the topic",
                              "expected_result": "Provide two sources", "allowed_tools": ["search_public_site"]}],
            })
            agent_run_store.store_agent_event(completed_parent, 2, {"type": "done", "status": "success"})
            metadata["parent_run_id"] = completed_parent
            with self.assertRaisesRegex(agent_run_store.InvalidRunRelationship, "must be active"):
                agent_run_store.create_agent_run("9" * 32, "conversation", "delegate", task, metadata)

    def test_child_cannot_widen_parent_permission_or_tools_or_workspace(self):
        from datetime import datetime, timedelta, timezone

        with isolated_store():
            agent_run_store.initialize_agent_store()
            parent = "6" * 32
            agent_run_store.create_agent_run(parent, "isolation", "agent", "parent", permission_level="auto-review")
            agent_run_store.store_agent_event(parent, 1, {"type": "delegation_plan", "status": "approved", "subtasks": [
                {"id": "edit", "role": "editor", "purpose": "Edit one file",
                 "expected_result": "Return a reviewed change", "allowed_tools": ["read_project_file", "propose_project_patch"]},
            ]})
            metadata = {
                "parent_run_id": parent, "subtask_id": "edit", "role": "editor", "dependency_ids": [],
                "context_scope": ["approved_task"], "workspace_scope": "isolated_task_workspace",
                "artifact_scope": [], "allowed_tools": ["propose_project_patch"], "permission_level": "full-access",
                "deadline_at": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
            }
            with self.assertRaisesRegex(agent_run_store.InvalidRunRelationship, "permission"):
                agent_run_store.create_agent_run("7" * 32, "isolation", "delegate", "Edit one file\n\nExpected result: Return a reviewed change", metadata)
            metadata["permission_level"] = "default"
            metadata["allowed_tools"] = ["browser_action"]
            with self.assertRaisesRegex(agent_run_store.InvalidRunRelationship, "tools"):
                agent_run_store.create_agent_run("8" * 32, "isolation", "delegate", "Edit one file\n\nExpected result: Return a reviewed change", metadata)
            metadata["allowed_tools"] = ["propose_project_patch"]
            metadata["max_tool_calls"] = 1
            with self.assertRaisesRegex(agent_run_store.InvalidRunRelationship, "execution limits"):
                agent_run_store.create_agent_run(
                    "c" * 32, "isolation", "delegate",
                    "Edit one file\n\nExpected result: Return a reviewed change", metadata,
                )
            metadata.pop("max_tool_calls")
            too_much_context = dict(metadata, context_scope=["approved_task", "dependency_results"])
            with self.assertRaisesRegex(agent_run_store.InvalidRunRelationship, "context exceeds"):
                agent_run_store.create_agent_run(
                    "9" * 32, "isolation", "delegate", "Edit one file\n\nExpected result: Return a reviewed change", too_much_context
                )
            unassigned_artifacts = dict(metadata, artifact_scope=["private-parent-artifact"])
            with self.assertRaisesRegex(ValueError, "Artifact access is unavailable"):
                agent_run_store.create_agent_run(
                    "a" * 32, "isolation", "delegate", "Edit one file\n\nExpected result: Return a reviewed change", unassigned_artifacts
                )
            metadata["workspace_scope"] = "shared_parent_workspace"
            with self.assertRaises(ValueError):
                agent_run_store.create_agent_run("b" * 32, "isolation", "delegate", "Edit one file\n\nExpected result: Return a reviewed change", metadata)

    def test_child_can_read_only_approved_completed_dependency_results(self):
        from datetime import datetime, timedelta, timezone

        with isolated_store():
            agent_run_store.initialize_agent_store()
            parent = "a" * 32
            first = "b" * 32
            second = "c" * 32
            agent_run_store.create_agent_run(parent, "deps", "agent", "parent")
            agent_run_store.store_agent_event(parent, 1, {"type": "delegation_plan", "status": "approved", "subtasks": [
                {"id": "first", "role": "worker", "purpose": "Work on first", "expected_result": "Result for first",
                 "allowed_tools": ["search_public_site"]},
                {"id": "second", "role": "worker", "purpose": "Work on second", "expected_result": "Result for second",
                 "depends_on": ["first"], "allowed_tools": ["save_text_artifact"]},
            ]})
            def metadata(subtask_id, tools, dependencies=()):
                return {
                    "parent_run_id": parent, "subtask_id": subtask_id, "role": "worker",
                    "dependency_ids": list(dependencies),
                    "context_scope": ["approved_task"] + (["dependency_results"] if dependencies else []),
                    "workspace_scope": "isolated_task_workspace", "artifact_scope": [],
                    "allowed_tools": tools, "permission_level": "default",
                    "deadline_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
                }
            first_task = "Work on first\n\nExpected result: Result for first"
            agent_run_store.create_agent_run(first, "deps", "delegate", first_task, metadata("first", ["search_public_site"]))
            agent_run_store.store_agent_event(first, 1, {"type": "done", "status": "success"})
            second_task = "Work on second\n\nExpected result: Result for second"
            agent_run_store.create_agent_run(second, "deps", "delegate", second_task, metadata("second", ["save_text_artifact"], [first]))
            replayed, _ = agent_run_store.get_run_events(second, 0, 10)
            self.assertEqual(replayed["delegation"]["dependency_ids"], [first])
            unauthorized_dependency = metadata("first", ["search_public_site"], [first])
            unauthorized_dependency["context_scope"] = ["approved_task"]
            with self.assertRaisesRegex(agent_run_store.InvalidRunRelationship, "approved for its subtask"):
                agent_run_store.create_agent_run("d" * 32, "deps", "delegate", first_task, unauthorized_dependency)

    def test_delegate_context_includes_only_approved_task_and_dependencies(self):
        from datetime import datetime, timedelta, timezone

        contract = DelegationContract(
            parent_run_id="1" * 32, subtask_id="research", role="researcher",
            dependency_ids=["2" * 32], context_scope=["approved_task", "dependency_results"],
            workspace_scope="isolated_task_workspace", artifact_scope=[],
            allowed_tools=["search_public_site"], permission_level="default",
            deadline_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        context = build_delegate_context(
            contract,
            approved_subtask={"id": "research", "role": "researcher", "purpose": "Research request", "expected_result": "Notes"},
            dependency_results={"2" * 32: {"summary": "Prior result"}, "3" * 32: {"summary": "Sibling result"}},
        )
        self.assertEqual(context["dependency_results"], {"2" * 32: {"summary": "Prior result"}})
        self.assertEqual(context["approved_task"], "Research request\n\nExpected result: Notes")
        self.assertNotIn("artifacts", context)
        specs = [
            {"type": "function", "function": {"name": "search_public_site"}},
            {"type": "function", "function": {"name": "browser_action"}},
        ]
        self.assertEqual(restrict_delegate_tools(contract, specs), [specs[0]])

    def test_delegation_result_is_versioned_and_typed(self):
        parent = "a" * 32
        event = agent_run_store._normalize_run_event({
            "type": "delegate_result", "contract_version": 1, "parent_run_id": parent,
            "result": {"contract_version": 1, "status": "completed", "summary": "Found two sources", "evidence": ["source-1"]},
        }, for_write=True)
        self.assertEqual(event["result"]["status"], "completed")
        with self.assertRaises(agent_run_store.RunEventContractError):
            agent_run_store._normalize_run_event({
                "type": "delegate_result", "contract_version": 1, "parent_run_id": parent,
                "result": {"status": "success", "summary": "unsupported status"},
            }, for_write=True)

    def test_terminal_child_accepts_one_typed_result_after_completion(self):
        with isolated_store():
            agent_run_store.initialize_agent_store()
            parent = "1" * 32
            child = "2" * 32
            agent_run_store.create_agent_run(parent, "conversation", "agent", "parent")
            agent_run_store.store_agent_event(parent, 1, {"type": "delegation_plan", "status": "approved", "subtasks": [
                {"id": "worker", "role": "worker", "purpose": "Work", "expected_result": "Result",
                 "allowed_tools": ["search_public_site"]},
            ]})
            agent_run_store.create_agent_run(child, "conversation", "delegate", "Work\n\nExpected result: Result", {
                "parent_run_id": parent, "subtask_id": "worker", "role": "worker", "dependency_ids": [],
                "context_scope": ["approved_task"], "workspace_scope": "isolated_task_workspace",
                "artifact_scope": [], "allowed_tools": ["search_public_site"], "permission_level": "default",
                "deadline_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            })
            agent_run_store.store_agent_event(child, 1, {"type": "done", "status": "success"})
            result = {
                "type": "delegate_result", "contract_version": 1, "parent_run_id": parent,
                "result": {"contract_version": 1, "status": "completed", "summary": "Result verified"},
            }
            self.assertTrue(agent_run_store.store_agent_event(child, 2, result))
            self.assertFalse(agent_run_store.store_agent_event(child, 3, result))
            late_activity = agent_run_store.store_agent_event(
                child, 4, {"type": "status", "message": "Should not persist"}
            )
            self.assertFalse(late_activity)
            run, events = agent_run_store.get_run_events(child, 0, 10)
            self.assertEqual(run["status"], "completed")
            self.assertEqual(events[-1]["event"]["type"], "delegate_result")
            self.assertEqual(events[-1]["event"]["result"]["summary"], "Result verified")

    def test_child_count_and_depth_limits_are_enforced(self):
        from datetime import datetime, timedelta, timezone

        with isolated_store():
            agent_run_store.initialize_agent_store()
            def create(run_id, parent_id, subtask_id):
                proposal = {
                    "id": subtask_id, "role": "worker", "purpose": f"Work on {subtask_id}",
                    "expected_result": f"Result for {subtask_id}",
                }
                agent_run_store.create_agent_run(run_id, "limits", "agent", delegate_task_prompt(proposal), {
                    "parent_run_id": parent_id, "subtask_id": subtask_id, "role": "worker", "dependency_ids": [],
                    "context_scope": ["approved_task"], "workspace_scope": "isolated_task_workspace",
                    "artifact_scope": [], "allowed_tools": ["search_public_site"], "permission_level": "default",
                    "deadline_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                })
            root = "a" * 32
            agent_run_store.create_agent_run(root, "limits", "agent", "root")
            agent_run_store.store_agent_event(root, 1, {"type": "delegation_plan", "status": "approved", "subtasks": [
                {"id": f"worker-{index}", "role": "worker", "purpose": f"Work on worker-{index}",
                 "expected_result": f"Result for worker-{index}", "allowed_tools": ["search_public_site"]}
                for index in range(16)
            ]})
            for index in range(16):
                create(f"{index + 1:032x}", root, f"worker-{index}")
            with self.assertRaises(agent_run_store.InvalidRunRelationship):
                create("f" * 32, root, "worker-0")
            chain_root = "9" * 32
            agent_run_store.create_agent_run(chain_root, "limits", "agent", "chain root")
            first, second, third, fourth = "b" * 32, "c" * 32, "d" * 32, "e" * 32
            agent_run_store.store_agent_event(chain_root, 1, {"type": "delegation_plan", "status": "approved", "subtasks": [
                {"id": "first", "role": "worker", "purpose": "Work on first", "expected_result": "Result for first", "allowed_tools": ["search_public_site"]}
            ]})
            create(first, chain_root, "first")
            for parent, child, subtask in [(first, second, "second"), (second, third, "third"), (third, fourth, "fourth")]:
                agent_run_store.store_agent_event(parent, 1, {"type": "delegation_plan", "status": "approved", "subtasks": [
                    {"id": subtask, "role": "worker", "purpose": f"Work on {subtask}",
                     "expected_result": f"Result for {subtask}", "allowed_tools": ["search_public_site"]}
                ]})
                if child != fourth:
                    create(child, parent, subtask)
            with self.assertRaises(agent_run_store.InvalidRunRelationship):
                create(fourth, third, "fourth")

    def test_new_event_gets_current_contract_version(self):
        event = agent_run_store._normalize_run_event({"type": "progress", "message": "Working"}, for_write=True)
        self.assertEqual(event["contract_version"], 1)

    def test_old_event_replays_as_legacy_version(self):
        event = agent_run_store._normalize_run_event({"type": "progress", "message": "Old"}, for_write=False)
        self.assertEqual(event["contract_version"], 0)

    def test_legacy_persisted_event_replays_without_migration(self):
        with isolated_store():
            agent_run_store.initialize_agent_store()
            run_id = "a" * 32
            agent_run_store.create_agent_run(run_id, None, "agent", "legacy replay check")
            with agent_run_store.telemetry.connect_db() as connection:
                connection.execute(
                    "INSERT INTO agent_run_events(run_id, sequence, created_at, event_type, payload) VALUES (?, ?, ?, ?, ?)",
                    (run_id, 1, "2026-01-01T00:00:00Z", "progress", '{"type":"progress","message":"Old"}'),
                )
            run, events = agent_run_store.get_run_events(run_id, 0, 10)
            self.assertEqual(run["run_id"], run_id)
            self.assertEqual(events[0]["event"]["contract_version"], 0)
            self.assertEqual(events[0]["event"]["message"], "Old")

    def test_cancel_request_and_terminal_event_survive_replay_and_reject_late_events(self):
        with isolated_store():
            agent_run_store.initialize_agent_store()
            run_id = "b" * 32
            agent_run_store.create_agent_run(run_id, None, "agent", "cancel check")
            self.assertEqual(agent_run_store.request_agent_run_cancel(run_id), {
                "accepted": True, "status": "cancelling", "reason": "user"
            })
            agent_run_store.finish_incomplete_agent_run(run_id)
            run, events = agent_run_store.get_run_events(run_id, 0, 10)
            self.assertEqual(run["status"], "cancelled")
            self.assertEqual(events[-1]["event"]["type"], "cancelled")
            self.assertFalse(agent_run_store.store_agent_event(run_id, 99, {"type": "done", "status": "success"}))
            run, _ = agent_run_store.get_run_events(run_id, 0, 10)
            self.assertEqual(run["status"], "cancelled")

    def test_approval_is_durable_payload_bound_and_replayable(self):
        with isolated_store():
            agent_run_store.initialize_agent_store()
            run_id = "8" * 32
            approval_id = "9" * 32
            agent_run_store.create_agent_run(run_id, None, "agent", "approval check")
            action = {"tool": "propose_project_patch", "path": "index.html", "diff": "-old\n+new"}
            action_hash = hashlib.sha256(json.dumps(action, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
            agent_run_store.create_agent_approval(run_id, approval_id, action_hash, action, expires_at)
            self.assertTrue(agent_run_store.store_agent_event(run_id, 1, {
                "type": "approval_requested", "approval_id": approval_id, "action_hash": action_hash, "action": action,
            }))
            with self.assertRaisesRegex(ValueError, "does not match"):
                agent_run_store.resolve_agent_approval(run_id, approval_id, "b" * 64, "approved")
            resolved = agent_run_store.resolve_agent_approval(run_id, approval_id, action_hash, "approved")
            self.assertTrue(resolved["accepted"])
            self.assertEqual(resolved["status"], "approved")
            self.assertTrue(agent_run_store.store_agent_event(run_id, 2, {
                "type": "approval_approved", "approval_id": approval_id, "action_hash": action_hash,
            }))
            run, events = agent_run_store.get_run_events(run_id, 0, 10)
            self.assertEqual(run["status"], "running")
            self.assertEqual(events[0]["event"]["action"], action)
            self.assertEqual(events[1]["event"]["type"], "approval_approved")
            self.assertFalse(agent_run_store.resolve_agent_approval(run_id, approval_id, action_hash, "rejected")["accepted"])

    def test_expired_or_inactive_run_approval_cannot_be_applied(self):
        with isolated_store():
            agent_run_store.initialize_agent_store()
            run_id = "7" * 32
            approval_id = "6" * 32
            agent_run_store.create_agent_run(run_id, None, "agent", "expired approval check")
            action = {"tool": "propose_project_patch", "path": "index.html", "diff": "+change"}
            action_hash = hashlib.sha256(json.dumps(action, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            agent_run_store.create_agent_approval(run_id, approval_id, action_hash, action, past)
            expired = agent_run_store.resolve_agent_approval(run_id, approval_id, action_hash, "approved")
            self.assertFalse(expired["accepted"])
            self.assertEqual(expired["status"], "expired")

    def test_timeout_request_finishes_as_timed_out_and_disconnect_as_interrupted(self):
        with isolated_store():
            agent_run_store.initialize_agent_store()
            timed_out = "c" * 32
            agent_run_store.create_agent_run(timed_out, None, "agent", "timeout check")
            agent_run_store.request_agent_run_cancel(timed_out, reason="timeout")
            agent_run_store.finish_incomplete_agent_run(timed_out)
            run, events = agent_run_store.get_run_events(timed_out, 0, 10)
            self.assertEqual(run["status"], "timed_out")
            self.assertEqual(events[-1]["event"]["type"], "timed_out")

            interrupted = "d" * 32
            agent_run_store.create_agent_run(interrupted, None, "agent", "disconnect check")
            agent_run_store.finish_incomplete_agent_run(interrupted)
            run, events = agent_run_store.get_run_events(interrupted, 0, 10)
            self.assertEqual(run["status"], "interrupted")
            self.assertEqual(events[-1]["event"]["type"], "interrupted")

    def test_gateway_restart_recovers_running_and_cancelling_runs(self):
        with isolated_store():
            agent_run_store.initialize_agent_store()
            running = "f" * 32
            cancelling = "1" * 32
            agent_run_store.create_agent_run(running, None, "agent", "restart while running")
            agent_run_store.create_agent_run(cancelling, None, "agent", "restart while cancelling")
            agent_run_store.request_agent_run_cancel(cancelling)
            self.assertEqual(agent_run_store.recover_incomplete_agent_runs(), 2)
            run, events = agent_run_store.get_run_events(running, 0, 10)
            self.assertEqual(run["status"], "interrupted")
            self.assertEqual(events[-1]["event"]["type"], "interrupted")
            run, events = agent_run_store.get_run_events(cancelling, 0, 10)
            self.assertEqual(run["status"], "cancelled")
            self.assertEqual(events[-1]["event"]["type"], "cancelled")

    def test_error_events_have_a_typed_error_envelope(self):
        event = agent_run_store._normalize_run_event({"type": "error", "message": "Failed"}, for_write=True)
        self.assertEqual(event["error"], {
            "contract_version": 1,
            "code": "agent_run_error",
            "message": "Failed",
            "retryable": False,
        })

    def test_unsupported_event_or_error_versions_fail_actionably(self):
        with self.assertRaisesRegex(agent_run_store.RunEventContractError, "supports versions 0 and 1"):
            agent_run_store._normalize_run_event({"type": "progress", "contract_version": 2}, for_write=True)
        with self.assertRaisesRegex(agent_run_store.RunEventContractError, "supports version 1"):
            agent_run_store._normalize_run_event({"type": "error", "error": {"contract_version": 2}}, for_write=True)


if __name__ == "__main__":
    unittest.main()
