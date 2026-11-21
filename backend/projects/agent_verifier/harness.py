"""Verified-run harness: hard stops, resume, rewind, targeted retry, replan.

The harness — never the model — decides whether a run is done:

* ``done`` requires a verifier ``pass``. A run whose executor claims done
  but whose verifier fails is recorded as ``failed`` with the verifier
  evidence, not as success.
* Hard stops enforced here, not by the model: max steps, max retries per
  step, max identical failures, max replans, max wall time.
* Resume never requires a fresh full plan: it reloads the persisted plan +
  capsule from the ledger and continues at the first unfinished step.
* Retry re-runs ONLY the failed step, with the failure signature attached
  to the executor call — never a from-scratch retry.
* Re-planning re-invokes a planner hook with the ledger + failure signature.
  The live planner is a separate service; the hook is a callable so it stays
  testable with a deterministic stub on this VM.

Known-bug boundaries (do not "fix" them here; the harness works around them):
* Planner 111s timeout (issue #83 family): resume/replan must not depend on
  a fresh full plan — resume reuses the stored plan, and a replan failure
  leaves the run ``failed`` with the signature instead of hanging.
* Executor zero-tools bug (#92): a step whose executor returns no tool calls
  and no result is treated as a step failure with signature
  ``executor_no_tools`` so the retry/replan path engages instead of the run
  silently "succeeding".
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

try:  # package import (backend root on sys.path)
    from agent_verifier.capsule import ChangedFile, StateCapsule
    from agent_verifier.ledger import Ledger
    from agent_verifier.verifiers import Verdict, run_critic, run_verifiers
except ImportError:  # service-folder import (projects/ on sys.path)
    from capsule import ChangedFile, StateCapsule
    from ledger import Ledger
    from verifiers import Verdict, run_critic, run_verifiers

MAX_IDENTICAL_FAILURES = 2
MAX_REPLANS = 3


@dataclass
class RunLimits:
    """Hard stop conditions. Defaults are deliberately small and explicit."""

    max_steps: int = 50
    max_retries: int = 2
    max_wall_seconds: int = 1800


@dataclass
class StepResult:
    """What an executor returns for one step. ``claimed_done`` is a claim,
    not a verdict — the harness still runs the verifier before completing."""

    status: str = "success"  # success | failed
    summary: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    claimed_done: bool = False
    error: dict | None = None


ExecutorFn = Callable[[dict, StateCapsule, dict], StepResult]
ReplanFn = Callable[[dict, dict], list[dict]]


def new_run_id() -> str:
    return secrets.token_hex(16)


def failure_signature(*, kind: str, step_index: int, detail: str, tool: str = "") -> dict:
    """Stable, bounded signature of one failure (dedup + replan input)."""
    fingerprint = hashlib.sha256(
        json.dumps({"kind": kind, "tool": tool, "detail": detail[:500]},
                   sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"kind": kind, "step_index": step_index, "tool": tool,
            "detail": detail[:500], "fingerprint": fingerprint}


class Harness:
    """Drives a ledger-backed run through an injected executor."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    # -- run lifecycle ------------------------------------------------------

    def start_run(
        self,
        task: str,
        plan: list[dict],
        *,
        task_type: str = "",
        requirements: list[str] | None = None,
        limits: RunLimits | None = None,
        run_id: str | None = None,
    ) -> str:
        run_id = run_id or new_run_id()
        self.ledger.create_run(
            run_id, task=task, task_type=task_type,
            requirements=requirements or [], plan=plan,
            limits={"max_steps": (limits or RunLimits()).max_steps,
                    "max_retries": (limits or RunLimits()).max_retries,
                    "max_wall_seconds": (limits or RunLimits()).max_wall_seconds},
        )
        return run_id

    def _limits(self, run: dict) -> RunLimits:
        raw = run.get("limits") or {}
        return RunLimits(
            max_steps=int(raw.get("max_steps", 50)),
            max_retries=int(raw.get("max_retries", 2)),
            max_wall_seconds=int(raw.get("max_wall_seconds", 1800)),
        )

    def _file_sha256(self, workspace: Path, relative: str) -> str:
        path = workspace / relative
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return ""

    def _run_step_once(
        self, run_id: str, step: dict, workspace: Path,
        executor: ExecutorFn, context: dict,
    ) -> tuple[StepResult, StateCapsule]:
        """One attempt at one step: write-ahead begin, execute, commit outcome."""
        capsule = StateCapsule.from_dict((self.ledger.get_run(run_id) or {}).get("capsule"))
        before_hashes = {rel: self._file_sha256(workspace, rel) for rel in step.get("files_changed_hint", [])}
        self.ledger.append_step_begin(run_id, step["step_index"], title=step.get("title", ""))
        try:
            result = executor(step, capsule, context)
        except Exception as err:  # noqa: BLE001 - executor crash is a step failure, not a harness crash
            result = StepResult(status="failed", summary="Executor raised",
                                error={"code": "executor_raised", "message": str(err)[:500]})
        if not isinstance(result, StepResult):
            result = StepResult(status="failed", summary="Executor returned an invalid result",
                                error={"code": "executor_invalid_result", "message": "not a StepResult"})
        # The executor zero-tools bug (#92): no tool calls and no usable
        # result is a failure with a signature, never a silent success.
        if result.status == "success" and not result.tool_calls and not result.summary.strip() \
                and not result.files_changed:
            result = StepResult(status="failed", summary="Executor produced nothing",
                                error={"code": "executor_no_tools",
                                       "message": "Executor returned success with zero tool calls and no result"})
        for call in result.tool_calls:
            self.ledger.record_tool_call(
                run_id, step["step_index"], tool=str(call.get("tool", "")),
                arguments=call.get("arguments") if isinstance(call.get("arguments"), dict) else {},
                status=str(call.get("status", "")), duration_ms=call.get("duration_ms"),
            )
        capsule.step_index = step["step_index"]
        capsule.next_step = step.get("title", "")
        for relative in result.files_changed:
            after = self._file_sha256(workspace, relative)
            before = before_hashes.get(relative, "")
            diff = self.ledger.record_file_diff(
                run_id, step["step_index"], path=relative, sha256_before=before, sha256_after=after)
            changed = capsule.record_file(relative, sha256_before=before, sha256=after)
            changed.diff_hash = diff["diff_hash"]
        if result.status == "success":
            capsule.decisions.append(f"Step {step['step_index']}: {result.summary[:200]}")
        self.ledger.append_step_end(
            run_id, step["step_index"],
            status="success" if result.status == "success" else "failed",
            result={"summary": result.summary, "claimed_done": result.claimed_done},
            error=result.error, capsule=capsule,
        )
        return result, capsule

    # -- main execution -----------------------------------------------------

    def execute_run(
        self,
        run_id: str,
        executor: ExecutorFn,
        *,
        workspace: str | Path,
        verifier_spec: dict,
        replan_fn: ReplanFn | None = None,
        critic_fn: Callable[[list[dict[str, str]]], dict] | None = None,
        started_at: float | None = None,
    ) -> dict:
        """Run (or resume) a ledger run to a terminal, verifier-gated outcome."""
        run = self.ledger.get_run(run_id)
        if run is None:
            raise ValueError("Run not found")
        if run["status"] in {"completed", "failed", "cancelled", "timed_out"}:
            raise ValueError(f"Run is already {run['status']}; rewind or start a new run")
        limits = self._limits(run)
        workspace_path = Path(workspace).expanduser()
        start = started_at or time.monotonic()
        failure_counts: dict[str, int] = {}
        replans = 0
        steps_executed = 0
        claimed_done = False

        while True:
            if time.monotonic() - start > limits.max_wall_seconds:
                self.ledger.record_event(run_id, "stopped", {"reason": "max_wall_seconds"})
                return self._finish_failed(run_id, "max_wall_seconds",
                                           {"reason": f"Wall time exceeded {limits.max_wall_seconds}s"})
            step = self.ledger.next_unfinished_step(run_id)
            if step is None:
                break
            if steps_executed >= limits.max_steps:
                self.ledger.record_event(run_id, "stopped", {"reason": "max_steps"})
                return self._finish_failed(run_id, "max_steps",
                                           {"reason": f"Step budget exceeded ({limits.max_steps})"})
            steps_executed += 1
            attempts = 0
            signature: dict | None = None
            while True:
                context: dict = {"attempt": attempts, "run_id": run_id}
                if signature is not None:
                    context["failure_signature"] = signature
                result, _capsule = self._run_step_once(run_id, step, workspace_path, executor, context)
                if result.status == "success":
                    if result.claimed_done:
                        claimed_done = True
                    break
                attempts += 1
                detail = str((result.error or {}).get("message", result.summary or "step failed"))
                signature = failure_signature(
                    kind=str((result.error or {}).get("code", "step_failed")),
                    step_index=step["step_index"], detail=detail,
                    tool=str((result.tool_calls or [{}])[-1].get("tool", "")) if result.tool_calls else "",
                )
                failure_counts[signature["fingerprint"]] = failure_counts.get(signature["fingerprint"], 0) + 1
                if failure_counts[signature["fingerprint"]] >= MAX_IDENTICAL_FAILURES:
                    return self._finish_failed(run_id, "identical_failure", signature)
                if attempts > limits.max_retries:
                    if replan_fn is not None and replans < MAX_REPLANS:
                        replans += 1
                        snapshot = self._snapshot(run_id)
                        try:
                            new_plan = replan_fn(snapshot, signature)
                        except Exception as err:  # noqa: BLE001 - a broken planner must not hang the run
                            return self._finish_failed(run_id, "replan_failed",
                                                      {"reason": f"Replan hook failed: {err}", **signature})
                        if not isinstance(new_plan, list) or not new_plan:
                            return self._finish_failed(run_id, "replan_failed",
                                                      {"reason": "Replan hook returned no plan", **signature})
                        self.ledger.replace_plan(run_id, new_plan)
                        self.ledger.record_event(run_id, "replanned",
                                                 {"step_index": step["step_index"], "replan": replans})
                        break  # outer loop picks up the new plan from the ledger
                    return self._finish_failed(run_id, "retries_exhausted", signature)
                # Otherwise: retry ONLY this step, with the signature attached.
                self.ledger.record_event(run_id, "step_retry",
                                         {"step_index": step["step_index"], "attempt": attempts,
                                          "failure_signature": signature})
        return self._finish_with_verdict(run_id, workspace_path, verifier_spec, critic_fn,
                                         claimed_done=claimed_done)

    def _snapshot(self, run_id: str) -> dict:
        run = self.ledger.get_run(run_id)
        assert run is not None
        return {"run": run, "steps": self.ledger.get_steps(run_id),
                "verdicts": self.ledger.get_verdicts(run_id),
                "file_diffs": self.ledger.get_file_diffs(run_id)}

    def _finish_with_verdict(
        self, run_id: str, workspace: Path, verifier_spec: dict,
        critic_fn: Callable[[list[dict[str, str]]], dict] | None,
        *, claimed_done: bool,
    ) -> dict:
        """Terminal gate: only a verifier pass completes a run."""
        run = self.ledger.get_run(run_id)
        assert run is not None
        verdict = run_verifiers(workspace, verifier_spec, run=run, critic_fn=critic_fn)
        for check in verdict.checks:
            self.ledger.record_verdict(
                run_id, verifier=check.name,
                verdict="pass" if check.status == "passed" else
                        "fail" if check.status == "failed" else
                        "error" if check.status == "error" else "skipped",
                evidence=[check.evidence], failed_check=check.name if check.status != "passed" else None,
            )
        if verdict.verdict == "pass":
            self.ledger.set_status(run_id, "completed")
            self.ledger.record_event(run_id, "completed", {"verifier": "pass", "claimed_done": claimed_done})
            return {"run_id": run_id, "status": "completed", "verdict": verdict.to_dict(),
                    "claimed_done": claimed_done}
        # Model said done but the verifier failed (or errored): FAILED, with evidence.
        signature = failure_signature(kind="verifier_failed", step_index=-1,
                                      detail=verdict.failed_check or "verifier did not pass")
        self.ledger.set_status(run_id, "failed", failure_signature=signature)
        self.ledger.record_event(run_id, "failed", {
            "reason": "verifier_failed", "failed_check": verdict.failed_check,
            "claimed_done": claimed_done,
            "model_claimed_done_but_verifier_failed": claimed_done,
        })
        return {"run_id": run_id, "status": "failed", "verdict": verdict.to_dict(),
                "claimed_done": claimed_done,
                "failure_signature": signature}

    def _finish_failed(self, run_id: str, reason: str, signature: dict) -> dict:
        self.ledger.set_status(run_id, "failed", failure_signature=signature)
        self.ledger.record_event(run_id, "failed", {"reason": reason, "failure_signature": signature})
        return {"run_id": run_id, "status": "failed", "reason": reason,
                "failure_signature": signature}

    # -- resume / rewind / targeted retry / replan --------------------------

    def resume_snapshot(self, run_id: str) -> dict:
        """What a resume needs, from disk only: plan remainder + capsule + next step.

        Resume does not call the planner and does not rebuild the plan: the
        stored plan is authoritative, which is what makes resume work around
        the planner timeout bug.
        """
        run = self.ledger.get_run(run_id)
        if run is None:
            raise ValueError("Run not found")
        if run["status"] in {"completed", "cancelled", "timed_out"}:
            raise ValueError(f"Run is {run['status']} and cannot be resumed")
        nxt = self.ledger.next_unfinished_step(run_id)
        capsule = StateCapsule.from_dict(run.get("capsule"))
        return {
            "run_id": run_id,
            "status": run["status"],
            "task": run["task"],
            "requirements": run["requirements"],
            "capsule": capsule.to_dict(),
            "capsule_hash": capsule.content_hash(),
            "next_step": nxt,
            "remaining_steps": [s for s in self.ledger.get_steps(run_id) if s["status"] != "success"],
            "verdicts": self.ledger.get_verdicts(run_id),
        }

    def resume_run(self, run_id: str, executor: ExecutorFn, **kwargs: Any) -> dict:
        """Resume a killed/interrupted run: reload from the ledger and continue."""
        snapshot = self.resume_snapshot(run_id)
        if snapshot["next_step"] is None:
            # Plan is done but the run never reached the verifier gate
            # (e.g. killed between the last step and finish): go to the gate.
            return self._finish_with_verdict(
                run_id, Path(kwargs["workspace"]).expanduser(), kwargs["verifier_spec"],
                kwargs.get("critic_fn"), claimed_done=False,
            )
        self.ledger.record_event(run_id, "resumed", {"next_step": snapshot["next_step"]["step_index"]})
        self.ledger.set_status(run_id, "running")
        return self.execute_run(run_id, executor, **kwargs)

    def rewind_run(self, run_id: str, step_index: int) -> dict:
        """Rewind to step N and return the summary (incl. unrestored files)."""
        return self.ledger.rewind(run_id, step_index)

    def retry_failed_subtask(
        self, run_id: str, step_index: int, executor: ExecutorFn, *,
        workspace: str | Path,
    ) -> dict:
        """Retry ONLY the failed step, with its failure signature attached.

        The step row is reset to pending first (via rewind to that step, which
        preserves earlier steps), then executed once. Bounded by the run's
        max_retries: if the step already exhausted its attempts, this raises
        instead of retrying forever.
        """
        step = self.ledger.get_step(run_id, step_index)
        if step is None:
            raise ValueError("Step not found")
        if step["status"] != "failed":
            raise ValueError(f"Step {step_index} is {step['status']}, not failed")
        limits = self._limits(self.ledger.get_run(run_id) or {})
        if step["attempts"] > limits.max_retries:
            raise ValueError(f"Step {step_index} already exceeded max_retries ({limits.max_retries})")
        signature = failure_signature(
            kind=str((step.get("error") or {}).get("code", "step_failed")),
            step_index=step_index,
            detail=str((step.get("error") or {}).get("message", step.get("result") or "step failed")),
        )
        self.ledger.rewind(run_id, step_index)
        self.ledger.record_event(run_id, "subtask_retry",
                                 {"step_index": step_index, "failure_signature": signature})
        result, _capsule = self._run_step_once(
            run_id, {**step, "step_index": step_index}, Path(workspace).expanduser(),
            executor, {"attempt": step["attempts"], "run_id": run_id,
                       "failure_signature": signature, "retry_only": True},
        )
        return {"run_id": run_id, "step_index": step_index, "status": result.status,
                "summary": result.summary, "failure_signature": signature}
