import os
import unittest
from unittest import mock

from projects.agent_tools.plan_progress import (
    PLAN_STEP_TOOL,
    plan_step_event,
    plan_step_reply,
    plan_step_reports_enabled,
    plan_step_tool_spec,
)

STEPS = ["Read the failing test", "Run it 20 times", "Find the race", "Fix it", "Run it again"]


class PlanStepEventTests(unittest.TestCase):
    def test_a_valid_step_becomes_an_event_with_its_label(self):
        self.assertEqual(
            plan_step_event({"step": 3}, STEPS),
            {"type": "plan_step", "step": 3, "total": 5, "label": "Find the race"},
        )

    def test_numbers_sent_as_text_or_whole_floats_are_accepted(self):
        self.assertEqual(plan_step_event({"step": " 2 "}, STEPS)["step"], 2)
        self.assertEqual(plan_step_event({"step": 4.0}, STEPS)["step"], 4)

    def test_out_of_range_and_malformed_steps_are_ignored(self):
        for arguments in ({"step": 0}, {"step": 6}, {"step": -1}, {"step": True}, {"step": 2.5},
                          {"step": "two"}, {}, None, "3", {"step": None}):
            self.assertIsNone(plan_step_event(arguments, STEPS), arguments)

    def test_long_labels_are_cut_and_whitespace_collapsed(self):
        event = plan_step_event({"step": 1}, ["Read\n\n" + "x" * 400, "Two"])
        self.assertLessEqual(len(event["label"]), 160)
        self.assertTrue(event["label"].startswith("Read x"))
        self.assertTrue(event["label"].endswith("…"))

    def test_replies_tell_the_model_to_carry_on(self):
        self.assertIn("step 3 of 5", plan_step_reply(plan_step_event({"step": 3}, STEPS), 5))
        self.assertIn("from 1 to 5", plan_step_reply(None, 5))


class PlanStepOfferTests(unittest.TestCase):
    def test_offered_only_for_multi_step_tool_runs_that_are_not_delegates(self):
        self.assertTrue(plan_step_reports_enabled(STEPS, delegated=False, has_tools=True))
        self.assertFalse(plan_step_reports_enabled(STEPS[:1], delegated=False, has_tools=True))
        self.assertFalse(plan_step_reports_enabled(STEPS, delegated=True, has_tools=True))
        self.assertFalse(plan_step_reports_enabled(STEPS, delegated=False, has_tools=False))

    def test_the_environment_switch_turns_it_off(self):
        with mock.patch.dict(os.environ, {"POCKPOCK_PLAN_STEP_REPORTS": "0"}):
            self.assertFalse(plan_step_reports_enabled(STEPS, delegated=False, has_tools=True))

    def test_the_schema_is_bounded_to_the_plan(self):
        spec = plan_step_tool_spec(5)
        self.assertEqual(spec["function"]["name"], PLAN_STEP_TOOL)
        step = spec["function"]["parameters"]["properties"]["step"]
        self.assertEqual((step["minimum"], step["maximum"]), (1, 5))
        self.assertFalse(spec["function"]["parameters"]["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
