import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "projects"))

from agent_verifier.verifiers import (
    list_verifiers,
    run_critic,
    run_verifiers,
)


def _workspace(files: dict[str, str]) -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp


class VerifierTests(unittest.TestCase):
    def test_registry_lists_the_builtin_verifiers(self):
        names = list_verifiers()
        for expected in ("python_syntax", "pytest", "lint", "typecheck",
                         "expected_files", "expected_content", "json_schema",
                         "git_diff_review"):
            self.assertIn(expected, names)

    def test_python_syntax_catches_a_syntax_error(self):
        with _workspace({"good.py": "x = 1\n", "bad.py": "def broken(:\n"}) as tmp:
            verdict = run_verifiers(tmp, {"verifiers": [{"name": "python_syntax"}]})
        self.assertEqual(verdict.verdict, "fail")
        self.assertEqual(verdict.failed_check, "python_syntax")
        self.assertIn("bad.py", verdict.checks[0].evidence)

    def test_expected_files_and_content_use_requirements_as_ground_truth(self):
        with _workspace({"app.py": "def main():\n    return 42\n"}) as tmp:
            verdict = run_verifiers(tmp, {"verifiers": [
                {"name": "expected_files", "files": ["app.py"]},
                {"name": "expected_content", "checks": [{"file": "app.py", "contains": "return 42"}]},
            ]})
        self.assertEqual(verdict.verdict, "pass")
        with _workspace({"app.py": "def main():\n    return 0\n"}) as tmp:
            verdict = run_verifiers(tmp, {"verifiers": [
                {"name": "expected_content", "checks": [{"file": "app.py", "contains": "return 42"}]},
            ]})
        self.assertEqual(verdict.verdict, "fail")
        self.assertEqual(verdict.failed_check, "expected_content")

    def test_json_schema_validates_without_a_third_party_library(self):
        schema = {"type": "object", "required": ["name", "version"],
                  "properties": {"name": {"type": "string"}, "version": {"type": "integer", "minimum": 1}}}
        with _workspace({"meta.json": json.dumps({"name": "x", "version": 2})}) as tmp:
            verdict = run_verifiers(tmp, {"verifiers": [
                {"name": "json_schema", "schema": schema, "files": ["meta.json"]}]})
        self.assertEqual(verdict.verdict, "pass")
        with _workspace({"meta.json": json.dumps({"name": "x"})}) as tmp:
            verdict = run_verifiers(tmp, {"verifiers": [
                {"name": "json_schema", "schema": schema, "files": ["meta.json"]}]})
        self.assertEqual(verdict.verdict, "fail")
        self.assertIn("version", verdict.checks[0].evidence)

    def test_pytest_verifier_reports_honestly_when_pytest_is_absent_or_present(self):
        with _workspace({"test_ok.py": "def test_ok():\n    assert 1 + 1 == 2\n"}) as tmp:
            verdict = run_verifiers(tmp, {"verifiers": [{"name": "pytest", "paths": ["test_ok.py"]}]})
        # In this repo venv pytest is not installed: the check must be
        # "skipped", never a false pass. Where pytest exists it must pass.
        self.assertIn(verdict.checks[0].status, ("passed", "skipped"))
        if verdict.checks[0].status == "skipped":
            self.assertIn("pytest", verdict.checks[0].evidence)

    def test_pytest_verifier_fails_on_a_failing_test_when_pytest_exists(self):
        try:
            subprocess.run([sys.executable, "-m", "pytest", "--version"],
                           capture_output=True, check=True, timeout=30)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            self.skipTest("pytest is not installed in this environment")
        with _workspace({"test_bad.py": "def test_bad():\n    assert False\n"}) as tmp:
            verdict = run_verifiers(tmp, {"verifiers": [{"name": "pytest", "paths": ["test_bad.py"]}]})
        self.assertEqual(verdict.verdict, "fail")
        self.assertEqual(verdict.failed_check, "pytest")

    def test_unknown_verifier_and_empty_spec_are_errors_not_passes(self):
        with _workspace({"a.py": "x = 1\n"}) as tmp:
            verdict = run_verifiers(tmp, {"verifiers": [{"name": "nope"}]})
            self.assertEqual(verdict.verdict, "error")
            empty = run_verifiers(tmp, {"verifiers": []})
            self.assertEqual(empty.verdict, "error")
            self.assertEqual(empty.failed_check, "no_verifiers_configured")

    def test_all_skipped_is_an_error_not_a_pass(self):
        with _workspace({}) as tmp:
            verdict = run_verifiers(tmp, {"verifiers": [{"name": "python_syntax"}]})
        self.assertEqual(verdict.checks[0].status, "skipped")
        self.assertEqual(verdict.verdict, "error")
        self.assertEqual(verdict.failed_check, "no_verifier_ran")

    def test_git_diff_review_flags_forbidden_paths(self):
        with _workspace({"app.py": "x = 1\n"}) as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
                            "commit", "-qm", "init"], cwd=root, check=True)
            (root / "app.py").write_text("x = 2\n", encoding="utf-8")
            verdict = run_verifiers(root, {"verifiers": [
                {"name": "git_diff_review", "expect_changes": True,
                 "forbidden_paths": ["app\\.py"]}]})
        self.assertEqual(verdict.verdict, "fail")
        self.assertEqual(verdict.failed_check, "git_diff_review")

    def test_critic_gets_requirements_and_evidence_but_never_the_transcript(self):
        seen: dict = {}

        def stub_critic(messages):
            seen["messages"] = messages
            return {"approved": True, "findings": []}

        result = run_critic(
            ["The file must contain 42"], ["Requirement is met by file content"],
            {"checks": [{"name": "expected_content", "status": "passed"}]},
            stub_critic,
        )
        self.assertEqual(result.status, "passed")
        payload = json.loads(seen["messages"][1]["content"])
        self.assertEqual(payload["requirements"], ["The file must contain 42"])
        self.assertNotIn("transcript", payload)
        self.assertNotIn("executor", json.dumps(payload).lower().replace("evidence", ""))

    def test_critic_rejection_fails_and_missing_critic_skips(self):
        def rejecting(messages):
            return {"approved": False, "findings": ["Requirement 1 not met by any file"]}

        result = run_critic(["Req 1"], ["rubric"], {}, rejecting)
        self.assertEqual(result.status, "failed")
        self.assertIn("Requirement 1", result.evidence)
        self.assertEqual(run_critic(["Req 1"], [], {}, None).status, "skipped")
        self.assertEqual(run_critic(["Req 1"], [], {}, lambda m: {"approved": "yes"}).status, "error")


if __name__ == "__main__":
    unittest.main()
