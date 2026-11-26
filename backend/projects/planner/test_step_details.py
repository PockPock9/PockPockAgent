"""The small actions under each plan step (owner request 2026-11-26)."""

import unittest

import app


class StepDetailsTests(unittest.TestCase):
    def test_details_are_aligned_with_the_steps_and_bounded(self):
        steps = ["Choose the design", "Write index.html", "Check the files"]
        raw = [["Use a warm theme", "  Pick   sections  "], "not a list", [123, "x" * 300, "a", "b", "c", "d", "e"]]
        details = app.normalized_step_details(raw, steps)
        self.assertEqual(len(details), 3)
        self.assertEqual(details[0], ["Use a warm theme", "Pick sections"])
        self.assertEqual(details[1], [])
        self.assertEqual(len(details[2]), app.MAX_STEP_DETAILS)
        self.assertEqual(len(details[2][0]), app.MAX_STEP_DETAIL_CHARS)
        self.assertEqual(app.normalized_step_details(None, steps), [[], [], []])

    def test_the_actions_are_added_to_the_run_instructions(self):
        prompt = app.with_step_details("Do the task.", ["Write index.html"], [["Write the header", "Link styles.css"]])
        self.assertIn("Planned actions for each step (follow them in order):\n1. Write index.html\n   - Write the header\n   - Link styles.css", prompt)
        self.assertEqual(app.with_step_details("Do the task.", ["Write index.html"], [[]]), "Do the task.")

    def test_the_plan_schema_allows_step_details(self):
        self.assertIn("step_details", app.PLAN_SCHEMA["properties"])
        self.assertNotIn("step_details", app.PLAN_SCHEMA["required"])


if __name__ == "__main__":
    unittest.main()
