import unittest

from projects.planner.replanning import ReplanningBudget, incomplete_success_checks


class ReplanningBudgetTests(unittest.TestCase):
    def test_first_failure_requests_revision_and_second_identical_failure_stops(self):
        state = ReplanningBudget()
        first = state.record(tool="search_public_site", arguments={"query": "x"}, status="error", error={"code": "provider_unavailable", "message": "offline"})
        second = state.record(tool="search_public_site", arguments={"query": "x"}, status="error", error={"code": "provider_unavailable", "message": "offline"})
        self.assertEqual(first["trigger"], "tool_unavailable")
        self.assertFalse(first["stop"])
        self.assertTrue(second["stop"])

    def test_successful_steps_are_reported_and_argument_change_is_distinct(self):
        state = ReplanningBudget()
        state.record(tool="read_project_file", arguments={"path": "a"}, status="success", error=None)
        revised = state.record(tool="read_project_file", arguments={"path": "b"}, status="error", error={"code": "tool_failed", "message": "failed"})
        self.assertEqual(revised["completed_steps"], ["read_project_file"])
        self.assertFalse(revised["stop"])

    def test_completion_requires_evidence_line_for_each_approved_check(self):
        checks = ["The page loads", "Validation passes"]
        self.assertEqual(incomplete_success_checks("[CHECK 1: PASS] Opened the page", checks), [checks[1]])
        self.assertEqual(incomplete_success_checks("[CHECK 1: PASS] Opened the page\n[CHECK 2: PASS] Validation returned valid=true", checks), [])

    def test_completion_accepts_bulleted_check_lines_with_explicit_evidence(self):
        checks = ["Summarize the page", "Cite the source"]
        answer = "- CHECK 1: PASS - Summary includes the purpose statement.\nCHECK 2: PASS - Linked the supplied source URL."
        self.assertEqual(incomplete_success_checks(answer, checks), [])

    def test_completion_accepts_evidence_check_appended_to_summary(self):
        answer = "The page explains its use for documentation examples. CHECK 1: PASS - The summary reflects visible page text."
        self.assertEqual(incomplete_success_checks(answer, ["Summarize the page"]), [])


if __name__ == "__main__":
    unittest.main()
