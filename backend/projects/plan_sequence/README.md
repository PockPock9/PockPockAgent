# plan_sequence — Plan-and-Sequence

Schema, validation, state capsule, verifier, sequenced runner, and model
routing for the Plan-and-Sequence design (wiki page `Plan-and-Sequence`):
a strong model plans a task as 5–15 sequential steps, a small local model
executes one step at a time, a code-first verifier checks each step, and
only a ≤400-token capsule passes between steps. Full feature doc:
`docs/features/plan-and-sequence.md`.

## Module map

| Module | Contents |
|---|---|
| `contracts.py` | Pydantic v2 models (`extra="forbid"` everywhere), constants, `validate_sequence_plan` |
| `capsule.py` | `build_capsule`, `capsule_to_text`, `capsule_token_estimate` |
| `verifier.py` | `verify_done_condition` — code-first done-condition checks (P2) |
| `runner.py` | `SequenceRunner`, `build_step_prompt` — one step at a time (P2) |
| `routing.py` | `choose_planner_model`, `choose_executor_model`, model defaults and env overrides (P3) |
| `__init__.py` | The frozen public API (see below) |

## Frozen public API

```python
from projects.plan_sequence import (
    MIN_STEPS, MAX_STEPS, MAX_CAPSULE_TOKENS, MAX_STEP_RETRIES,
    MAX_TOOLS_PER_STEP, SEQUENCE_CONTRACT_VERSION,
    DoneCondition, SequenceStep, SequencePlan,
    CapsuleEntry, StateCapsule, StepResult, SequenceRunResult,
    validate_sequence_plan, build_capsule, capsule_to_text,
    capsule_token_estimate, verify_done_condition,
    SequenceRunner, build_step_prompt,
    DEFAULT_PLANNER_MODEL, DEFAULT_EXECUTOR_MODEL, SIMPLE_EXECUTOR_MODEL,
    choose_planner_model, choose_executor_model,
)
```

Constants: `MIN_STEPS = 5`, `MAX_STEPS = 15`, `MAX_CAPSULE_TOKENS = 400`,
`MAX_STEP_RETRIES = 2`, `MAX_TOOLS_PER_STEP = 3`,
`SEQUENCE_CONTRACT_VERSION = 1`.

## How validation works

`validate_sequence_plan(raw, *, allowed_tools=None) -> dict` validates a raw
plan dict with `SequencePlan` and returns its normalised JSON form
(`model_dump(mode="json")`). It raises `ValueError` with a specific message
on any problem:

- **Step count:** 5–15 steps; step ids must be unique and match
  `^[a-z0-9][a-z0-9_-]{0,31}$`.
- **Tools:** each step's `tools_allowed` holds 1–3 unique names, and every
  name must be in `allowed_tools` — by default the registered tool contract
  names from `projects.agent_tools` (`registered_tool_contracts`).
- **Done-conditions:** typed, with exactly the fields the type needs.
  `file_exists` needs `path`; `file_contains` needs `path` + `pattern`;
  `value_equals` needs `field` + `expected`; `command_exit_0` and
  `no_error` take no fields. Any other combination is rejected.
- **Inputs:** each input is either the literal `"task"` (the original
  request is always available) or the id of an *earlier* step — i.e. "whatever
  that step put in the capsule". Steps declare no output keys, so a step id
  is the only static handle on an earlier step's capsule entries; anything
  else is a dangling input and the plan is rejected.

## How the capsule works

`build_capsule(entries, *, max_tokens=MAX_CAPSULE_TOKENS)` accepts a list of
dicts, a list of `CapsuleEntry`, or an existing `StateCapsule`, and returns a
`StateCapsule` of at most 24 entries and at most `max_tokens` tokens
(estimated with `tool_retriever.estimate_tokens`, ~4 chars per token).

Trimming drops the oldest entries first, in this order:

1. `"summary"` entries,
2. then `"value"` entries,
3. `"path"` / `"id"` pointers are never dropped while any summary or value
   remains. Only when the capsule is still over budget after every summary
   and value is gone are the oldest pointers dropped — and that loss is
   recorded on the capsule as `dropped_pointers=True` (and logged), because
   a later step may need the pointer to re-read its input.

`StateCapsule.to_text()` renders one `key: value` line per entry, grouped by
source step (entries with no source step first, then one group per step in
order of first appearance), so the text round-trips back to the entries.
`capsule_to_text` is the same render; `capsule_token_estimate` wraps the
shared token estimator.

## How the verifier works

`verify_done_condition(condition, *, workspace, step_result) -> dict`
checks one typed done-condition against the real state — files on disk and
the recorded step result — never against the model's claim. It returns
`{"passed": bool, "evidence": str, "detail": str}` and never raises for bad
input; malformed conditions, paths escaping the workspace, or unusable step
results are reported as `passed=False` with a reason. It runs no model calls
and executes no shell commands; it only reads files and the step result.
`file_exists` / `file_contains` resolve paths inside `workspace`
(`..` segments, absolute paths outside, and symlinks pointing outside are
rejected). `command_exit_0` passes only when every recorded exit code is 0.
`value_equals` compares a field from the step result's JSON-object tool
outputs. `no_error` passes only when no errors were recorded and no tool
call failed.

## How the runner works

`SequenceRunner(chat, execute_tool, retriever=None, on_event=None,
record_event=None)` runs a validated plan one step at a time.
`chat` and `execute_tool` are injected callables, so the runner works
against the gateway, OpenClaw-as-tool-provider, or a fake in tests.

