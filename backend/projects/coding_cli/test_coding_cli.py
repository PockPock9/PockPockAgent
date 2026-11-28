"""PockPock Code without a model: tools, text tool calls, approvals and the agent loop with a scripted model."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from projects.coding_cli import agent as agent_module
from projects.coding_cli import llm, tools
from projects.coding_cli.agent import Agent


class FakeUI:
    def __init__(self, answer="yes"):
        self.answer, self.events = answer, []

    def text(self, chunk): pass
    def thinking(self, chunk): pass
    def end_text(self): pass
    def tool_start(self, name, arguments): self.events.append(("start", name))
    def tool_result(self, name, arguments, output, ok): self.events.append(("result", name, ok, output))
    def approve(self, kind, summary, detail): self.events.append(("approve", kind)); return self.answer
    def notice(self, message): self.events.append(("notice", message))


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        self.ws = tools.Workspace(root=self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_paths_stay_inside_the_project(self):
        with self.assertRaises(tools.ToolError):
            tools.read_file(self.ws, "../outside.txt")

    def test_read_numbers_lines_and_says_where_the_file_ends(self):
        output = tools.read_file(self.ws, "src/app.py")
        self.assertIn("    2      return a - b", output)
        self.assertIn("end of file, 2 lines", output)

    def test_a_missing_file_suggests_close_names(self):
        with self.assertRaises(tools.ToolError) as caught:
            tools.read_file(self.ws, "src/ap.py")
        self.assertIn("src/app.py", str(caught.exception))

    def test_edit_replaces_exact_text_and_shows_a_diff(self):
        output = tools.edit_file(self.ws, "src/app.py", "return a - b", "return a + b")
        self.assertIn("+    return a + b", output)
        self.assertIn("a + b", (self.root / "src" / "app.py").read_text())

    def test_edit_tolerates_indentation_drift(self):
        tools.edit_file(self.ws, "src/app.py", "return a - b", "return a + b")  # exact
        tools.edit_file(self.ws, "src/app.py", "def add(a, b):\nreturn a + b", "def add(a, b):\n    return b + a")
        self.assertEqual((self.root / "src" / "app.py").read_text(), "def add(a, b):\n    return b + a\n")

    def test_an_ambiguous_edit_is_refused(self):
        (self.root / "dup.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
        with self.assertRaises(tools.ToolError):
            tools.edit_file(self.ws, "dup.py", "x = 1", "x = 2")

    def test_write_will_not_blindly_replace_an_unread_file(self):
        with self.assertRaises(tools.ToolError):
            tools.write_file(self.ws, "src/app.py", "print('hi')")
        tools.read_file(self.ws, "src/app.py")
        self.assertIn("Replaced", tools.write_file(self.ws, "src/app.py", "print('hi')"))

    def test_undo_restores_edits_and_removes_new_files(self):
        self.ws.begin_turn()
        tools.edit_file(self.ws, "src/app.py", "a - b", "a + b")
        tools.write_file(self.ws, "src/new.py", "x = 1")
        self.assertEqual(sorted(self.ws.undo()), ["src/app.py", "src/new.py"])
        self.assertIn("a - b", (self.root / "src" / "app.py").read_text())
        self.assertFalse((self.root / "src" / "new.py").exists())

    def test_search_and_list(self):
        self.assertIn("src/app.py:2:", tools.search(self.ws, r"return a"))
        self.assertEqual(tools.list_files(self.ws, pattern="*.py"), "src/app.py")

    def test_run_command_reports_the_exit_code(self):
        self.assertTrue(tools.run_command(self.ws, "echo hello").startswith("Exit code 0"))

    def test_argument_aliases_from_other_agents_are_accepted(self):
        self.assertIn("return", tools.call(self.ws, "read_file", {"file_path": "src/app.py"}))


class TextToolCallTests(unittest.TestCase):
    names = {"read_file", "run_command"}

    def test_tagged_fenced_and_bare_calls(self):
        calls, rest = llm.text_tool_calls('Let me look.\n<tool_call>{"name": "read_file", "arguments": {"path": "a.py"}}</tool_call>', self.names)
        self.assertEqual((calls[0].name, calls[0].arguments, rest), ("read_file", {"path": "a.py"}, "Let me look."))
        calls, _ = llm.text_tool_calls('```json\n{"name": "run_command", "arguments": {"command": "pytest"}}\n```', self.names)
        self.assertEqual(calls[0].arguments["command"], "pytest")
        calls, _ = llm.text_tool_calls('{"name": "read_file", "parameters": "{\\"path\\": \\"b.py\\"}"}', self.names)
        self.assertEqual(calls[0].arguments, {"path": "b.py"})

    def test_unknown_tools_and_plain_json_are_left_alone(self):
        self.assertEqual(llm.text_tool_calls('{"name": "delete_all", "arguments": {}}', self.names)[0], [])
        self.assertEqual(llm.text_tool_calls('Here is JSON: {"a": 1}', self.names)[0], [])

    def test_model_choice(self):
        self.assertEqual(llm.pick_model(["llava:7b", "qwen3.5:9b"]), "qwen3.5:9b")
        with self.assertRaises(llm.ModelError):
            llm.pick_model(["qwen3.5:9b"], "nope:1b")


def scripted(*replies):
    queue = list(replies)

    def fake_chat(messages, **kwargs):
        return queue.pop(0)
    return fake_chat


def call(name, **arguments):
    return llm.Reply(tool_calls=[llm.ToolCall(name=name, arguments=arguments)])


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, mode="auto-edit"):
        return Agent(ws=tools.Workspace(root=self.root), model="fake", mode=mode)

    def test_reads_edits_checks_and_answers(self):
        replies = scripted(call("read_file", path="calc.py"), call("edit_file", path="calc.py", old_text="a - b", new_text="a + b"),
                           call("run_command", command="echo ok"), llm.Reply(content="Fixed add in calc.py; checked with echo."))
        ui = FakeUI()
        with mock.patch.object(agent_module.llm, "chat", replies):
            final = self.make().run("fix add", ui)
        self.assertEqual(final, "Fixed add in calc.py; checked with echo.")
        self.assertIn(("approve", "command"), ui.events, "auto-edit asks before commands, not edits")
        self.assertNotIn(("approve", "edit"), ui.events)

    def test_unchecked_edits_get_one_nudge(self):
        replies = scripted(call("read_file", path="calc.py"), call("edit_file", path="calc.py", old_text="a - b", new_text="a + b"),
                           llm.Reply(content="Done."), llm.Reply(content="No tests here. Done."))
        agent = self.make()
        with mock.patch.object(agent_module.llm, "chat", replies):
            final = agent.run("fix add", FakeUI())
        self.assertEqual(final, "No tests here. Done.")
        self.assertTrue(any("did not run any check" in str(m.get("content")) for m in agent.messages))

    def test_open_todos_get_one_nudge(self):
        replies = scripted(call("todo_write", items=[{"task": "a", "status": "pending"}]), llm.Reply(content="Starting."), llm.Reply(content="All done."))
        with mock.patch.object(agent_module.llm, "chat", replies):
            self.assertEqual(self.make().run("plan", FakeUI()), "All done.")

    def test_a_declined_command_is_reported_to_the_model(self):
        replies = scripted(call("run_command", command="rm -rf build"), llm.Reply(content="OK, not running it."))
        agent = self.make()
        with mock.patch.object(agent_module.llm, "chat", replies):
            agent.run("clean", FakeUI(answer="no"))
        self.assertIn("declined", agent.messages[-2]["content"])

    def test_repeated_identical_calls_are_refused(self):
        same = [call("read_file", path="calc.py") for _ in range(3)]
        replies = scripted(*same, llm.Reply(content="done"))
        ui = FakeUI()
        with mock.patch.object(agent_module.llm, "chat", replies):
            self.make().run("look", ui)
        results = [e for e in ui.events if e[0] == "result"]
        self.assertFalse(results[-1][2])
        self.assertIn("already called", results[-1][3])

    def test_suggest_mode_asks_before_edits(self):
        replies = scripted(call("edit_file", path="calc.py", old_text="a - b", new_text="a + b"), llm.Reply(content="ok"))
        ui = FakeUI(answer="no")
        with mock.patch.object(agent_module.llm, "chat", replies):
            self.make("suggest").run("fix", ui)
        self.assertIn(("approve", "edit"), ui.events)
        self.assertIn("a - b", (self.root / "calc.py").read_text())

    def test_compaction_shortens_old_tool_output(self):
        agent = self.make()
        agent.num_ctx = 2000
        agent.messages += [{"role": "tool", "content": "x" * 3000} for _ in range(12)]
        self.assertTrue(agent.compact())
        self.assertLess(agent.context_chars(), 12 * 3000)


if __name__ == "__main__":
    unittest.main()
