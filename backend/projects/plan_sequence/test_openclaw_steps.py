"""Plan-in-steps steps done by OpenClaw (openclaw_agent) and still checked in code."""

import asyncio
import queue
import tempfile
import unittest
from pathlib import Path

from projects.openclaw_bridge.step_delegate import make_openclaw_delegate, openclaw_model
from projects.plan_sequence.contracts import OPENCLAW_STEP_TOOL, validate_sequence_plan
from projects.plan_sequence.runner import SequenceRunner, build_openclaw_prompt
from projects.plan_sequence.test_runner import FakeChat, FakeTools, _plan, _step


class OpenClawStepRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_openclaw_step_is_delegated_then_checked_and_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            plan = _plan([
                _step("write", ["save_text_artifact"], {"type": "file_exists", "path": "notes.md"}),
                _step("scaffold", [OPENCLAW_STEP_TOOL], {"type": "file_exists", "path": "pubspec.yaml"}, inputs=["write"]),
            ], task="Make a Flutter app")
            prompts = []

            async def delegate(*, step, prompt, run_id, attempt, waiting):
                prompts.append(prompt)
                if attempt == 2:  # The first attempt "forgets" the file; the code check catches it.
                    (workspace / "pubspec.yaml").write_text("name: app\n")
                return {"tool_calls": [{"tool": "openclaw:exec", "ok": True}, {"tool": "openclaw_agent", "ok": True, "output": "done"}], "values": {}, "errors": []}

            chat = FakeChat([{"content": "", "tool_calls": [{"name": "save_text_artifact", "arguments": {"filename": "notes.md", "content": "x"}}]}])
            runner = SequenceRunner(chat=chat, execute_tool=FakeTools(workspace), delegate=delegate)
            result = await runner.run(plan, workspace=workspace, artifact_dir=workspace, run_id="r1", executor_model="qwen3.5:9b")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(len(prompts), 2, "the failed check sent the step back to OpenClaw")
            self.assertIn("pubspec.yaml", prompts[0])
            self.assertIn("file pubspec.yaml exists", prompts[1].lower().replace("the file ", "file "))
            self.assertEqual(len(chat.calls), 1, "the step model never ran the OpenClaw step")

    async def test_without_openclaw_the_step_fails_with_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            plan = _plan([
                _step("a", ["list_project_files"], {"type": "no_error"}),
                _step("b", [OPENCLAW_STEP_TOOL], {"type": "no_error"}, inputs=["a"]),
            ])
            chat = FakeChat([{"content": "", "tool_calls": [{"name": "list_project_files", "arguments": {}}]}])
            result = await SequenceRunner(chat=chat, execute_tool=FakeTools(workspace)).run(plan, workspace=workspace, run_id="r2", executor_model="m")
            self.assertEqual(result["status"], "needs_replan")
            self.assertIn("OpenClaw is not available", result["failure"]["detail"])

    def test_openclaw_is_a_steps_only_tool(self):
        plan = validate_sequence_plan(_plan([
            _step("a", ["list_project_files"], {"type": "no_error"}),
            _step("b", [OPENCLAW_STEP_TOOL, "read_project_file"], {"type": "no_error"}, inputs=["a"]),
        ]))
        self.assertEqual(plan["steps"][1]["tools_allowed"], [OPENCLAW_STEP_TOOL])

    def test_the_prompt_names_only_this_step_and_its_check(self):
        prompt = build_openclaw_prompt(task="Build an app", step=_step("run", [OPENCLAW_STEP_TOOL], {"type": "command_exit_0"}), capsule_text="")
        self.assertIn("ONE step", prompt)
        self.assertIn("This step: Do step run", prompt)


