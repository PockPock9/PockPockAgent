import asyncio
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from pockpock_server import AgentRunTermination, _await_agent_operation
import pockpock_server as gateway
import agent_run_store


class AgentCancellationTests(unittest.TestCase):
    def test_cancel_request_interrupts_an_inflight_operation(self):
        async def scenario():
            cancel_event = asyncio.Event()
            operation_stopped = asyncio.Event()

            async def operation():
                try:
                    await asyncio.Event().wait()
                finally:
                    operation_stopped.set()

            running = asyncio.create_task(
                _await_agent_operation(operation(), cancel_event, lambda: "user")
            )
            await asyncio.sleep(0)
            cancel_event.set()
            with self.assertRaises(AgentRunTermination) as raised:
                await running
            self.assertEqual(raised.exception.reason, "user")
            self.assertTrue(operation_stopped.is_set())

        asyncio.run(scenario())

    def test_local_stop_endpoint_cancels_active_stream_and_replays_terminal_event(self):
        async def scenario(output_root: Path):
            run_id = "e" * 32
            entered_model = asyncio.Event()
            frames = []
            connections = []

            def tracked_connect():
                Path(agent_run_store.telemetry.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(agent_run_store.telemetry.DB_PATH, timeout=5, check_same_thread=False)
                connection.row_factory = sqlite3.Row
                connections.append(connection)
                return connection
            scope = {
                "type": "http",
                "method": "POST",
                "path": f"/api/runs/{run_id}/cancel",
                "headers": [(b"origin", b"http://127.0.0.1:5173")],
                "client": ("127.0.0.1", 40000),
                "server": ("127.0.0.1", 8766),
                "scheme": "http",
                "query_string": b"",
            }

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            request = Request(scope, receive=receive)

            async def wait_for_cancel(*_args, **_kwargs):
                entered_model.set()
                await asyncio.Event().wait()

            with patch.object(agent_run_store.telemetry, "DB_PATH", output_root / "run-store.sqlite3"), \
                 patch.object(agent_run_store.telemetry, "connect_db", tracked_connect), \
                 patch.object(agent_run_store, "_use_remote_store", return_value=False), \
                 patch.object(gateway, "read_setting", return_value="1"), \
                 patch.object(gateway, "record"), \
                 patch.object(gateway, "task_output_dir", side_effect=lambda _task_id: output_root / run_id), \
                 patch.object(gateway.router, "_deep_classify", side_effect=wait_for_cancel):
                (output_root / run_id).mkdir(parents=True)
                agent_run_store.initialize_agent_store()
                plan_id = "9" * 32
                ticket = {
                    "plan_id": plan_id,
                    "request": "Explain this task",
                    "source_task": "Explain this task",
                    "permission_mode": "auto-review",
                    "workspace_path": None,
                    "plan": ["Inspect the request"],
                    "success_checks": ["Report a useful explanation"],
                    "proposed_plan": ["Inspect the request"],
                    "proposed_checks": ["Report a useful explanation"],
                    "execution_prompt": "Complete the user's request using available tools.",
                    "selected_model": "test-model",
                    "reason": "Test fixture",
                    "status": "approved",
                    "expires_at": gateway.time.monotonic() + 600,
                }
                ticket["task_brief"] = gateway.TaskBrief(
                    original_request="Explain this task",
                    desired_outcome="Provide a useful explanation",
                    permission_level="auto-review",
                    milestones=[{"id": "one", "title": "Inspect", "completion_check": "Inspect request"}],
                    success_checks=["Report a useful explanation"],
                ).model_dump(mode="json")
                ticket["action_hash"] = gateway.agent_plan_hash(ticket)
                ticket["approved_hash"] = ticket["action_hash"]
                gateway.AGENT_PLAN_TICKETS[plan_id] = ticket
                execution_prompt = (
                    f"{ticket['execution_prompt']}\n\nApproved plan:\n1. Inspect the request"
                    "\n\nApproved success checks:\n- Report a useful explanation"
                )
                payload = gateway.AgentTaskPayload(
                    task=execution_prompt,
                    source_task="Explain this task",
                    preferred_model="test-model",
                    run_id=run_id,
                    plan=["Inspect the request"],
                    success_checks=["Report a useful explanation"],
                    task_brief=ticket["task_brief"],
                    plan_history=[
                        {
                            "version": 1, "status": "proposed", "plan": ticket["proposed_plan"],
                            "success_checks": ticket["proposed_checks"], "rationale": ticket["reason"],
                            "plan_hash": gateway.agent_plan_version_hash(ticket, 1, ticket["proposed_plan"], ticket["proposed_checks"]),
                        },
                        {
                            "version": 2, "status": "approved", "plan": ticket["plan"],
                            "success_checks": ticket["success_checks"], "rationale": "User approved the proposed plan.",
                            "plan_hash": gateway.agent_plan_version_hash(ticket, 2, ticket["plan"], ticket["success_checks"]),
                        },
                    ],
                    plan_id=plan_id,
                    plan_hash=ticket["approved_hash"],
                )
                response = await gateway.run_agent_task(payload, request)

                async def consume_stream():
                    async for frame in response.body_iterator:
                        frames.append(frame.decode() if isinstance(frame, bytes) else frame)

                consumer = asyncio.create_task(consume_stream())
                await asyncio.wait_for(entered_model.wait(), timeout=2)
                result = await gateway.cancel_agent_run(run_id, request)
                self.assertTrue(result["accepted"])
                await asyncio.wait_for(consumer, timeout=3)

                run, events = agent_run_store.get_run_events(run_id, 0, 100)
                self.assertEqual(run["status"], "cancelled")
                self.assertEqual(events[-1]["event"]["type"], "cancelled")
                plan_events = [item["event"] for item in events if item["event"].get("type") == "plan_version"]
                self.assertEqual([event["version"] for event in plan_events], [1, 2])
                self.assertEqual(plan_events[-1]["status"], "approved")
                self.assertTrue(any(item["event"].get("type") == "plan_decision" for item in events))
                self.assertTrue(any('"type":"cancelled"' in frame for frame in frames))
                for connection in connections:
                    connection.close()

        with tempfile.TemporaryDirectory() as temporary:
            asyncio.run(scenario(Path(temporary)))

    def test_operation_timeout_cancels_the_underlying_tool(self):
        async def scenario():
            operation_stopped = asyncio.Event()

            async def operation():
                try:
                    await asyncio.sleep(10)
                finally:
                    operation_stopped.set()

            with self.assertRaises(asyncio.TimeoutError):
                await _await_agent_operation(operation(), asyncio.Event(), lambda: "user", 0.01)
            self.assertTrue(operation_stopped.is_set())

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
