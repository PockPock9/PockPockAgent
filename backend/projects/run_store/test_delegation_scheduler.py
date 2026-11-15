import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import agent_run_store
import frog_ai_server as gateway
from projects.agent_tools import common as agent_tool_common
from projects.planner.contracts import SubtaskPlan
from projects.run_store.delegation_scheduler import (
    configured_delegate_concurrency,
    create_or_load_delegate_run,
    existing_delegate_result,
    run_subtask_plan,
    stable_delegate_run_id,
)
from projects.run_store.contracts import DelegationContract, DelegationResult, bounded_dependency_results


class DelegateSchedulerTests(unittest.IsolatedAsyncioTestCase):
    def test_gateway_child_payload_contains_only_approved_scope(self):
        parent_brief = gateway.TaskBrief(
            original_request="Private parent conversation",
            desired_outcome="Complete parent work",
            permission_level="full-access",
            milestones=[{
                "id": "one", "title": "Parent", "completion_check": "Complete parent",
            }],
            success_checks=["Complete parent"],
        )
        parent_payload = gateway.AgentTaskPayload(
            task="Parent execution prompt",
            source_task="Private parent conversation",
            preferred_model="local-model",
            conversation_id="conversation",
            permission_mode="full-access",
            plan=["Parent"],
            success_checks=["Complete parent"],
            task_brief=parent_brief,
            plan_history=[
                {"version": 1, "status": "proposed", "plan": ["Parent"],
                 "success_checks": ["Complete parent"], "plan_hash": "1" * 64},
                {"version": 2, "status": "approved", "plan": ["Parent"],
                 "success_checks": ["Complete parent"], "plan_hash": "2" * 64},
            ],
            plan_id="3" * 32,
            plan_hash="4" * 64,
        )
        subtask = {
            "id": "summarize", "role": "writer", "purpose": "Summarize the result",
            "expected_result": "A concise summary", "allowed_tools": ["save_text_artifact"],
            "max_tool_calls": 4, "max_duration_seconds": 120,
        }
        contract = DelegationContract(
            parent_run_id="a" * 32,
            subtask_id="summarize",
            role="writer",
            dependency_ids=["b" * 32],
            context_scope=["approved_task", "dependency_results"],
            workspace_scope="isolated_task_workspace",
            artifact_scope=[],
            allowed_tools=["save_text_artifact"],
            max_tool_calls=4,
            max_duration_seconds=120,
            permission_level="default",
            deadline_at=datetime.now(timezone.utc) + timedelta(minutes=2),
        )
        with patch.dict(gateway.AGENT_PLAN_TICKETS, {}, clear=True):
            child = gateway.build_delegate_execution_payload(
                parent_payload=parent_payload,
                child_run_id="c" * 32,
                subtask=subtask,
                contract=contract,
                dependency_results={
                    "b" * 32: DelegationResult(
                        status="completed", summary="Approved dependency output",
                    ).model_dump(mode="json"),
                },
            )
            self.assertEqual(child.source_task, "Summarize the result\n\nExpected result: A concise summary")
            self.assertEqual(child.files, [])
            self.assertIsNone(child.workspace_path)
            self.assertEqual(child.permission_mode, "default")
            self.assertEqual(child.delegation_contract.allowed_tools, ["save_text_artifact"])
            self.assertIn("Approved dependency output", child.task)
            self.assertNotIn("Private parent conversation", child.task)
            self.assertEqual(len(gateway.AGENT_PLAN_TICKETS), 1)

    async def test_gateway_executes_child_with_filtered_tools_and_persists_result(self):
        parent_id = "d" * 32
        subtask_data = {
            "id": "summarize", "role": "writer", "purpose": "Summarize the result",
            "expected_result": "A concise summary", "depends_on": [],
            "allowed_tools": ["list_project_files", "propose_project_patch"], "max_tool_calls": 4,
            "max_duration_seconds": 120,
        }
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request({
            "type": "http",
            "method": "POST",
            "path": "/api/agents/run",
            "headers": [(b"origin", b"http://127.0.0.1:5173")],
            "client": ("127.0.0.1", 40000),
            "server": ("127.0.0.1", 8766),
            "scheme": "http",
            "query_string": b"",
        }, receive=receive)
        sent_tool_sets = []
        model_requests = []
        child_chat_calls = [0]
        connections = []

        class FakeResponse:
            status = 200

            def __init__(self, value):
                self.value = value

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def json(self):
                return self.value

        class FakeSession:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def post(self, url, **kwargs):
                if url.endswith("/api/show"):
                    return FakeResponse({"capabilities": ["tools"]})
                request_payload = kwargs.get("json", {})
                tool_names = [item["function"]["name"] for item in request_payload.get("tools", [])]
                sent_tool_sets.append(tool_names)
                model_requests.append(request_payload)
                is_child = any(
                    isinstance(message.get("content"), str)
                    and "Approved subtask:" in message["content"]
                    for message in request_payload.get("messages", [])
                )
                if is_child:
                    child_chat_calls[0] += 1
                    if child_chat_calls[0] <= 2:
                        name = "list_project_files" if child_chat_calls[0] == 1 else "propose_project_patch"
                        arguments = {} if child_chat_calls[0] == 1 else {
                            "path": "src/new.py",
                            "content": "value = 1\n",
                            "summary": "Create child module",
                        }
                        return FakeResponse({"choices": [{
                            "message": {
                                "content": "",
                                "tool_calls": [{
                                    "id": f"child-call-{child_chat_calls[0]}",
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(arguments),
                                    },
                                }],
                            }
                        }]})
                return FakeResponse({"choices": [{
                    "message": {
                        "content": "Summary complete.\n[CHECK 1: PASS] Derived from the approved dependency results."
                    }
                }]})

        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary)

            def tracked_connect():
                connection = sqlite3.connect(
                    output_root / "runs.sqlite3",
                    timeout=5,
                    check_same_thread=False,
                )
                connection.row_factory = sqlite3.Row
                connections.append(connection)
                return connection

            def child_output_dir(run_id):
                path = output_root / run_id
                path.mkdir(parents=True, exist_ok=True)
                return path

            try:
                with patch.object(agent_run_store.telemetry, "DB_PATH", output_root / "runs.sqlite3"), \
                     patch.object(agent_run_store.telemetry, "connect_db", tracked_connect), \
                     patch.object(agent_run_store, "_use_remote_store", return_value=False), \
                     patch.object(gateway, "read_setting", return_value="1"), \
                     patch.object(gateway, "record"), \
                     patch.object(gateway, "task_output_dir", side_effect=child_output_dir), \
                     patch.object(gateway.router, "_deep_classify", new=AsyncMock(return_value={
                         "model": "test-model", "complexity": 1, "reason": "Mocked local route",
                     })), \
                     patch.object(gateway.router, "_tune_execution_parameters", return_value={
                         "temperature": 0, "top_p": 1,
                     }), \
                     patch.object(gateway, "ollama_json", new=AsyncMock(return_value={
                         "models": [{"name": "test-model"}],
                     })), \
                     patch.object(gateway, "active_model_names", return_value=["test-model"]), \
                     patch.object(gateway.aiohttp, "ClientSession", FakeSession), \
                     patch.dict(gateway.AGENT_PLAN_TICKETS, {}, clear=True), \
                     patch.dict(agent_tool_common._PENDING_PROJECT_PATCHES, {}, clear=True):
                    agent_run_store.initialize_agent_store()
                    parent_brief = gateway.TaskBrief(
                        original_request="Private parent conversation",
                        desired_outcome="Complete parent work",
                        permission_level="full-access",
                        milestones=[{"id": "one", "title": "Parent", "completion_check": "Complete parent"}],
                        success_checks=["Complete parent"],
                    ).model_dump(mode="json")
                    plan_id = "3" * 32
                    plan = ["Parent"]
                    checks = ["Complete parent"]
                    delegation_plan = SubtaskPlan.model_validate({"subtasks": [subtask_data]})
                    ticket = {
                        "plan_id": plan_id,
                        "request": "Private parent conversation",
                        "source_task": "Private parent conversation",
                        "permission_mode": "full-access",
                        "workspace_path": None,
                        "plan": plan,
                        "success_checks": checks,
                        "execution_prompt": "Parent execution prompt",
                        "selected_model": "test-model",
                        "task_brief": parent_brief,
                        "delegation_plan": delegation_plan.model_dump(mode="json"),
                        "reason": "Mocked parent plan",
                        "status": "approved",
                        "expires_at": gateway.time.monotonic() + 600,
                        "proposed_plan": plan,
                        "proposed_checks": checks,
                    }
                    ticket["action_hash"] = gateway.agent_plan_hash(ticket)
                    ticket["approved_hash"] = ticket["action_hash"]
                    gateway.AGENT_PLAN_TICKETS[plan_id] = ticket
                    execution_prompt = (
                        f"{ticket['execution_prompt']}\n\nApproved plan:\n1. Parent"
                        "\n\nApproved success checks:\n- Complete parent"
                    )
                    parent_payload = gateway.AgentTaskPayload(
                        task=execution_prompt,
                        source_task="Private parent conversation",
                        preferred_model="test-model",
                        conversation_id="conversation",
                        run_id=parent_id,
                        permission_mode="full-access",
                        plan=plan,
                        success_checks=checks,
                        task_brief=parent_brief,
                        plan_history=[
                            {"version": 1, "status": "proposed", "plan": plan,
                             "success_checks": checks,
                             "plan_hash": gateway.agent_plan_version_hash(ticket, 1, plan, checks)},
                            {"version": 2, "status": "approved", "plan": plan,
                             "success_checks": checks,
                             "plan_hash": gateway.agent_plan_version_hash(ticket, 2, plan, checks)},
                        ],
                        plan_id=plan_id,
                        plan_hash=ticket["approved_hash"],
                        delegation_plan=delegation_plan,
                    )
                    response = await gateway.run_agent_task(parent_payload, request)
                    frames = []
                    async for frame in response.body_iterator:
                        frames.append(frame)
                        event = gateway.decode_agent_sse_frame(frame)
                        if event and event.get("type") == "approval_requested":
                            approval_result = await gateway.decide_agent_approval(
                                parent_id,
                                str(event["approval_id"]),
                                gateway.AgentApprovalDecision(
                                    action_hash=str(event["action_hash"]),
                                    decision="approved",
                                ),
                                request,
                            )
                            self.assertTrue(approval_result["accepted"])

                    child_id = stable_delegate_run_id(parent_id, "summarize")
                    stored_run, stored_events = agent_run_store.get_run_events(child_id, 0, 1000)
                    self.assertEqual(stored_run["status"], "completed")
                    self.assertEqual(set(sent_tool_sets[0]), {"list_project_files", "propose_project_patch"})
                    self.assertFalse(agent_run_store.claim_delegate_execution(child_id, parent_id))
                    final_result = stored_events[-1]["event"]
                    self.assertEqual(final_result["type"], "delegate_result")
                    self.assertEqual(final_result["result"]["status"], "completed")
                    parent_run, parent_events = agent_run_store.get_run_events(parent_id, 0, 1000)
                    self.assertEqual(parent_run["status"], "completed")
                    parent_event_types = [item["event"]["type"] for item in parent_events]
                    self.assertIn("delegate_status", parent_event_types)
                    self.assertIn("delegate_event", parent_event_types)
                    self.assertIn("delegate_task_result", parent_event_types)
                    self.assertIn("delegate_patch_proposal", parent_event_types)
                    patch_proposal = next(
                        item["event"] for item in parent_events
                        if item["event"]["type"] == "delegate_patch_proposal"
                    )
                    self.assertEqual(patch_proposal["status"], "pending")
                    self.assertIn("+value = 1", patch_proposal["diff"])
                    merged_file = output_root / parent_id / "src" / "new.py"
                    self.assertTrue(merged_file.exists())
                    self.assertEqual(merged_file.read_text(encoding="utf-8"), "value = 1\n")
                    self.assertIn("delegate_merge_validation", parent_event_types)
                    self.assertIn("artifact", parent_event_types)
                    self.assertTrue(any(
                        item["event"].get("status") == "passed"
                        for item in parent_events
                        if item["event"]["type"] == "delegate_merge_validation"
                    ))
                    parent_done = next(
                        item["event"] for item in reversed(parent_events)
                        if item["event"]["type"] == "done"
                    )
                    self.assertTrue(any(
                        item.get("path") == "src/new.py"
                        for item in parent_done.get("artifacts", [])
                    ))
                    child_status = next(
                        item["event"] for item in parent_events
                        if item["event"]["type"] == "delegate_status"
                        and item["event"].get("status") == "running"
                    )
                    self.assertEqual(child_status["model"], "test-model")
                    self.assertEqual(child_status["context_scope"], ["approved_task"])
                    self.assertEqual(child_status["workspace_scope"], "isolated_task_workspace")
                    synthesis_request = next(
                        item for item in model_requests
                        if any(
                            isinstance(message.get("content"), str)
                            and "Approved delegate results follow" in message["content"]
                            for message in item.get("messages", [])
                        )
                    )
                    synthesis_context = next(
                        message["content"] for message in synthesis_request["messages"]
                        if isinstance(message.get("content"), str)
                        and "Approved delegate results follow" in message["content"]
                    )
                    self.assertIn(child_id, synthesis_context)
                    self.assertIn("conflicting evidence explicitly", synthesis_context)
                    self.assertTrue(any('"type":"done"' in str(frame) for frame in frames))
                    self.assertEqual(stored_run["delegation"]["max_tool_calls"], 4)
                    self.assertNotIn("Private parent conversation", stored_events[0]["event"].get("task", ""))

                    failed_parent_id = "e" * 32
                    failed_plan_id = "5" * 32
                    failed_ticket = dict(ticket)
                    failed_ticket["plan_id"] = failed_plan_id
                    failed_ticket["action_hash"] = gateway.agent_plan_hash(failed_ticket)
                    failed_ticket["approved_hash"] = failed_ticket["action_hash"]
                    gateway.AGENT_PLAN_TICKETS[failed_plan_id] = failed_ticket
                    failed_plan_history = [
                        gateway.TaskPlanVersion(
                            version=1,
                            status="proposed",
                            plan=plan,
                            success_checks=checks,
                            rationale="Mocked parent plan",
                            plan_hash=gateway.agent_plan_version_hash(failed_ticket, 1, plan, checks),
                        ),
                        gateway.TaskPlanVersion(
                            version=2,
                            status="approved",
                            plan=plan,
                            success_checks=checks,
                            rationale="User approved the proposed plan.",
                            plan_hash=gateway.agent_plan_version_hash(failed_ticket, 2, plan, checks),
                        ),
                    ]
                    failed_payload = parent_payload.model_copy(update={
                        "run_id": failed_parent_id,
                        "plan_id": failed_plan_id,
                        "plan_hash": failed_ticket["approved_hash"],
                        "plan_history": failed_plan_history,
                    })
                    failed_result = DelegationResult(
                        status="failed",
                        summary="The child model service was unavailable.",
                        incomplete_checks=["The approved child task did not complete."],
                    ).model_dump(mode="json")
                    with patch.object(
                        gateway,
                        "run_subtask_plan",
                        new=AsyncMock(return_value={"summarize": failed_result}),
                    ):
                        failed_response = await gateway.run_agent_task(failed_payload, request)
                        failed_frames = []
                        async for frame in failed_response.body_iterator:
                            failed_frames.append(frame)
                    failed_run, failed_events = agent_run_store.get_run_events(failed_parent_id, 0, 1000)
                    self.assertEqual(failed_run["status"], "partial")
                    failed_done = next(
                        item["event"] for item in reversed(failed_events)
                        if item["event"]["type"] == "done"
                    )
                    self.assertEqual(failed_done["status"], "partial")
                    self.assertTrue(any('"status":"partial"' in str(frame) for frame in failed_frames))
            finally:
                for connection in connections:
                    connection.close()

    def test_child_workspace_changes_become_parent_review_proposals(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            agent_tool_common._PENDING_PROJECT_PATCHES, {}, clear=True
        ):
            root = Path(temporary)
            parent_root = root / "parent"
            child_root = root / "child"
            (child_root / "src").mkdir(parents=True)
            (child_root / "src" / "new.py").write_text("value = 1\n", encoding="utf-8")
            parent_context = gateway.ProjectAgentContext("parent", parent_root)

            proposal = gateway.stage_delegate_workspace_patches(
                parent_context,
                "a" * 32,
                child_root,
                [{"path": "src/new.py", "summary": "Add the child module"}],
            )[0]
            self.assertEqual(proposal["status"], "pending")
            self.assertIn("+value = 1", proposal["diff"])
            self.assertFalse((parent_root / "src" / "new.py").exists())

            (parent_root / "src").mkdir(parents=True)
            (parent_root / "src" / "new.py").write_text("parent value = 2\n", encoding="utf-8")
            conflict = gateway.stage_delegate_workspace_patches(
                parent_context,
                "b" * 32,
                child_root,
                [{"path": "src/new.py", "summary": "Conflicting child module"}],
            )[0]
            self.assertEqual(conflict["status"], "conflict")
            self.assertEqual((parent_root / "src" / "new.py").read_text(encoding="utf-8"), "parent value = 2\n")

    def test_validation_failure_reverts_unchanged_approved_child_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "new.py"
            target.write_bytes(b"value = 1\n")
            proposal = {
                "path": "new.py",
                "_content": "value = 1\n",
                "subtask_id": "write",
                "child_run_id": "a" * 32,
            }
            with patch.object(gateway, "validate_project", return_value={
                "valid": False,
                "issues": [{"code": "invalid-child-file"}],
            }):
                validation, new_issues, rollback_failures = gateway.validate_delegate_patch_batch(
                    gateway.ProjectAgentContext("parent", root),
                    set(),
                    [proposal],
                )
            self.assertFalse(validation["valid"])
            self.assertEqual(new_issues, [{"code": "invalid-child-file"}])
            self.assertEqual(rollback_failures, [])
            self.assertFalse(target.exists())

    async def test_scheduler_runs_only_ready_subtasks_within_limit(self):
        plan = SubtaskPlan.model_validate({"subtasks": [
            {"id": "first", "role": "researcher", "purpose": "Research A", "expected_result": "A",
             "allowed_tools": ["search_public_site"]},
            {"id": "second", "role": "researcher", "purpose": "Research B", "expected_result": "B",
             "allowed_tools": ["search_public_site"]},
            {"id": "combine", "role": "writer", "purpose": "Combine", "expected_result": "Combined",
             "depends_on": ["first", "second"], "allowed_tools": ["save_text_artifact"]},
        ]})
        active = 0
        peak = 0
        dependency_contexts = {}

        async def execute(subtask, dependencies):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            dependency_contexts[subtask.id] = dependencies
            try:
                await asyncio.sleep(0.02)
                status = {"first": "partial", "second": "failed"}.get(subtask.id, "completed")
                return {"status": status, "id": subtask.id}
            finally:
                active -= 1

        results = await run_subtask_plan(
            plan, execute, max_concurrency=2, cancel_event=asyncio.Event()
        )
        self.assertEqual(peak, 2)
        self.assertEqual(results["combine"]["status"], "completed")
        self.assertEqual(set(dependency_contexts["combine"]), {"first", "second"})
        self.assertEqual(dependency_contexts["combine"]["first"]["status"], "partial")
        self.assertEqual(dependency_contexts["combine"]["second"]["status"], "failed")

    async def test_scheduler_cancels_active_work_and_does_not_start_queued_tasks(self):
        plan = SubtaskPlan.model_validate({"subtasks": [
            {"id": f"worker-{index}", "role": "worker", "purpose": "Work", "expected_result": "Result",
             "allowed_tools": ["search_public_site"]}
            for index in range(3)
        ]})
        cancel_event = asyncio.Event()
        started = []
        cancelled = []

        async def execute(subtask, _dependencies):
            started.append(subtask.id)
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(subtask.id)

        task = asyncio.create_task(run_subtask_plan(
            plan, execute, max_concurrency=1, cancel_event=cancel_event
        ))
        while not started:
            await asyncio.sleep(0)
        cancel_event.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(started, ["worker-0"])
        self.assertEqual(cancelled, ["worker-0"])

    async def test_scheduler_propagates_service_errors_and_cancels_siblings(self):
        plan = SubtaskPlan.model_validate({"subtasks": [
            {"id": "fail", "role": "worker", "purpose": "Fail", "expected_result": "Error",
             "allowed_tools": ["search_public_site"]},
            {"id": "slow", "role": "worker", "purpose": "Wait", "expected_result": "Cancelled",
             "allowed_tools": ["search_public_site"]},
        ]})
        sibling_cancelled = asyncio.Event()

        async def execute(subtask, _dependencies):
            if subtask.id == "fail":
                await asyncio.sleep(0)
                raise RuntimeError("delegate service failed")
            try:
                await asyncio.Event().wait()
            finally:
                sibling_cancelled.set()

        with self.assertRaisesRegex(RuntimeError, "delegate service failed"):
            await run_subtask_plan(plan, execute, max_concurrency=2, cancel_event=asyncio.Event())
        self.assertTrue(sibling_cancelled.is_set())

    async def test_scheduler_rejects_invalid_concurrency(self):
        plan = SubtaskPlan(subtasks=[])
        with self.assertRaisesRegex(ValueError, "between 1 and"):
            await run_subtask_plan(
                plan, lambda *_: asyncio.sleep(0), max_concurrency=0, cancel_event=asyncio.Event()
            )
        with patch.dict(os.environ, {"POCKPOCK_MAX_DELEGATE_CONCURRENCY": "1"}):
            self.assertEqual(
                await run_subtask_plan(
                    plan, lambda *_: asyncio.sleep(0), cancel_event=asyncio.Event()
                ),
                {},
            )

    def test_concurrency_configuration_is_bounded_and_explicit(self):
        self.assertEqual(configured_delegate_concurrency(None), 3)
        self.assertEqual(configured_delegate_concurrency("5"), 5)
        for value in ("not-a-number", "0", "17"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                configured_delegate_concurrency(value)

    def test_delegate_run_identity_is_stable_and_validated(self):
        parent = "a" * 32
        first = stable_delegate_run_id(parent, "worker-1")
        self.assertEqual(first, stable_delegate_run_id(parent, "worker-1"))
        self.assertNotEqual(first, stable_delegate_run_id(parent, "worker-2"))
        with self.assertRaises(ValueError):
            stable_delegate_run_id("invalid", "worker")
        with self.assertRaises(ValueError):
            stable_delegate_run_id(parent, "-invalid")

    def test_dependency_context_is_typed_bounded_and_keeps_all_dependencies(self):
        dependency_results = {
            f"{index:032x}": DelegationResult(
                status="completed",
                summary="x" * 4000,
                evidence=["e" * 500, "second evidence"],
                artifact_ids=["artifact.txt"],
            ).model_dump(mode="json")
            for index in range(1, 16)
        }
        bounded = bounded_dependency_results(dependency_results)
        self.assertEqual(len(bounded), 15)
        self.assertLessEqual(len(json.dumps(bounded)), 5_000)
        self.assertTrue(all(result["status"] == "completed" for result in bounded.values()))
        with self.assertRaisesRegex(ValueError, "must be an object"):
            bounded_dependency_results({"invalid": None})

    def test_retry_reuses_durable_child_run_without_duplicate_dispatch(self):
        original_connect = agent_run_store.telemetry.connect_db
        with tempfile.TemporaryDirectory() as directory:
            connections = []

            def tracked_connect():
                connection = original_connect()
                connections.append(connection)
                return connection

            try:
                with patch.object(agent_run_store.telemetry, "DB_PATH", Path(directory) / "runs.sqlite3"), patch.object(
                    agent_run_store.telemetry, "connect_db", tracked_connect
                ), patch.object(agent_run_store, "_use_remote_store", return_value=False):
                    agent_run_store.initialize_agent_store()
                    parent = "a" * 32
                    agent_run_store.create_agent_run(parent, "conversation", "agent", "parent")
                    subtask = {
                        "id": "research", "role": "researcher", "purpose": "Research the topic",
                        "expected_result": "Provide two sources", "allowed_tools": ["search_public_site"],
                        "max_tool_calls": 8, "max_duration_seconds": 300,
                    }
                    agent_run_store.store_agent_event(parent, 1, {
                        "type": "delegation_plan", "status": "approved", "subtasks": [subtask],
                    })
                    task = SubtaskPlan.model_validate({"subtasks": [subtask]}).subtasks[0]
                    deadline = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
                    created, first_run, _ = create_or_load_delegate_run(
                        parent, "conversation", task, dependency_run_ids=[],
                        permission_level="default", deadline_at=deadline,
                    )
                    agent_run_store.store_agent_event(first_run["run_id"], 1, {
                        "type": "status", "message": "Child execution started",
                    })
                    agent_run_store.store_agent_event(first_run["run_id"], 2, {
                        "type": "done", "status": "success",
                    })
                    typed_result = DelegationResult(
                        status="completed",
                        summary="Research completed.",
                        evidence=["https://example.com/source"],
                    ).model_dump(mode="json")
                    agent_run_store.store_agent_event(first_run["run_id"], 3, {
                        "type": "delegate_result",
                        "contract_version": 1,
                        "parent_run_id": parent,
                        "result": typed_result,
                    })
                    retried, second_run, events = create_or_load_delegate_run(
                        parent, "conversation", task, dependency_run_ids=[],
                        permission_level="default", deadline_at=deadline,
                    )
                    self.assertTrue(created)
                    self.assertFalse(retried)
                    self.assertEqual(first_run["run_id"], second_run["run_id"])
                    self.assertEqual(len(events), 3)
                    self.assertEqual(second_run["status"], "completed")
                    self.assertEqual(second_run["delegation"]["max_tool_calls"], 8)
                    self.assertEqual(second_run["delegation"]["max_duration_seconds"], 300)
                    self.assertEqual(existing_delegate_result(second_run, events), typed_result)
                    self.assertEqual(
                        len(agent_run_store.list_runs_for_conversation("conversation")), 2
                    )
            finally:
                for connection in connections:
                    connection.close()
