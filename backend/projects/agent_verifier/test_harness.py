import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "projects"))

from agent_verifier.harness import Harness, RunLimits, StepResult, failure_signature
from agent_verifier.ledger import Ledger

PLAN = [{"title": "Write the file"}, {"title": "Add the answer"}]
SPEC = {"verifiers": [
    {"name": "expected_files", "files": ["result.txt"]},
    {"name": "expected_content", "checks": [{"file": "result.txt", "contains": "42"}]},
]}


def _executor_factory(workspace: Path, *, fail_first: dict[int, int] | None = None,
                      claim_done: bool = False, write_wrong: bool = False):
    """Deterministic executor: writes result.txt; optionally fails a step N times."""
    calls: dict[int, int] = {}

    def executor(step, capsule, context):
        index = step["step_index"]
        calls[index] = calls.get(index, 0) + 1
        if fail_first and calls[index] <= fail_first.get(index, 0):
            return StepResult(status="failed", summary="boom",
                              error={"code": "write_failed", "message": "disk full (simulated)"},
                              tool_calls=[{"tool": "write_file", "status": "error"}])
        if index == 0:
            (workspace / "result.txt").write_text("the answer is 42\n", encoding="utf-8")
        elif index == 1:
            (workspace / "result.txt").write_text(
                "the answer is 0\n" if write_wrong else "the answer is 42\n", encoding="utf-8")
        return StepResult(
            status="success", summary=f"step {index} done",
            tool_calls=[{"tool": "write_file", "status": "success"}],
            files_changed=["result.txt"],
            claimed_done=claim_done and index == 1,
        )

    executor.calls = calls
    return executor


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name) / "work"
        self.work.mkdir()
        self.ledger = Ledger(Path(self._tmp.name) / "ledger.sqlite3")
        self.harness = Harness(self.ledger)

    def tearDown(self):
        self._tmp.cleanup()

    def test_verified_run_completes_only_after_a_verifier_pass(self):
        run_id = self.harness.start_run("Produce the answer", PLAN, requirements=["result.txt contains 42"])
        outcome = self.harness.execute_run(run_id, _executor_factory(self.work),
                                           workspace=self.work, verifier_spec=SPEC)
        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(outcome["verdict"]["verdict"], "pass")
        self.assertEqual(self.ledger.get_run(run_id)["status"], "completed")
        self.assertEqual((self.work / "result.txt").read_text(), "the answer is 42\n")

    def test_model_claimed_done_but_verifier_failed_is_recorded_failed(self):
        run_id = self.harness.start_run("Produce the answer", PLAN, requirements=["result.txt contains 42"])
        outcome = self.harness.execute_run(
            run_id, _executor_factory(self.work, claim_done=True, write_wrong=True),
            workspace=self.work, verifier_spec=SPEC)
        self.assertEqual(outcome["status"], "failed")
        self.assertTrue(outcome["claimed_done"])
        self.assertEqual(outcome["verdict"]["verdict"], "fail")
        self.assertEqual(outcome["verdict"]["failed_check"], "expected_content")
        run = self.ledger.get_run(run_id)
        self.assertEqual(run["status"], "failed")
        events = self.ledger.get_events(run_id)
        self.assertTrue(any(e["event_type"] == "failed" and
                            e["payload"].get("model_claimed_done_but_verifier_failed") for e in events))

    def test_kill_simulation_resume_finishes_from_the_ledger(self):
        run_id = self.harness.start_run("Produce the answer", PLAN, requirements=["result.txt contains 42"])
        # First attempt: execute step 0, then "die" mid-run (no finish call).
        executor = _executor_factory(self.work)
        # Drive only step 0 through the harness internals, then drop the objects.
        self.harness._run_step_once(
            run_id, {"step_index": 0, "title": "Write the file"}, self.work, executor, {})
        self.assertEqual((self.work / "result.txt").read_text(), "the answer is 42\n")
        # New process, same ledger file: resume must pick up at step 1, not re-plan.
        ledger2 = Ledger(Path(self._tmp.name) / "ledger.sqlite3")
        harness2 = Harness(ledger2)
        snapshot = harness2.resume_snapshot(run_id)
        self.assertEqual(snapshot["next_step"]["step_index"], 1)
        self.assertEqual(snapshot["capsule"]["goal"], "Produce the answer")
        outcome = harness2.resume_run(run_id, _executor_factory(self.work),
                                      workspace=self.work, verifier_spec=SPEC)
        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(ledger2.get_steps(run_id)[0]["attempts"], 1)  # step 0 was NOT re-run

    def test_resume_after_last_step_goes_straight_to_the_verifier_gate(self):
        run_id = self.harness.start_run("Produce the answer", PLAN, requirements=["result.txt contains 42"])
        executor = _executor_factory(self.work)
        for index in (0, 1):
            self.harness._run_step_once(run_id, {"step_index": index, "title": PLAN[index]["title"]},
                                        self.work, executor, {})
        outcome = Harness(Ledger(Path(self._tmp.name) / "ledger.sqlite3")).resume_run(
            run_id, _executor_factory(self.work), workspace=self.work, verifier_spec=SPEC)
        self.assertEqual(outcome["status"], "completed")

    def test_rewind_then_resume_reruns_from_step_n(self):
        run_id = self.harness.start_run("Produce the answer", PLAN, requirements=["result.txt contains 42"])
        outcome = self.harness.execute_run(run_id, _executor_factory(self.work, write_wrong=True),
                                           workspace=self.work, verifier_spec=SPEC)
        self.assertEqual(outcome["status"], "failed")  # step 1 overwrote the file with 0
        summary = self.harness.rewind_run(run_id, 1)
        self.assertEqual([f["path"] for f in summary["unrestored_files"]], [])
        # Re-running step 1 rewrites the file with the correct answer.
        outcome = self.harness.resume_run(run_id, _executor_factory(self.work),
                                          workspace=self.work, verifier_spec=SPEC)
        self.assertEqual(outcome["status"], "completed")

    def test_retry_failed_subtask_reruns_only_that_step_with_signature(self):
        run_id = self.harness.start_run("Produce the answer", PLAN, requirements=["result.txt contains 42"])
        executor = _executor_factory(self.work, fail_first={0: 1})
        # Drive step 0 to failure directly, then use the targeted retry.
        result, _ = self.harness._run_step_once(
            run_id, {"step_index": 0, "title": "Write the file"}, self.work, executor, {})
        self.assertEqual(result.status, "failed")
        seen: dict = {}

        def retry_executor(step, capsule, context):
            seen.update(context)
            return _executor_factory(self.work)(step, capsule, context)

        outcome = self.harness.retry_failed_subtask(run_id, 0, retry_executor, workspace=self.work)
        self.assertEqual(outcome["status"], "success")
        self.assertEqual(seen.get("failure_signature", {}).get("kind"), "write_failed")
        self.assertTrue(seen.get("retry_only"))
        self.assertEqual(self.ledger.get_step(run_id, 0)["status"], "success")

    def test_retry_inside_execute_uses_signature_and_bounded_retries(self):
        run_id = self.harness.start_run("Produce the answer", PLAN, requirements=["result.txt contains 42"],
                                        limits=RunLimits(max_retries=1))
        executor = _executor_factory(self.work, fail_first={0: 1})
        outcome = self.harness.execute_run(run_id, executor, workspace=self.work, verifier_spec=SPEC)
        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(executor.calls[0], 2)  # one failure + one retry of the same step

    def test_identical_failure_stops_instead_of_looping(self):
        run_id = self.harness.start_run("Produce the answer", PLAN, requirements=["result.txt contains 42"],
                                        limits=RunLimits(max_retries=5))
        executor = _executor_factory(self.work, fail_first={0: 99})
        outcome = self.harness.execute_run(run_id, executor, workspace=self.work, verifier_spec=SPEC)
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["reason"], "identical_failure")
        self.assertEqual(executor.calls[0], 2)  # MAX_IDENTICAL_FAILURES

    def test_max_steps_is_enforced_by_the_harness(self):
        plan = [{"title": f"Step {i}"} for i in range(5)]

        def looping(step, capsule, context):
            return StepResult(status="success", summary="ok",
                              tool_calls=[{"tool": "noop", "status": "success"}])

        run_id = self.harness.start_run("Loop forever", plan, limits=RunLimits(max_steps=2))
        outcome = self.harness.execute_run(run_id, looping, workspace=self.work, verifier_spec=SPEC)
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["reason"], "max_steps")

    def test_zero_tool_success_is_a_failure_not_a_silent_pass(self):
        def empty(step, capsule, context):
            return StepResult(status="success", summary="")

        run_id = self.harness.start_run("Produce the answer", PLAN, requirements=["result.txt contains 42"])
        outcome = self.harness.execute_run(run_id, empty, workspace=self.work, verifier_spec=SPEC)
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["reason"], "identical_failure")  # same signature twice
        self.assertEqual(self.ledger.get_step(run_id, 0)["error"]["code"], "executor_no_tools")

    def test_replan_hook_replaces_the_remaining_plan(self):
        def replanner(snapshot, signature):
            self.assertEqual(signature["kind"], "write_failed")
            self.assertIn("steps", snapshot)
            return [{"title": "Write the file differently"}, {"title": "Add the answer"}]

        run_id = self.harness.start_run("Produce the answer", PLAN, requirements=["result.txt contains 42"],
                                        limits=RunLimits(max_retries=0))
        executor = _executor_factory(self.work, fail_first={0: 1})
        outcome = self.harness.execute_run(run_id, executor, workspace=self.work,
                                           verifier_spec=SPEC, replan_fn=replanner)
        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(self.ledger.get_run(run_id)["plan"][0]["title"], "Write the file differently")
        self.assertTrue(any(e["event_type"] == "replanned" for e in self.ledger.get_events(run_id)))

    def test_failure_signature_is_stable(self):
        first = failure_signature(kind="write_failed", step_index=0, detail="disk full")
        second = failure_signature(kind="write_failed", step_index=0, detail="disk full")
        third = failure_signature(kind="write_failed", step_index=0, detail="other error")
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertNotEqual(first["fingerprint"], third["fingerprint"])


if __name__ == "__main__":
    unittest.main()
