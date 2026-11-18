import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from projects.plan_sequence.contracts import (
    MAX_CAPSULE_TOKENS,
    DoneCondition,
    SequencePlan,
    validate_sequence_plan,
)


def _step(step_id, tools=("list_project_files",), done=None, inputs=()):
    return {
        "id": step_id,
        "goal": f"Do step {step_id}",
        "tools_allowed": list(tools),
        "done_condition": done or {"type": "no_error"},
        "inputs": list(inputs),
    }


def _valid_plan():
    return {
        "task": "Summarise my Canva invoices from Gmail and save the totals.",
        "steps": [
            _step("find-files", ["list_project_files"],
                  {"type": "file_exists", "path": "src/main.py"}),
            _step("read-code", ["read_project_file"],
                  {"type": "file_contains", "path": "src/main.py", "pattern": "def main"},
                  inputs=["find-files"]),
            _step("check-code", ["validate_project"],
                  {"type": "command_exit_0"}, inputs=["read-code"]),
            _step("write-summary", ["save_text_artifact"],
                  {"type": "file_exists", "path": "summary.md"}, inputs=["check-code"]),
            _step("verify", ["read_project_file"],
                  {"type": "value_equals", "field": "total", "expected": "42"},
                  inputs=["write-summary"]),
        ],
    }


def _n_step_plan(count):
    return {
        "task": "A task with many steps.",
        "steps": [
            _step(f"step-{index + 1}", ["list_project_files"])
            for index in range(count)
        ],
    }


class ValidateSequencePlanTests(unittest.TestCase):
    def test_valid_plan_passes_unchanged(self):
        plan = _valid_plan()
        result = validate_sequence_plan(plan)
        self.assertEqual(result["contract_version"], 1)
        self.assertEqual(result["task"], plan["task"])
        self.assertEqual(
            [step["id"] for step in result["steps"]],
            ["find-files", "read-code", "check-code", "write-summary", "verify"],
        )
        self.assertEqual(result["steps"][0]["tools_allowed"], ["list_project_files"])
        self.assertEqual(result["steps"][0]["budget_tokens"], 4000)
        self.assertEqual(result["steps"][0]["budget_seconds"], 300)
        # The normalised form is exactly what the model dumps.
        self.assertEqual(result, SequencePlan.model_validate(plan).model_dump(mode="json"))

    def test_four_steps_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least 5"):
            validate_sequence_plan(_n_step_plan(4))

    def test_sixteen_steps_rejected(self):
        with self.assertRaisesRegex(ValueError, "at most 15"):
            validate_sequence_plan(_n_step_plan(16))

    def test_five_and_fifteen_steps_accepted(self):
        validate_sequence_plan(_n_step_plan(5))
        validate_sequence_plan(_n_step_plan(15))

    def test_duplicate_step_id_rejected(self):
        plan = _valid_plan()
        plan["steps"][1]["id"] = plan["steps"][0]["id"]
        with self.assertRaisesRegex(ValueError, "Duplicate step id"):
            validate_sequence_plan(plan)

    def test_unknown_tool_rejected(self):
        plan = _valid_plan()
        plan["steps"][0]["tools_allowed"] = ["does_not_exist"]
        with self.assertRaisesRegex(ValueError, "unknown tool.*does_not_exist"):
            validate_sequence_plan(plan)

    def test_allowed_tools_override_is_honoured(self):
        plan = _valid_plan()
        with self.assertRaisesRegex(ValueError, "unknown tool"):
            validate_sequence_plan(plan, allowed_tools={"list_project_files"})
        allowed = {
            "list_project_files", "read_project_file", "validate_project",
            "save_text_artifact",
        }
        self.assertEqual(validate_sequence_plan(plan, allowed_tools=allowed)["task"], plan["task"])

    def test_duplicate_tools_allowed_rejected(self):
        plan = _valid_plan()
        plan["steps"][0]["tools_allowed"] = ["list_project_files", "list_project_files"]
        with self.assertRaisesRegex(ValueError, "tools_allowed must be unique"):
            validate_sequence_plan(plan)

    def test_zero_tools_allowed_rejected(self):
        plan = _valid_plan()
        plan["steps"][0]["tools_allowed"] = []
        with self.assertRaisesRegex(ValueError, "at least 1"):
            validate_sequence_plan(plan)

    def test_four_tools_allowed_rejected(self):
        plan = _valid_plan()
        plan["steps"][0]["tools_allowed"] = [
            "list_project_files", "read_project_file", "search_project", "validate_project",
        ]
        with self.assertRaisesRegex(ValueError, "at most 3"):
            validate_sequence_plan(plan)

    def test_extra_field_rejected(self):
        plan = _valid_plan()
        plan["steps"][0]["surprise"] = True
        with self.assertRaises(ValueError):
            validate_sequence_plan(plan)

    def test_non_dict_rejected(self):
        with self.assertRaises(ValueError):
            validate_sequence_plan(["not", "a", "plan"])