class OutputFileTests(unittest.TestCase):
    def test_a_utf16_file_from_powershell_is_read(self):
        from projects.plan_sequence.verifier import verify_done_condition

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "output.txt").write_bytes("1\r\n2\r\nFizz\r\nFizzBuzz\r\n".encode("utf-16"))
            result = verify_done_condition({"type": "file_contains", "path": "output.txt", "pattern": "FizzBuzz"}, workspace=Path(tmp), step_result={"tool_calls": [], "values": {}, "errors": []})
        self.assertTrue(result["passed"], result)

    def test_fields_a_check_does_not_have_are_dropped(self):
        plan = validate_sequence_plan(_plan([
            _step("a", ["list_project_files"], {"type": "no_error"}),
            _step("b", [OPENCLAW_STEP_TOOL], {"type": "command_exit_0", "command": "python -m unittest"}, inputs=["a"]),
        ]))
        self.assertEqual(plan["steps"][1]["done_condition"]["type"], "command_exit_0")

    def test_a_step_that_expects_a_failure_is_not_checked_by_exit_0(self):
        see = _step("see", [OPENCLAW_STEP_TOOL], {"type": "command_exit_0"}, inputs=["a"])
        see["goal"] = "Run the unit tests to capture the current failure state and error messages."
        done = _step("done", [OPENCLAW_STEP_TOOL], {"type": "command_exit_0"}, inputs=["see"])
        done["goal"] = "Run the unit tests again to verify that all tests now pass."
        plan = validate_sequence_plan(_plan([_step("a", ["list_project_files"], {"type": "no_error"}), see, done]))
        self.assertEqual([s["done_condition"]["type"] for s in plan["steps"][1:]], ["no_error", "command_exit_0"])


class FakeTurn:
    def __init__(self, events):
        self.events = queue.Queue()
        for event in events:
            self.events.put(event)
        self.events.put(None)
        self.aborted = False

    def next_event(self, timeout):
        return self.events.get()

    def abort(self):
        self.aborted = True

    def close(self):
        self.closed = True


class FakeBridge:
    def __init__(self, events, ok=True):
        self.events, self.ok, self.started = events, ok, []

    def available(self):
        return (self.ok, "")

    def start_turn(self, session, message, mode, model, selection, folder):
        self.started.append((session, mode, model, folder))
        return FakeTurn(self.events)


class DelegateTests(unittest.IsolatedAsyncioTestCase):
    async def test_events_are_relayed_and_only_the_last_exit_code_counts(self):
        events = [
            {"type": "tool", "phase": "start", "id": "1", "name": "exec", "title": "npm test"},
            {"type": "tool_detail", "id": "1", "command": "npm test", "exitCode": 1},
            {"type": "tool", "phase": "end", "id": "1", "name": "exec", "status": "failed", "error": "1 failing"},
            {"type": "approval", "id": "ap", "title": "Install packages"},
            {"type": "approval_resolved", "id": "ap", "decision": "allow-once"},
            {"type": "tool", "phase": "start", "id": "2", "name": "exec", "title": "npm test"},
            {"type": "tool_detail", "id": "2", "command": "npm test", "exitCode": 0},
            {"type": "final", "text": "Tests pass now."},
        ]
        bridge, emitted, waits = FakeBridge(events), [], []

        class Waiting:
            def __enter__(self): waits.append("in")
            def __exit__(self, *exc): waits.append("out")

        with tempfile.TemporaryDirectory() as tmp:
            delegate = make_openclaw_delegate(bridge, run_id="a" * 32, folder=Path(tmp), permission_mode="full-access", executor_model="qwen3.5:9b", emit=emitted.append)
            result = await delegate(step={"id": "test"}, prompt="run tests", run_id="a" * 32, attempt=1, waiting=Waiting)
        self.assertEqual(bridge.started[0][:3], ("pockpock-steps-" + "a" * 16, "full", "qwen3.5:9b"))
        codes = [call.get("exit_code") for call in result["tool_calls"] if "exit_code" in call]
        self.assertEqual(codes, [0])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["tool_calls"][-1]["output"], "Tests pass now.")
        self.assertEqual(waits, ["in", "out"], "the step clock stops while the approval waits")
        self.assertIn("openclaw_approval", [e["type"] for e in emitted])

    def test_no_delegate_without_openclaw_or_in_default_permission(self):
        self.assertIsNone(make_openclaw_delegate(FakeBridge([], ok=False), run_id="a" * 32, folder=Path("."), permission_mode="full-access", executor_model="m", emit=print))
        self.assertIsNone(make_openclaw_delegate(FakeBridge([]), run_id="a" * 32, folder=Path("."), permission_mode="default", executor_model="m", emit=print))
        self.assertIsNone(openclaw_model("nim/meta/llama-3.3-70b-instruct"))
        self.assertEqual(openclaw_model("huihui_ai/qwen3.5-abliterated:9b"), "huihui_ai/qwen3.5-abliterated:9b")


if __name__ == "__main__":
    unittest.main()
