# Plan-and-Sequence

Design page: `Plan-and-Sequence` (wiki). Package:
`backend/projects/plan_sequence/` (see its
[README](../../backend/projects/plan_sequence/README.md)). P1 measurement
report: `backend/scripts/plan_sequence_eval.md`.

## Purpose

Make PockPock Agent work well with small local models by splitting the
work: a strong model plans in detail and breaks the task into many small
sequential subtasks, and a small local model executes one subtask at a
time. The problem this addresses, in the design's own numbers: PockPock's
OpenClaw mode measured a **~21K-token system prompt**, far above Ollama's
4,096-token default context, and qwen3.5:2b turns never completed against
it. Each sequenced step instead gets a short instruction, 1–3 pinned tool
schemas, and a ≤400-token state capsule — measured at most **390 tokens
per step** on the P1 task sample (see Verification).

## Status: what exists and what is planned

Implemented and tested: the plan schema and validator (P0), the state
capsule (P0), the code-first verifier with retry and re-plan (P2), the
sequenced runner (P2), planner/executor model routing (P3), the planner
service endpoint `POST /plan-sequence` (P3), the gateway routes
`POST /api/agents/plan-sequence` and `POST /api/agents/run-sequence`, and
**Plan in steps** in PockPock Agent (desktop, 2026-11-22). OpenClaw subtask
mode exists in the Node turn helper (P4) but nothing sends it a subtask yet.

Not yet: OpenClaw as the step runner, persistence of sequence events in the
run store (a reopened task shows what the app saved, not a replay), notes
while a sequence runs, attached files in a sequence (a task with attached
documents keeps the one-model plan), and re-planning the remaining steps
automatically (the user retries from the failed step).

## User flow

1. In PockPock Agent, the model menu has a **Planning** section: **One model
   plans and works** (the default, the editable plan as before), or **Plan in
   steps with** a connected cloud model (for example an NVIDIA NIM model) or
   a local model. The model above it in the menu does the steps. The model
   pill then reads "… · steps planned by <planner>".
2. The app asks the gateway for a step plan (`POST /api/agents/plan-sequence`
   with `planner_model`, and `preferred_model` for the steps).
3. The **Plan in steps** card shows each step, each step's check in plain
   words, who plans and who works, and, when a cloud model is involved, that
   the request, the plan and each step's results (file names and short
   excerpts) are sent to that service. The plan is approved or declined as a
   whole; it cannot be edited (its hash binds the exact steps).
4. The run (`POST /api/agents/run-sequence`) shows **Step N of M** in the run
   bar and plan card, each check as a step ("Step 2 checked: …"), retries
   ("Trying step 2 again: …"), approval cards for changes in the open folder
   (Auto-review), and the files changed or saved.
5. It ends with a short reply (what was planned and done), or, when a step
   still fails after two retries, as a failed run whose card says which step
   and offers **Retry from step N**.

## Modules involved

| Module | Responsibility |
|---|---|
| `backend/projects/plan_sequence/contracts.py` | `SequencePlan` / `SequenceStep` / `DoneCondition` / `StateCapsule` schemas (Pydantic v2, `extra="forbid"`), `validate_sequence_plan` |
| `backend/projects/plan_sequence/capsule.py` | `build_capsule` — ≤400-token, ≤24-entry capsule; trims summaries, then values, then (last resort) pointers |
| `backend/projects/plan_sequence/verifier.py` | `verify_done_condition` — code-first checks, no model calls |
| `backend/projects/plan_sequence/runner.py` | `SequenceRunner`, `build_step_prompt` — one step at a time, `think=False`, harness-enforced pinning |
| `backend/projects/plan_sequence/routing.py` | `choose_planner_model`, `choose_executor_model`, model defaults and env overrides |
| `backend/projects/planner/app.py` | `POST /plan-sequence` — asks the planner model for a plan, validates it, one fix-up attempt |
| `backend/projects/agent_tools/tool_retriever.py` | Supplies each step's pinned tool specs (the runner asks it for the step's `tools_allowed`) |
| `backend/projects/agent_tools/` | The 15 registered tools a step may pin |
| `backend/projects/openclaw_bridge/gateway_turn.mjs`, `turn_helpers.mjs` | OpenClaw subtask mode: validates a subtask, builds the small step message, applies its budget as the turn timeout |
| `backend/scripts/evaluate_plan_sequence.py` | P1 eval harness (Measurements A–C) |

## Data and control flow

