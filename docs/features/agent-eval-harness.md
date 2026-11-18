# Agent eval harness

A local benchmark for the agent itself — Phase 1, item #7 of the
agentic-AI differentiation plan (research report §2.7 / §5 #7). It is
built **first**, before skill memory (#1) and the verifier/checkpoint
system (#2), because those are measured against it: without evals,
every other claim in that plan is unprovable.

## What it is

- A task-suite format: JSON/YAML tasks with a prompt, optional
  attachments and setup files, a reference solution as tool calls,
  and deterministic verifiers (file assertions, command exit codes,
  a small JSON-Schema subset). The verifiers — never the model —
  decide pass/fail.
- A runner that executes tasks through the real tool implementations
  and reports **pass@1 and pass^k** (k=3, 5), steps/task, tokens/task
  and wall time, recording the exact model + quantisation + seed per
  run.
- A GEPA/DSPy-style prompt optimiser (training-free, no new
  dependencies): proposes prompt variants, evaluates them on a
  held-out slice, keeps the best.
- A trace exporter that writes verified successful runs as SFT JSONL
  for later LoRA distillation of the small executor (format/tool-use
  only — never planner reasoning).

Implementation lives in
[`backend/projects/agent_eval/`](../../backend/projects/agent_eval/);
the package README is the operator's guide (how to run it, add
tasks, read pass^k, run the optimiser). This page is the design
record.

## Design decisions and tradeoffs

**Two executors, honestly labelled.** The deterministic stub runs
each task's reference solution through the real tools and proves the
harness, tools and verifiers work; it measures nothing about a model.
The live Ollama loop (Tool-RAG schema selection, `think: false`,
real tool dispatch) measures the model + tools. Every report carries
the executor name so a stub number is never mistaken for a model
number.

**No gateway round-trip yet.** The live loop deliberately bypasses
the gateway planner: the planner 111s timeout bug and the executor
zero-tools bug (issues #83/#92 area) mean a live gateway round-trip
cannot currently be measured end-to-end. Fixing those bugs is out of
scope for this item; a gateway-backed executor can replace the loop
later without changing the task or verifier format.

**pass^k is the headline metric.** pass@1 flatters — τ-bench showed
GPT-4o retail dropping from 60.4% pass@1 to ~25% at pass@8. A task
counts toward pass@k only if all k attempts pass. The gap between
pass@1 and pass@5 measures flakiness, the failure users actually feel.

**External ground truth only.** Verifiers check the workspace the
agent left behind. The model is never asked whether it is done, and
its final text is not part of verification. This is the
generator–verifier separation the research calls for (§2.2): without
an oracle, self-correction is a confident random walk.

**Patches are auto-approved inside the eval workspace.** Project
tools stage a pending diff in the real agent; the gateway applies it
after user approval. The harness auto-applies staged diffs inside the
attempt's throwaway workspace (the harness is the approver there) so
a task can complete and be verified in one run. This is not the
gateway's approval behaviour and must not be copied into it.

**No new dependencies.** Stdlib plus the existing `aiohttp` /
`model_router` / `agent_tools`. The JSON-Schema check is a small
in-repo subset because the backend has no `jsonschema` package;
`validate_project` uses the in-process validator because the
registry's project-tool path needs the loopback validator service and
its internal token.

## Suite

Seed suite: 21 tasks in
[`backend/projects/agent_eval/suite.json`](../../backend/projects/agent_eval/suite.json)
— 5 artifact saves (converted from real user phrasings in
`backend/scripts/tool_retrieval_real_cases.md`), 2 office documents,
7 code tasks (write / fix / add, verified by running the result),
2 Terminal-Bench-style terminal tasks (attached CSV in, computed
answer file out), 3 BFCL-style multi-turn tool tasks (read → save,
search → read → answer, write → validate), and 2 research tasks
tagged `requires: ["network"]`, skipped by default so the suite runs
offline.

## Metrics recorded per run

`report.json` → `summary`: pass@1, pass@3, pass@5 (when run),
mean steps / tokens / wall seconds per task (all attempts and passing
attempts), plus `config` with model, quantisation, seed, executor and
the system-prompt hash. Compare runs only with the same model +
quantisation + seed + suite version.

## Prompt optimisation

GEPA-style loop in `optimizer.py`: a pool of 5 candidates (base + 4
hand-written variants), one seeded mutation round on the winner
(append / drop / swap a sentence), selection on a train slice and a
single held-out scoring of the winner. Metric: pass@1, then fewer
steps, then fewer tokens. `--dry-run` scores prompts heuristically
with no model calls — a smoke test of the loop only. The winning
prompt is written out for human review and is never applied
automatically.

## LoRA hooks

`traces.jsonl` per run: only verified passing attempts with at
least one tool call, SFT chat format, tool results capped at 4,000
chars. No planner reasoning is recorded (the harness never runs the
planner). The training recipe is in
[LoRA distillation recipe](lora-distillation-recipe.md).

## Limitations (honest)

- The stub cannot measure the model; the live loop cannot measure
  the planner or the gateway approval flow.
- Live runs are slow on a CPU-only VM (qwen3.5:2b ≈ 10 tok/s): a full
  19-task live run takes well over an hour there. Run slices with
  `--tasks` and record the hardware with the numbers.
- The suite is small (21 tasks) and local: it measures PockPock on
  its own repeated tasks, not frontier-benchmark parity — that is the
  point, but it means scores are not comparable to published
  benchmark numbers.
- The `command` verifier runs the agent's own output; it is bounded
  (no shell, workspace cwd, timeout) but a task author must still
  keep verifier commands reviewable — a malicious task file could
  run arbitrary code in its own workspace.

## Related work

- Tool-retrieval eval (`backend/scripts/evaluate_tool_retrieval.py`):
  measures retrieval recall, not agent task success; the two are
  complementary.
- Roadmap task EVA-01 (privacy-safe tool evaluation and replay
  tests) is related but broader; this harness does not close it.
- Sequencing: this harness is the precondition for #1 (skill memory:
  cold-vs-warm success on this suite) and #2 (verifier/checkpoint:
  pass^k and verified-completion rate on this suite).
