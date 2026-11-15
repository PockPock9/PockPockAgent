import re
import unittest

from app import build_execution_prompt


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


if __name__ == "__main__":
    unittest.main()