```
User task
  → planner service POST /plan-sequence (strong model)
      → validated SequencePlan (2–15 steps; tools, budgets, typed
        done-conditions, inputs = "task" or earlier step ids)
  → [planned] user approves the exact plan
  → SequenceRunner.run(plan, workspace, run_id, executor_model)
      for each step:
        capsule_text = capsule entries from the step's inputs only
        specs = ToolRetriever specs for tools_allowed
        prompt = build_step_prompt(task, step, capsule, specs)
        chat(executor_model, [system, user=prompt], specs, think=False)
        execute_tool(name, arguments) for each returned call
            (rejected without executing if outside tools_allowed)
        verify_done_condition(done_condition, workspace, step_result)
            pass → append capsule entries, next step
            fail → retry ≤2× with the failure detail fed back
            retries exhausted → needs_replan (remaining steps only)
      → SequenceRunResult: per-step results, final capsule, total prompt tokens
```

The state capsule carries pointers, not payloads: file paths, record IDs,
short summaries. The executor re-reads any file it needs instead of
trusting a summary. The capsule is filtered per step: a step sees only the
entries from the steps named in its `inputs` (plus the task itself).

A plan is validated before anything executes. Validation rejects: wrong
step count (not 2–15), duplicate step ids, unknown or duplicated tools in
`tools_allowed`, done-conditions with the wrong fields for their type, and
dangling inputs (anything that is not `"task"` or an earlier step id).

The minimum was 5 steps; it is 2 since 2026-11-21, because a small task (write two files) plans
naturally in 3–4 steps and the 5-step minimum rejected those plans with a 502. Before validation the
planner also swaps the two artifact tools when a step's done-condition names a file the pinned tool
cannot write: `save_text_artifact` writes `.txt/.md/.csv/.json/.html`, `create_office_document` only
`.docx/.xlsx/.pptx` (a live run had pinned the Office tool to `notes.md`, which produced
`notes.md.docx` and never passed). File done-conditions are checked in the open folder and then in
the run's task folder, where the artifact tools save.

## API contracts

### Planner service: `POST /plan-sequence` (implemented)

Internal loopback service on port 8771, authenticated with the internal
token (`X-PockPock-Internal-Token`). Request (`SequencePlanRequest`):
`task` (1–8,000 chars), `capable_models` (1–64), `model_profiles`,
`preferred_model`, `default_model`, `workspace_path`,
`permission_mode` (`default` | `auto-review` | `full-access`),
`planner_model`. Response: `contract_version: 1`, `sequence_plan` (the
validated plan), `selected_model` (planner), `executor_model`, `reason`,
`executor_reason`.

Behaviour: the planner model is picked by `choose_planner_model` and the
executor by `choose_executor_model`; the model is asked for plan JSON and
the plan is validated. On validation failure the model gets exactly one
fix-up attempt with the validation error and its previous JSON; a
still-invalid plan fails with 502 — no invalid plan is ever returned. A
planner timeout fails with 502 whose detail names it as a re-plan trigger,
not a fatal error. The known planner-timeout bug itself is out of scope
here (see Failure states).

### Gateway: `POST /api/agents/plan-sequence`, `POST /api/agents/run-sequence`

`POST /api/agents/plan-sequence` takes the agent plan body plus an optional
`planner_model`. The planner is `planner_model` (or `preferred_model`); a
connected cloud model is passed to the planner service with its profile, and
the planner service calls it through the gateway's local `/cloud/v1` endpoint,
so no cloud key leaves the gateway. `preferred_model` is sent as the step
(executor) model and used when available. The reply has `plan_id`,
`plan_hash`, `sequence_plan`, `selected_model` (planner), `executor_model`,
`step_checks` (each step's done-condition in plain words), `planner_cloud` and
`executor_cloud`. A cloud model that is not connected is refused with `409`.

Before validation the planner service repairs three things it saw models get
wrong in live runs: the artifact tool for a file kind (`repair_artifact_tools`);
a step that writes after an earlier step read something gets that reading
tool, within the 3-tool limit (`repair_read_tools`), because each step sees
only a short summary of earlier steps; and, with a folder open, a request to
write "in this folder" (or project, workspace) uses `propose_project_patch`
instead of `save_text_artifact`, so the file lands in that folder
(`repair_folder_writes`; not in Default mode).

The plan decision endpoint approves or rejects a sequence plan as a whole and
returns `approved_plan_hash` only. `POST /api/agents/run-sequence` with
`{plan_id, plan_hash, run_id}` runs it:

- Tools: files in the workspace go through the project tools with one context
  for the run; other tools through the agent tools. A tool's text for the step
  model comes from what it returns (`content`, `files`, `matches` or `output`;
  `tool_output_text`).
- Changes: `propose_project_patch` / `propose_project_edit` only propose. In
  Auto-review the gateway shows the approval card (Allow once, Allow for this
  task, Deny; 5 minutes), and the step's time budget is paused while it waits
  (`SequenceRunner.waiting_for_user`); in Full access the change is applied;
  Default refuses the change tools. An applied change sends `patch` and
  `artifact`; a saved file sends `artifact`.
- Events: the runner's own events (`plan_started`, `step_started`,
  `step_verified`, `step_retry`, `step_failed`, `replan_needed`,
  `plan_completed`, keyed `event`) and, for the app (`ui_events.py`):
  `plan_step` (`step`, `total`, `label`), `status`, `sequence_check`
  (`step`, `passed`, `message`), `sequence_retry`, and `error` (`status:
  partial`) when a step cannot be finished; then a `token` with the reply and
  `done` with the `SequenceRunResult`.

