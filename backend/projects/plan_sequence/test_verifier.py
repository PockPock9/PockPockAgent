import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from projects.plan_sequence.contracts import DoneCondition
from projects.plan_sequence.verifier import verify_done_condition


def _result(tool_calls=None, values=None, errors=None):
    return {
        "tool_calls": tool_calls or [],
        "values": values or {},
        "errors": errors or [],
    }


def _call(tool="validate_project", ok=True, output="", exit_code=None):
    return {"tool": tool, "ok": ok, "output": output, "exit_code": exit_code}


class FileExistsTests(unittest.TestCase):
    def test_passes_when_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "summary.md").write_text("hello\n")
            result = verify_done_condition(
                {"type": "file_exists", "path": "summary.md"},
                workspace=root, step_result=_result(),
            )
            self.assertTrue(result["passed"])
            self.assertIn("summary.md", result["evidence"])

    def test_fails_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = verify_done_condition(
                {"type": "file_exists", "path": "nope.md"},
                workspace=Path(tmp), step_result=_result(),
            )
            self.assertFalse(result["passed"])
            self.assertIn("does not exist", result["detail"])

    def test_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root.parent / "outside-secret.txt"
            outside.write_text("secret")
            try:
                for escape in ("../outside-secret.txt", "/etc/passwd", "../../etc/passwd"):
                    with self.subTest(path=escape):
                        result = verify_done_condition(
                            {"type": "file_exists", "path": escape},
                            workspace=root, step_result=_result(),
                        )
                        self.assertFalse(result["passed"])
                        self.assertIn("escapes the workspace", result["detail"])
            finally:
                outside.unlink(missing_ok=True)

    def test_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root.parent / "outside-target.txt"
            outside.write_text("secret")
            try:
                (root / "link.txt").symlink_to(outside)
                result = verify_done_condition(
                    {"type": "file_exists", "path": "link.txt"},
                    workspace=root, step_result=_result(),
                )
                self.assertFalse(result["passed"])
                self.assertIn("escapes the workspace", result["detail"])
            finally:
                outside.unlink(missing_ok=True)

    def test_no_workspace_fails(self):
        result = verify_done_condition(
            {"type": "file_exists", "path": "summary.md"},
            workspace=None, step_result=_result(),
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["detail"], "no workspace")

    def test_accepts_done_condition_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("x")
            result = verify_done_condition(
                DoneCondition(type="file_exists", path="a.md"),
                workspace=root, step_result=_result(),
            )
            self.assertTrue(result["passed"])


