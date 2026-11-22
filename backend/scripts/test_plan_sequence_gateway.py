"""Gateway tests for Plan-and-Sequence P3: plan-sequence / run-sequence.

Hermetic: the planner HTTP call, the model client, and execute_agent_tool
are all faked. No live Ollama, no live planner service, no real gateway
port, and no writes outside a temporary directory. Handlers are called
directly, following backend/scripts/test_pockpock_chat.py.
"""

import asyncio
import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pockpock_server
from fastapi import HTTPException, Request

TASK = "Summarise the files and save the totals."


def _step(step_id, tools, done, inputs=()):
    return {
        "id": step_id,
        "goal": f"Do step {step_id}",
        "tools_allowed": list(tools),
        "budget_tokens": 4000,
        "budget_seconds": 300,
        "done_condition": done,
        "inputs": list(inputs),
    }


def _valid_plan():
    return {
        "contract_version": 1,
        "task": TASK,
        "steps": [
            _step("step-1", ["list_project_files"], {"type": "no_error"}),
            _step("step-2", ["save_text_artifact"], {"type": "file_exists", "path": "summary.md"}, inputs=["step-1"]),
            _step("step-3", ["read_project_file"], {"type": "file_contains", "path": "summary.md", "pattern": "hello"}, inputs=["step-2"]),
            _step("step-4", ["validate_project"], {"type": "command_exit_0"}, inputs=["step-3"]),
            _step("step-5", ["read_project_file"], {"type": "value_equals", "field": "total", "expected": "42"}, inputs=["step-4"]),
        ],
    }


def _local_request():
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
        "client": ("127.0.0.1", 5000),
    })


class _FakePlannerResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self._payload


class _FakePlannerSession:
    """Stands in for aiohttp.ClientSession; serves one canned response."""

    def __init__(self, response, captured):
        self._response = response
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def post(self, url, json=None, headers=None):
        self._captured["url"] = url
        self._captured["json"] = json
        self._captured["headers"] = headers
        return self._response


class _FakeModelClient:
    """Returns one allowed tool call per step, keyed by the step id in the prompt."""

    def __init__(self):
        self.calls = []

    async def complete(self, request, timeout=None):
        tools = list(request.tools or [])
        tool_name = tools[0]["function"]["name"] if tools else ""
        prompt = ""
        for message in request.messages or []:
            if message.get("role") == "user":
                prompt = message.get("content", "")
        match = re.search(r"Step (step-\d+):", prompt)
        step_id = match.group(1) if match else "step-1"
        arguments = {
            "step-1": {},
            "step-2": {"filename": "summary.md", "content": "hello total 42"},
            "step-3": {"path": "summary.md"},
            "step-4": {},
            "step-5": {"path": "data.json"},
        }[step_id]
        self.calls.append({"model": request.model, "think": request.think, "tool": tool_name, "step": step_id})
        return {
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": f"call-{step_id}",
                        "type": "function",
                        "function": {"name": tool_name, "arguments": json.dumps(arguments)},
                    }],
                },
            }],
        }


