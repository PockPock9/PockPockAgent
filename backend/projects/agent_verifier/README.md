# Agent verifier service

External verification + durable checkpoint / replan / resume for agent runs
(agentic-AI differentiation Phase 1, item #2). The point, from the research
evidence: self-correction without external feedback degrades performance
(Huang et al., ICLR 2024), Magentic-One loses 31% without its Task/Progress
ledgers, and Reflexion only works because the environment supplies ground
truth. So this service never trusts the model saying "done": a run completes
only when an external verifier passes, and every step is persisted to disk
before and after it runs.

- Entry point: `app:app`
- Local port: `8775`
- Routes: `GET /health`; authenticated run creation/listing/read, step read,
  `POST /runs/{id}/verify`, `POST /runs/{id}/rewind`, `POST /runs/{id}/resume`
  (resume snapshot).
- CLI: `python -m cli verify|show|resume|rewind|list-verifiers`
  (run from this folder with the repository environment).
- Run from this folder with the repository environment:
  `..\..\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8775`.

Install the service dependencies listed in `requirements.txt` into the shared
repository environment. The service is also registered in
`backend/scripts/pockpock.py` (`SERVICES`, port 8775) and its requirements
manifest is picked up by `requirements_files()`.

## Modules

| Module | Owns |
| --- | --- |
| `ledger.py` | Durable run ledger (SQLite, WAL, `synchronous=FULL`): runs, per-step state capsules, tool calls, file diffs, verifier verdicts, append-only events. Write-ahead: a step row is committed as `running` *before* the executor runs it and its outcome is committed *after*. A fresh process reopening the same file sees exactly what survived a kill. |
| `capsule.py` | `StateCapsule`: goal, decisions, constraints, files changed (path + content/diff hashes), open threads, next step. The resume unit — never the executor transcript. |
| `verifiers.py` | Verifier registry + built-ins. Deterministic, external ground truth only: `python_syntax`, `pytest`, `lint` (ruff/flake8), `typecheck` (mypy), `expected_files`, `expected_content`, `json_schema` (built-in subset, no third-party dependency), `git_diff_review`, plus `critic` (a rubric model given the original requirements and check evidence — never the executor transcript). Verdicts: `pass`/`fail`/`error`/`skipped`; all-skipped is an `error`, never a pass. |
| `harness.py` | `Harness`: drives a ledger run through an injected executor. Enforces the hard stops (max steps, max retries, max identical failures = 2, max replans = 3, max wall time) and the terminal gate: `done` requires a verifier pass. Resume reloads the stored plan + capsule and continues at the first unfinished step — no fresh full plan. Retry re-runs only the failed step with its failure signature attached. Replan re-invokes a planner hook with the ledger snapshot + failure signature. |
| `app.py` | HTTP control plane (ledger reads, verification, rewind, resume snapshot). Step execution stays in-process; the service never executes agent steps itself. |
| `cli.py` | Standalone verification against any finished run. |

## Ledger format

SQLite file: `POCKPOCK_AGENT_VERIFIER_DB` if set, else
`<PockPock data dir>/agent-verifier-ledger.sqlite3`.

- `runs`: run_id (32-hex), task_type, task, requirements (JSON), plan (JSON),
  status (`running|completed|failed|interrupted|cancelled|timed_out`),
  limits, capsule, failure_signature, timestamps.
- `steps`: (run_id, step_index), title, status
  (`pending|running|success|failed|skipped|rewound`), attempts, tool calls
  (JSON, latest 50), result/error (JSON), capsule.
- `tool_calls`: one row per call (tool, arguments, status, duration).
- `file_diffs`: path, sha256 before/after, diff hash, restored flag.
- `verdicts`: verifier, verdict (`pass|fail|error|skipped`), evidence,
  failed check, optional step index.
- `events`: append-only audit log (`run_created`, `step_started`,
  `step_finished`, `step_retry`, `replanned`, `resumed`, `rewound`,
  `completed`, `failed`, `stopped`, `status_changed`).

This ledger is separate from the existing run store
(`backend/scripts/agent_run_store.py`), which owns gateway run metadata,
approvals, and delegation contracts. A verifier run may reuse a run-store
run_id, but the verifier ledger never duplicates the run store's tables.

## Verifier types

- **Deterministic (preferred):** run the real tools — `pytest`, linter,
  type-checker, JSON-schema validation, file/content expectations taken from
  the run's stored requirements, `git diff` review (expected changes,
  forbidden paths). A missing tool is recorded as `skipped`, never as a pass.
- **Critic model:** a *different* small model (think:false) judging the
  outcome against the original requirements and a rubric, given only the
  verifier check outcomes, file list, and diff hashes. It never sees the
  executor's transcript, so it cannot be talked into passing. Without a
  configured critic callable the check is `skipped`. The live critic call is
  injected by the caller (gateway/planner wiring); the harness and CLI accept
  it as a parameter and the unit tests cover it with a stub.
- **Registry:** add a verifier with `@register_verifier("name")` in
  `verifiers.py`; unknown names in a spec are recorded as `error`.

