# External verifier + durable checkpoint / replan / resume

Agentic-AI differentiation Phase 1, item #2. A run is only done when an
external verifier passes — never when the model says it is done — and every
step is persisted to disk before and after it runs, so a killed run can
resume, rewind, or retry only the failed subtask.

## Why

Self-correction without external feedback degrades performance (Huang et
al., ICLR 2024); Magentic-One loses 31% without its Task/Progress ledgers;
Reflexion only works because the environment supplies ground truth. The
verifier and the ledger are the harness that makes the local agent reliable
across repeats and long horizons.

## Modules

All in `backend/projects/agent_verifier/`:

- `ledger.py` — durable run ledger (SQLite, WAL, `synchronous=FULL`):
  runs, per-step state capsules, tool calls, file diffs, verifier verdicts,
  append-only events. Write-ahead: a step row is committed as `running`
  before the executor runs it and its outcome is committed after.
- `capsule.py` — `StateCapsule` (goal, decisions, constraints, files
  changed with content/diff hashes, open threads, next step). The resume
  unit; never the executor transcript.
- `verifiers.py` — verifier registry. Deterministic external ground truth:
  `python_syntax`, `pytest`, `lint`, `typecheck`, `expected_files`,
  `expected_content`, `json_schema`, `git_diff_review`; plus `critic`, a
  rubric model given the original requirements and check evidence, never
  the executor transcript. Verdicts `pass`/`fail`/`error`/`skipped`;
  all-skipped is an `error`, never a pass.
- `harness.py` — `Harness`: drives a ledger run through an injected
  executor, enforces the hard stops, and gates completion on a verifier
  pass. Resume, rewind, targeted retry, and the replan hook live here.
- `app.py` — HTTP control plane on port 8775 (`GET /health`, run
  create/list/read, `POST /runs/{id}/verify`, `/rewind`, `/resume`).
- `cli.py` — standalone verification: `verify`, `show`, `resume`,
  `rewind`, `list-verifiers`.

The ledger is separate from the existing run store
(`backend/scripts/agent_run_store.py`), which owns gateway run metadata,
approvals, and delegation contracts. A verifier run may reuse a run-store
run_id, but the verifier ledger never duplicates the run store's tables.
The service is registered in `backend/scripts/pockpock.py` (`SERVICES`,
port 8775, `POCKPOCK_AGENT_VERIFIER_URL`).

## User flow

1. A run is created with a task, the original requirements, and a plan.
   The plan and its pending steps are persisted before anything executes.
2. The harness runs each step through the executor, committing the step
   outcome, tool calls, file diffs (content hashes), and the updated
   capsule to the ledger as it goes.
3. When the plan is done — or the executor claims it is done — the
   verifiers run against the workspace on disk. A pass completes the run.
   A fail or error fails it, with the verifier evidence persisted and an
   event recording whether the model had claimed done.
4. If the process dies, the user (or the gateway) resumes from the ledger:
   the stored plan and capsule reload and execution continues at the first
   unfinished step. No fresh plan is needed, so resume works even when the
   planner is unavailable.
5. If a step went wrong, the run can rewind to step N (later ledger entries
   truncated; files changed past N are reported as unrestored, with hashes)
   or retry only the failed step with its failure signature attached.

## Data and control flow

```
executor ──► Harness.execute_run ──► Ledger (SQLite, WAL, FULL sync)
                │  step begin (commit) → execute → step end (commit)
                │  failure → retry same step (signature attached)
                │  retries out → replan_fn(snapshot, signature) → replace_plan
                └─► plan done / claimed done → run_verifiers(workspace)
                        pass → completed │ fail/error → failed + evidence
```

The HTTP service is a control plane only: it owns ledger reads, runs the
verifiers, and hands out resume snapshots. Step execution stays in-process
through `Harness`, so a crashed executor cannot take the ledger down.

## API contract

Authenticated with `X-PockPock-Internal-Token` (all routes except
`GET /health`); base `http://127.0.0.1:8775`.

| Route | Purpose |
| --- | --- |
| `GET /health` | `{"ok": true, "service": "agent-verifier", "verifiers": [...]}` |
| `POST /runs` | Create a run: `task`, `task_type`, `requirements[]`, `plan[]` (step titles), `max_steps`, `max_retries`, `max_wall_seconds`. Returns the run. |
| `GET /runs?status=&limit=` | List runs, newest first. |
| `GET /runs/{run_id}` | Run + steps + verdicts + file diffs. |
| `GET /runs/{run_id}/steps/{n}` | One step + its file diffs. |
| `POST /runs/{run_id}/verify` | Body: `workspace_path`, `spec` (see below). Runs the verifiers, persists verdicts, fails a still-running run on a non-pass. |
| `POST /runs/{run_id}/rewind` | Body: `step_index`. Truncates the ledger past N, reports unrestored files. |
| `POST /runs/{run_id}/resume` | Resume snapshot: stored plan remainder, capsule (+ hash), next step, verdicts. Execution itself is driven in-process via `Harness.resume_run`. |

Verifier spec example:

```json
{"verifiers": [
  {"name": "pytest", "paths": ["tests"]},
  {"name": "expected_files", "files": ["result.txt"]},
  {"name": "expected_content", "checks": [{"file": "result.txt", "contains": "42"}]},
  {"name": "json_schema", "schema": {"type": "object", "required": ["name"]}, "files": ["meta.json"]}
],
 "critic": {"rubric": ["Every requirement is met by a file on disk"]}}
```

CLI (from `backend/projects/agent_verifier/`, repo venv):

```bash
python -m cli verify --run-id <32-hex> --workspace <dir> --spec spec.json
python -m cli show --run-id <32-hex>
python -m cli resume --run-id <32-hex>
python -m cli rewind --run-id <32-hex> --step 1
```

`verify` exits 0 only on a verifier pass.

## Persistence

Ledger SQLite file: `POCKPOCK_AGENT_VERIFIER_DB`, else
`<PockPock data dir>/agent-verifier-ledger.sqlite3`. Tables: `runs`,
`steps`, `tool_calls`, `file_diffs`, `verdicts`, `events` (append-only).
No prompts, transcripts, or credentials are persisted; tool-call arguments
are stored, so keep secrets out of them.

## Stop conditions

Enforced by the harness, never by the model: max steps (default 50), max
retries per step (2), identical failure twice, max replans (3), max wall
time (1800s), and the verifier gate. A step whose executor returns success
with zero tool calls, no summary, and no files changed is a failure with
signature `executor_no_tools` (the known executor zero-tools bug, #92).

## Known limits

- The planner 111s timeout bug and the executor zero-tools bug (#92) are
  not fixed here. Resume works around the planner bug by reusing the stored
  plan; the zero-tools bug becomes a signed step failure so retry/replan
  engages. A full live agent round-trip was not verified on this CPU-only
  VM (no GPU, ~7.7 GB RAM): the harness, ledger, and verifiers are verified
  with a deterministic executor, and the replan hook with a stub.
- Rewind records unrestored files; it does not restore file contents (no
  whole-file snapshots). Restore from version control using the reported
  paths and hashes, or re-run from step N.
- The critic check needs a caller-supplied model function; without one it
  is `skipped` and the deterministic verifiers decide the run.

## Verification

Unit tests in `backend/projects/agent_verifier/test_*.py` (39 tests, 1 skip
— the pytest-failure test skips where pytest is not installed). Full
backend suite: `backend/scripts/run_tests.py` — 373 tests, all passing.
End-to-end demo with a deterministic executor (kill-simulation + resume,
rewind, verifier catching a wrong outcome, model-claimed-done-but-verifier-
failed): all four scenarios pass.
