import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "projects"))

from agent_verifier.ledger import Ledger, LedgerError


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self._tmp.name) / "ledger.sqlite3")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, run_id="a" * 32, plan=None):
        return self.ledger.create_run(
            run_id, task="Do the thing", task_type="test",
            requirements=["The file exists"],
            plan=plan if plan is not None else [{"title": "Step one"}, {"title": "Step two"}],
        )

    def test_create_run_persists_plan_and_pending_steps(self):
        run = self._run()
        self.assertEqual(run["status"], "running")
        self.assertEqual(len(run["plan"]), 2)
        steps = self.ledger.get_steps("a" * 32)
        self.assertEqual([s["title"] for s in steps], ["Step one", "Step two"])
        self.assertTrue(all(s["status"] == "pending" for s in steps))

    def test_create_run_rejects_bad_id_and_duplicate(self):
        with self.assertRaises(LedgerError):
            self.ledger.create_run("not-hex", task="x")
        self._run()
        with self.assertRaises(LedgerError):
            self._run()

    def test_step_begin_is_written_before_execution_and_survives_reopen(self):
        self._run()
        step = self.ledger.append_step_begin("a" * 32, 0)
        self.assertEqual(step["status"], "running")
        self.assertEqual(step["attempts"], 1)
        # Simulate a process kill: a fresh Ledger on the same file sees the step.
        reopened = Ledger(Path(self._tmp.name) / "ledger.sqlite3")
        step = reopened.get_step("a" * 32, 0)
        self.assertEqual(step["status"], "running")
        self.assertEqual(reopened.next_unfinished_step("a" * 32)["step_index"], 0)

    def test_step_end_commits_outcome_capsule_and_diffs(self):
        self._run()
        self.ledger.append_step_begin("a" * 32, 0)
        from agent_verifier.capsule import StateCapsule
        capsule = StateCapsule(goal="Do the thing", step_index=0, next_step="Step two")
        self.ledger.record_tool_call("a" * 32, 0, tool="write_file", status="success")
        diff = self.ledger.record_file_diff("a" * 32, 0, path="out.txt", sha256_before="", sha256_after="f" * 64)
        self.assertTrue(diff["diff_hash"])
        step = self.ledger.append_step_end("a" * 32, 0, status="success",
                                           result={"summary": "done"}, capsule=capsule)
        self.assertEqual(step["status"], "success")
        self.assertEqual(step["tool_calls"][0]["tool"], "write_file")
        self.assertEqual(self.ledger.get_file_diffs("a" * 32)[0]["path"], "out.txt")
        self.assertEqual(self.ledger.get_run("a" * 32)["capsule"]["next_step"], "Step two")

    def test_successful_step_cannot_be_rerun_without_rewind(self):
        self._run()
        self.ledger.append_step_begin("a" * 32, 0)
        self.ledger.append_step_end("a" * 32, 0, status="success")
        with self.assertRaises(LedgerError):
            self.ledger.append_step_begin("a" * 32, 0)

    def test_verdicts_and_events_are_recorded(self):
        self._run()
        self.ledger.record_verdict("a" * 32, verifier="pytest", verdict="pass", evidence=["3 passed"])
        self.ledger.record_event("a" * 32, "resumed", {"next_step": 1})
        verdicts = self.ledger.get_verdicts("a" * 32)
        self.assertEqual(verdicts[0]["verifier"], "pytest")
        self.assertEqual(verdicts[0]["verdict"], "pass")
        events = self.ledger.get_events("a" * 32)
        self.assertEqual(events[-1]["event_type"], "resumed")
        with self.assertRaises(LedgerError):
            self.ledger.record_verdict("a" * 32, verifier="x", verdict="maybe")

    def test_list_runs_filters_by_status(self):
        self._run("a" * 32)
        self._run("b" * 32)
        self.ledger.set_status("b" * 32, "failed")
        self.assertEqual(len(self.ledger.list_runs()), 2)
        self.assertEqual([r["run_id"] for r in self.ledger.list_runs(status="failed")], ["b" * 32])

    def test_rewind_truncates_steps_and_flags_unrestored_files(self):
        self._run()
        for index in (0, 1):
            self.ledger.append_step_begin("a" * 32, index)
            self.ledger.record_file_diff("a" * 32, index, path=f"f{index}.txt",
                                         sha256_before="", sha256_after="a" * 64)
            self.ledger.append_step_end("a" * 32, index, status="success")
        summary = self.ledger.rewind("a" * 32, 0)
        self.assertEqual(summary["rewound_to_step"], 0)
        self.assertEqual([f["path"] for f in summary["unrestored_files"]], ["f1.txt"])
        self.assertIn("not snapshotted", summary["file_restore"])
        steps = self.ledger.get_steps("a" * 32)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["status"], "pending")
        # The diff rows past N are kept (flagged), not silently deleted.
        self.assertEqual(len(self.ledger.get_file_diffs("a" * 32)), 2)
        self.assertEqual(self.ledger.get_run("a" * 32)["status"], "running")

    def test_replace_plan_keeps_successful_steps(self):
        self._run()
        self.ledger.append_step_begin("a" * 32, 0)
        self.ledger.append_step_end("a" * 32, 0, status="success")
        self.ledger.replace_plan("a" * 32, [{"title": "Step one"}, {"title": "New step two"}])
        steps = self.ledger.get_steps("a" * 32)
        self.assertEqual(steps[0]["status"], "success")
        self.assertEqual(steps[1]["title"], "New step two")
        self.assertEqual(steps[1]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
