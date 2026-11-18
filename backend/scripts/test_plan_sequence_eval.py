"""Tests for the Plan-and-Sequence P1 eval harness.

The eval script itself (``evaluate_plan_sequence.py`` beside this file)
is the P1 artifact; these tests pin its pure helpers and one
representative fake-model run so a broken reference plan or a capsule
regression fails fast. No live model is used here.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evaluate_plan_sequence as eval_ps  # noqa: E402


class ReferencePlanTests(unittest.TestCase):
    def test_all_reference_plans_validate(self):
        errors = eval_ps.validate_reference_plans()
        self.assertEqual(errors, [])

    def test_six_tasks_five_steps_each(self):
        self.assertEqual(len(eval_ps.REFERENCE_TASKS), 6)
        for task_def in eval_ps.REFERENCE_TASKS:
            self.assertEqual(len(task_def["plan"]["steps"]), 5)
            self.assertEqual(len(task_def["script"]), 5)


class BaselineTests(unittest.TestCase):
    def test_monolithic_baseline_is_21k_plus_measured_schemas(self):
        baseline = eval_ps.monolithic_baseline_tokens()
        self.assertEqual(baseline["system_prompt_tokens"], 21_000)
        # 15 registered tools; schemas measured, not hard-coded.
        self.assertGreater(baseline["full_schema_tokens"], 0)
        self.assertEqual(
            baseline["total_with_schemas"],
            21_000 + baseline["full_schema_tokens"],
        )


class MeasurementATests(unittest.TestCase):
    def test_first_task_prompts_and_capsule_within_targets(self):
        result = eval_ps.measure_prompt_tokens(eval_ps.REFERENCE_TASKS[0])
        self.assertEqual(result["steps_over_target"], 0)
        self.assertLessEqual(
            result["max_step_prompt_tokens"], eval_ps.STEP_PROMPT_TOKEN_TARGET
        )
        self.assertLessEqual(
            result["max_capsule_tokens"], eval_ps.MAX_CAPSULE_TOKENS
        )
        self.assertEqual(len(result["rows"]), 5)


class MeasurementBTests(unittest.TestCase):
    def test_first_task_completes_with_fake_model_and_real_tools(self):
        result = eval_ps.run_fake(eval_ps.REFERENCE_TASKS[0])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["steps_passed"], result["steps_total"])
        self.assertEqual(result["retries_used"], 0)
        self.assertTrue(result["think_always_false"])
        self.assertLessEqual(
            result["final_capsule_tokens"], eval_ps.MAX_CAPSULE_TOKENS
        )


if __name__ == "__main__":
    unittest.main()
