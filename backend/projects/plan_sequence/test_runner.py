import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from projects.plan_sequence.runner import SequenceRunner, build_step_prompt


def _step(step_id, tools, done, inputs=(), budget_tokens=4000, budget_seconds=300):
    return {
        "id": step_id,
        "goal": f"Do step {step_id}",
        "tools_allowed": list(tools),
        "budget_tokens": budget_tokens,
        "budget_seconds": budget_seconds,
        "done_condition": done,
        "inputs": list(inputs),
    }


def _plan(steps, task="Summarise the files and save the totals."):
    return {"task": task, "steps": steps}


def _happy_plan():
    return _plan([
        _step("step-1", ["list_project_files"], {"type": "no_error"}),
        _step("step-2", ["save_text_artifact"], {"type": "file_exists", "path": "summary.md"}, inputs=["step-1"]),
        _step("step-3", ["read_project_file"], {"type": "file_contains", "path": "summary.md", "pattern": "hello"}, inputs=["step-2"]),
        _step("step-4", ["validate_project"], {"type": "command_exit_0"}, inputs=["step-3"]),
        _step("step-5", ["read_project_file"], {"type": "value_equals", "field": "total", "expected": "42"}, inputs=["step-4"]),
    ])


class FakeChat:
    """Returns queued responses in order; records every call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, model, messages, tools, *, think):
        self.calls.append({"model": model, "messages": messages, "tools": tools, "think": think})
        if not self.responses:
            return {"content": "done", "tool_calls": []}
        return self.responses.pop(0)


class FakeTools:
    """Fake execute_tool over a temp workspace; records every call."""

    def __init__(self, workspace):
        self.workspace = Path(workspace)
        self.calls = []

    async def __call__(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "save_text_artifact":
            path = self.workspace / arguments["filename"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(arguments.get("content", ""))
            return {"ok": True, "output": f"saved {arguments['filename']}", "exit_code": None, "error": None}
        if name == "read_project_file":
            if arguments.get("path") == "data.json":
                return {"ok": True, "output": '{"total": "42"}', "exit_code": None, "error": None}
            path = self.workspace / arguments.get("path", "")
            return {"ok": True, "output": path.read_text() if path.is_file() else "", "exit_code": None, "error": None}
        if name == "list_project_files":
            files = sorted(p.name for p in self.workspace.iterdir() if p.is_file())
            return {"ok": True, "output": ", ".join(files) or "(empty)", "exit_code": None, "error": None}
        if name == "validate_project":
            return {"ok": True, "output": "valid", "exit_code": 0, "error": None}
        return {"ok": True, "output": "ok", "exit_code": None, "error": None}


def _happy_responses(workspace):
    return [
        {"content": "listed", "tool_calls": [{"name": "list_project_files", "arguments": {}}]},
        {"content": "saved", "tool_calls": [{"name": "save_text_artifact", "arguments": {"filename": "summary.md", "content": "hello total 42\n"}}]},
        {"content": "read", "tool_calls": [{"name": "read_project_file", "arguments": {"path": "summary.md"}}]},
        {"content": "validated", "tool_calls": [{"name": "validate_project", "arguments": {}}]},
        {"content": "read json", "tool_calls": [{"name": "read_project_file", "arguments": {"path": "data.json"}}]},
    ]


class BuildStepPromptTests(unittest.TestCase):
    def test_contains_goal_capsule_and_tool_schemas(self):
        prompt = build_step_prompt(
            task="Do the thing.",
            step={"id": "step-1", "goal": "List the files"},
            capsule_text="summary.md: /tmp/summary.md",
            tool_specs=[{"type": "function", "function": {"name": "list_project_files", "description": "List files.", "parameters": {"type": "object", "properties": {}}}}],
        )
        self.assertIn("List the files", prompt)
        self.assertIn("summary.md: /tmp/summary.md", prompt)
        self.assertIn("list_project_files", prompt)
        self.assertIn('"name": "list_project_files"', prompt)
        self.assertNotIn("prior history", prompt)


class RunnerHappyPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_completes_and_capsule_flows_forward(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "notes.txt").write_text("notes")
            chat = FakeChat(_happy_responses(workspace))
            tools = FakeTools(workspace)
            events = []
            recorded = []
            runner = SequenceRunner(
                chat=chat, execute_tool=tools,
                on_event=events.append, record_event=recorded.append,
            )
            result = await runner.run(
                _happy_plan(), workspace=workspace, run_id="run-1",
                executor_model="qwen3.5:9b",
            )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["remaining_steps"], [])
            self.assertIsNone(result["failure"])
            self.assertEqual([s["step_id"] for s in result["steps"]], ["step-1", "step-2", "step-3", "step-4", "step-5"])
            self.assertTrue(all(s["status"] == "passed" for s in result["steps"]))
            # Every chat call used the executor model with think=False.
            self.assertEqual(len(chat.calls), 5)
            for call in chat.calls:
                self.assertEqual(call["model"], "qwen3.5:9b")
                self.assertIs(call["think"], False)
            # No message carries prior steps' full history: each prompt
            # mentions only its own step goal.
            self.assertIn("Do step step-2", chat.calls[1]["messages"][1]["content"])
            self.assertNotIn("Do step step-1", chat.calls[1]["messages"][1]["content"])
            # Capsule from step 1 is visible to step 2 (step-2 inputs step-1),
            # and step 2's file path is visible to step 3.
            step2_prompt = chat.calls[1]["messages"][1]["content"]
            self.assertIn("notes.txt", step2_prompt)
            step3_prompt = chat.calls[2]["messages"][1]["content"]
            self.assertIn("summary.md", step3_prompt)
            # Step 3 inputs only step-2, so step 1's list output is filtered out.
            self.assertNotIn("notes.txt", step3_prompt)
            # Prompt tokens are recorded per step and totalled.
            self.assertEqual(
                result["total_prompt_tokens"],
                sum(s["prompt_tokens"] for s in result["steps"]),
            )
            self.assertTrue(all(s["prompt_tokens"] > 0 for s in result["steps"]))
            # Capsule holds the path entry from the file-writing step.
            kinds = {e["kind"]: e["value"] for e in result["capsule"]["entries"]}
            self.assertEqual(kinds.get("path"), "summary.md")
            # Events went to both handlers, each with contract_version 1.
            self.assertEqual(events, recorded)
            names = [e["event"] for e in events]
            self.assertIn("plan_started", names)
            self.assertIn("plan_completed", names)
            self.assertEqual(names.count("step_started"), 5)
            self.assertEqual(names.count("step_verified"), 5)
            for event in events:
                self.assertEqual(event["contract_version"], 1)
                self.assertEqual(event["run_id"], "run-1")
                self.assertIn("status", event)

    async def test_retriever_supplies_tool_specs(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "notes.txt").write_text("notes")

            class StubRetriever:
                def __init__(self):
                    self.calls = []
                    from projects.agent_tools.registry import registered_tool_specs
                    self.by_name = {
                        spec["function"]["name"]: spec
                        for spec in registered_tool_specs()
                    }

                def retrieve(self, task, *, permitted=None):
                    self.calls.append((task, permitted))
                    selected = [name for name in (permitted or []) if name in self.by_name]
                    return mock.Mock(selected_names=selected, by_name=self.by_name)

            retriever = StubRetriever()
            chat = FakeChat(_happy_responses(workspace))
            runner = SequenceRunner(chat=chat, execute_tool=FakeTools(workspace), retriever=retriever)
            result = await runner.run(_happy_plan(), workspace=workspace, run_id="run-r", executor_model="qwen3.5:9b")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(len(retriever.calls), 5)
            # The pinned specs handed to chat are the retriever's, step 2 only.
            step2_tools = [t["function"]["name"] for t in chat.calls[1]["tools"]]
            self.assertEqual(step2_tools, ["save_text_artifact"])


class RunnerFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_step_retries_then_needs_replan(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "notes.txt").write_text("notes")
            plan = _happy_plan()
            # Step 2 must check content, not just existence, so the wrong
            # content is caught at the step boundary.
            plan["steps"][1]["done_condition"] = {
                "type": "file_contains", "path": "summary.md", "pattern": "expected-total",
            }
            chat = FakeChat([
                {"content": "listed", "tool_calls": [{"name": "list_project_files", "arguments": {}}]},
                # Step 2 writes the file without the expected content, 3x.
                {"content": "saved", "tool_calls": [{"name": "save_text_artifact", "arguments": {"filename": "summary.md", "content": "wrong content\n"}}]},
                {"content": "saved", "tool_calls": [{"name": "save_text_artifact", "arguments": {"filename": "summary.md", "content": "wrong content\n"}}]},
                {"content": "saved", "tool_calls": [{"name": "save_text_artifact", "arguments": {"filename": "summary.md", "content": "wrong content\n"}}]},
            ])
            tools = FakeTools(workspace)
            events = []
            runner = SequenceRunner(chat=chat, execute_tool=tools, on_event=events.append)
            result = await runner.run(plan, workspace=workspace, run_id="run-2", executor_model="qwen3.5:9b")
            self.assertEqual(result["status"], "needs_replan")
            self.assertEqual(result["remaining_steps"], ["step-2", "step-3", "step-4", "step-5"])
            self.assertEqual(result["failure"]["step_id"], "step-2")
            self.assertEqual(result["failure"]["attempts"], 3)  # 1 + MAX_STEP_RETRIES (2)
            # Step 1 passed once; step 2 retried twice; steps 3-5 never ran.
            self.assertEqual(len(chat.calls), 4)
            self.assertEqual([s["step_id"] for s in result["steps"]], ["step-1", "step-2"])
            self.assertEqual(result["steps"][1]["status"], "needs_replan")
            # The retry prompt feeds the verifier detail back, grounded.
            retry_prompt = chat.calls[2]["messages"][1]["content"]
            self.assertIn("The previous attempt failed:", retry_prompt)
            self.assertIn("does not contain", retry_prompt)
            names = [e["event"] for e in events]
            self.assertEqual(names.count("step_retry"), 2)
            self.assertIn("replan_needed", names)
            self.assertNotIn("plan_completed", names)

    async def test_tool_outside_allowed_is_rejected_without_executing(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            plan = _happy_plan()
            chat = FakeChat([
                # Step 1 only allows list_project_files; the model tries a write.
                {"content": "sneaky", "tool_calls": [{"name": "save_text_artifact", "arguments": {"filename": "evil.md", "content": "x"}}]},
                {"content": "sneaky", "tool_calls": [{"name": "save_text_artifact", "arguments": {"filename": "evil.md", "content": "x"}}]},
                {"content": "sneaky", "tool_calls": [{"name": "save_text_artifact", "arguments": {"filename": "evil.md", "content": "x"}}]},
            ])
            tools = FakeTools(workspace)
            runner = SequenceRunner(chat=chat, execute_tool=tools)
            result = await runner.run(plan, workspace=workspace, run_id="run-3", executor_model="qwen3.5:9b")
            self.assertEqual(result["status"], "needs_replan")
            self.assertEqual(result["failure"]["step_id"], "step-1")
            # The forbidden tool was never executed and the file never appeared.
            self.assertNotIn(("save_text_artifact", {"filename": "evil.md", "content": "x"}), tools.calls)
            self.assertFalse((workspace / "evil.md").exists())
            self.assertIn("tool not allowed for this step", result["failure"]["detail"])

    async def test_invalid_plan_raises_before_any_chat_call(self):
        chat = FakeChat([])
        runner = SequenceRunner(chat=chat, execute_tool=FakeTools(tempfile.mkdtemp()))
        bad = _plan([_step("only-one", ["list_project_files"], {"type": "no_error"})])
        with self.assertRaises(ValueError):
            await runner.run(bad, workspace=None, run_id="run-4", executor_model="qwen3.5:9b")
        self.assertEqual(chat.calls, [])

    async def test_prompt_over_budget_fails_step_without_retry_or_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            plan = _plan([
                _step("step-1", ["list_project_files"], {"type": "no_error"}, budget_tokens=500),
                _step("step-2", ["list_project_files"], {"type": "no_error"}),
                _step("step-3", ["list_project_files"], {"type": "no_error"}),
                _step("step-4", ["list_project_files"], {"type": "no_error"}),
                _step("step-5", ["list_project_files"], {"type": "no_error"}),
            ], task="x" * 4000)
            chat = FakeChat([{"content": "ok", "tool_calls": []}])
            runner = SequenceRunner(chat=chat, execute_tool=FakeTools(workspace))
            result = await runner.run(plan, workspace=workspace, run_id="run-5", executor_model="qwen3.5:9b")
            self.assertEqual(result["status"], "needs_replan")
            self.assertEqual(result["remaining_steps"], ["step-1", "step-2", "step-3", "step-4", "step-5"])
            self.assertEqual(chat.calls, [])
            self.assertIn("exceeds budget_tokens", result["failure"]["detail"])

    async def test_step_timeout_retries_then_needs_replan(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            plan = _happy_plan()

            async def _never_wait_for(coro, timeout=None):
                coro.close()
                raise asyncio.TimeoutError()

            chat = FakeChat(_happy_responses(workspace))
            tools = FakeTools(workspace)
            events = []
            runner = SequenceRunner(chat=chat, execute_tool=tools, on_event=events.append)
            # Simulate the wait_for timeout without waiting out the 300s
            # budget three times over: the patched wait_for raises at once.
            with mock.patch("asyncio.wait_for", new=_never_wait_for):
                result = await runner.run(plan, workspace=workspace, run_id="run-6", executor_model="qwen3.5:9b")
            self.assertEqual(result["status"], "needs_replan")
            self.assertEqual(result["failure"]["step_id"], "step-1")
            self.assertEqual(result["failure"]["attempts"], 3)
            self.assertIn("timed out", result["failure"]["detail"])
            self.assertEqual([e["event"] for e in events].count("step_retry"), 2)
            # The timed-out chat/tool calls never actually ran.
            self.assertEqual(chat.calls, [])


if __name__ == "__main__":
    unittest.main()
