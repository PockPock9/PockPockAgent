import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import ssl
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from projects import agent_tools
from projects.agent_tools import (
    AgentToolContext,
    AgentToolError,
    ProjectAgentContext,
    _PageTextParser,
    _validate_public_url,
    apply_project_patch,
    create_office_artifact,
    explicit_task_hosts,
    execute_agent_tool,
    execute_project_tool,
    is_bulk_media_download_request,
    list_project_files,
    normalize_public_url,
    propose_project_addition,
    propose_project_edit,
    propose_project_patch,
    read_project_file,
    revert_project_addition,
    requested_artifact_extension,
    save_text_artifact,
    search_project,
    search_public_site,
    website_ssl_context,
)
from pockpock_server import require_local_agent_request



class WorkspaceToolTests(unittest.TestCase):
        def test_npm_validation_runs_without_opening_a_console(self):
            from projects.agent_tools.workspace import validate_project
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "package.json").write_text(json.dumps({"scripts": {"build": "vite build"}}), encoding="utf-8")
                context = ProjectAgentContext("hidden-command", root, allow_execution=True)
                completed = subprocess.CompletedProcess(["npm", "run", "build"], 0, "", "")
                with patch("projects.agent_tools.workspace.shutil.which", return_value="npm.cmd"), patch(
                    "projects.agent_tools.workspace.subprocess.run", return_value=completed
                ) as run:
                    result = validate_project(context)
                self.assertEqual(result["checks"][0]["status"], "passed")
                self.assertTrue(run.call_args.kwargs["capture_output"])
                self.assertEqual(run.call_args.kwargs["timeout"], 120)
                self.assertEqual(
                    run.call_args.kwargs["creationflags"],
                    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )

        def test_cjs_and_mjs_files_are_validated_with_one_check_name(self):
            # Issues #69 and #53: .cjs/.mjs were never listed, so a broken one passed with 0 files.
            from projects.agent_tools.workspace import validate_project
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "bad.cjs").write_text("module.exports = {\n", encoding="utf-8")
                (root / "ok.mjs").write_text("export const ok = 1\n", encoding="utf-8")
                (root / "bad.py").write_text("def broken(:\n", encoding="utf-8")
                self.assertIn("bad.cjs", list_project_files(ProjectAgentContext("files", root)))
                result = validate_project(ProjectAgentContext("validation", root))
                names = {check["path"]: (check["name"], check["status"]) for check in result["checks"] if "syntax" in check["name"]}
                self.assertEqual(names["bad.py"], ("Python syntax", "failed"))
                if shutil.which("node"):
                    self.assertEqual(names["bad.cjs"], ("JavaScript syntax", "failed"))
                    self.assertEqual(names["ok.mjs"], ("JavaScript syntax", "passed"))
                self.assertFalse(result["valid"])

        def test_validation_flags_blocking_dialogs_that_freeze_games(self):
            from projects.agent_tools.workspace import validate_project
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "game.js").write_text(
                    "function check() {\n  if (hit) { alert('Game Over!'); location.reload(); }\n}\n// confirm('not code')\nconst p = obj.prompt(1);\n",
                    encoding="utf-8",
                )
                (root / "ok.js").write_text("ctx.fillText('Game Over', 10, 10);\n", encoding="utf-8")
                result = validate_project(ProjectAgentContext("validation", root))
                self.assertFalse(result["valid"])
                self.assertEqual([issue["path"] for issue in result["issues"]], ["game.js"])
                self.assertIn("alert()", result["issues"][0]["message"])
                self.assertNotIn("confirm()", result["issues"][0]["message"])

        def test_project_agent_cannot_read_outside_or_sensitive_files(self):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "scripts").mkdir()
                (root / "scripts" / "sample.py").write_text("value = 1\n", encoding="utf-8")
                (root / ".env").write_text("SECRET=value\n", encoding="utf-8")
                (root / "private.db").write_bytes(b"not readable")
                (root / "credentials.json").write_text("{\"secret\":true}", encoding="utf-8")
                context = ProjectAgentContext("a" * 32, root)
                files = list_project_files(context)
                self.assertEqual(files, ["scripts/sample.py"])
                self.assertEqual(read_project_file(context, files[0])["content"].replace("\r\n", "\n"), "value = 1\n")
                self.assertEqual(search_project(context, "value")["matches"][0]["path"], "scripts/sample.py")
                self.assertEqual(context.files_read, 1)
                for path in ("../outside.txt", str(root / "scripts" / "sample.py"), ".env", "private.db", "credentials.json"):
                    with self.subTest(path=path), self.assertRaises(AgentToolError):
                        read_project_file(context, path)

        def test_project_patch_waits_for_approval_and_applies_only_unmodified_target(self):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / "README.md"
                target.write_text("# Old title\n", encoding="utf-8")
                context = ProjectAgentContext("b" * 32, root)
                read_project_file(context, "README.md")
                staged = propose_project_patch(context, "README.md", "# New title\n", "Clarify project title")
                self.assertIn("-# Old title", staged["diff"])
                self.assertEqual(target.read_text(encoding="utf-8"), "# Old title\n")
                applied = apply_project_patch(staged["patch_id"], root)
                self.assertEqual(applied["status"], "applied")
                self.assertEqual(target.read_text(encoding="utf-8"), "# New title\n")
                with self.assertRaises(AgentToolError):
                    apply_project_patch(staged["patch_id"], root)

        def test_project_patch_rejects_stale_diff_and_uninspected_changes(self):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / "README.md"
                target.write_text("before\n", encoding="utf-8")
                context = ProjectAgentContext("c" * 32, root)
                with self.assertRaises(AgentToolError):
                    asyncio.run(execute_project_tool(
                        "propose_project_patch",
                        {"path": "README.md", "content": "after\n", "summary": "Change"},
                        context,
                    ))
                (root / "other.md").write_text("unrelated\n", encoding="utf-8")
                read_project_file(context, "other.md")
                with self.assertRaises(AgentToolError):
                    propose_project_patch(context, "README.md", "after\n", "Change")
                read_project_file(context, "README.md")
                staged = propose_project_patch(context, "README.md", "after\n", "Change")
                target.write_text("changed outside review\n", encoding="utf-8")
                with self.assertRaises(AgentToolError):
                    apply_project_patch(staged["patch_id"], root)
                self.assertEqual(target.read_text(encoding="utf-8"), "changed outside review\n")

        def test_child_addition_is_staged_only_when_parent_path_is_absent(self):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / "new.py"
                parent = ProjectAgentContext("parent", root)
                staged = propose_project_addition(parent, "new.py", "value = 1\n", "Add child output")
                self.assertEqual(staged["status"], "pending")
                self.assertFalse(target.exists())
                with self.assertRaisesRegex(AgentToolError, "another pending parent patch"):
                    propose_project_addition(parent, "new.py", "value = 3\n", "Overlapping child output")

                target.write_text("parent edit\n", encoding="utf-8")
                with self.assertRaisesRegex(AgentToolError, "conflicts with a file"):
                    propose_project_addition(parent, "new.py", "value = 2\n", "Conflicting child output")
                with self.assertRaisesRegex(AgentToolError, "changed after this diff"):
                    apply_project_patch(staged["patch_id"], root)
                self.assertEqual(target.read_text(encoding="utf-8"), "parent edit\n")

        def test_revert_removes_only_the_exact_applied_child_addition(self):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / "new.py"
                target.write_bytes(b"value = 1\n")
                self.assertEqual(
                    revert_project_addition("new.py", "value = 1\n", root)["status"],
                    "reverted",
                )
                self.assertFalse(target.exists())

                target.write_bytes(b"later edit\n")
                with self.assertRaisesRegex(AgentToolError, "changed after application"):
                    revert_project_addition("new.py", "value = 1\n", root)
                self.assertEqual(target.read_bytes(), b"later edit\n")

        def test_overlapping_reviewed_patches_conflict_without_overwriting(self):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / "README.md"
                target.write_text("base\n", encoding="utf-8")
                first_context = ProjectAgentContext("1" * 32, root)
                second_context = ProjectAgentContext("2" * 32, root)
                read_project_file(first_context, "README.md")
                read_project_file(second_context, "README.md")
                first = propose_project_patch(first_context, "README.md", "first edit\n", "First delegate edit")
                second = propose_project_patch(second_context, "README.md", "second edit\n", "Second delegate edit")
                apply_project_patch(first["patch_id"], root)
                with self.assertRaisesRegex(AgentToolError, "changed after this diff was created"):
                    apply_project_patch(second["patch_id"], root)
                self.assertEqual(target.read_text(encoding="utf-8"), "first edit\n")

        def test_project_reads_are_bounded_and_exact_edits_remain_approval_gated(self):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / "large.py"
                original = "".join(f"value_{index} = {index}\n" for index in range(220))
                target.write_text(original, encoding="utf-8")
                context = ProjectAgentContext("d" * 32, root)
    
                first_chunk = read_project_file(context, "large.py", 1, 220)
                self.assertEqual(first_chunk["start_line"], 1)
                self.assertEqual(first_chunk["end_line"], 160)
                self.assertEqual(first_chunk["total_lines"], 220)
                self.assertTrue(first_chunk["truncated"])
                self.assertEqual(first_chunk["next_start_line"], 161)
                self.assertEqual(context.files_read, 1)
                with self.assertRaisesRegex(AgentToolError, "entire file in one call"):
                    propose_project_patch(context, "large.py", "replacement\n", "Replace a partially read file")
    
                second_chunk = read_project_file(context, "large.py", 161, 180)
                self.assertIn("value_165 = 165", second_chunk["content"])
                self.assertEqual(context.files_read, 1)
                staged = propose_project_edit(
                    context,
                    "large.py",
                    "value_165 = 165\n",
                    "value_165 = 42\n",
                    "Update one exact source line",
                )
                self.assertIn("-value_165 = 165", staged["diff"])
                self.assertIn("+value_165 = 42", staged["diff"])
                self.assertEqual(target.read_text(encoding="utf-8"), original)
                apply_project_patch(staged["patch_id"], root)
                self.assertIn("value_165 = 42\n", target.read_text(encoding="utf-8"))

        def test_project_edit_requires_unique_inspected_text(self):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / "README.md"
                target.write_text("repeat\nrepeat\n", encoding="utf-8")
                context = ProjectAgentContext("e" * 32, root)
                with self.assertRaises(AgentToolError):
                    propose_project_edit(context, "README.md", "repeat\n", "once\n", "Edit a line")
                read_project_file(context, "README.md")
                with self.assertRaises(AgentToolError):
                    propose_project_edit(context, "README.md", "repeat\n", "once\n", "Edit a line")

        def test_full_replacement_requires_unchanged_complete_read(self):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / "README.md"
                target.write_text("before\n", encoding="utf-8")
                context = ProjectAgentContext("f" * 32, root)
                read_project_file(context, "README.md")
    
                target.write_text("changed after inspection\n", encoding="utf-8")
                with self.assertRaisesRegex(AgentToolError, "changed after it was read in full"):
                    propose_project_patch(context, "README.md", "replacement\n", "Replace inspected file")
    
                read_project_file(context, "README.md")
                staged = propose_project_patch(context, "README.md", "replacement\n", "Replace inspected file")
                self.assertEqual(staged["status"], "pending")
                self.assertEqual(target.read_text(encoding="utf-8"), "changed after inspection\n")

if __name__ == "__main__":
    unittest.main()
