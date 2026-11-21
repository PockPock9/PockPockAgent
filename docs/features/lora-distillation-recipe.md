# LoRA distillation recipe (executor-only)

How to turn verified harness traces into a better small executor.
This is a **plan, not a run**: no training has happened on this VM
(no GPU, ~7.7 GB RAM) and none should be attempted here. The recipe
targets the user's RTX 4070 PC (12 GB VRAM, 32 GB RAM).

## What the data is

`traces.jsonl` from `backend/scripts/run_agent_eval.py` — one SFT
record per verified passing attempt with at least one tool call:

- `messages`: system prompt, user task, assistant tool calls, tool
  results (capped at 4,000 chars). Chat format, OpenAI-style
  `tool_calls`.
- `verified: true`, plus `task_id`, `model`, `quantisation`, `seed`
  and the outcome (steps / tokens / wall time) for filtering.
- **Format / tool-use only.** The transcripts contain no planner
  reasoning: the harness never runs the planner, and no thinking
  trace is recorded. That is deliberate — fine-tuning teaches format,
  style and tool use reliably and rarely teaches new reasoning
  (research report §2.7), which is exactly what the small executor
  needs. Never train the executor on planner reasoning; that is the
  planner's job, and the executor must stay short-output and
  format-tight.

## Data preparation

1. Collect traces across harness runs (live executor only — stub
   traces are reference solutions, useful as a bootstrap but not as
   evidence of what the model does). Aim for **500–2,000 verified
   traces** before a first training run; fewer than ~200 is not worth
   the setup. Grow the suite first (more tasks, more repeats) rather
   than training on a thin set.
2. Deduplicate by `(task_id, tool-call sequence)` — a task passed
   five identical ways is one example, not five.
3. Hold out 10% of tasks (by task id, not by trace) as an eval split;
   never train on a task you will use to claim an improvement.
4. Drop traces whose tool results are mostly error text, and any
   trace whose final tool call did not verify (the exporter already
   guarantees verification, but re-check after merging files).
5. Keep the mix representative: artifact saves, code writes/fixes,
   multi-turn reads, and validation calls in roughly suite
   proportions — a skewed set teaches a skewed executor.

## Training

- **Stack:** Unsloth + TRL (SFT), QLoRA on the executor model
  (e.g. Qwen3.5-2B/4B). Unsloth's 4-bit path fits a 2–4B model with
  activations on a 12 GB card; use the base (non-instruct) weights
  only if the instruct model's tool format is the thing being fixed —
  otherwise start from the instruct model the harness already runs.
- **Scope:** executor only. Train the model that makes tool calls
  with `think: false`; do not train the planner, and do not mix
  planner-style reasoning traces into this data.
- **Settings (starting point, tune on the held-out split):**
  LoRA rank 16, alpha 32, dropout 0.05, target all linear layers;
  learning rate 2e-4 with cosine decay, 2–3 epochs, batch size 4
  with gradient accumulation 4, max sequence length 2,048 (executor
  turns are short; longer mostly wastes VRAM on tool-result padding).
  Mask the loss to assistant tokens only (prompt + tool results are
  context, not targets) — most SFT trainers do this by default with
  a chat template; verify it, because training on tool-result tokens
  teaches the model to hallucinate tool outputs.
- **Do not** train on traces from a different (larger) model's
  behaviour unless the harness verified them under the executor's own
  name — distillation data is only as honest as its verification.

## Evaluation (the part that matters)

1. Before training, run the harness on the held-out task split with
   the base executor model and record pass@1 / pass@3, steps/task,
   tokens/task. Same model name, quantisation and seed discipline as
   any harness run.
2. Swap in the LoRA adapter (same base model, same harness flags)
   and re-run the identical held-out split.
3. Ship only if held-out pass@1 improves **and** pass@3 does not
   regress — a gain that only shows up on trained tasks is
   memorisation, and a pass@1 gain bought with flakiness is a loss.
   Report both numbers with the model + quantisation + seed, as with
   any harness run.
4. If the adapter helps, re-run the prompt optimiser against it:
   the best prompt for the base model is not necessarily the best
   prompt for the tuned one.

## What not to do

- Do not full-fine-tune the base model (expensive, ties you to one
  base release, overtaken by the next Qwen release — LoRA adapters
  are cheap to retrain and cheap to throw away).
- Do not use RL (GRPO/RLVR) for this: GEPA-style prompt optimisation
  beats it on cost by ~35× fewer rollouts (report §2.7) for the same
  class of gain. Revisit only if prompt optimisation plateaus and
  the failure mode is clearly a behaviour, not a format problem.
- Do not train on failed runs, unverified runs, or traces with no
  tool calls — the exporter already excludes them; keep it that way.
