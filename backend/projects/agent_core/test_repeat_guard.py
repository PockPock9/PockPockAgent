import unittest

from projects.agent_core.repeat_guard import MAX_REFUSALS, RepeatGuard, call_key


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

    def test_a_call_that_may_change_state_resets_the_count(self):
        guard = RepeatGuard()
        guard.check("read_project_file", {"path": "a.py"})
        guard.after_call("read")
        guard.check("read_project_file", {"path": "a.py"})
        guard.after_call("high")  # for example a file write in between
        self.assertIsNone(guard.check("read_project_file", {"path": "a.py"}))
        self.assertIsNone(guard.check("read_project_file", {"path": "a.py"}))

    def test_the_run_stops_after_repeated_refusals(self):
        guard = RepeatGuard()
        guard.check("t", {})
        guard.check("t", {})
        for _ in range(MAX_REFUSALS):
            self.assertIsNotNone(guard.check("t", {}))
        self.assertTrue(guard.exhausted)

    def test_unserialisable_arguments_do_not_crash(self):
        guard = RepeatGuard()
        self.assertIsNone(guard.check("t", {"x": object()}))


if __name__ == "__main__":
    unittest.main()