### OpenClaw subtask mode (implemented in the Node helper, not wired up)

`backend/projects/openclaw_bridge/turn_helpers.mjs`:
`validateSubtask` (id non-empty ≤128 chars, goal non-empty ≤500 chars,
`tools_allowed` 1–3 unique non-empty strings, `budget_seconds` 30–900 when
present, `capsule_text` string when present), `buildSubtaskMessage`
(short template + goal + pinned tools + capsule truncated at 1,200 chars,
no system prompt, no history; ends with a `DONE:` / `FAILED:` line), and
`subtaskTimeoutSeconds` (the step budget replaces the caller's per-turn
timeout). `gateway_turn.mjs` accepts a `subtask` in the helper's start
message on stdin, validates it before connecting (invalid subtask fails
fast with `invalid_subtask`), and echoes the subtask id back as
`subtaskId` on `started` / `final` events.

Not wired up: `openclaw_bridge` (`bridge.py`) does not send a subtask yet,
and the `SequenceRunner` has no OpenClaw `chat` callable in the repo — the
subtask path is exercised only by the Node unit tests
(`turn_helpers.test.mjs`).

## Task folder file types

`save_text_artifact` accepts the text and code files in `TEXT_ARTIFACT_EXTENSIONS` (`agent_tools/artifacts.py`): `.txt .md .csv .json .html .htm .css .js .mjs .ts .svg .xml .yml .yaml .py`. Before 0.2.12 it accepted only `.txt/.md/.csv/.json/.html`, so a website made without an open folder could never save `styles.css` or `script.js`. `contracts.repair_artifact_tools` uses the same set. The files are only saved, never run.

## Persistence

The runner emits events to injected `on_event` / `record_event` handlers:
`plan_started`, `step_started`, `step_verified` (with `passed`, `evidence`,
`detail`, `attempt`), `step_retry`, `step_failed`, `replan_needed`
(with `remaining_steps`), `plan_completed`. Each event carries
`contract_version: 1`, `run_id`, and `step_id` where applicable.

**Nothing persists these events into the run store yet.** There is no
wiring from the runner to `backend/scripts/agent_run_store.py` or the run
store service (:8773), so sequenced runs are not replayable from run
history today. The run result itself (`SequenceRunResult`: per-step
`StepResult`s, final capsule, `total_prompt_tokens`, plus
`remaining_steps` and `failure`) is returned to the caller as a dict; the
caller owns persisting it.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `POCKPOCK_PLAN_SEQUENCE_PLANNER_MODEL` | `qwen3.6:35b-a3b` | Planner model override |
| `POCKPOCK_PLAN_SEQUENCE_EXECUTOR_MODEL` | `qwen3.5:9b` (standard) / `qwen3.5:2b` (simple) | Executor model override (wins over both defaults when installed) |
| `POCKPOCK_PLAN_SEQUENCE_CLOUD_PLANNER_MODEL` | — (local by default) | Cloud planner model; used only when explicitly requested |

Model defaults: planner `qwen3.6:35b-a3b` (Qwen3.6-35B-A3B, 35B total /
3B active MoE); executor `qwen3.5:9b`, or `qwen3.5:2b` for the simplest,
most constrained steps. The `qwen3.6:35b-a3b` tag is a real Ollama library
tag, verified Nov 2026 against independent setup guides (`qwen3.6:35b`
is the short alias for the same build, ~23–24 GB) — but the tag has not
been pulled or run in this repo, and the planner model has not been
exercised live here. Routing falls back deterministically when a default
is not installed (largest installed tool-capable model for planning;
smallest at or above 2B for execution). Both chooser functions raise
`ValueError` when no model is available.

