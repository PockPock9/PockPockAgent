"""PockPock Code's gateway engines without a gateway: the auto choice and following scripted events."""

import unittest
from unittest import mock

from projects.coding_cli import engines


class RecordingUI:
    quiet = False

    def __init__(self, answer="yes"):
        self.answer, self.lines, self.approvals, self.streamed_any = answer, [], [], False

    def text(self, chunk): self.lines.append(("text", chunk)); self.streamed_any = True
    def end_text(self): pass
    def tool_start(self, name, arguments): self.lines.append(("tool", name))
    def tool_result(self, name, arguments, output, ok): self.lines.append(("result", name, ok))
    def approve(self, kind, summary, detail): self.approvals.append((kind, summary)); return self.answer
    def notice(self, message): self.lines.append(("notice", message))
    def error(self, message): self.lines.append(("error", message))
    def _print(self, message="", style=None): self.lines.append(("print", message))
    def _tail(self, output): self.lines.append(("tail", output))


class ChooseEngineTests(unittest.TestCase):
    def choose(self, request, has_code=True, up=True):
        return engines.choose_engine(request, project_has_code=has_code, gateway_up=up)[0]

    def test_coding_requests_stay_in_the_built_in_agent(self):
        self.assertEqual(self.choose("Fix the failing test in cart.js"), "code")
        self.assertEqual(self.choose("How does the router pick a model?"), "code")
        self.assertEqual(self.choose("Add a --verbose flag to the CLI"), "code")

    def test_actions_on_this_pc_go_to_openclaw(self):
        self.assertEqual(self.choose("Open the browser and take a screenshot of https://example.com"), "openclaw")
        self.assertEqual(self.choose("Check my inbox and summarise new email"), "openclaw")

    def test_new_deliverables_go_to_plan_in_steps(self):
        self.assertEqual(self.choose("Build a nice website for my restaurant", has_code=False), "pockpock")
        self.assertEqual(self.choose("Create a resume in Word and PDF", has_code=False), "pockpock")

    def test_without_the_gateway_everything_stays_local(self):
        self.assertEqual(self.choose("Open the browser", up=False), "code")


class PockPockEngineTests(unittest.TestCase):
    def test_a_sequence_run_shows_steps_checks_and_answers_approvals(self):
        events = [
            {"type": "plan_step", "step": 1, "total": 2, "label": "Write index.html"},
            {"type": "approval_requested", "approval_id": "a" * 32, "action_hash": "b" * 64, "action": {"path": "index.html", "diff": "+<html>"}},
            {"type": "tool_start", "call_id": "1", "tool": "propose_project_patch", "input": {"path": "index.html"}},
            {"type": "tool_result", "call_id": "1", "tool": "propose_project_patch", "status": "success"},
            {"type": "sequence_check", "step": 1, "total": 2, "passed": True, "message": "Step 1 checked: index.html exists"},
            {"type": "token", "content": "Finished all 2 steps."},
            {"type": "done", "result": {"status": "completed"}},
        ]
        engine = engines.PockPockEngine(root="C:/p", model="qwen3.5:9b", planner="qwen3.8:27b", auto_approve_plan=True)
        posted = []
        with mock.patch.object(engines, "gateway_json", side_effect=lambda base, path, body=None, timeout=900: posted.append((path, body)) or {"accepted": True}):
            ui = RecordingUI(answer="always")
            final = engine._follow(iter(events), ui, "c" * 32)
        self.assertEqual(final, "Finished all 2 steps.")
        self.assertEqual(engine.last_status, "completed")
        self.assertEqual(ui.approvals, [("edit", "index.html")])
        self.assertEqual(posted[0][1], {"action_hash": "b" * 64, "decision": "approved", "scope": "task"})
        self.assertIn(("print", "▸ Step 1 of 2: Write index.html"), ui.lines)

    def test_the_cli_modes_map_to_each_engines_permissions(self):
        self.assertEqual(engines.POCKPOCK_PERMISSION["full-auto"], "full-access")
        self.assertEqual(engines.OPENCLAW_PERMISSION["suggest"], "ask")


class OpenClawEngineTests(unittest.TestCase):
    def test_a_turn_streams_tools_and_answers_approvals(self):
        events = [
            {"type": "tool", "phase": "start", "id": "t1", "title": "exec: npm test"},
            {"type": "tool_detail", "id": "t1", "command": "npm test", "output": "ok"},
            {"type": "approval", "id": "ap1", "title": "Run npm install", "description": "installs packages"},
            {"type": "replace", "content": "Tests pass."},
            {"type": "done"},
        ]
        engine = engines.OpenClawEngine(root="C:/Proj", model="qwen3.5:9b", mode="auto-edit")
        posted = []
        with mock.patch.object(engines, "gateway_stream", return_value=iter(events)) as stream, \
             mock.patch.object(engines, "gateway_json", side_effect=lambda base, path, body=None, timeout=900: posted.append(body) or {"ok": True}):
            final = engine.run("run the tests", RecordingUI(answer="no"))
        self.assertEqual(final, "Tests pass.")
        body = stream.call_args.args[2]
        self.assertEqual((body["model"], body["permission_mode"], body["workspace_path"]), ("ollama/qwen3.5:9b", "auto", "C:/Proj"))
        self.assertTrue(body["session_id"].startswith("pockpock-code-"), "one session per folder keeps the prompt cached")
        self.assertEqual(posted, [{"approval_id": "ap1", "decision": "deny"}])


if __name__ == "__main__":
    unittest.main()
