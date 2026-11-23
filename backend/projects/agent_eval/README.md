# Agent eval harness

A local benchmark for the agent itself: a fixed suite of verifiable
tasks, a runner that measures **pass@1 and pass^k** (k=3, 5), steps /
tokens / wall time per task, a training-free prompt optimiser, and a
trace exporter for later LoRA distillation of the small executor.
This is Phase 1, item #7 of the agentic-AI differentiation plan
(research report §2.7 / §5 #7): build the harness *first*, because
everything else — skill memory, verifier, subagents — is measured
against it.

## What a number means

Two executors, two different claims:

| Executor | What it measures |
| --- | --- |
| `stub` | The harness, the real tools, and the verifiers. It runs each task's reference solution (`stub_actions`) through the real tool implementations in a fresh workspace. A stub pass means "this task is solvable and verifiable" — it says **nothing** about the model. |
| `ollama` | The local model + tools, in a small agent loop (Tool-RAG schema selection, `think: false`, real tool dispatch). This is the number that measures the agent. |

The live loop deliberately bypasses the gateway planner: the
planner's 111s timeout bug and the executor zero-tools bug (issues
#83/#92 area) mean a live gateway round-trip cannot currently be
measured end-to-end. The harness measures model + tools directly and
records that limitation in every report. A gateway-backed executor
can replace the loop later without changing tasks or verifiers.

`pass@k` is the headline metric: a task counts toward pass@k only if
**all** k attempts pass. A task that passes once in five tries scores
0 on pass@5 — flaky is failing. (τ-bench: GPT-4o retail 60.4% pass@1,
~25% at pass@8.)

## Run it

From the repo root, with the backend venv:

```bash
# Stub run: proves harness + tools + verifiers (fast, no model)
.venv/bin/python backend/scripts/run_agent_eval.py

# Live run against qwen3.5:2b (slow on a CPU-only VM — see below)
.venv/bin/python backend/scripts/run_agent_eval.py --executor ollama \
    --model qwen3.5:2b --quantisation Q4_K_M --k 3

# One task only, with network tasks included
.venv/bin/python backend/scripts/run_agent_eval.py --tasks code-greet,code-fix-counter
.venv/bin/python backend/scripts/run_agent_eval.py --include-network
```

Each run writes into `agent_eval_runs/<timestamp>/` (or `--out`):

- `report.json` — full machine-readable report (config incl. exact
  model + quantisation + seed, per-task/per-attempt results).
- `report.md` — short human summary.
- `traces.jsonl` — verified passing traces in SFT format (see below).
- `workspaces/<task>/attempt-N/` — the workspace each attempt left
  behind, for debugging a failure by hand.

`--min-pass 0.8` makes the exit code gate on pass@1; by default the
harness reports and exits 0.

### Live runs on a CPU-only VM

qwen3.5:2b at ~10 tokens/sec needs minutes per task; a full 19-task
live run can take well over an hour on this VM. Use `--tasks` to run a
slice, and `--k 1` unless you specifically need pass^k. On the
target RTX 4070 PC the same run is far faster — record the hardware
alongside the numbers when you compare runs.

## Add a task

Add an entry to `suite.json` (or your own suite file passed with
`--suite`). A task needs:

- `id` (unique), `prompt` (what the user asks), `verifiers` (at least
  one — these decide pass/fail, never the model).
- `stub_actions`: the reference solution as tool calls. Keep it
  minimal and honest: it must use the same tools the agent would.
  Project patches are staged then auto-applied inside the attempt's
  throwaway workspace (the harness is the approver there).
- `setup.files`: files written into the workspace before the run
  (buggy code to fix, input data, check scripts).
- `attachments`: files the agent may read via `read_selected_file`.
- `requires`: e.g. `["network"]` — skipped unless
  `--include-network` is given, so the default suite runs offline.

Verifier kinds: `file_exists`, `file_contains`, `file_not_contains`,
`file_matches` (regex), `file_json` (small JSON-Schema subset: `type`,
`required`, `properties`, `items`, `enum`, `minimum`/`maximum`,
`minLength`/`maxLength`), `command` (argv, no shell, `{python}` is
replaced with the current interpreter, `expect_exit`,
`stdout_contains`/`stderr_contains`), and the `all` / `any`
combinators. Verifier paths cannot escape the workspace.

## Read pass^k

`report.json` → `summary`:

```json
{"pass@1": 0.84, "pass@3": 0.63, "pass@5": 0.47, "mean_steps_per_task": 2.1, ...}
```

- pass@1 < pass@3 < pass@5 gaps measure flakiness, not capability.
- Compare runs only with the same model + quantisation + seed +
  suite version — all recorded in `config`.
- A stub pass@1 below 1.0 is a harness/task bug, not a model result:
  fix the task or the tool, then re-run.

## Optimise the prompt

GEPA-style, training-free, no new dependencies
(`backend/scripts/optimize_agent_prompt.py`):

```bash
# Smoke-test the loop mechanics (heuristic scores, no model calls)
.venv/bin/python backend/scripts/optimize_agent_prompt.py --dry-run

# Real optimisation (live model; slow on CPU — small slices first)
.venv/bin/python backend/scripts/optimize_agent_prompt.py \
    --model qwen3.5:2b --quantisation Q4_K_M --train-size 12
```

Candidates (base + 4 hand-written variants) are scored on a train
slice, the winner is mutated (append / drop / swap a sentence, seeded
RNG), and the best-on-train prompt is scored **once** on the held-out
slice — the held-out number is the reported result. The winner is
written to `best_prompt.txt` and is **never applied automatically**:
review it, then pass it with `--system-prompt-file` to the harness or
wire it into the executor. Every evaluation is logged to
`optimizer_log.jsonl`.

The optimiser needs a real executor: the stub ignores the prompt, so
optimising against it would optimise nothing.

## LoRA distillation hooks

Every harness run exports `traces.jsonl`: only attempts that **passed
verification** and made **at least one tool call**, in SFT chat
format (system / user / assistant tool calls / tool results). The
transcripts contain no planner reasoning — the harness never runs the
planner — so the data teaches format and tool use only, which is the
right scope for distilling the small executor. No training happens
here; the recipe is in
[`docs/features/lora-distillation-recipe.md`](../../../docs/features/lora-distillation-recipe.md)
(Unsloth/TRL, executor-only).

## Layout

| File | What it owns |
| --- | --- |
| `tasks.py` | Task schema, JSON/YAML loading, train/held-out split |
| `verifiers.py` | Deterministic file / JSON / command verifiers |
| `executors.py` | `StubExecutor`, `OllamaExecutor`, real tool dispatch |
| `runner.py` | Suite runner, pass@1/pass^k aggregation, JSON + Markdown reports |
| `optimizer.py` | GEPA-style prompt optimisation loop |
| `traces.py` | SFT JSONL export of verified traces |
| `suite.json` | Seed suite (21 tasks: artifacts, office docs, code, terminal, multi-turn, research) |
| `test_agent_eval.py` | Deterministic unit tests (no model needed) |

## Verification

```bash
.venv/bin/python -m unittest projects.agent_eval.test_agent_eval -v  # from backend/
.venv/bin/python backend/scripts/run_tests.py                        # full backend suite
.venv/bin/python backend/scripts/run_agent_eval.py                  # stub end-to-end
```

## Boundaries

- No planner, no gateway, no desktop UI. The live loop is a
  stand-in until the planner/executor bugs are fixed.
- No network by default; network tasks are tagged and skipped.
- No new dependencies (stdlib + the existing `aiohttp` /
  `model_router` / `agent_tools`). YAML suites need PyYAML, already a
  backend dependency.
- Verifiers run commands only inside the attempt workspace, with no
  shell and a bounded timeout.
