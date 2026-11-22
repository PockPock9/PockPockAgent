import unittest

from projects.plan_sequence.contracts import repair_folder_writes, repair_read_tools
from projects.plan_sequence.ui_events import done_condition_text, final_reply, tool_output_text, ui_events

STEPS = [
    {"id": "read", "goal": "Read notes.md", "tools_allowed": ["read_project_file"], "done_condition": {"type": "no_error"}},
    {"id": "write", "goal": "Write summary.md", "tools_allowed": ["save_text_artifact"], "done_condition": {"type": "file_contains", "path": "summary.md", "pattern": "Friday"}},
]


class ToolOutputTests(unittest.TestCase):
    def test_each_tool_kind_gives_its_text(self):
        # Live validation 2026-11-22: a read file's content reached the next step as nothing.
        self.assertEqual(tool_output_text({"path": "notes.md", "content": "Release on Friday"}), "Release on Friday")
        self.assertEqual(tool_output_text({"files": ["a.md", "b.md"]}), "a.md\nb.md")
        self.assertIn("Friday", tool_output_text({"matches": [{"path": "a.md", "line": "Friday"}]}))
        self.assertEqual(tool_output_text({"output": "ok"}), "ok")
        self.assertIn("summary.md", tool_output_text({"saved": True, "name": "summary.md", "path": "x/summary.md"}))
        self.assertNotIn("+++", tool_output_text({"patch_id": "p", "diff": "+++ b/x"}))


class RepairTests(unittest.TestCase):
    def test_a_writing_step_after_a_read_can_read_again(self):
        plan = {"steps": [dict(step, tools_allowed=list(step["tools_allowed"])) for step in STEPS]}
        repair_read_tools(plan)
        self.assertEqual(plan["steps"][1]["tools_allowed"], ["save_text_artifact", "read_project_file"])

    def test_no_tool_the_plan_did_not_use_and_the_limit_is_kept(self):
        plan = {"steps": [{"tools_allowed": ["save_text_artifact"]}, {"tools_allowed": ["save_text_artifact"]}]}
        repair_read_tools(plan)
        self.assertEqual(plan["steps"][1]["tools_allowed"], ["save_text_artifact"], "nothing was read before")
        full = {"steps": [{"tools_allowed": ["scrape_public_page"]}, {"tools_allowed": ["save_text_artifact", "create_office_document", "validate_project"]}]}
        repair_read_tools(full)
        self.assertEqual(len(full["steps"][1]["tools_allowed"]), 3)


class FolderWriteTests(unittest.TestCase):
    def plan(self):
        return {"steps": [{"tools_allowed": ["read_project_file"]}, {"tools_allowed": ["save_text_artifact"]}]}

    def test_writing_in_this_folder_uses_the_change_tool(self):
        plan = repair_folder_writes(self.plan(), task="Write summary.md in this folder", folder_open=True, permission_mode="auto-review")
        self.assertEqual(plan["steps"][1]["tools_allowed"], ["propose_project_patch"])

    def test_left_alone_without_a_folder_in_default_mode_or_when_not_asked(self):
        for kwargs in ({"task": "Write summary.md in this folder", "folder_open": False, "permission_mode": "auto-review"},
                       {"task": "Write summary.md in this folder", "folder_open": True, "permission_mode": "default"},
                       {"task": "Write a summary of notes.md", "folder_open": True, "permission_mode": "auto-review"}):
            self.assertEqual(repair_folder_writes(self.plan(), **kwargs)["steps"][1]["tools_allowed"], ["save_text_artifact"], kwargs)


class EventTests(unittest.TestCase):
    def test_runner_events_become_app_events(self):
        started = ui_events({"event": "step_started", "step_id": "write"}, STEPS)
        self.assertEqual(started[0], {"type": "plan_step", "step": 2, "total": 2, "label": "Write summary.md"})
        checked = ui_events({"event": "step_verified", "step_id": "read", "status": "passed", "detail": "no errors"}, STEPS)
        self.assertTrue(checked[0]["passed"])
        failed = ui_events({"event": "replan_needed", "step_id": "write", "detail": "summary.md does not contain Friday"}, STEPS)
        self.assertEqual(failed[0]["type"], "error")
        self.assertIn("retry from step 2", failed[0]["message"])
        self.assertEqual(ui_events({"event": "plan_started"}, STEPS), [])

    def test_checks_and_reply_in_plain_words(self):
        self.assertEqual(done_condition_text({"type": "file_contains", "path": "summary.md", "pattern": "Friday"}), "summary.md contains “Friday”")
        reply = final_reply({"status": "completed", "steps": [{"status": "passed"}, {"status": "passed"}]}, STEPS, "nvidia/big", "qwen3.5:9b")
        self.assertIn("Finished all 2 steps", reply)
        self.assertIn("Planned by nvidia/big", reply)


if __name__ == "__main__":
    unittest.main()
