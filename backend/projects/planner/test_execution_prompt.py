import re
import unittest

from app import build_execution_prompt, planning_timeout


class ExecutionPromptTests(unittest.TestCase):
    def test_short_model_prompt_uses_reviewed_plan_and_verification(self):
        prompt = build_execution_prompt(
            "Open YouTube",
            ["Navigate to YouTube", "Verify the page title"],
            "Open the requested site.",
        )

        self.assertIn("Original user request: Open YouTube", prompt)
        self.assertIn("1. Navigate to YouTube", prompt)
        self.assertIn("Verify every success check", prompt)
        self.assertGreaterEqual(len(re.findall(r"\b[\w'-]+\b", prompt)), 40)

    def test_detailed_model_prompt_is_preserved(self):
        model_prompt = " ".join(f"Instruction{index}" for index in range(45))
        prompt = build_execution_prompt("Open YouTube", ["Navigate to YouTube"], model_prompt)

        self.assertIn(f"Detailed execution prompt:\n{model_prompt}", prompt)
        self.assertNotIn("Reviewed plan:", prompt)


class PlanningTimeoutTests(unittest.TestCase):
    def test_large_models_get_longer_planner_calls(self):
        profiles = [{"name": "big", "parameter_billions": 27.8}, {"name": "mid", "parameter_billions": 9.7}]

        self.assertEqual(planning_timeout(profiles, "big").total, 900)
        self.assertEqual(planning_timeout(profiles, "mid").total, 600)
        self.assertEqual(planning_timeout(profiles, "unknown").total, 600)
        # The read timeout is the longest silence while the reply streams, not the whole answer.
        self.assertEqual(planning_timeout(profiles, "mid").sock_read, 240)


if __name__ == "__main__":
    unittest.main()