- The plan is validated with `validate_sequence_plan` before any step runs;
  an invalid plan raises `ValueError` and nothing executes.
- Each step's prompt is built by `build_step_prompt` — short instruction +
  step goal + capsule + the pinned 1–3 tool schemas (one line each plus the
  full JSON schema). Conversation history is never included.
- The executor is always called with `think=False` (issue #86).
- Pinned tools are enforced in the harness: a tool outside
  `tools_allowed` is rejected without executing.
- After each attempt the verifier checks the done-condition. Pass moves to
  the next step; fail retries the step (≤2 retries, the failure detail fed
  back as grounded feedback). When retries are exhausted, or a step's prompt
  cannot fit its token budget, the run stops with `status="needs_replan"`,
  `remaining_steps` (the failed step onwards), and `failure`. Re-plan scope
  is the remaining steps only — passed steps and their capsule entries are kept.
- `execute_tool` must return `{"ok": bool, "output": str, "exit_code": int | None,
  "error": str | None}`. **There is no in-repo adapter from this shape to the
  repo's `execute_agent_tool` / `execute_project_tool` yet** — those return
  bare result dicts with no `ok`/`output` keys, so a bare success would read
  as `ok=False`. The P1 eval harness (`backend/scripts/evaluate_plan_sequence.py`,
  `RealToolAdapter`) supplies the translation for measurement only.
- The runner emits `plan_started`, `step_started`, `step_verified`,
  `step_retry`, `step_failed`, `replan_needed`, and `plan_completed` events
  to `on_event` / `record_event` handlers. **Nothing persists these events
  into the run store yet** — that wiring does not exist.
- `SequenceRunResult` (returned as a dict, plus `remaining_steps` and
  `failure` keys) records per-step `StepResult`s, the final capsule, and
  `total_prompt_tokens`.

## Model routing

`choose_planner_model(installed, *, preferred=None, cloud_model=None,
fallback=None, profiles=None)` picks the planner: explicit `preferred` if
available, else the `POCKPOCK_PLAN_SEQUENCE_PLANNER_MODEL` env model, else
the default local planner `qwen3.6:35b-a3b`, else the gateway fallback, else
the largest installed tool-capable model. Cloud is never the silent default:
a cloud model is used only when explicitly requested and configured via
`POCKPOCK_PLAN_SEQUENCE_CLOUD_PLANNER_MODEL`.

`choose_executor_model(installed, *, step_complexity="standard", profiles=None)`
picks the executor: `qwen3.5:2b` for `"simple"` steps, `qwen3.5:9b` for
`"standard"` steps, with `POCKPOCK_PLAN_SEQUENCE_EXECUTOR_MODEL` winning
over both when installed; otherwise the smallest installed tool-capable
model at or above 2B parameters.

`qwen3.6:35b-a3b` is a real Ollama library tag for Qwen3.6-35B-A3B, verified
Nov 2026 against independent setup guides; `qwen3.6:35b` is the short alias
for the same build. The tag has not been pulled or run in this repo — the
planner model has not been exercised live here.

## What is wired up — and what is not

Implemented and tested in this package: plan schema + validation, capsule,
verifier + retry, runner, model routing, and the planner service endpoint
`POST /plan-sequence` (`backend/projects/planner/app.py`, P3).

Not wired up (planned, not implemented): there is no gateway
`/api/agents/plan-sequence` or `/api/agents/run-sequence` route, the
`SequenceRunner` has no in-repo caller and no adapter to the real tools,
runner events are not persisted to the run store, and
`openclaw_bridge` does not send a subtask yet — OpenClaw subtask mode
lives only in the Node helper (`gateway_turn.mjs` / `turn_helpers.mjs`,
P4), where pinning is prompt-level only. See
`docs/features/plan-and-sequence.md` for the full status.

## P1 measurement (2026-11-17)

`backend/scripts/evaluate_plan_sequence.py` measures the design targets;
results are in `backend/scripts/plan_sequence_eval.md`:

- Prompt tokens per step: max **390** over 30 steps (target ~1,500) —
  confirmed. Total 8,159 tokens over 30 steps (mean 272).
- Capsule: max **109** tokens at any step boundary (cap 400) — confirmed.
- Fake model + real tools: **30/30 steps, 6/6 tasks completed**, 0 retries.
- Monolithic baseline: 21,000-token system prompt (spec's cited PockPock
  measurement) + 1,909 measured full-schema tokens = 22,909 per call.
- Live run with real `qwen3.5:2b`: **not measured** — the single bounded
  attempt exceeded its 120 s overall budget on this VM (cold model load;
  no model was loaded when it started). End-to-end success vs the
  monolithic path is therefore also **not measured** — there is no
  monolithic runner to compare against.

## Running the tests

From `backend/` with the repo venv:

```bash
../../../PockPockAgent/.venv/bin/python -m py_compile projects/plan_sequence/*.py
../../../PockPockAgent/.venv/bin/python -m unittest discover -s projects/plan_sequence -t . -p "test_*.py" -v
```

Or run the whole backend suite with `backend/scripts/run_tests.py`, which
includes this package. The P1 eval harness runs as:

```bash
../../../PockPockAgent/.venv/bin/python backend/scripts/evaluate_plan_sequence.py [--no-live] [--self-check]
```
