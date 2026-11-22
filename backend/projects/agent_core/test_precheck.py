import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from projects.agent_core.precheck import named_files, plan_precheck  # noqa: E402


def brief(**overrides):
    return {"required_capabilities": [], "deliverables": [], "clarifying_questions": [], **overrides}


class NamedFilesTests(unittest.TestCase):
    def test_names_exclude_attachments_and_deliverables(self):
        request = "Summarise notes.md and docs/plan.txt into summary.md\n\nAttached files: budget.xlsx"
        self.assertEqual(named_files(request, ["summary.md"]), ["notes.md", "docs/plan.txt"])

    def test_no_names(self):
        self.assertEqual(named_files("Write a poem about the sea", []), [])


class PlanPrecheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        (self.folder / "docs").mkdir()
        (self.folder / "docs" / "notes.md").write_text("x", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def by_id(self, checks):
        return {item["id"]: item for item in checks}

    def test_all_pass(self):
        checks = self.by_id(plan_precheck(request="Summarise notes.md into summary.md", task_brief=brief(required_capabilities=["workspace_read", "artifact_creation"], deliverables=["summary.md"]),
                                          workspace=self.folder, permission_mode="auto-review", research_enabled=False))
        self.assertEqual(checks["files"]["status"], "pass")  # found below the folder by name
        self.assertEqual(checks["tools"]["status"], "pass")
        self.assertEqual(checks["questions"]["status"], "pass")

    def test_missing_file_and_no_folder(self):
        checks = self.by_id(plan_precheck(request="Read missing.csv", task_brief=brief(), workspace=self.folder, permission_mode="auto-review", research_enabled=False))
        self.assertEqual(checks["files"]["status"], "warn")
        self.assertIn("missing.csv", checks["files"]["detail"])
        checks = self.by_id(plan_precheck(request="Read notes.md", task_brief=brief(), workspace=None, permission_mode="auto-review", research_enabled=False))
        self.assertEqual(checks["files"]["label"], "No folder open")

    def test_default_permission_blocks_folder_tools(self):
        checks = self.by_id(plan_precheck(request="Fix the bug", task_brief=brief(required_capabilities=["workspace_write"]), workspace=self.folder, permission_mode="default", research_enabled=True))
        self.assertEqual(checks["tools"]["status"], "warn")

    def test_research_must_be_on(self):
        checks = self.by_id(plan_precheck(request="Research it", task_brief=brief(required_capabilities=["public_research"]), workspace=None, permission_mode="auto-review", research_enabled=False))
        self.assertEqual(checks["tools"]["label"], "Research is off")

    def test_open_questions(self):
        checks = self.by_id(plan_precheck(request="Do it", task_brief=brief(clarifying_questions=["Include cloud models?"]), workspace=None, permission_mode="auto-review", research_enabled=True))
        self.assertEqual(checks["questions"]["label"], "1 question open")

    def test_path_outside_the_folder_is_not_found(self):
        checks = self.by_id(plan_precheck(request="Read ../secret.md", task_brief=brief(), workspace=self.folder / "docs", permission_mode="auto-review", research_enabled=False))
        self.assertEqual(checks["files"]["status"], "warn")


if __name__ == "__main__":
    unittest.main()
