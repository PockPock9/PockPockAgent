"""Suite runner: executes tasks, verifies them, reports pass@1 / pass^k.

Metrics (report §4/§5 #7 — pass^k is the headline reliability metric,
because pass@1 flatters: τ-bench showed GPT-4o retail dropping from
60.4% pass@1 to ~25% at pass@8):

* ``pass@1`` — fraction of tasks whose *first* attempt verified.
* ``pass@k`` — fraction of tasks where *all* k attempts verified
  (k = 3 and 5 when that many attempts were run). A task that passes
  once in five tries scores 0 on pass@5: flaky is failing.
* ``steps/task``, ``tokens/task``, ``wall_seconds/task`` — means over
  all attempts, plus means over passing attempts.

Every run records the exact model, quantisation, seed, executor and
system-prompt hash, because harness swings of 25–55pp on the same
model are documented — an unlabelled number is not a measurement.

Each attempt runs in a fresh temporary workspace (setup files written
in, nothing shared between attempts), so repeats are independent.
Output per run: ``report.json`` (machine-readable) and ``report.md``
(short human summary) under the output directory.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .executors import DEFAULT_SYSTEM_PROMPT, ExecutorResult
from .tasks import EvalTask
from .verifiers import VerificationResult, verify_task

SUITE_VERSION = 1


@dataclass
class RunConfig:
    """Everything needed to reproduce one harness run."""

    model: str = "stub"
    quantisation: str = "n/a"
    seed: int = 0
    attempts: int = 1
    executor: str = "stub"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    include_network: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "quantisation": self.quantisation,
            "seed": self.seed,
            "attempts": self.attempts,
            "executor": self.executor,
            "system_prompt_sha256": hashlib.sha256(self.system_prompt.encode()).hexdigest()[:16],
            "include_network": self.include_network,
        }


@dataclass
class AttemptResult:
    task_id: str
    attempt: int
    passed: bool
    seed: int
    executor: ExecutorResult
    verification: VerificationResult
    skipped: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "attempt": self.attempt,
            "passed": self.passed,
            "seed": self.seed,
            "skipped": self.skipped,
            "steps": self.executor.steps,
            "tokens": self.executor.tokens,
            "wall_seconds": round(self.executor.wall_seconds, 3),
            "error": self.executor.error,
            "tool_calls": [
                {"tool": call["tool"], "arguments": call["arguments"]}
                for call in self.executor.tool_calls
            ],
            "verification": self.verification.to_dict(),
        }


@dataclass
class TaskResult:
    task_id: str
    title: str
    category: str
    attempts: list[AttemptResult] = field(default_factory=list)
    skipped: str | None = None

    @property
    def passed_attempts(self) -> int:
        return sum(1 for attempt in self.attempts if attempt.passed)

    def pass_k(self, k: int) -> bool | None:
        """True only if the first k attempts all passed; None if fewer ran."""
        if len(self.attempts) < k:
            return None
        return all(attempt.passed for attempt in self.attempts[:k])

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "category": self.category,
            "skipped": self.skipped,
            "passed_attempts": self.passed_attempts,
            "attempts_run": len(self.attempts),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }


@dataclass
class RunReport:
    config: RunConfig
    suite_name: str
    started_at: str
    tasks: list[TaskResult] = field(default_factory=list)

    # -- aggregates -----------------------------------------------------
    @property
    def ran_tasks(self) -> list[TaskResult]:
        return [task for task in self.tasks if task.skipped is None]

    @property
    def skipped_tasks(self) -> list[TaskResult]:
        return [task for task in self.tasks if task.skipped is not None]

    def pass_at_1(self) -> float | None:
        ran = self.ran_tasks
        if not ran:
            return None
        return sum(1 for task in ran if task.attempts and task.attempts[0].passed) / len(ran)

    def pass_at_k(self, k: int) -> float | None:
        ran = [task for task in self.ran_tasks if task.pass_k(k) is not None]
        if not ran:
            return None
        return sum(1 for task in ran if task.pass_k(k)) / len(ran)

    def _mean(self, values: list[float]) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    def summary(self) -> dict[str, Any]:
        attempts = [a for task in self.ran_tasks for a in task.attempts]
        passed_attempts = [a for a in attempts if a.passed]
        summary: dict[str, Any] = {
            "suite": self.suite_name,
            "tasks_total": len(self.tasks),
            "tasks_run": len(self.ran_tasks),
            "tasks_skipped": len(self.skipped_tasks),
            "pass@1": self.pass_at_1(),
            "attempts_per_task": self.config.attempts,
            "mean_steps_per_task": self._mean([float(a.executor.steps) for a in attempts]),
            "mean_tokens_per_task": self._mean([float(a.executor.tokens) for a in attempts]),
            "mean_wall_seconds_per_task": self._mean([a.executor.wall_seconds for a in attempts]),
            "mean_steps_per_pass": self._mean([float(a.executor.steps) for a in passed_attempts]),
            "mean_tokens_per_pass": self._mean([float(a.executor.tokens) for a in passed_attempts]),
        }
        for k in (3, 5):
            value = self.pass_at_k(k)
            if value is not None:
                summary[f"pass@{k}"] = value
        return summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_version": SUITE_VERSION,
            "started_at": self.started_at,
            "config": self.config.to_dict(),
            "summary": self.summary(),
            "tasks": [task.to_dict() for task in self.tasks],
        }


def _write_setup_files(task: EvalTask, workspace: Path) -> None:
    for relative, content in task.setup_files.items():
        target = workspace / relative
        if target.resolve().parent != workspace.resolve() and workspace.resolve() not in target.resolve().parents:
            raise ValueError(f"Setup path escapes the workspace: {relative!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def run_task(
    task: EvalTask,
    executor: Any,
    config: RunConfig,
    *,
    workspaces_root: Path,
) -> TaskResult:
    """Run one task ``config.attempts`` times; each attempt is independent."""
    result = TaskResult(task_id=task.id, title=task.title, category=task.category)
    if "network" in task.requires and not config.include_network:
        result.skipped = "requires network (rerun with --include-network)"
        return result
    for index in range(config.attempts):
        attempt_seed = config.seed + index
        attempt_dir = workspaces_root / task.id / f"attempt-{index + 1}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        _write_setup_files(task, attempt_dir)
        started = time.monotonic()
        try:
            executed = executor.run(
                task,
                attempt_dir,
                config.system_prompt,
                seed=attempt_seed,
                timeout_s=task.timeout_s,
            )
        except Exception as err:  # noqa: BLE001 - executor crash is a failed attempt
            executed = ExecutorResult(
                finished=False,
                steps=0,
                wall_seconds=time.monotonic() - started,
                error=f"{type(err).__name__}: {err}",
            )
        verification = verify_task(task, attempt_dir)
        result.attempts.append(AttemptResult(
            task_id=task.id,
            attempt=index + 1,
            passed=executed.finished and verification.passed,
            seed=attempt_seed,
            executor=executed,
            verification=verification,
        ))
    return result


def run_suite(
    tasks: Sequence[EvalTask],
    executor: Any,
    config: RunConfig,
    *,
    suite_name: str = "agent_eval",
    out_dir: Path | None = None,
    keep_workspaces: bool = False,
) -> RunReport:
    """Run a whole suite and, when ``out_dir`` is given, write reports."""
    report = RunReport(
        config=config,
        suite_name=suite_name,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    root = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="agent_eval_"))
    workspaces_root = root / "workspaces"
    workspaces_root.mkdir(parents=True, exist_ok=True)
    try:
        for task in tasks:
            report.tasks.append(run_task(task, executor, config, workspaces_root=workspaces_root))
    finally:
        if out_dir is None and not keep_workspaces:
            shutil.rmtree(root, ignore_errors=True)
    if out_dir is not None:
        write_reports(report, root)
    return report


def _format_metric(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def render_markdown(report: RunReport) -> str:
    """Short human summary of a run (the JSON holds the full detail)."""
    summary = report.summary()
    lines = [
        f"# Agent eval: {report.suite_name}",
        "",
        f"Run at {report.started_at} — executor `{report.config.executor}`, "
        f"model `{report.config.model}` ({report.config.quantisation}), "
        f"seed {report.config.seed}, {report.config.attempts} attempt(s) per task.",
        "",
        f"- Tasks: {summary['tasks_run']} run, {summary['tasks_skipped']} skipped, "
        f"{summary['tasks_total']} total",
        f"- pass@1: {_format_metric(summary['pass@1'])}",
    ]
    for k in (3, 5):
        if f"pass@{k}" in summary:
            lines.append(f"- pass@{k}: {_format_metric(summary[f'pass@{k}'])}")
    lines += [
        f"- Mean steps/task: {summary['mean_steps_per_task']}",
        f"- Mean tokens/task: {summary['mean_tokens_per_task']}",
        f"- Mean wall time/task: {summary['mean_wall_seconds_per_task']}s",
        "",
        "| Task | Category | Attempts passed |",
        "| --- | --- | ---: |",
    ]
    for task in report.tasks:
        if task.skipped is not None:
            lines.append(f"| {task.task_id} | {task.category} | skipped: {task.skipped} |")
        else:
            lines.append(
                f"| {task.task_id} | {task.category} | "
                f"{task.passed_attempts}/{len(task.attempts)} |"
            )
    failed = [
        task.task_id for task in report.ran_tasks
        if task.attempts and not task.attempts[0].passed
    ]
    if failed:
        lines += ["", "## First-attempt failures", ""]
        for task in report.ran_tasks:
            if task.task_id not in failed:
                continue
            attempt = task.attempts[0]
            failed_checks = [
                check.detail for check in attempt.verification.checks if not check.passed
            ]
            lines.append(
                f"- **{task.task_id}**: {attempt.executor.error or '; '.join(failed_checks) or 'no detail'}"
            )
    lines.append("")
    return "\n".join(lines)


def write_reports(report: RunReport, out_dir: Path) -> tuple[Path, Path]:
    """Write ``report.json`` and ``report.md``; return their paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    md_path = out_dir / "report.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def load_report(path: str | Path) -> dict[str, Any]:
    """Load a ``report.json`` written by :func:`write_reports`."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
