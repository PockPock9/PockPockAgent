import unittest

from projects.agent_core.repeat_guard import MAX_REFUSALS, RepeatGuard, call_key
from projects.agent_core.executor import tool_call_budget


class RepeatGuardTests(unittest.TestCase):
    def test_a_third_identical_call_is_refused_with_guidance(self):
        guard = RepeatGuard()
        self.assertIsNone(guard.check("read_project_file", {"path": "a.py"}))
        self.assertIsNone(guard.check("read_project_file", {"path": "a.py"}))
        message = guard.check("read_project_file", {"path": "a.py"})
        self.assertIn("Not run", message)
        self.assertIn("read_project_file", message)
        self.assertFalse(guard.exhausted)

    def test_different_arguments_and_key_order(self):
        guard = RepeatGuard()
        for _ in range(2):
            self.assertIsNone(guard.check("search", {"q": "x", "limit": 3}))
        self.assertIsNotNone(guard.check("search", {"limit": 3, "q": "x"}), "argument order does not matter")
        self.assertIsNone(guard.check("search", {"q": "y", "limit": 3}))
        self.assertNotEqual(call_key("a", {"x": 1}), call_key("b", {"x": 1}))

    def test_a_write_resets_the_count_but_running_checks_does_not(self):
        guard = RepeatGuard()
        guard.check("read_project_file", {"path": "a.py"})
        guard.after_call("workspace_read")
        guard.check("read_project_file", {"path": "a.py"})
        guard.after_call("project_check_execution")  # validate_project changes nothing
        self.assertIsNotNone(guard.check("read_project_file", {"path": "a.py"}), "checks do not make a re-read new")
        guard.after_call("workspace_write")  # a file write in between
        self.assertIsNone(guard.check("read_project_file", {"path": "a.py"}))
        self.assertIsNone(guard.check("read_project_file", {"path": "a.py"}))

    def test_the_run_stops_after_repeated_refusals(self):
        guard = RepeatGuard()
        guard.check("t", {})
        guard.check("t", {})
        for _ in range(MAX_REFUSALS):
            self.assertIsNotNone(guard.check("t", {}))
        self.assertTrue(guard.exhausted)

    def test_the_tool_call_budget_grows_with_the_plan(self):
        self.assertEqual(tool_call_budget(0), 20)
        self.assertEqual(tool_call_budget(3), 20)
        self.assertEqual(tool_call_budget(6), 32)
        self.assertEqual(tool_call_budget(30), 48)

    def test_unserialisable_arguments_do_not_crash(self):
        guard = RepeatGuard()
        self.assertIsNone(guard.check("t", {"x": object()}))


if __name__ == "__main__":
    unittest.main()
