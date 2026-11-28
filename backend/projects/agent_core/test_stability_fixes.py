"""Fixes from live end-to-end runs of "One model plans and works" (2026-11-27)."""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from projects.agent_core.executor import effective_task_capabilities, names_folder_file
from projects.agent_tools import ProjectAgentContext
from projects.agent_tools.workspace import validate_project_service


class FolderFileTests(unittest.TestCase):
    def test_a_request_naming_a_file_in_the_open_folder_may_read_the_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "resume.txt").write_text("Kan Chan\n", encoding="utf-8")
            self.assertTrue(names_folder_file("Turn resume.txt into a nicely formatted resume.html", folder))
            self.assertFalse(names_folder_file("Turn cv.txt into cv.html", folder))
            self.assertFalse(names_folder_file("Turn resume.txt into resume.html", None))
            capabilities = effective_task_capabilities(["attachment_read", "workspace_write"], requires_tool=True, has_files=False, reads_folder_file=True)
            self.assertIn("workspace_read", capabilities)
            self.assertNotIn("workspace_read", effective_task_capabilities(["workspace_write"], requires_tool=True, has_files=False))


class ValidatorUnavailableTests(unittest.TestCase):
    def test_a_validator_that_is_not_running_is_a_result_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ProjectAgentContext("a" * 32, Path(tmp))
            with mock.patch.dict(os.environ, {"POCKPOCK_VALIDATOR_URL": "http://127.0.0.1:9", "POCKPOCK_INTERNAL_TOKEN": "t"}):
                result = asyncio.run(validate_project_service(context))
        self.assertEqual(result["status"], "unavailable")
        for field in ("valid", "checks", "issues", "checked_files", "execution_enabled"):
            self.assertIn(field, result, "the tool's output contract requires it")
        self.assertIn("Do not call validate_project again", result["summary"])


if __name__ == "__main__":
    unittest.main()
