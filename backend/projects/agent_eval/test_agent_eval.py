"""Tests for the agent eval harness (Phase 1: eval + prompt optimisation + LoRA hooks).

Unit tests are deterministic and model-free: the stub executor runs
reference solutions through the real tools, and the fake providers /
executors below stand in for the live model. Live-model behaviour is
covered by running backend/scripts/run_agent_eval.py, not by this file.
"""

import json
import tempfile
import unittest
from pathlib import Path

from projects.agent_eval import (
    DEFAULT_SYSTEM_PROMPT,
    OllamaExecutor,
    RunConfig,
    StubExecutor,
    export_traces_from_report,
    load_suite,
    split_suite,
)
from projects.agent_eval.executors import ExecutorResult, estimate_tokens
from projects.agent_eval.optimizer import candidate_pool, mutate_prompt, optimize
from projects.agent_eval.runner import run_suite
from projects.agent_eval.tasks import EvalTask
from projects.agent_eval.traces import normalise_transcript, trace_record
from projects.agent_eval.verifiers import run_check, verify_task

SUITE_PATH = Path(__file__).resolve().parent / "suite.json"


def _task(**overrides) -> EvalTask:
    values = {
        "id": "test-task",
        "prompt": "Save hello.txt containing Hello.",
        "verifiers": [{"kind": "file_contains", "path": "hello.txt", "contains": ["Hello"]}],
        "stub_actions": [
            {"tool": "save_text_artifact",
             "arguments": {"filename": "hello.txt", "content": "Hello\n"}}
        ],
    }
    values.update(overrides)
    return EvalTask(**values)