Per-step budgets are set on the plan, not globally: `budget_tokens`
(default 4,000, range 500–16,000) and `budget_seconds` (default 300,
range 30–900). A step whose prompt cannot fit its token budget fails
without retry (see Failure states).

## Permission and security boundaries

- **Harness-enforced pinned tools (gateway executor):** the runner rejects
  a tool call outside the step's `tools_allowed` without executing it.
  Pinning is enforced in the harness, not requested in the prompt.
- **Verifier is code-only:** `verify_done_condition` runs no model calls
  and executes no shell commands; it reads files inside the workspace and
  the recorded step result. A model cannot judge its own success.
- **Executor always runs with `think=False`:** thinking traces must never
  eat the executor's output budget on tool-call turns (issue #86). The
  runner passes `think=False` on every chat call; the P1 eval asserts it.
- **Workspace confinement:** verifier file checks resolve inside the run
  workspace (`..` segments, absolute paths outside, and escaping symlinks
  are rejected). Tool execution itself is bounded by the existing agent
  tool contracts and the run's permission mode.
- **OpenClaw allow-list is prompt-level only:** in subtask mode the pinned
  tools are named in the step message and enforced by the PockPock
  permission plugin — OpenClaw itself has no tool allow-list API, and the
  bridge does not remove tools from OpenClaw. Harness-level enforcement
  lives in the Python sequenced runner, which is not yet wired to
  OpenClaw. Do not rely on the subtask message alone as an enforcement
  boundary.
- **Planner is the strong model by rule, never the executor model**, and
  cloud planning is never the silent default (see Configuration).
- **No new network or credential surface:** the planner service and the
  runner use the existing internal-token and model-adapter paths. The
  eval harness talks to local Ollama only.

## Failure states

