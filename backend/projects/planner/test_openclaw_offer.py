"""The planner offers OpenClaw steps only when the gateway says OpenClaw can run them."""

import unittest

import app


class OpenClawOfferTests(unittest.TestCase):
    def test_the_prompt_explains_openclaw_steps_only_when_offered(self):
        tools = ["read_project_file", "save_text_artifact"]
        without = app.build_sequence_plan_prompt("Build a Flutter app", tools, None, "full-access")
        offered = app.build_sequence_plan_prompt("Build a Flutter app", tools + [app.OPENCLAW_STEP_TOOL], None, "full-access", openclaw=True)
        self.assertNotIn("openclaw_agent hands", without)
        self.assertIn("openclaw_agent hands a whole step to the OpenClaw agent", offered)
        self.assertIn("Writing, reading and editing files never need it", offered)

    def test_the_request_defaults_to_no_openclaw(self):
        payload = app.SequencePlanRequest(task="x", capable_models=["m"], default_model="m")
        self.assertFalse(payload.openclaw_available)


if __name__ == "__main__":
    unittest.main()
