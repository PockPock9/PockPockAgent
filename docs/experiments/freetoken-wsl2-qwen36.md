# Experiment: FreeToken in WSL2 for Qwen3.6-35B-A3B

**Status: unmeasured.** Nothing here has been run on Kan's PC. This is a
copy-ready experiment, not an integration — no FreeToken code is in the
app, and the app cannot point at FreeToken today (see below).

## Hardware this is for

- RTX 4070 12 GB VRAM, AMD Ryzen 7, 32 GB RAM, Windows + WSL2.
- Linux x86_64 inside WSL2, NVIDIA driver r580 or newer (CUDA 13),
  Python 3.10+.

## What FreeToken is

An Apache-2.0 MoE inference engine from UC Berkeley / UT Austin (FlashML).
Instead of a fixed GPU/CPU split it measures PCIe / RAM / GPU bandwidth
and, per token, decides how many missing experts to fetch over PCIe vs
compute on CPU. Published numbers (paper/vendor — treat as claims until
reproduced here): Qwen3.6-35B-A3B at 77–83 tok/s on an RTX 5090 vs 33–43
tok/s for the best baseline (1.8–2.3× llama.cpp/Ollama/KTransformers);
39.3 tok/s on an RTX 4060 laptop 8 GB. No published RTX 4070 or WSL2
measurement exists — that is what this experiment produces.

Qwen3.6-35B-A3B needs ~18 GB of weights in host RAM, so it fits 32 GB
RAM. The engine only supports a few model families at launch; Qwen3.6
is one of them.

Sources: https://docs.tokios.com/guides/freetoken-moe-inference ·
https://github.com/FlashML-org/FreeToken

## Setup

```powershell
# In PowerShell: raise the WSL2 RAM cap first (WSL2 defaults to 50% of
# system RAM — 16 GB here — which can force the expert pool to page).
# In %USERPROFILE%\.wslconfig:
#   [wsl2]
#   memory=28GB
# Then: wsl --shutdown  (from PowerShell), and reopen WSL2.
```

```bash
# Inside WSL2 (Ubuntu). Keep models inside the WSL2 ext4 filesystem,
# never under /mnt/c — /mnt/c disk is 30-50% the speed.
# CUDA 13 toolkit with nvcc on PATH is required: the PyPI package
# JIT-compiles its CUDA kernels on first use.
uv venv && source .venv/bin/activate
uv pip install "freetoken[accel]"

# Download the model into WSL2 (about 18 GB). A Hugging Face repo id
# also works directly as --model; a local path avoids re-downloading.
huggingface-cli download Qwen/Qwen3.6-35B-A3B --local-dir ~/models/Qwen3.6-35B-A3B
```

## Run

```bash
ft serve --model ~/models/Qwen3.6-35B-A3B
# Ready when the log says the API server is ready on 127.0.0.1:1919.
# (Some older docs say port 8000 — trust the log line, not this doc.)
# FreeToken speaks OpenAI-compatible /v1/chat/completions and
# Anthropic /v1/messages on that port.

curl http://127.0.0.1:1919/v1/models
```

## Measure

From the repo root, with FreeToken running:

```bash
python3 docs/experiments/measure-tool-calls.py \
  --base-url http://127.0.0.1:1919/v1 \
  --model Qwen3.6-35B-A3B \
  --out freetoken-qwen36.json
```

Also record a plain generation speed for comparison (prompt processing
and decode separately if the server reports them):

```bash
curl http://127.0.0.1:1919/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "Qwen3.6-35B-A3B",
  "messages": [{"role": "user", "content": "Write a Python function that reverses a string, with a docstring."}],
  "temperature": 0, "max_tokens": 300, "stream": false
}'
```

Baseline to compare against: the llama-server `--n-cpu-moe` run from
`n-cpu-moe-qwen36.md`, measured with the same script and the same
tasks. Compare all three: **tok/s, mean TTFT, and tool-call accuracy
(tasks passed)**. A faster engine that breaks tool calls is a failure,
not a win.

## What success looks like

- The model loads and serves on 12 GB VRAM + 32 GB RAM without
  OOM or falling back to host-pagefile paging.
- Tool-call accuracy on the app's tasks is at least as good as the
  llama-server baseline.
- tok/s and TTFT beat the llama-server `--n-cpu-moe` baseline by a
  clear margin (the paper claims ~2×; anything under ~1.3× is noise
  on one rig and not worth an engine change).
- `nvidia-smi` shows the GPU busy during generation, not idle while
  the CPU pages experts.

## Pointing PockPock at it

**Not supported today — do not try to wire the gateway to FreeToken
for real use.** The gateway talks to Ollama's native API (`/api/tags`,
`/api/show`, `/api/chat`) and FreeToken only speaks OpenAI-compatible
`/v1`; pointing `OLLAMA_BASE_URL` at it would break model listing,
capability checks, and chat. Running it standalone and measuring it is
the whole experiment. If the numbers justify it, the follow-up work is
a generic OpenAI-compatible backend in the gateway — a separate task,
not this experiment.

## If it fails

- `ft serve` fails to build kernels: check `nvcc --version` (CUDA 13)
  and that the `[accel]` extra installed.
- Server binds but the model never loads: check free RAM in WSL2
  (`free -g`) — the 28 GB `.wslconfig` cap matters here — and disk
  space inside the ext4 filesystem.
- Slow first tokens (tens of seconds): expected on first load while
  experts are paged in; measure TTFT after warm-up, and report both
  cold and warm numbers.
