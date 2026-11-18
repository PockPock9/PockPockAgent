import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from projects.plan_sequence.routing import (
    DEFAULT_EXECUTOR_MODEL,
    DEFAULT_PLANNER_MODEL,
    SIMPLE_EXECUTOR_MODEL,
    choose_executor_model,
    choose_planner_model,
)


def _profile(name, billions, tools=True):
    return {
        "name": name,
        "capabilities": ["tools"] if tools else ["completion"],
        "parameter_billions": billions,
    }


class ChoosePlannerModelTests(unittest.TestCase):
    def test_preferred_wins_when_installed(self):
        model, reason = choose_planner_model(
            {"qwen3.5:9b", DEFAULT_PLANNER_MODEL}, preferred="qwen3.5:9b"
        )
        self.assertEqual(model, "qwen3.5:9b")
        self.assertIn("explicitly requested", reason)

    def test_preferred_cloud_model_wins_without_install(self):
        model, reason = choose_planner_model(
            {"qwen3.5:9b"}, preferred="anthropic/claude-opus-4-6",
            cloud_model="anthropic/claude-opus-4-6",
        )
        self.assertEqual(model, "anthropic/claude-opus-4-6")
        self.assertIn("cloud", reason)

    def test_unavailable_preferred_falls_through_to_default(self):
        model, _ = choose_planner_model(
            {DEFAULT_PLANNER_MODEL}, preferred="not-installed"
        )
        self.assertEqual(model, DEFAULT_PLANNER_MODEL)

    def test_env_model_wins_when_installed(self):
        with mock.patch.dict(os.environ, {"POCKPOCK_PLAN_SEQUENCE_PLANNER_MODEL": "qwen3.5:9b"}):
            model, reason = choose_planner_model({"qwen3.5:9b", DEFAULT_PLANNER_MODEL})
        self.assertEqual(model, "qwen3.5:9b")
        self.assertIn("POCKPOCK_PLAN_SEQUENCE_PLANNER_MODEL", reason)

    def test_env_model_ignored_when_not_installed(self):
        with mock.patch.dict(os.environ, {"POCKPOCK_PLAN_SEQUENCE_PLANNER_MODEL": "not-installed"}):
            model, _ = choose_planner_model({DEFAULT_PLANNER_MODEL})
        self.assertEqual(model, DEFAULT_PLANNER_MODEL)

    def test_default_planner_model_is_the_verified_tag(self):
        self.assertEqual(DEFAULT_PLANNER_MODEL, "qwen3.6:35b-a3b")

    def test_gateway_default_model_used_as_fallback(self):
        model, reason = choose_planner_model(
            {"qwen3.5:9b"}, fallback="qwen3.5:9b"
        )
        self.assertEqual(model, "qwen3.5:9b")
        self.assertIn("gateway's configured default", reason)

    def test_fallback_is_largest_tool_capable_model(self):
        profiles = [
            _profile("qwen3.5:2b", 2.0),
            _profile("qwen3.5:9b", 9.7),
            _profile("big-no-tools", 70.0, tools=False),
        ]
        model, reason = choose_planner_model(
            {"qwen3.5:2b", "qwen3.5:9b", "big-no-tools"}, profiles=profiles
        )
        self.assertEqual(model, "qwen3.5:9b")
        self.assertIn("largest", reason)

    def test_no_model_available_raises(self):
        with self.assertRaisesRegex(ValueError, "No model available for planning"):
            choose_planner_model(set())
        profiles = [_profile("only-model", 9.0, tools=False)]
        with self.assertRaisesRegex(ValueError, "No model available for planning"):
            choose_planner_model({"only-model"}, profiles=profiles)


class ChooseExecutorModelTests(unittest.TestCase):
    def test_simple_step_prefers_small_model(self):
        model, reason = choose_executor_model(
            {"qwen3.5:2b", DEFAULT_EXECUTOR_MODEL}, step_complexity="simple"
        )
        self.assertEqual(model, SIMPLE_EXECUTOR_MODEL)
        self.assertEqual(model, "qwen3.5:2b")
        self.assertIn("simple", reason)

    def test_simple_step_falls_back_to_default_executor(self):
        model, _ = choose_executor_model(
            {DEFAULT_EXECUTOR_MODEL}, step_complexity="simple"
        )
        self.assertEqual(model, DEFAULT_EXECUTOR_MODEL)

    def test_standard_step_prefers_default_executor(self):
        model, reason = choose_executor_model(
            {"qwen3.5:2b", DEFAULT_EXECUTOR_MODEL}, step_complexity="standard"
        )
        self.assertEqual(model, DEFAULT_EXECUTOR_MODEL)
        self.assertEqual(model, "qwen3.5:9b")

    def test_standard_fallback_is_smallest_tool_capable_model_at_or_above_2b(self):
        profiles = [
            _profile("qwen3.5:2b", 2.0),
            _profile("qwen3.5:4b", 4.0),
            _profile("qwen3.5:9b", 9.7),
            _profile("tiny", 1.5),
        ]
        model, reason = choose_executor_model(
            {"qwen3.5:2b", "qwen3.5:4b", "tiny"},
            step_complexity="standard",
            profiles=profiles,
        )
        self.assertEqual(model, "qwen3.5:2b")
        self.assertIn("smallest", reason)

    def test_models_below_2b_are_excluded_from_fallback(self):
        profiles = [_profile("tiny", 1.5)]
        with self.assertRaisesRegex(ValueError, "No model available for execution"):
            choose_executor_model({"tiny"}, step_complexity="standard", profiles=profiles)

    def test_env_model_wins_when_installed(self):
        with mock.patch.dict(os.environ, {"POCKPOCK_PLAN_SEQUENCE_EXECUTOR_MODEL": "qwen3.5:4b"}):
            model, reason = choose_executor_model(
                {"qwen3.5:4b", DEFAULT_EXECUTOR_MODEL}, step_complexity="standard"
            )
        self.assertEqual(model, "qwen3.5:4b")
        self.assertIn("POCKPOCK_PLAN_SEQUENCE_EXECUTOR_MODEL", reason)

    def test_no_model_available_raises(self):
        with self.assertRaisesRegex(ValueError, "No model available for execution"):
            choose_executor_model(set())

    def test_unknown_complexity_raises(self):
        with self.assertRaisesRegex(ValueError, "Unknown step complexity"):
            choose_executor_model({"qwen3.5:9b"}, step_complexity="hard")


if __name__ == "__main__":
    unittest.main()
