# Experiment: native MTP speculative decoding A/B for Qwen3.6-35B-A3B

> **Update 2026-11-21:** measured through Ollama instead, no WSL2 needed: Ollama's `qwen3.6:35b-a3b` runs MTP itself. MTP on 66.5 tok/s vs off 48.3 tok/s (+38%), tool calls 9/9 both ways, output not bit-exact between the two. See [the README](README.md#measured-on-the-reference-pc-2026-11-21-through-ollama). The llama-server run below is still unmeasured.

**Status: unmeasured.** Nothing here has been run on Kan's PC. This is a
copy-ready A/B experiment, not an integration — no MTP code or flag is
set in the app.

## Hardware this is for

- RTX 4070 12 GB VRAM, AMD Ryzen 7, 32 GB RAM, Windows + WSL2.
- llama-server (llama.cpp) build new enough for MTP (`--spec-type
  draft-mtp`); Qwen3.6 support needs a 2026 build.

## What MTP is

Multi-token prediction: the model's own trained extra heads act as the
draft, proposing several tokens per step while the main model verifies
them in one pass. Published numbers: Qwen3.6-35B-A3B on an RTX 3070 8 GB,
28.6 → 40.6 tok/s (+42%, 90% draft acceptance); Qwen3.8-27B on an RTX
3090, +60% decode. But MTP in llama.cpp is **not bit-for-bit lossless
in practice** — in the Qwen3.8 study, 92–100% of requests diverged from
serial greedy decoding at a 1,600-token cap (semantic better/worse was
not measured). For agents that means: fine for draft/chat, risky for
exact JSON/tool-call determinism. That is exactly what this A/B
measures.

Qwen3.6-35B-A3B's MTP layers ship as a separate GGUF
(`unsloth/Qwen3.6-35B-A3B-MTP-GGUF`); the MTP head costs ~1 GB VRAM.

Sources: https://blog.lucad.cloud/articles/turboquant-mtp-get-406-toks-out-of-qwen36 ·
https://hackmd.io/@thc1006/qwen3-8-27b-speculative-decoding-rtx-3090

## Setup

```bash
# Inside WSL2. Keep models inside the WSL2 ext4 filesystem, not /mnt/c.
# Qwen publishes the GGUF in a -GGUF repo; if the file name below has
# changed, pick the Q3_K_M file from the repo's Files page.
huggingface-cli download Qwen/Qwen3.6-35B-A3B-Instruct-2507-GGUF \
  Qwen3.6-35B-A3B-Instruct-2507-Q3_K_M.gguf --local-dir ~/models
# MTP head (separate GGUF):
huggingface-cli download unsloth/Qwen3.6-35B-A3B-MTP-GGUF \
  --local-dir ~/models/qwen36-mtp --local-dir-use-symlinks False

# Build or install a current llama.cpp (MTP flags moved across 2026
# builds — run `llama-server --help` and confirm --spec-type and
# --model-draft exist before trusting the commands below).
```

## Run A: baseline (MTP off)

```bash
llama-server -m ~/models/Qwen3.6-35B-A3B-Instruct-2507-Q3_K_M.gguf \
  -ngl 99 --n-cpu-moe 12 --moe-cache-mib 1536 \
  -c 16384 -fa --cache-type-k q8_0 --cache-type-v q8_0 \
  --cache-reuse 256 --port 9931
# llama.cpp v0.7.0 moved the default port 8080 -> 9931; --port pins it.
```

Measure (from the repo root):

```bash
python3 docs/experiments/measure-tool-calls.py \
  --base-url http://127.0.0.1:9931/v1 \
  --model Qwen3.6-35B-A3B-Instruct-2507-Q3_K_M \
  --out mtp-off-qwen36.json
```

Stop the server before run B.

## Run B: MTP on

```bash
llama-server -m ~/models/Qwen3.6-35B-A3B-Instruct-2507-Q3_K_M.gguf \
  --model-draft ~/models/qwen36-mtp/<mtp-file>.gguf \
  --spec-type draft-mtp --spec-draft-n-max 2 \
  -ngl 99 --n-cpu-moe 12 --moe-cache-mib 1536 \
  -c 16384 -fa --cache-type-k q8_0 --cache-type-v q8_0 \
  --cache-reuse 256 --port 9931
```

Measure with the same script and the same tasks:

```bash
python3 docs/experiments/measure-tool-calls.py \
  --base-url http://127.0.0.1:9931/v1 \
  --model Qwen3.6-35B-A3B-Instruct-2507-Q3_K_M \
  --out mtp-on-qwen36.json
```

Also note the draft acceptance rate from the server log/metrics if
your build reports it (`llama-server` logs per-request timings;
acceptance below ~60% usually means no net win).

## Decide

Compare `mtp-off-qwen36.json` vs `mtp-on-qwen36.json` on three numbers:

| Metric | Keep MTP on | Turn MTP off |
|---|---|---|
| Tool-call accuracy (tasks passed) | Same or better | Any drop |
| Mean tok/s | Clearly higher (+20% or more) | Flat or lower |
| Draft acceptance | Above ~70% | Below ~60% |

**Tool-call accuracy is the veto.** A tok/s gain that costs even one
tool-call task is a loss for the agent brain: MTP divergence lands
exactly on the structured JSON the agent depends on. If accuracy
holds and acceptance is high, MTP is a keep for generation-heavy turns;
if accuracy drops, MTP stays off for tool-call turns even if chat gets
faster.

Do not run MTP and a draft-model (DFlash2) at the same time — test one
speculative path at a time.

## If it fails

- `llama-server --help` shows no `--spec-type`: the build predates MTP
  support (or the flags moved) — update llama.cpp and re-check.
- MTP head file rejected: the MTP GGUF must match the base model's
  architecture and quant family; check the Unsloth repo notes for the
  exact pairing.
- Slower with MTP on: low acceptance on this workload (agent loops with
  many short structured tool calls are the worst case for speculative
  decoding) — that is a valid result, not a setup error. Record it and
  keep MTP off.