class FileContainsTests(unittest.TestCase):
    def test_passes_and_evidences_first_matching_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("first line\ntotal: 42 here\ntotal: 43\n")
            result = verify_done_condition(
                {"type": "file_contains", "path": "a.md", "pattern": "total: 42"},
                workspace=root, step_result=_result(),
            )
            self.assertTrue(result["passed"])
            self.assertEqual(result["evidence"], "total: 42 here")

    def test_evidence_truncated_to_200_chars(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("needle " + "x" * 300 + "\n")
            result = verify_done_condition(
                {"type": "file_contains", "path": "a.md", "pattern": "needle"},
                workspace=root, step_result=_result(),
            )
            self.assertTrue(result["passed"])
            self.assertLessEqual(len(result["evidence"]), 200)

    def test_fails_when_pattern_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("nothing here\n")
            result = verify_done_condition(
                {"type": "file_contains", "path": "a.md", "pattern": "total"},
                workspace=root, step_result=_result(),
            )
            self.assertFalse(result["passed"])
            self.assertIn("does not contain", result["detail"])

    def test_case_sensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("Total: 42\n")
            result = verify_done_condition(
                {"type": "file_contains", "path": "a.md", "pattern": "total"},
                workspace=root, step_result=_result(),
            )
            self.assertFalse(result["passed"])

    def test_fails_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = verify_done_condition(
                {"type": "file_contains", "path": "a.md", "pattern": "x"},
                workspace=Path(tmp), step_result=_result(),
            )
            self.assertFalse(result["passed"])


class CommandExit0Tests(unittest.TestCase):
    def test_passes_when_all_exits_zero(self):
        result = verify_done_condition(
            {"type": "command_exit_0"},
            workspace=None,
            step_result=_result([_call(exit_code=0), _call(exit_code=0)]),
        )
        self.assertTrue(result["passed"])

    def test_fails_when_any_exit_nonzero(self):
        result = verify_done_condition(
            {"type": "command_exit_0"},
            workspace=None,
            step_result=_result([_call(exit_code=0), _call(exit_code=1)]),
        )
        self.assertFalse(result["passed"])
        self.assertIn("failed", result["detail"])

    def test_fails_when_no_command_recorded(self):
        for calls in ([], [_call(exit_code=None)], [_call()]):
            with self.subTest(calls=calls):
                result = verify_done_condition(
                    {"type": "command_exit_0"},
                    workspace=None, step_result=_result(calls),
                )
                self.assertFalse(result["passed"])
                self.assertEqual(result["detail"], "no command result recorded")


class ValueEqualsTests(unittest.TestCase):
    def test_passes_on_match(self):
        result = verify_done_condition(
            {"type": "value_equals", "field": "total", "expected": "42"},
            workspace=None, step_result=_result(values={"total": "42"}),
        )
        self.assertTrue(result["passed"])
        self.assertIn("42", result["evidence"])

    def test_fails_on_mismatch(self):
        result = verify_done_condition(
            {"type": "value_equals", "field": "total", "expected": "42"},
            workspace=None, step_result=_result(values={"total": "43"}),
        )
        self.assertFalse(result["passed"])
        self.assertIn("mismatch", result["detail"])

    def test_fails_when_field_missing(self):
        result = verify_done_condition(
            {"type": "value_equals", "field": "total", "expected": "42"},
            workspace=None, step_result=_result(values={}),
        )
        self.assertFalse(result["passed"])
        self.assertIn("missing", result["detail"])


class NoErrorTests(unittest.TestCase):
    def test_passes_with_no_calls_and_no_errors(self):
        result = verify_done_condition(
            {"type": "no_error"}, workspace=None, step_result=_result(),
        )
        self.assertTrue(result["passed"])

    def test_passes_when_all_calls_ok(self):
        result = verify_done_condition(
            {"type": "no_error"},
            workspace=None, step_result=_result([_call(ok=True)]),
        )
        self.assertTrue(result["passed"])

    def test_fails_when_a_call_failed(self):
        result = verify_done_condition(
            {"type": "no_error"},
            workspace=None, step_result=_result([_call(ok=False)]),
        )
        self.assertFalse(result["passed"])

    def test_fails_when_errors_listed(self):
        result = verify_done_condition(
            {"type": "no_error"},
            workspace=None, step_result=_result([_call(ok=True)], errors=["boom"]),
        )
        self.assertFalse(result["passed"])
        self.assertIn("boom", result["detail"])


class UnknownAndGarbageTests(unittest.TestCase):
    def test_unknown_type_fails(self):
        result = verify_done_condition(
            {"type": "looks_good"}, workspace=None, step_result=_result(),
        )
        self.assertFalse(result["passed"])
        self.assertIn("unknown done-condition type", result["detail"])

    def test_never_raises_on_garbage_input(self):
        garbage_conditions = [
            None, "file_exists", 123, [], {}, {"type": None},
            {"type": "file_exists"}, {"type": "file_exists", "path": None},
            {"type": "file_exists", "path": 42},
            {"type": "file_contains", "path": "a.md"},
            {"type": "value_equals", "field": "x"},
            {"type": "command_exit_0", "path": "x"},
        ]
        garbage_results = [None, "nope", 42, {"tool_calls": "nope"}, {"values": []}]
        for condition in garbage_conditions:
            for step_result in garbage_results:
                with self.subTest(condition=condition, step_result=step_result):
                    try:
                        result = verify_done_condition(
                            condition, workspace=None, step_result=step_result,
                        )
                    except Exception as exc:  # pragma: no cover
                        self.fail(f"verify_done_condition raised {exc!r}")
                    self.assertIsInstance(result, dict)
                    self.assertFalse(result["passed"])
                    self.assertIn("detail", result)
                    self.assertIn("evidence", result)


if __name__ == "__main__":
    unittest.main()