class _FakeTools:
    """Fake execute_agent_tool over a temp workspace; records every call."""

    def __init__(self, workspace):
        self.workspace = Path(workspace)
        self.calls = []

    async def __call__(self, name, arguments, context):
        self.calls.append((name, arguments))
        # The gateway passes the run's output dir in the context; the
        # verifier checks done-conditions against that same directory.
        # File tools get the run's project context (rooted at the workspace, here the output dir).
        workspace = Path(getattr(context, "output_dir", None) or context.project_root)
        if name == "save_text_artifact":
            path = workspace / arguments["filename"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(arguments.get("content", ""))
            return {"output": f"saved {arguments['filename']}"}
        if name == "read_project_file":
            if arguments.get("path") == "data.json":
                return {"output": '{"total": "42"}'}
            path = workspace / arguments.get("path", "")
            return {"output": path.read_text() if path.is_file() else ""}
        if name == "list_project_files":
            return {"output": "summary.md"}
        if name == "validate_project":
            return {"output": "valid", "exit_code": 0}
        return {"output": "ok"}


async def _passthrough_stream(run_id, source, encode_event):
    async for frame in source:
        yield frame


def _parse_sse_frames(chunks):
    text = "".join(chunk if isinstance(chunk, str) else chunk.decode("utf-8") for chunk in chunks)
    events = []
    for frame in text.split("\n\n"):
        frame = frame.strip()
        if not frame.startswith("data:"):
            continue
        events.append(json.loads(frame[5:].strip()))
    return events


class PlanSequenceGatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._temp.name)
        pockpock_server.AGENT_PLAN_TICKETS.clear()
        pockpock_server.AGENT_RUN_CANCEL_EVENTS.clear()
        pockpock_server.AGENT_RUN_CANCEL_REASONS.clear()
        self._patches = [
            mock.patch.object(pockpock_server, "read_setting", lambda key, fallback="": "1"),
            mock.patch.object(pockpock_server, "record", lambda event: None),
            mock.patch.object(pockpock_server, "create_agent_run", lambda *args, **kwargs: None),
            mock.patch.object(pockpock_server, "finish_incomplete_agent_run", lambda run_id: None),
            mock.patch.object(pockpock_server, "track_agent_stream", _passthrough_stream),
            mock.patch.object(
                pockpock_server,
                "task_output_dir",
                lambda run_id: self._ensure_dir(self.workspace / run_id),
            ),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self._patches):
            patch.stop()
        pockpock_server.AGENT_PLAN_TICKETS.clear()
        pockpock_server.AGENT_RUN_CANCEL_EVENTS.clear()
        pockpock_server.AGENT_RUN_CANCEL_REASONS.clear()
        self._temp.cleanup()

    @staticmethod
    def _ensure_dir(path):
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def _fake_tool_capable_models(self):
        return (
            [{"name": "qwen3.5:9b", "capabilities": ["tools"], "parameter_billions": 9.0}],
            {"qwen3.5:9b"},
        )

    def _planner_result(self, sequence_plan=None):
        return {
            "contract_version": 1,
            "sequence_plan": _valid_plan() if sequence_plan is None else sequence_plan,
            "selected_model": "qwen3.6:35b-a3b",
            "executor_model": "qwen3.5:9b",
            "reason": "Used the default local planner model.",
            "executor_reason": "Used the default executor model.",
        }

    async def _plan(self, payload=None, planner_payload=None, status=200):
        captured = {}
        session = _FakePlannerSession(_FakePlannerResponse(status, planner_payload), captured)
        with (
            mock.patch.object(pockpock_server.aiohttp, "ClientSession", lambda *args, **kwargs: session),
            mock.patch.object(pockpock_server, "tool_capable_models", self._fake_tool_capable_models),
        ):
            result = await pockpock_server.plan_sequence_agent_task(
                payload or pockpock_server.AgentPlanPayload(task=TASK),
                _local_request(),
            )
        return result, captured

    async def _approved_ticket(self):
        result, _ = await self._plan(planner_payload=self._planner_result())
        decision = await pockpock_server.decide_agent_plan(
            result["plan_id"],
            pockpock_server.AgentPlanDecisionPayload(
                action_hash=result["plan_hash"], decision="approved",
            ),
            _local_request(),
        )
        self.assertEqual(decision["status"], "approved")
        return result

    # -- POST /api/agents/plan-sequence -----------------------------------

    async def test_plan_sequence_creates_ticket_with_validated_plan(self):
        result, captured = await self._plan(planner_payload=self._planner_result())
        self.assertEqual(result["contract_version"], 1)
        self.assertEqual(result["selected_model"], "qwen3.6:35b-a3b")
        self.assertEqual(result["executor_model"], "qwen3.5:9b")
        self.assertEqual(result["sequence_plan"]["task"], TASK)
        self.assertEqual(len(result["sequence_plan"]["steps"]), 5)
        self.assertEqual(captured["url"], "http://127.0.0.1:8771/plan-sequence")
        self.assertEqual(captured["json"]["task"], TASK)
        ticket = pockpock_server.AGENT_PLAN_TICKETS[result["plan_id"]]
        self.assertEqual(ticket["status"], "pending")
        self.assertEqual(ticket["sequence_plan"], result["sequence_plan"])
        self.assertEqual(ticket["executor_model"], "qwen3.5:9b")
        self.assertEqual(ticket["action_hash"], result["plan_hash"])
        self.assertEqual(ticket["action_hash"], pockpock_server.agent_plan_hash(ticket))
        self.assertGreater(ticket["expires_at"], 0)

    async def test_plan_sequence_rejects_invalid_plan_with_502(self):
        bad = _valid_plan()
        bad["steps"][0]["tools_allowed"] = ["no_such_tool"]
        with self.assertRaises(HTTPException) as ctx:
            await self._plan(planner_payload=self._planner_result(sequence_plan=bad))
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(pockpock_server.AGENT_PLAN_TICKETS, {})

    async def test_plan_sequence_propagates_planner_error(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._plan(planner_payload={"detail": "Planner timed out"}, status=502)
        self.assertEqual(ctx.exception.status_code, 502)

    # -- agent_plan_hash ---------------------------------------------------

    def test_agent_plan_hash_monolithic_bound_unchanged(self):
        state = {
            "plan_id": "a" * 32,
            "request": "do it",
            "source_task": "do it",
            "permission_mode": "auto-review",
            "workspace_path": None,
            "plan": ["step one"],
            "success_checks": ["done"],
            "execution_prompt": "do step one",
            "selected_model": "qwen3.5:9b",
            "task_brief": {"desired_outcome": "done"},
            "delegation_plan": {"contract_version": 1, "subtasks": []},
            "critic_review": None,
            "reason": "picked",
        }
        keys = (
            "plan_id", "request", "source_task", "permission_mode", "workspace_path",
            "plan", "success_checks", "execution_prompt", "selected_model",
            "task_brief", "delegation_plan", "critic_review", "reason",
        )
        bound = {key: state.get(key) for key in keys}
        expected = hashlib.sha256(
            json.dumps(bound, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.assertEqual(pockpock_server.agent_plan_hash(state), expected)

    def test_agent_plan_hash_binds_sequence_plan(self):
        ticket_a = {"plan_id": "a" * 32, "request": TASK, "source_task": TASK,
                    "permission_mode": "auto-review", "workspace_path": None,
                    "sequence_plan": _valid_plan(), "selected_model": "m",
                    "executor_model": "qwen3.5:9b", "reason": "r", "executor_reason": "e"}
        ticket_b = dict(ticket_a)
        changed = _valid_plan()
        changed["steps"][0]["goal"] = "Do something else entirely"
        ticket_b["sequence_plan"] = changed
        self.assertNotEqual(
            pockpock_server.agent_plan_hash(ticket_a),
            pockpock_server.agent_plan_hash(ticket_b),
        )

    # -- plan decision on sequence tickets ---------------------------------

    async def test_decision_approve_sequence_ticket(self):
        result, _ = await self._plan(planner_payload=self._planner_result())
        decision = await pockpock_server.decide_agent_plan(
            result["plan_id"],
            pockpock_server.AgentPlanDecisionPayload(
                action_hash=result["plan_hash"], decision="approved",
            ),
            _local_request(),
        )
        self.assertEqual(decision, {
            "accepted": True,
            "status": "approved",
            "approved_plan_hash": result["plan_hash"],
        })
        ticket = pockpock_server.AGENT_PLAN_TICKETS[result["plan_id"]]
        self.assertEqual(ticket["status"], "approved")
        self.assertEqual(ticket["approved_hash"], result["plan_hash"])

    async def test_decision_wrong_hash_rejected(self):
        result, _ = await self._plan(planner_payload=self._planner_result())
        with self.assertRaises(HTTPException) as ctx:
            await pockpock_server.decide_agent_plan(
                result["plan_id"],
                pockpock_server.AgentPlanDecisionPayload(
                    action_hash="0" * 64, decision="approved",
                ),
                _local_request(),
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(pockpock_server.AGENT_PLAN_TICKETS[result["plan_id"]]["status"], "pending")

    async def test_decision_reject_sequence_ticket(self):
        result, _ = await self._plan(planner_payload=self._planner_result())
        decision = await pockpock_server.decide_agent_plan(
            result["plan_id"],
            pockpock_server.AgentPlanDecisionPayload(
                action_hash=result["plan_hash"], decision="rejected",
            ),
            _local_request(),
        )
        self.assertEqual(decision, {"accepted": True, "status": "rejected"})
        self.assertNotIn(result["plan_id"], pockpock_server.AGENT_PLAN_TICKETS)

    async def test_decision_approve_twice_rejected(self):
        result = await self._approved_ticket()
        with self.assertRaises(HTTPException) as ctx:
            await pockpock_server.decide_agent_plan(
                result["plan_id"],
                pockpock_server.AgentPlanDecisionPayload(
                    action_hash=result["plan_hash"], decision="approved",
                ),
                _local_request(),
            )
        self.assertEqual(ctx.exception.status_code, 409)

    # -- monolithic decision path unchanged -------------------------------

    def _monolithic_ticket(self):
        ticket = {
            "plan_id": "d" * 32,
            "request": TASK,
            "source_task": TASK,
            "permission_mode": "auto-review",
            "workspace_path": None,
            "plan": ["Step one"],
            "success_checks": ["done"],
            "execution_prompt": "Do step one.",
            "selected_model": "qwen3.5:9b",
            "task_brief": {"desired_outcome": "done"},
            "delegation_plan": {"contract_version": 1, "subtasks": []},
            "critic_review": None,
            "reason": "picked",
            "status": "pending",
            "expires_at": 10**9,
            "proposed_plan": ["Step one"],
            "proposed_checks": ["done"],
        }
        ticket["action_hash"] = pockpock_server.agent_plan_hash(ticket)
        pockpock_server.AGENT_PLAN_TICKETS[ticket["plan_id"]] = ticket
        return ticket

    async def test_decision_monolithic_approve_still_works(self):
        ticket = self._monolithic_ticket()
        decision = await pockpock_server.decide_agent_plan(
            ticket["plan_id"],
            pockpock_server.AgentPlanDecisionPayload(
                action_hash=ticket["action_hash"],
                decision="approved",
                plan=["Revised step one"],
                success_checks=["done"],
            ),
            _local_request(),
        )
        self.assertEqual(decision["status"], "approved")
        self.assertEqual(
            pockpock_server.AGENT_PLAN_TICKETS[ticket["plan_id"]]["plan"],
            ["Revised step one"],
        )

    async def test_decision_monolithic_empty_plan_still_rejected(self):
        ticket = self._monolithic_ticket()
        with self.assertRaises(HTTPException) as ctx:
            await pockpock_server.decide_agent_plan(
                ticket["plan_id"],
                pockpock_server.AgentPlanDecisionPayload(
                    action_hash=ticket["action_hash"], decision="approved",
                ),
                _local_request(),
            )
        self.assertEqual(ctx.exception.status_code, 422)

    # -- POST /api/agents/run-sequence -------------------------------------

    async def test_run_sequence_refuses_unapproved_ticket(self):
        result, _ = await self._plan(planner_payload=self._planner_result())
        with self.assertRaises(HTTPException) as ctx:
            await pockpock_server.run_sequence_agent_task(
                pockpock_server.AgentSequenceRunPayload(
                    plan_id=result["plan_id"], plan_hash=result["plan_hash"],
                ),
                _local_request(),
            )
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_run_sequence_refuses_wrong_hash(self):
        result = await self._approved_ticket()
        with self.assertRaises(HTTPException) as ctx:
            await pockpock_server.run_sequence_agent_task(
                pockpock_server.AgentSequenceRunPayload(
                    plan_id=result["plan_id"], plan_hash="0" * 64,
                ),
                _local_request(),
            )
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_run_sequence_refuses_missing_ticket(self):
        with self.assertRaises(HTTPException) as ctx:
            await pockpock_server.run_sequence_agent_task(
                pockpock_server.AgentSequenceRunPayload(
                    plan_id="f" * 32, plan_hash="0" * 64,
                ),
                _local_request(),
            )
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_run_sequence_runs_five_step_plan_end_to_end(self):
        result = await self._approved_ticket()
        fake_model = _FakeModelClient()
        fake_tools = _FakeTools(self.workspace)
        run_id = "b" * 32
        with (
            mock.patch.object(pockpock_server, "MODEL_CLIENT", fake_model),
            mock.patch.object(pockpock_server, "execute_agent_tool", fake_tools),
            mock.patch.object(pockpock_server, "execute_project_tool", fake_tools),
        ):
            response = await pockpock_server.run_sequence_agent_task(
                pockpock_server.AgentSequenceRunPayload(
                    plan_id=result["plan_id"], plan_hash=result["plan_hash"], run_id=run_id,
                ),
                _local_request(),
            )
            chunks = [chunk async for chunk in response.body_iterator]
        events = _parse_sse_frames(chunks)
        names = [event.get("event", event.get("type")) for event in events]
        self.assertEqual(names[0], "plan_started")
        self.assertIn("plan_completed", names)
        self.assertEqual(names[-1], "done")
        step_events = [event for event in events if event.get("event") == "step_verified"]
        self.assertEqual(len(step_events), 5)
        self.assertTrue(all(event.get("passed") is True for event in step_events))
        done = events[-1]
        self.assertEqual(done["task_id"], run_id)
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["result"]["status"], "completed")
        self.assertEqual(len(done["result"]["steps"]), 5)
        self.assertTrue(all(step["status"] == "passed" for step in done["result"]["steps"]))
        # One executor call per step, think off, executor model from the ticket.
        self.assertEqual(len(fake_model.calls), 5)
        self.assertTrue(all(call["model"] == "qwen3.5:9b" for call in fake_model.calls))
        self.assertTrue(all(call["think"] is False for call in fake_model.calls))
        self.assertEqual(
            [name for name, _ in fake_tools.calls],
            ["list_project_files", "save_text_artifact", "read_project_file", "validate_project", "read_project_file"],
        )
        self.assertEqual((self.workspace / run_id / "summary.md").read_text(), "hello total 42")
        # The ticket is consumed and the run leaves no cancel state behind.
        self.assertNotIn(result["plan_id"], pockpock_server.AGENT_PLAN_TICKETS)
        self.assertEqual(pockpock_server.AGENT_RUN_CANCEL_EVENTS, {})
        self.assertEqual(pockpock_server.AGENT_RUN_CANCEL_REASONS, {})
        self.assertFalse(pockpock_server.AGENT_TASK_SEMAPHORE.locked())

    async def test_run_sequence_shows_each_step_in_the_app(self):
        result = await self._approved_ticket()
        with (
            mock.patch.object(pockpock_server, "MODEL_CLIENT", _FakeModelClient()),
            mock.patch.object(pockpock_server, "execute_agent_tool", _FakeTools(self.workspace)),
            mock.patch.object(pockpock_server, "execute_project_tool", _FakeTools(self.workspace)),
        ):
            response = await pockpock_server.run_sequence_agent_task(
                pockpock_server.AgentSequenceRunPayload(plan_id=result["plan_id"], plan_hash=result["plan_hash"], run_id="c" * 32),
                _local_request(),
            )
            events = _parse_sse_frames([chunk async for chunk in response.body_iterator])
        steps = [(event["step"], event["total"]) for event in events if event.get("type") == "plan_step"]
        self.assertEqual(steps, [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)])
        self.assertEqual(sum(1 for event in events if event.get("type") == "sequence_check" and event["passed"]), 5)
        reply = next(event["content"] for event in events if event.get("type") == "token")
        self.assertIn("Finished all 5 steps", reply)
        self.assertIn("summary.md exists", reply)
        artifacts = [event for event in events if event.get("type") == "artifact"]
        self.assertEqual([item["name"] for item in artifacts], [])  # the fake save returns no name

    async def test_a_change_in_auto_review_waits_for_approval_then_is_applied(self):
        plan = {
            "contract_version": 1, "task": TASK,
            "steps": [
                _step("step-1", ["propose_project_patch"], {"type": "file_exists", "path": "notes.md"}),
                _step("step-2", ["read_project_file"], {"type": "file_contains", "path": "notes.md", "pattern": "hello"}, inputs=["step-1"]),
            ],
        }
        planned, _ = await self._plan(planner_payload=self._planner_result(plan))
        decision = await pockpock_server.decide_agent_plan(
            planned["plan_id"], pockpock_server.AgentPlanDecisionPayload(action_hash=planned["plan_hash"], decision="approved"), _local_request())

        class Model:
            async def complete(self, request, timeout=None):
                name = request.tools[0]["function"]["name"]
                arguments = {"path": "notes.md", "content": "hello from step one\n", "summary": "Add notes"} if name == "propose_project_patch" else {"path": "notes.md"}
                return {"choices": [{"message": {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}}]}

        approvals = []

        def create_approval(run_id, approval_id, action_hash, action, expires_at):
            approvals.append(action)
            return {"approval_id": approval_id, "action_hash": action_hash, "action": action, "expires_at": expires_at}

        run_id = "d" * 32
        with (
            mock.patch.object(pockpock_server, "MODEL_CLIENT", Model()),
            mock.patch.object(pockpock_server, "create_agent_approval", create_approval),
        ):
            response = await pockpock_server.run_sequence_agent_task(
                pockpock_server.AgentSequenceRunPayload(plan_id=planned["plan_id"], plan_hash=decision["approved_plan_hash"], run_id=run_id),
                _local_request(),
            )
            events = []
            async for chunk in response.body_iterator:
                for event in _parse_sse_frames([chunk]):
                    events.append(event)
                    if event.get("type") == "approval_requested":
                        # The user presses Allow once on the card.
                        pockpock_server.AGENT_RUN_APPROVAL_FUTURES[event["approval_id"]].set_result("approved")
        types = [event.get("type") for event in events]
        self.assertIn("approval_requested", types)
        self.assertLess(types.index("approval_requested"), types.index("patch"), "nothing is written before approval")
        self.assertEqual(approvals[0]["path"], "notes.md")
        self.assertEqual((self.workspace / run_id / "notes.md").read_text(), "hello from step one\n")
        self.assertEqual(events[-1]["status"], "completed")

    async def test_plan_in_steps_uses_the_chosen_planner_and_step_models(self):
        _, captured = await self._plan(
            payload=pockpock_server.AgentPlanPayload(task=TASK, preferred_model="qwen3.5:9b", planner_model="qwen3.6:35b-a3b"),
            planner_payload=self._planner_result(),
        )
        self.assertEqual(captured["json"]["planner_model"], "qwen3.6:35b-a3b")
        self.assertEqual(captured["json"]["executor_model"], "qwen3.5:9b")

    async def test_run_sequence_text_tool_call_fallback(self):
        result = await self._approved_ticket()
        # The model prints the call as JSON text instead of using tool_calls.
        calls = {"count": 0}

        class TextModelClient:
            async def complete(self, request, timeout=None):
                calls["count"] += 1
                tools = list(request.tools or [])
                name = tools[0]["function"]["name"] if tools else ""
                prompt = next(
                    (m.get("content", "") for m in request.messages or [] if m.get("role") == "user"),
                    "",
                )
                match = re.search(r"Step (step-\d+):", prompt)
                step_id = match.group(1) if match else "step-1"
                arguments = {
                    "step-1": {},
                    "step-2": {"filename": "summary.md", "content": "hello total 42"},
                    "step-3": {"path": "summary.md"},
                    "step-4": {},
                    "step-5": {"path": "data.json"},
                }[step_id]
                text = json.dumps({"name": name, "arguments": arguments})
                return {"choices": [{"message": {"content": text, "tool_calls": []}}]}

        fake_tools = _FakeTools(self.workspace)
        with (
            mock.patch.object(pockpock_server, "MODEL_CLIENT", TextModelClient()),
            mock.patch.object(pockpock_server, "execute_agent_tool", fake_tools),
            mock.patch.object(pockpock_server, "execute_project_tool", fake_tools),
        ):
            response = await pockpock_server.run_sequence_agent_task(
                pockpock_server.AgentSequenceRunPayload(
                    plan_id=result["plan_id"], plan_hash=result["plan_hash"], run_id="c" * 32,
                ),
                _local_request(),
            )
            chunks = [chunk async for chunk in response.body_iterator]
        events = _parse_sse_frames(chunks)
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["status"], "completed")
        self.assertEqual(calls["count"], 5)


if __name__ == "__main__":
    unittest.main()