| Failure | What happens |
|---|---|
| Invalid plan | Rejected at validation, before any step runs (`ValueError`, specific message). The planner service gives the model one fix-up attempt, then 502s. No invalid plan is ever executed or returned. |
| Verifier fail | The step is retried ≤2× with the failure detail fed back as grounded feedback. If it still fails, the run stops with `status="needs_replan"`, `remaining_steps` (failed step onwards), and `failure` (step id, detail, attempts). Passed steps and their capsule entries are kept; a re-plan covers the remaining steps only. |
| Step prompt over budget | The step fails with no retry: the prompt is rebuilt without the capsule and re-checked, and if it still exceeds `budget_tokens` the step reports `needs_replan`. |
| Step timeout | Each attempt is bounded by the step's `budget_seconds`; a timeout fails that attempt like any other verifier failure (retry, then re-plan). |
| Planner timeout | Treated as a re-plan trigger, not a fatal error (planner service returns 502 naming it so). **Fixed 2026-11-21:** planner calls stream, so a slow model that keeps writing is no longer cut off at about 111 seconds; only 240 s of silence or the per-call limit (600 s, 900 s for large models) stops it. |
| Executor zero-tools bug | **Fixed in 0.2.5 (#92, PR #99):** a task that needs a tool but was planned with no capability gets the artifact tools. |
| Capsule pointer loss | If trimming must drop a `path`/`id` pointer to fit 400 tokens, the capsule records `dropped_pointers=True` and logs a warning; a later step may need to re-derive the pointer. (Not observed in the P1 sample: no capsule dropped pointers.) |
| Executor prints the file instead of saving it | Small models often answer "create index.html" with the file in a code block and no tool call, so a file check failed on every attempt (report 2026-11-25). Since 0.2.12, `printed_file_call` in `runner.py` saves it: when the step's check is `file_exists`/`file_contains` for one path, the step may use `save_text_artifact` or `propose_project_patch`, and the reply holds a code block for that file (matching language, the only block, or a bare HTML document for an `.html` file), the block is written with the allowed tool as if the executor had called it. A retry after "file does not exist" now names the exact call (`retry_instruction`): "Call save_text_artifact now with filename "index.html" and content set to the complete file. Do not answer with the file as text". Each `step_verified` event also records the attempt's `tools` (name and ok) and up to five `errors`, so a failed step can be diagnosed from the run's history. |
| Tool outside the pinned subset | Rejected by the runner without executing; recorded as a step error and verified as a failure. |

## Verification

Plan in steps, live (2026-11-22, RTX 4070 SUPER 12 GB; planner `qwen3.6:35b-a3b`, steps `qwen3.5:9b`; gateway and planner from source, temporary folder, Auto-review with each change allowed once):

- "Read notes.md and write summary.md in this folder with three bullet points…": planned in 33–38 s as 2 steps. The first run found three faults, now fixed: the read file's text reached step 2 as nothing (tools return `content`, not `output`), step 2 could not re-read the file and wrote placeholders, and the file was saved to the task folder. The second run wrote the right facts but failed its check on case ("release date" against "Release date"); `file_contains` now ignores case. The third run asked for approval, wrote `summary.md` into the open folder with the three facts, and passed both checks; the steps took 12 s.
- "List the files in this folder and write files.md…": completed (step 2 passed on its second try, after approval). `files.md` lists `notes.md` and `todo.txt` but not `budget.csv`, because `list_project_files` does not list `.csv` files; the step model wrote what the tool returned.
- Not verified: a cloud planner (NVIDIA NIM) with a real key; a sequence through OpenClaw.

P1 measurement (2026-11-17, `backend/scripts/evaluate_plan_sequence.py`;
full results in `backend/scripts/plan_sequence_eval.md`):

```bash
# From the repo root, with the repo venv:
.venv/bin/python backend/scripts/evaluate_plan_sequence.py [--no-live] [--self-check]
.venv/bin/python -m unittest discover -s backend/projects/plan_sequence -t backend -p "test_*.py"
```

Results (token counts are the repo's `estimate_tokens`, ~4 chars/token):

- **~1,500 tokens per step: confirmed.** Max step prompt **390 tokens**
  over 30 steps (6 tasks × 5 steps), 0 steps over target; total 8,159
  tokens (mean 272/step). Monolithic baseline per call: 21,000-token
  system prompt (spec's cited PockPock measurement) + 1,909 measured
  full-schema tokens = 22,909. A sequenced step prompt is ~1.7% of the
  monolithic per-call prompt at worst.
- **Capsule ≤ 400 tokens: confirmed.** Max **109 tokens** at any step
  boundary; final capsules 103–190 tokens.
- **Step success / end-to-end (fake model, real tools): 30/30 steps, 6/6
  tasks completed, 0 retries.** This measures the harness (runner,
  verifier, capsule) with a scripted fake chat client — it must not be
  quoted as model performance. The fake model always makes the right
  call; a real model has to produce these calls itself.
- **Live run with real `qwen3.5:2b`: NOT MEASURED.** The single bounded
  attempt (120 s overall cap, expenses task) exceeded its budget on this
  VM — no model was loaded when it started, so the attempt included a
  cold model load, and CPU generation did not finish the 5 steps in time.
  No model was pulled and no service was restarted. Wall-clock for the
  whole eval invocation was 2m42s (120 s cap plus in-flight call
  teardown).
- **Live run through the gateway, 2026-11-21 (RTX 4070 SUPER, `qwen3.5:9b` as planner and
  executor):** task "create notes.md listing three fruits, then summary.md saying how many fruits
  notes.md lists". The first runs exposed four bugs, all fixed: a 5-step minimum rejected the
  planner's 4-step plan (now 2–15); the planner pinned `create_office_document` to `notes.md`
  (repaired before validation); file checks ignored the task folder when a folder is open; and a
  step could not read and then write (now up to 3 executor turns per attempt). After the fixes,
  **3 of 3 runs completed**: a 3-step plan in 4–11 s, the run in 12–16 s, with the correct
  `notes.md` and `summary.md` ("notes.md lists 3 fruits."). One small task, one model, three
  runs: a working path, not a success-rate measurement.
- **End-to-end task success vs the monolithic path: NOT MEASURED.** There
  is no monolithic runner to run the same tasks through, and no live
  monolithic comparison was attempted. Prior PockPock validation (Nov
  2026) found qwen3.5:2b OpenClaw turns never completed against the ~21K
  prompt; that is prior evidence, not a P1 measurement.

Task sample and adaptations (honest limits): the 6 reference plans are
hand-written, not planner output — plan quality is not measured. The
spec's Canva worked example names `gmail_search`, `read_message`,
`calculator`, and `write_file`, which are not among the 15 registered
tools, so it was adapted (invoices as an attached file, executor-side
addition). The data.csv task reads via attachment because
`read_project_file` cannot read `.csv`. No in-repo adapter exists from the
runner's `{"ok", "output", ...}` tool-result shape to the repo's bare
`execute_agent_tool` / `execute_project_tool` results — the eval supplies
that translation (`RealToolAdapter`) for measurement only.

Unit tests (84 in `backend/projects/plan_sequence/`, plus 5 eval-harness
tests in `backend/scripts/test_plan_sequence_eval.py`):

```bash
.venv/bin/python -m unittest discover -s backend/projects/plan_sequence -t backend -p "test_*.py"
# 84 tests, OK
```
