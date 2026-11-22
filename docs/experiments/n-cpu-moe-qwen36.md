# Experiment: `--n-cpu-moe` / `--moe-cache-mib` llama-server recipe for Qwen3.6-35B-A3B

> **Update 2026-11-21:** the Ollama baseline is measured (Qwen3.6-35B-A3B Q4_K_M, 61% CPU / 39% GPU, 66.5 tok/s with MTP, 48.3 without): see [the README](README.md#measured-on-the-reference-pc-2026-11-21-through-ollama). This llama-server `--n-cpu-moe` recipe is still unmeasured.

**Status: unmeasured.** Nothing here has been run on Kan's PC. This is a
copy-ready tuning experiment, not an integration — the app keeps Ollama
as its backend; this recipe is for measuring the llama-server lane that
Ollama hides.

## Hardware this is for

- RTX 4070 12 GB VRAM, AMD Ryzen 7, 32 GB RAM, Windows + WSL2.
- llama-server (llama.cpp) current build; model files inside the WSL2
  ext4 filesystem, not `/mnt/c`.

## Why this recipe exists

Qwen3.6-35B-A3B is 35B total but only ~3B active per token, so it
generates at small-model speed while needing big-model memory: the
Q4_K_M file is ~18.6 GB and does not fit 12 GB VRAM. On Windows,
naive full offload (`-ngl 99` on an oversize model) is ~5× slow
because NVIDIA's System Memory Fallback silently backs the oversize
CUDA allocation with host RAM and pages it over PCIe (measured
11 tok/s vs 54 tok/s for the same model with `--n-cpu-moe 12` on a
12 GB RTX 5070). The fix is to keep attention, router, norms, and KV
cache on GPU and spill only experts to RAM — and to keep the *lowest*
number of CPU experts that fits, because lower N is faster.

Sources: https://www.bigiron.cc/guides/llama-cpp-vram-tuning-for-moe-models-on-gpu ·
https://aliteq.com/n-cpu-moe-llama-cpp-what-it-actually-does

## Setup

```bash
# Inside WSL2. Q3_K_M (~13.7 GB) is the 12 GB fit; Q4_K_M does not fit
# fully and is only usable with a large CPU spill (slower). Note the
# quality caution: aggressive MoE quants scored worst in one small
# independent suite, so the tool-call measurement below is the gate —
# do not adopt Q3_K_M for agent work on speed alone.
# Qwen publishes the GGUF in a -GGUF repo; if the file name below has
# changed, pick the Q3_K_M file from the repo's Files page.
huggingface-cli download Qwen/Qwen3.6-35B-A3B-Instruct-2507-GGUF \
  Qwen3.6-35B-A3B-Instruct-2507-Q3_K_M.gguf --local-dir ~/models
```

## Run (starting point)

```bash
llama-server -m ~/models/Qwen3.6-35B-A3B-Instruct-2507-Q3_K_M.gguf \
  -ngl 99 --n-cpu-moe 12 --moe-cache-mib 1536 \
  -c 16384 -fa --cache-type-k q8_0 --cache-type-v q8_0 \
  --cache-reuse 256 --port 9931
# llama.cpp v0.7.0 moved the default port 8080 -> 9931; --port pins it.
# --moe-cache-mib is an LRU cache in VRAM for CPU-resident experts
# (v0.7.0+): ~10% of total expert weights, ~1.5-2 GB here. It helps
# decode only, not prefill/TTFT, and competes with layers/KV for VRAM.
```

## Tune `--n-cpu-moe`

Start at 12 (or 20 per BigIron's 12 GB recipe), then lower N stepwise
until VRAM is nearly full — lower N is faster. At each step, watch
`nvidia-smi` in another terminal:

```bash
watch -n 2 nvidia-smi
```

- **Good:** VRAM nearly full, "shared" / fallback allocation near zero,
  generation steady.
- **Red flag:** Windows System Memory Fallback paging (shared memory
  climbing while tok/s collapses) — N is too low for the fit, or the
  model + KV is oversize; raise N again.
- If VRAM remains after N is as low as it goes, raise
  `--moe-cache-mib` (up to ~2 GB) and re-measure.

Re-measure tok/s at each step with a fixed prompt so the numbers are
comparable (the script below gives you the tool-call side; for raw
speed use `llama-bench` or the timed curl in the FreeToken doc).

## Measure

```bash
python3 docs/experiments/measure-tool-calls.py \
  --base-url http://127.0.0.1:9931/v1 \
  --model Qwen3.6-35B-A3B-Instruct-2507-Q3_K_M \
  --out ncpumoe-qwen36.json
```

## What success looks like

- Generation in the 35–55 tok/s band on the RTX 4070 (the published
  reference is 54 tok/s on a 12 GB RTX 5070 with `--n-cpu-moe 12`;
  treat it as a guide, not a promise).
- Tool-call accuracy on the app's tasks holds vs the Ollama baseline
  (`qwen3.5:9b` through the same script) — if Q3_K_M breaks tool
  calls, the recipe fails even if it is fast.
- No fallback paging in `nvidia-smi` during a sustained run.
- Context: 16K here is the practical ceiling with offload; do not
  raise `-c` without re-checking VRAM, and keep the agent loop's
  compaction in mind (the app compacts at 75% of 32K estimated tokens
  — a 16K server window is a tighter bound than the app assumes).

## What this does not do

- This does not change the app: Ollama stays the default backend.
  The recipe is the baseline the FreeToken experiment compares against,
  and the lane to use if you ever want a llama-server backend for
  power users (a separate task, with the `--cache-reuse 256` and
  `--cache-ram` prefix-cache flags made explicit).
- Do not quote the 54 tok/s figure as Kan's result — it is a 5070
  measurement. Kan's 4070 number is whatever this experiment records.