class DoneConditionTests(unittest.TestCase):
    def test_each_type_valid_with_its_fields(self):
        valid = [
            {"type": "file_exists", "path": "summary.md"},
            {"type": "file_contains", "path": "summary.md", "pattern": "42"},
            {"type": "command_exit_0"},
            {"type": "value_equals", "field": "total", "expected": "42"},
            {"type": "no_error"},
        ]
        for condition in valid:
            with self.subTest(condition=condition):
                self.assertEqual(DoneCondition.model_validate(condition).type, condition["type"])

    def test_each_type_missing_required_field_rejected(self):
        invalid = [
            ({"type": "file_exists"}, "path"),
            ({"type": "file_contains", "path": "summary.md"}, "pattern"),
            ({"type": "file_contains", "pattern": "42"}, "path"),
            ({"type": "value_equals", "field": "total"}, "expected"),
            ({"type": "value_equals", "expected": "42"}, "field"),
        ]
        for condition, field in invalid:
            with self.subTest(condition=condition):
                with self.assertRaisesRegex(ValueError, f"requires.*{field}"):
                    DoneCondition.model_validate(condition)

    def test_each_type_forbidden_field_rejected(self):
        invalid = [
            ({"type": "file_exists", "path": "a", "pattern": "b"}, "pattern"),
            ({"type": "file_contains", "path": "a", "pattern": "b", "field": "c"}, "field"),
            ({"type": "command_exit_0", "path": "a"}, "path"),
            ({"type": "command_exit_0", "expected": "0"}, "expected"),
            ({"type": "value_equals", "field": "t", "expected": "1", "path": "a"}, "path"),
            ({"type": "no_error", "pattern": "ok"}, "pattern"),
        ]
        for condition, field in invalid:
            with self.subTest(condition=condition):
                with self.assertRaisesRegex(ValueError, f"forbids.*{field}"):
                    DoneCondition.model_validate(condition)

    def test_unknown_done_condition_type_rejected(self):
        with self.assertRaises(ValueError):
            DoneCondition.model_validate({"type": "looks_good"})


class StepInputTests(unittest.TestCase):
    def test_dangling_input_rejected(self):
        plan = _valid_plan()
        plan["steps"][1]["inputs"] = ["no_such_step"]
        with self.assertRaisesRegex(ValueError, "dangling input 'no_such_step'"):
            validate_sequence_plan(plan)

    def test_task_input_allowed(self):
        plan = _valid_plan()
        plan["steps"][1]["inputs"] = ["task"]
        plan["steps"][4]["inputs"] = ["task", "write-summary"]
        validate_sequence_plan(plan)

    def test_earlier_step_input_allowed(self):
        plan = _valid_plan()
        plan["steps"][4]["inputs"] = ["find-files", "read-code"]
        validate_sequence_plan(plan)

    def test_later_step_input_rejected(self):
        plan = _valid_plan()
        plan["steps"][0]["inputs"] = ["verify"]
        with self.assertRaisesRegex(ValueError, "dangling input 'verify'"):
            validate_sequence_plan(plan)

    def test_self_input_rejected(self):
        plan = _valid_plan()
        plan["steps"][2]["inputs"] = ["check-code"]
        with self.assertRaisesRegex(ValueError, "dangling input 'check-code'"):
            validate_sequence_plan(plan)


class ConstantsTests(unittest.TestCase):
    def test_frozen_bounds(self):
        from projects.plan_sequence.contracts import (
            MAX_STEPS,
            MAX_STEP_RETRIES,
            MAX_TOOLS_PER_STEP,
            MIN_STEPS,
            SEQUENCE_CONTRACT_VERSION,
        )
        self.assertEqual((MIN_STEPS, MAX_STEPS), (5, 15))
        self.assertEqual(MAX_CAPSULE_TOKENS, 400)
        self.assertEqual(MAX_STEP_RETRIES, 2)
        self.assertEqual(MAX_TOOLS_PER_STEP, 3)
        self.assertEqual(SEQUENCE_CONTRACT_VERSION, 1)


if __name__ == "__main__":
    unittest.main()
