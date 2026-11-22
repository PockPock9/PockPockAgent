# Experiments: local-AI efficiency on Kan's RTX 4070 PC

Copy-ready experiments for the RTX 4070 12 GB VRAM / Ryzen 7 / 32 GB RAM /
Windows + WSL2 machine. None of these is integrated into the app: no
FreeToken/MTP code in the app, no model swap, no engine switch. The app
keeps Ollama as its default backend with the app-level wins documented in
`../features/local-ai-efficiency.md`.

## Measured on the reference PC (2026-11-21, through Ollama)

Qwen3.6-35B-A3B and its MTP head turned out to need no WSL2 or
llama-server to measure: Ollama 0.40.15 publishes `qwen3.6:35b-a3b`
(22 GB, Q4_K_M, built from the `35b-a3b-mtp` source) and runs MTP
speculative decoding itself (`draft_num_predict 2` in the model's
parameters). MTP off is the same weights with `PARAMETER
draft_num_predict 0` in a Modelfile (`ollama create
qwen3.6-mtp-off:35b-a3b`; no extra disk). PC: RTX 4070 **SUPER** 12 GB,
Windows, `OLLAMA_CONTEXT_LENGTH=32768`.

| | `qwen3.5:9b` | `qwen3.6:35b-a3b`, MTP on (default) | Qwen3.6, MTP off |
|---|---|---|---|
| Placement (`ollama ps`) | 100% GPU | 61% CPU / 39% GPU | 57% CPU / 43% GPU |
| Decode, 400 tokens, temp 0 (median of 3) | 72.7 tok/s | **66.5 tok/s** | 48.3 tok/s |
| Prompt processing | ~1,980 tok/s | ~980 tok/s | ~1,010 tok/s |
| Cold load | — | 31 s | 25 s |
| `measure-tool-calls.py`, thinking really off | 9/9 | 9/9 | 9/9 |
| Mean time to the tool call, thinking really off | 0.61 s | 1.01 s | 1.14 s |
| Same, with only `"think": false` (thinking still on) | 1.50 s, 9/9 | 2.80 s, 8/9 | 4.13 s, 8/9 |

- **MTP: +38% decode** (48.3 → 66.5 tok/s), and the three runs at
  temperature 0 were identical within each mode. MTP on and off were
  not identical to each other (one function name differed in a 400-token
  answer), as the MTP doc warns: speculative decoding here is not
  bit-exact.
- **In PockPock (Qwen3.6 as the agent model):** chat works (a compacted
  30K-token history answered correctly, 69 s including the model load).
  The ten-file agent task from the compaction check passed with 10/10
  correct, but took **326 s against 34 s for `qwen3.5:9b`**, and planning
  40 s against 6 s: each agent step re-reads the growing prompt at about
  half the 9B's prompt speed, partly on the CPU. On this PC Qwen3.6 is
  fine for chat and too slow as the default agent model.
- `--n-cpu-moe` in llama-server and **FreeToken were not run**: both need
  WSL2 changes (FreeToken needs the 28 GB `.wslconfig` cap, a
  `wsl --shutdown` that stops Docker Desktop and the NemoClaw sandbox, and
  the CUDA 13 toolkit). The app cannot use FreeToken today anyway (see its
  doc), so it is worth running only if Qwen3.6 becomes a target model.
- Thinking: Ollama's `/v1` endpoint ignores `"think": false`. The script
  now also sends `reasoning_effort: "none"`; before that, Qwen3.6's 512
  tokens went to hidden reasoning on the plain-text task and the reply
  was empty.

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
