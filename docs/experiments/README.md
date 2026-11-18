# Experiments: local-AI efficiency on Kan's RTX 4070 PC

Copy-ready experiments for the RTX 4070 12 GB VRAM / Ryzen 7 / 32 GB RAM /
Windows + WSL2 machine. **Nothing here has been run on that PC — every
result is unmeasured until Kan runs it.** None of these is integrated
into the app: no FreeToken/MTP code in the app, no model swap, no engine
switch. The app keeps Ollama as its default backend with the app-level
wins documented in `../features/local-ai-efficiency.md`.

## The experiments

| Experiment | Question it answers | Doc |
|---|---|---|
| FreeToken in WSL2 | Is FreeToken's dynamic MoE serving faster than llama-server `--n-cpu-moe` for Qwen3.6-35B-A3B, at the same tool-call accuracy? | `freetoken-wsl2-qwen36.md` |
| Native MTP speculative decoding A/B | Does MTP speed up Qwen3.6-35B-A3B without breaking tool-call accuracy? (MTP is not bit-exact in llama.cpp.) | `mtp-ab-qwen36.md` |
| `--n-cpu-moe` / `--moe-cache-mib` recipe | What is the fastest stable llama-server setup for Qwen3.6-35B-A3B on 12 GB VRAM? | `n-cpu-moe-qwen36.md` |

Run the `--n-cpu-moe` recipe first: it is the baseline the other two
compare against.

## Shared measurement script

`measure-tool-calls.py` (stdlib only, no dependencies) measures all
three experiments the same way:

```bash
python3 docs/experiments/measure-tool-calls.py \
  --base-url http://127.0.0.1:11434/v1 --model qwen3.5:2b
```

- **Tool-call accuracy**: 9 fixed tasks with a fixed tool list (same
  order, same schemas, every run). It scores only the *first* tool call
  — right function, valid JSON arguments, right values — plus two plain
  factual/text tasks that must not call a tool. It does not execute tools
  and does not score multi-turn task completion, so treat it as a smoke
  measurement, not a full agent evaluation.
- **TTFT**: time to first streamed token, after a warm-up call so the
  model load is not counted in the first task.
- **tok/s**: only reported for the long plain-text task. Tool calls
  stream as a single chunk once generation is done, so no decode rate
  can be measured from them; for raw generation speed use a longer
  fixed prompt (`llama-bench` or the timed curl in the experiment docs).

The script writes a JSON results file (default
`measure-<model>-<timestamp>.json`) so two runs can be compared
directly. It exits 0 when every task passes, 1 otherwise.

## Ground rules

- Keep models inside the WSL2 ext4 filesystem, never under `/mnt/c`
  (30–50% disk speed there). Raise the WSL2 RAM cap in `.wslconfig`
  (32 GB RAM defaults to a 16 GB WSL2 cap).
- Compare the same tasks, the same prompts, and the same model/quant
  across runs. A faster engine that breaks tool calls is a failure,
  not a win — tool-call accuracy is the veto in every experiment.
- Treat every published tok/s figure in the research as a claim until
  reproduced on this rig: the research notes flag several corrected or
  single-rig numbers.