class TaskLoadingTests(unittest.TestCase):
    def test_seed_suite_loads_with_unique_ids(self):
        tasks = load_suite(SUITE_PATH)
        self.assertGreaterEqual(len(tasks), 15)
        self.assertEqual(len({task.id for task in tasks}), len(tasks))
        categories = {task.category for task in tasks}
        for expected in ("artifact", "code", "terminal", "multiturn"):
            self.assertIn(expected, categories)

    def test_seed_suite_has_network_tasks_flagged(self):
        tasks = load_suite(SUITE_PATH)
        network = [task for task in tasks if "network" in task.requires]
        self.assertGreaterEqual(len(network), 1)
        self.assertTrue(all(task.requires == ["network"] for task in network))

    def test_load_rejects_missing_verifiers_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps([{"id": "x", "prompt": "y"}]), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_suite(bad)
            dup = Path(tmp) / "dup.json"
            dup.write_text(json.dumps([_task().to_dict(), _task().to_dict()]), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_suite(dup)

    def test_split_is_deterministic_and_disjoint(self):
        tasks = load_suite(SUITE_PATH)
        first_a, first_b = split_suite(tasks, train_size=12, seed=7)
        second_a, second_b = split_suite(tasks, train_size=12, seed=7)
        self.assertEqual([t.id for t in first_a], [t.id for t in second_a])
        self.assertEqual([t.id for t in first_b], [t.id for t in second_b])
        self.assertEqual(len(first_a), 12)
        self.assertFalse({t.id for t in first_a} & {t.id for t in first_b})


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_file_exists_contains_and_matches(self):
        (self.workspace / "a.txt").write_text("hello world 42\n", encoding="utf-8")
        self.assertTrue(run_check({"kind": "file_exists", "path": "a.txt"}, self.workspace).passed)
        self.assertFalse(run_check({"kind": "file_exists", "path": "nope.txt"}, self.workspace).passed)
        self.assertTrue(run_check(
            {"kind": "file_contains", "path": "a.txt", "contains": ["hello", "42"]},
            self.workspace).passed)
        self.assertFalse(run_check(
            {"kind": "file_contains", "path": "a.txt", "contains": ["goodbye"]},
            self.workspace).passed)
        self.assertTrue(run_check(
            {"kind": "file_not_contains", "path": "a.txt", "contains": ["goodbye"]},
            self.workspace).passed)
        self.assertTrue(run_check(
            {"kind": "file_matches", "path": "a.txt", "pattern": r"world\s+42"},
            self.workspace).passed)

    def test_file_json_schema_subset(self):
        (self.workspace / "s.json").write_text(
            '{"theme": "dark", "font_size": 14}', encoding="utf-8")
        schema = {"type": "object", "required": ["theme", "font_size"],
                  "properties": {"font_size": {"type": "integer", "minimum": 8}}}
        self.assertTrue(run_check(
            {"kind": "file_json", "path": "s.json", "schema": schema}, self.workspace).passed)
        bad_schema = {"type": "object", "required": ["missing_key"]}
        self.assertFalse(run_check(
            {"kind": "file_json", "path": "s.json", "schema": bad_schema}, self.workspace).passed)
        (self.workspace / "broken.json").write_text("{not json", encoding="utf-8")
        self.assertFalse(run_check(
            {"kind": "file_json", "path": "broken.json"}, self.workspace).passed)

    def test_command_verifier_runs_in_workspace(self):
        (self.workspace / "greet.py").write_text('print("Good morning")\n', encoding="utf-8")
        self.assertTrue(run_check(
            {"kind": "command", "command": ["{python}", "greet.py"],
             "expect_exit": 0, "stdout_contains": ["Good morning"]},
            self.workspace).passed)
        self.assertFalse(run_check(
            {"kind": "command", "command": ["{python}", "greet.py"],
             "expect_exit": 0, "stdout_contains": ["Good night"]},
            self.workspace).passed)
        self.assertFalse(run_check(
            {"kind": "command", "command": ["{python}", "missing.py"]},
            self.workspace).passed)

    def test_all_any_combinators_and_unknown_kind(self):
        (self.workspace / "a.txt").write_text("x", encoding="utf-8")
        self.assertTrue(run_check({"kind": "all", "checks": [
            {"kind": "file_exists", "path": "a.txt"},
            {"kind": "file_contains", "path": "a.txt", "contains": ["x"]},
        ]}, self.workspace).passed)
        self.assertFalse(run_check({"kind": "all", "checks": [
            {"kind": "file_exists", "path": "a.txt"},
            {"kind": "file_exists", "path": "missing.txt"},
        ]}, self.workspace).passed)
        self.assertTrue(run_check({"kind": "any", "checks": [
            {"kind": "file_exists", "path": "missing.txt"},
            {"kind": "file_exists", "path": "a.txt"},
        ]}, self.workspace).passed)
        self.assertFalse(run_check({"kind": "nope"}, self.workspace).passed)

    def test_verifier_path_cannot_escape_workspace(self):
        result = run_check({"kind": "file_exists", "path": "../secret.txt"}, self.workspace)
        self.assertFalse(result.passed)


class StubExecutorTests(unittest.TestCase):
    def test_stub_runs_reference_solution_through_real_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = StubExecutor().run(_task(), Path(tmp), DEFAULT_SYSTEM_PROMPT)
            self.assertTrue(result.finished)
            self.assertIsNone(result.error)
            self.assertEqual(result.steps, 1)
            self.assertEqual(result.tool_calls[0]["tool"], "save_text_artifact")
            self.assertEqual((Path(tmp) / "hello.txt").read_text(encoding="utf-8"), "Hello\n")

    def test_stub_applies_staged_project_patches(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = _task(
                id="patch-task",
                prompt="Write greet.py that prints 'Good morning'.",
                verifiers=[{"kind": "command", "command": ["{python}", "greet.py"],
                            "expect_exit": 0, "stdout_contains": ["Good morning"]}],
                stub_actions=[{"tool": "propose_project_patch", "arguments": {
                    "path": "greet.py", "content": 'print("Good morning")\n',
                    "summary": "Add greet.py"}}],
            )
            result = StubExecutor().run(task, Path(tmp), DEFAULT_SYSTEM_PROMPT)
            self.assertTrue(result.finished, result.error)
            self.assertTrue((Path(tmp) / "greet.py").exists())
            self.assertTrue(verify_task(task, Path(tmp)).passed)

    def test_stub_failure_is_a_result_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = _task(stub_actions=[{"tool": "save_text_artifact", "arguments": {
                "filename": "bad/name.txt", "content": "x"}}])
            result = StubExecutor().run(task, Path(tmp), DEFAULT_SYSTEM_PROMPT)
            self.assertFalse(result.finished)
            self.assertIsNotNone(result.error)


class FakeProvider:
    """Canned Ollama-shaped provider: first call emits one tool call, then a final answer."""

    def __init__(self, tool_name: str, arguments: dict):
        self.tool_name = tool_name
        self.arguments = arguments
        self.calls = 0

    async def complete(self, request, *, timeout):  # noqa: ANN001, ANN202
        self.calls += 1
        if self.calls == 1:
            return {"choices": [{"message": {
                "content": "",
                "tool_calls": [{"id": "call_0", "type": "function", "function": {
                    "name": self.tool_name,
                    "arguments": json.dumps(self.arguments),
                }}],
            }}], "usage": {"total_tokens": 120}}
        return {"choices": [{"message": {"content": "Done.", "tool_calls": []}}],
                "usage": {"total_tokens": 30}}

    def stream_tokens(self, request, *, timeout):  # noqa: ANN001, ANN202
        raise NotImplementedError


class OllamaExecutorTests(unittest.TestCase):
    def test_live_loop_calls_tool_then_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeProvider("save_text_artifact", {
                "filename": "hello.txt", "content": "Hello\n"})
            executor = OllamaExecutor(provider, model="fake-model", max_steps=4)
            result = executor.run(_task(), Path(tmp), DEFAULT_SYSTEM_PROMPT, seed=0)
            self.assertTrue(result.finished, result.error)
            self.assertEqual(result.steps, 1)
            self.assertEqual(result.tokens, 150)
            self.assertEqual((Path(tmp) / "hello.txt").read_text(encoding="utf-8"), "Hello\n")
            self.assertTrue(verify_task(_task(), Path(tmp)).passed)

    def test_live_loop_records_provider_errors(self):
        class FailingProvider(FakeProvider):
            async def complete(self, request, *, timeout):  # noqa: ANN001, ANN202
                raise RuntimeError("model unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            executor = OllamaExecutor(FailingProvider("save_text_artifact", {}),
                                      model="fake-model", max_steps=2)
            result = executor.run(_task(), Path(tmp), DEFAULT_SYSTEM_PROMPT)
            self.assertFalse(result.finished)
            self.assertIn("unavailable", result.error or "")


class RunnerTests(unittest.TestCase):
    def test_stub_suite_passes_offline_tasks_with_pass_k(self):
        tasks = [task for task in load_suite(SUITE_PATH) if "network" not in task.requires]
        config = RunConfig(model="stub", executor="stub", attempts=3)
        with tempfile.TemporaryDirectory() as tmp:
            report = run_suite(tasks, StubExecutor(), config,
                               suite_name="test", out_dir=Path(tmp))
            summary = report.summary()
            self.assertEqual(summary["tasks_run"], len(tasks))
            self.assertEqual(summary["tasks_skipped"], 0)
            self.assertEqual(summary["pass@1"], 1.0)
            self.assertEqual(summary["pass@3"], 1.0)
            self.assertTrue((Path(tmp) / "report.json").exists())
            self.assertTrue((Path(tmp) / "report.md").exists())
            stored = json.loads((Path(tmp) / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["config"]["model"], "stub")
            self.assertEqual(stored["config"]["seed"], 0)

    def test_network_tasks_skipped_by_default_and_counted(self):
        tasks = load_suite(SUITE_PATH)
        config = RunConfig(model="stub", executor="stub", attempts=1)
        with tempfile.TemporaryDirectory() as tmp:
            report = run_suite(tasks, StubExecutor(), config,
                               suite_name="test", out_dir=Path(tmp))
            self.assertEqual(report.summary()["tasks_skipped"], 2)
            self.assertEqual(report.summary()["tasks_run"], len(tasks) - 2)

    def test_failing_task_scores_zero_on_pass_k(self):
        task = _task(stub_actions=[])  # reference solution does nothing: file never appears
        config = RunConfig(model="stub", executor="stub", attempts=3)
        report = run_suite([task], StubExecutor(), config, suite_name="test")
        self.assertEqual(report.summary()["pass@1"], 0.0)
        self.assertEqual(report.summary()["pass@3"], 0.0)
        self.assertEqual(report.tasks[0].passed_attempts, 0)

    def test_flaky_task_passes_once_but_fails_pass_k(self):
        # An executor that only succeeds on odd attempts: pass@1 yes, pass@3 no.
        class FlakyExecutor:
            name = "flaky"

            def __init__(self):
                self.seen = 0

            def run(self, task, workspace, system_prompt, *, seed=0, timeout_s=120):  # noqa: ANN001, ANN202
                self.seen += 1
                if self.seen % 2 == 1:
                    (Path(workspace) / "hello.txt").write_text("Hello\n", encoding="utf-8")
                return ExecutorResult(finished=True, steps=1, tokens=10, wall_seconds=0.01)

        config = RunConfig(model="stub", executor="flaky", attempts=3, seed=0)
        report = run_suite([_task()], FlakyExecutor(), config, suite_name="test")
        self.assertEqual(report.summary()["pass@1"], 1.0)
        self.assertEqual(report.summary()["pass@3"], 0.0)


class OptimizerTests(unittest.TestCase):
    def test_candidate_pool_and_mutation_are_deterministic(self):
        import random

        pool = candidate_pool()
        self.assertEqual(len(pool), 5)
        self.assertTrue(all(item["prompt"] for item in pool))
        self.assertEqual(
            mutate_prompt(DEFAULT_SYSTEM_PROMPT, random.Random(3)),
            mutate_prompt(DEFAULT_SYSTEM_PROMPT, random.Random(3)),
        )
        self.assertNotEqual(mutate_prompt(DEFAULT_SYSTEM_PROMPT, random.Random(3)),
                            DEFAULT_SYSTEM_PROMPT)

    def test_dry_run_scores_without_model_calls(self):
        tasks = load_suite(SUITE_PATH)[:6]
        result = optimize(tasks, lambda: None, RunConfig(), train_size=4,
                          mutations=2, seed=1, dry_run=True)
        self.assertTrue(result.best.prompt)
        self.assertIsNotNone(result.held_out)
        self.assertEqual(len(result.evaluations), 5 + 2 + 1)

    def test_live_selection_prefers_the_prompt_that_actually_works(self):
        # Fake executor: only prompts containing "verify" produce the file.
        class PromptSensitiveExecutor:
            name = "prompt-sensitive"

            def run(self, task, workspace, system_prompt, *, seed=0, timeout_s=120):  # noqa: ANN001, ANN202
                if "verify" in system_prompt.lower():
                    (Path(workspace) / "hello.txt").write_text("Hello\n", encoding="utf-8")
                transcript = [{"role": "system", "content": system_prompt},
                              {"role": "user", "content": task.prompt}]
                return ExecutorResult(finished=True, steps=1, tokens=estimate_tokens(system_prompt),
                                      transcript=transcript)

        tasks = [_task() for _ in range(4)]
        result = optimize(
            tasks, PromptSensitiveExecutor, RunConfig(),
            candidates=[
                {"name": "plain", "prompt": "Do the task.", "source": "pool"},
                {"name": "verify", "prompt": "Do the task and verify the result.", "source": "pool"},
            ],
            train_size=2, mutations=0, seed=0,
        )
        self.assertEqual(result.best.name, "verify")
        self.assertEqual(result.best.pass_at_1, 1.0)
        self.assertEqual(result.held_out.pass_at_1, 1.0)


class TraceTests(unittest.TestCase):
    def test_trace_record_requires_tool_call_and_user_message(self):
        record = trace_record(
            task_id="t1", model="qwen3.5:2b", quantisation="Q4_K_M", seed=0,
            transcript=[
                {"role": "system", "content": "Behave."},
                {"role": "user", "content": "Save hello.txt."},
                {"role": "assistant",
                 "tool_calls": [{"name": "save_text_artifact",
                                 "arguments": {"filename": "hello.txt", "content": "Hello"}}]},
                {"role": "tool", "name": "save_text_artifact",
                 "content": '{"saved": true, "name": "hello.txt"}'},
            ],
            outcome={"steps": 1, "tokens": 100, "wall_seconds": 0.5},
        )
        self.assertIsNotNone(record)
        self.assertTrue(record["verified"])
        self.assertEqual(record["schema_version"], 1)
        assistant = [m for m in record["messages"] if m["role"] == "assistant"][0]
        self.assertEqual(assistant["tool_calls"][0]["function"]["name"], "save_text_artifact")
        self.assertIsInstance(assistant["tool_calls"][0]["function"]["arguments"], str)
        self.assertIsNone(trace_record(
            task_id="t1", model="m", quantisation="q", seed=0,
            transcript=[{"role": "user", "content": "hi"},
                        {"role": "assistant", "content": "hello"}],
            outcome={}))

    def test_export_only_verified_passing_tool_traces(self):
        config = RunConfig(model="stub", executor="stub", attempts=1)
        with tempfile.TemporaryDirectory() as tmp:
            report = run_suite([_task()], StubExecutor(), config, suite_name="test")
            counts = export_traces_from_report(report, Path(tmp) / "traces.jsonl")
            self.assertEqual(counts, {"attempts": 1, "exported": 1, "skipped": 0})
            lines = (Path(tmp) / "traces.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["task_id"], "test-task")
            self.assertTrue(all("thinking" not in json.dumps(m).lower()
                                for m in record["messages"]))

    def test_normalise_transcript_caps_long_tool_results(self):
        messages = normalise_transcript([
            {"role": "tool", "name": "x", "content": "y" * 10_000},
        ])
        self.assertEqual(len(messages[0]["content"]), 4000)


if __name__ == "__main__":
    unittest.main()