A verifier spec is JSON, for example:

```json
{"verifiers": [
  {"name": "pytest", "paths": ["tests"]},
  {"name": "expected_files", "files": ["result.txt"]},
  {"name": "expected_content", "checks": [{"file": "result.txt", "contains": "42"}]},
  {"name": "json_schema", "schema": {"type": "object", "required": ["name"]}, "files": ["meta.json"]}
],
 "critic": {"rubric": ["Every requirement is met by a file on disk"]}}
```

## Resume / rewind / retry / replan

- **Resume:** `Harness.resume_run(run_id, executor, workspace=..., verifier_spec=...)`
  or `POST /runs/{id}/resume` for the snapshot (stored plan remainder +
  capsule + next step). Resume never calls the planner and never rebuilds the
  plan — this is what makes it work around the known planner 111s timeout
  bug. A run killed between its last step and the verifier gate resumes
  straight into the gate. Completed/cancelled/timed-out runs cannot resume.
- **Rewind:** `Harness.rewind_run(run_id, N)` / `POST /runs/{id}/rewind`.
  Steps, tool calls, and verdicts after N are truncated; step N returns to
  `pending`. File contents are **not** snapshotted, so file diffs after N
  are kept and reported as `unrestored_files` (path + before/after hashes) —
  re-run from N or restore them from version control. The rewind is recorded
  in the event log.
- **Retry:** `Harness.retry_failed_subtask(run_id, N, executor, workspace=...)`
  re-runs only the failed step, with its failure signature attached, bounded
  by the run's `max_retries`. Inside `execute_run`, a failed step is retried
  the same way before any replan is considered.
- **Replan:** pass `replan_fn(snapshot, failure_signature) -> new plan` to
  `execute_run`. The hook receives the full ledger snapshot (run, steps,
  verdicts, diffs) plus the failure signature, and the new plan is persisted
  via `Ledger.replace_plan` before execution continues. A failing or empty
  replan fails the run with the signature instead of hanging. At most 3
  replans per run.

## Stop conditions (enforced by the harness, never by the model)

| Limit | Default | Behaviour on breach |
| --- | --- | --- |
| `max_steps` | 50 | Run fails with reason `max_steps` |
| `max_retries` (per step) | 2 | Retry exhausted → replan hook, else fail with `retries_exhausted` |
| Identical failure | 2 | Run fails with reason `identical_failure` (same fingerprint twice) |
| `max_wall_seconds` | 1800 | Run fails with reason `max_wall_seconds` |
| `max_replans` | 3 | Further failures fail the run instead of replanning |
| Verifier gate | — | Executor claiming `done` with a failing/erroring verifier → run `failed`, evidence persisted, event records `model_claimed_done_but_verifier_failed` |

A step whose executor returns success with zero tool calls, no summary, and
no files changed is treated as a failure with signature `executor_no_tools`
(the known executor zero-tools bug, #92) — never a silent pass.

## Known limits (not fixed here, by design)

- The planner 111s timeout bug and the executor zero-tools bug (#92) are
  **not** fixed in this change. Resume works around the planner bug by
  reusing the stored plan; the zero-tools bug is converted into a signed
  step failure so retry/replan engages. Live verification of a full agent
  round-trip was not possible on this CPU-only VM (no GPU, ~7.7 GB RAM):
  a real planner call times out and no live model round-trip was run. The
  harness, ledger, and verifiers are verified with a deterministic executor
  (see tests) and the replan hook is testable with a stub.
- File restore on rewind is recorded, not performed: no whole-file snapshots
  are taken. Rewinding a run whose steps wrote files you cannot regenerate
  requires restoring those files from version control using the reported
  paths and hashes.
- The critic model check needs a caller-supplied model function; without one
  it is `skipped` and the run is judged by the deterministic verifiers only.

## Configuration

- `POCKPOCK_AGENT_VERIFIER_DB`: ledger SQLite path (default: PockPock data
  dir `agent-verifier-ledger.sqlite3`).
- `POCKPOCK_INTERNAL_TOKEN`: required for every non-health route.
- `POCKPOCK_AGENT_VERIFIER_URL`: `http://127.0.0.1:8775` (set by
  `pockpock.py service_environment()`).

## Security

Bind to `127.0.0.1`; non-health requests require `X-PockPock-Internal-Token`.
Verifiers run bounded subprocesses (`pytest`, linters, `mypy`, `git`) with
the workspace as working directory and a 120s timeout; they never use the
network and never execute the executor's output as code. Ledger contents
stay on the local machine; no prompts, transcripts, or credentials are
persisted (tool-call arguments are stored — keep secrets out of them, as
with the run store).

## Tests

`test_capsule.py`, `test_ledger.py`, `test_verifiers.py`,
`test_harness.py`, `test_app.py` in this folder; run via
`backend/scripts/run_tests.py` (the `agent_verifier` service) or
`python -m unittest discover -s . -p "test_*.py"` from this folder.
