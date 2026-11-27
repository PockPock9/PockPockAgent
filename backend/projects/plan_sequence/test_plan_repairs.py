"""Corrections for plan mistakes that guarantee a failed step (live runs 2026-11-27)."""

import tempfile
import unittest
from pathlib import Path

from projects.plan_sequence.contracts import names_a_website, repair_plan_mistakes
from projects.plan_sequence.verifier import verify_done_condition


def step(step_id, tools, condition, inputs=("task",)):
    return {"id": step_id, "goal": step_id, "tools_allowed": list(tools), "done_condition": condition, "inputs": list(inputs)}


class PlanRepairTests(unittest.TestCase):
    def test_web_tools_are_dropped_when_the_request_names_no_website(self):
        plan = {"steps": [step("research", ["browse_public_page", "scrape_public_page"], {"type": "file_contains", "path": "notes.md", "pattern": "competitors"})]}
        fixed = repair_plan_mistakes(plan, task="Build a nice website for my restaurant", folder_open=True, permission_mode="full-access")
        self.assertEqual(fixed["steps"][0]["tools_allowed"], ["propose_project_patch"], "left with no tool, it gets the writer")

    def test_web_tools_stay_when_the_request_names_a_site(self):
        plan = {"steps": [step("read", ["scrape_public_page"], {"type": "no_error"})]}
        fixed = repair_plan_mistakes(plan, task="Summarise https://example.com/menu", folder_open=False, permission_mode="auto-review")
        self.assertEqual(fixed["steps"][0]["tools_allowed"], ["scrape_public_page"])

    def test_the_image_tool_is_dropped_when_the_result_is_not_an_image(self):
        plan = {"steps": [
            step("summary", ["generate_local_image"], {"type": "file_contains", "path": "summary.md", "pattern": "key point"}),
            step("hero", ["generate_local_image"], {"type": "file_exists", "path": "hero.png"}),
        ]}
        fixed = repair_plan_mistakes(plan, task="Write summary.md", folder_open=False, permission_mode="auto-review")
        self.assertEqual(fixed["steps"][0]["tools_allowed"], ["save_text_artifact"])
        self.assertEqual(fixed["steps"][1]["tools_allowed"], ["generate_local_image"])

    def test_a_read_only_step_checks_that_the_file_exists_not_guessed_text(self):
        plan = {"steps": [step("read", ["read_project_file"], {"type": "file_contains", "path": "resume.txt", "pattern": "John Doe"})]}
        fixed = repair_plan_mistakes(plan, task="Turn resume.txt into resume.html", folder_open=True, permission_mode="full-access")
        self.assertEqual(fixed["steps"][0]["done_condition"]["type"], "file_exists")
        self.assertEqual(fixed["steps"][0]["tools_allowed"], ["read_project_file"])

    def test_a_listing_step_keeps_its_tools(self):
        plan = {"steps": [step("find", ["list_project_files"], {"type": "file_exists", "path": "src/main.py"})]}
        fixed = repair_plan_mistakes(plan, task="Explain src/main.py", folder_open=True, permission_mode="auto-review")
        self.assertEqual(fixed["steps"][0]["tools_allowed"], ["list_project_files"])

    def test_inputs_that_name_no_earlier_step_are_dropped(self):
        plan = {"steps": [
            step("outline", ["save_text_artifact"], {"type": "file_exists", "path": "outline.md"}),
            step("page", ["save_text_artifact"], {"type": "file_exists", "path": "index.html"}, inputs=["content_outline.md", "outline"]),
        ]}
        fixed = repair_plan_mistakes(plan, task="Build a website", folder_open=False, permission_mode="auto-review")
        self.assertEqual(fixed["steps"][1]["inputs"], ["outline"])

    def test_a_website_is_a_url_or_host_name_not_a_file_name(self):
        self.assertTrue(names_a_website("Read https://example.com/a"))
        self.assertTrue(names_a_website("What is new on docs.python.org?"))
        self.assertFalse(names_a_website("Read notes.md and write summary.md"))
        self.assertFalse(names_a_website("Build index.html and styles.css"))


class PatternListTests(unittest.TestCase):
    def check(self, text, pattern):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "page.html").write_text(text, encoding="utf-8")
            return verify_done_condition({"type": "file_contains", "path": "page.html", "pattern": pattern}, workspace=root, step_result={"tool_calls": [], "values": {}, "errors": []})

    def test_a_pattern_that_lists_tags_or_words_passes_when_each_is_present(self):
        page = '<!DOCTYPE html>\n<html lang="en"><head><title>Home</title></head>\n<body><nav>Home | Menu | About | Contact</nav></body></html>\n'
        self.assertTrue(self.check(page, "<html><head><body>")["passed"])
        self.assertTrue(self.check(page, "home menu about contact")["passed"])
        missing = self.check(page, "home menu booking")
        self.assertFalse(missing["passed"])
        self.assertIn("“booking”", missing["detail"])

    def test_the_folder_with_the_file_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace, task_folder = Path(tmp, "ws"), Path(tmp, "task")
            workspace.mkdir(); task_folder.mkdir()
            (workspace / "resume.txt").write_text("Kan Chan\n", encoding="utf-8")
            result = verify_done_condition({"type": "file_contains", "path": "resume.txt", "pattern": "Jane"}, workspace=workspace, artifact_dir=task_folder, step_result={"tool_calls": [], "values": {}, "errors": []})
            self.assertIn("does not contain", result["detail"])


if __name__ == "__main__":
    unittest.main()
