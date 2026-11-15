import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "projects"))

from planner.evaluation import DEFAULT_ROUTING_PROFILES, evaluate_routing
from planner.routing import choose_candidate, required_context_tokens, task_capability


class RoutingEvaluationTests(unittest.TestCase):
    profiles = list(DEFAULT_ROUTING_PROFILES)

    def test_fixed_privacy_safe_routing_suite(self):
        report = evaluate_routing(self.profiles)

        self.assertEqual(report.suite, "local-routing-v1")
        self.assertEqual(report.case_count, 3)
        self.assertEqual(report.passed, report.case_count)
        self.assertEqual(report.accuracy, 1.0)
        self.assertTrue(all(result.passed for result in report.results))
        self.assertNotIn("task", report.results[0].__dict__)

    def test_incompatible_context_and_tool_models_are_excluded(self):
        profiles = [
            {"name": "too-small", "capabilities": ["tools"], "context_window": 4096, "avg_latency_ms": 10},
            {"name": "no-tools", "capabilities": ["completion"], "context_window": 65536, "avg_latency_ms": 1},
            {"name": "unknown-context", "capabilities": ["tools"], "context_window": None, "avg_latency_ms": 600},
        ]
        self.assertEqual(choose_candidate(profiles, task="Build an app", preferred=None, fallback="missing")[0], "unknown-context")

    def test_context_budget_and_task_classification_are_bounded(self):
        self.assertGreaterEqual(required_context_tokens("x" * 20_000), 8192)
        self.assertEqual(required_context_tokens("x" * 1_000_000), 32768)
        self.assertEqual(task_capability("Fix this website"), "workspace")
        self.assertEqual(task_capability("Research API documentation"), "research")


class SmallModelRankingTests(unittest.TestCase):
    def test_tiny_models_are_skipped_when_a_larger_one_is_enabled(self):
        profiles = [
            {"name": "qwen2.5:1.5b", "capabilities": ["tools"], "context_window": 32768, "avg_latency_ms": 900, "parameter_billions": 1.5},
            {"name": "qwen3.5:9b", "capabilities": ["tools"], "context_window": 65536, "avg_latency_ms": 9000, "parameter_billions": 9.7},
        ]
        self.assertEqual(choose_candidate(profiles, task="Create a file", preferred=None, fallback="missing")[0], "qwen3.5:9b")
        self.assertEqual(choose_candidate(profiles[:1], task="Create a file", preferred=None, fallback="missing")[0], "qwen2.5:1.5b")
        self.assertEqual(choose_candidate(profiles, task="Create a file", preferred="qwen2.5:1.5b", fallback="missing")[0], "qwen2.5:1.5b")


if __name__ == "__main__":
    unittest.main()
