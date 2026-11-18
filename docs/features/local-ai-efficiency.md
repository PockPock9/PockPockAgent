# Local-AI efficiency (app-level wins)

The app-level changes from the local-AI efficiency research (research notes
in `~/workspace/research_notes/local-ai-efficiency-*/`, plan in
`~/workspace/pockpock-test/wiki/Local-AI-Efficiency.md`). The research
conclusion was that Ollama *is* llama.cpp for GGUF models, so there is no
faster engine to switch to — the wins are configuration, routing, and
harness hygiene. This page documents what the app does today. The
model-swap and engine experiments (Qwen3.6, FreeToken, MTP) are experiments
only, under `docs/experiments/` — none of them is integrated into the app.

## Model routing: small model for simple turns

Simple/triage turns run on the small model instead of a mid-size one:

- The Smart Router's `quick_model` valve defaults to `qwen3.5:2b` — the
  model already installed as the router classifier — instead of
  `qwen2.5:7b`. The heuristic gate (greetings, short factual questions
  under 60 characters) and the classifier's `quick` category both map to
  it. Routing is deterministic and heuristic-first: no extra model call
  decides whether a turn is simple.
- Reasoning, code, agentic, and vision turns keep their larger configured
  models (`reasoning_model`, `code_model`/`heavy_code_model`,
  `agentic_model`, `vision_model`).
- If the small model is not installed, the turn falls back to the
  configured general model instead of failing:
  `Pipe.resolve_routed_model()` in `backend/scripts/smart_router.py`
  returns the general model for a missing `quick_model`, and the gateway's
  `/api/chat` prefers that default over the first enabled model when an
  auto-routed model is disabled or missing. A manually picked model is
  never replaced — picking a missing model still errors.
- Tool-call drafting stays on the agent's tool-capable model: the
  draft-then-verify pattern from the research is not implemented, and
  the 2B model's tool-call reliability is unproven (its BFCL-V4 score is
  well below the triage pick's), so the small model is used for chat
  triage only, never for agent tool loops.

Modules: `backend/scripts/smart_router.py`,
`backend/scripts/pockpock_server.py` (`/api/chat`).
Tests: `backend/scripts/test_smart_router.py`.

## Keep-alive and context window

Every local Ollama request sends two settings the gateway previously left
at Ollama's defaults (see `backend/projects/model_router/client.py`):

| Setting | Default sent | Ollama default | Why |
|---|---|---|---|
| `keep_alive` | `30m` | `5m` | The model stays resident between turns of one session instead of unloading and paying a reload on the next turn. Staying resident also keeps its KV cache alive for the next turn (see prefix caching). |
| `num_ctx` | `16384` | `4096` on cards under 24 GB | 4K truncates ordinary agent turns. 16K fits them while keeping KV-cache VRAM in check (about 3 GB for a 14B model). |

Both are named constants (`DEFAULT_KEEP_ALIVE`,
`DEFAULT_CONTEXT_WINDOW_TOKENS`), env-overridable
(`POCKPOCK_OLLAMA_KEEP_ALIVE`, `POCKPOCK_NUM_CTX`; an invalid
`POCKPOCK_NUM_CTX` falls back to the default), and an explicit
`ChatCompletionRequest.context_window` or `keep_alive` wins over the
defaults. A caller-supplied `num_ctx` option wins over the default but
not over `context_window`. The defaults apply on the native `/api/chat`
path and on the OpenAI-compatible `/v1/chat/completions` tool path —
tool-call turns previously sent neither, so agent turns ran on the 4K
default. The shared `to_payload()` contract used by cloud providers is
unchanged; these fields are added by the Ollama adapter only.

Raising `POCKPOCK_NUM_CTX` much above 16K costs KV VRAM (roughly
200 KB per token for a 14B model) and can force partial CPU offload on
a 12 GB card. The agent loop's compaction budget (32K estimated tokens,
compact at 75%) is separate: compaction bounds prompt growth and
latency, while `num_ctx` bounds what Ollama allocates.

Tests: `backend/projects/model_router/test_client.py`.

## Prefix caching: what is stable, what invalidates it

Ollama keeps a KV cache per loaded model automatically; the win comes
from a byte-identical stable prefix, because matching is exact at the
token level — one reordered tool definition or a per-turn timestamp in
the prefix silently zeroes the hit rate.

Verified stable within a run or conversation:

- **Agent loop** (`backend/projects/agent_core/executor.py`): the system
  prompt is built once per run from fixed strings plus run-scoped values
  (workspace path, task, allowed hosts, attachment names); the tool
  index lines from retrieval are appended to it once, before the loop.
  Tool schemas come from the registry in deterministic insertion order,
  and retrieval returns them in deterministic ranked order. History is
  append-only. No timestamps or random IDs are placed in the messages
  sent to the model (timestamps and run IDs live in telemetry events,
  not in the prompt).
- **Gateway chat** (`/api/chat`): `prepare_chat_messages()` in
  `backend/scripts/pockpock_server.py` merges saved preferences and the
  router's role directive into a single system message, in a fixed
  order, so the prefix is one stable block instead of two messages
  whose order could vary.

What invalidates the cache (expected, not bugs): compaction replaces
the middle of the history with a summary, so the turn after a
compaction re-prefills; `search_tools` hydration appends newly
discovered tool schemas mid-run; switching models unloads the previous
model's cache. Compaction is therefore deliberately rare (75% of the
window) rather than per-turn.

## Chat compaction

`/api/chat` previously re-sent the full transcript every turn with no
bound. It now runs the same deterministic compaction as the agent loop
(`backend/projects/agent_tools/context_compaction.py`: prune old tool
results, then summarise the old portion keeping a recent tail, at 75%
of a 32K-token window). The gateway-built shape — exactly one system
message at index 0 — is compacted; when the client sent its own system
message the history is left uncompacted so that message is never
summarised away. A `context_compaction` telemetry event is recorded
when chat compaction runs, as in the agent loop. Compaction is
deterministic and never calls a model, so it cannot invent facts about
the conversation.

Tests: `backend/scripts/test_pockpock_chat.py`
(`prepare_chat_messages`: merge, no-compaction shapes, long-history
compaction with the system message and recent tail intact).

## Configuration summary

| Setting | Default | Where |
|---|---|---|
| `POCKPOCK_OLLAMA_KEEP_ALIVE` | `30m` | `backend/projects/model_router/client.py` |
| `POCKPOCK_NUM_CTX` | `16384` | `backend/projects/model_router/client.py` |
| `POCKPOCK_CONTEXT_WINDOW_TOKENS` | `32768` | `backend/projects/agent_tools/context_compaction.py` |
| `POCKPOCK_COMPACT_AT_FRACTION` | `0.75` | `backend/projects/agent_tools/context_compaction.py` |
| `POCKPOCK_MAX_TOOL_RESULT_CHARS` | `50000` | `backend/projects/agent_tools/context_compaction.py` |

## Experiments (not integrated)

Copy-ready experiment scripts for Kan's RTX 4070 PC live in
`docs/experiments/`:

- `freetoken-wsl2-qwen36.md` — FreeToken in WSL2 for Qwen3.6-35B-A3B.
- `mtp-ab-qwen36.md` — native MTP speculative decoding A/B (tool-call
  accuracy MTP on vs off).
- `n-cpu-moe-qwen36.md` — the `--n-cpu-moe` / `--moe-cache-mib`
  llama-server recipe for Qwen3.6-35B-A3B on 12 GB VRAM.
- `measure-tool-calls.py` — shared measurement script (tok/s, TTFT,
  tool-call accuracy on the app's own tasks) used by the FreeToken and
  MTP experiments.

All results are unmeasured until Kan runs them on the RTX 4070 PC. No
FreeToken or MTP code is in the app itself, and pointing the gateway at
an alternate backend is not supported today (see the FreeToken doc).

## Deliberately not done

- No model swap: the default model is unchanged (no Qwen3.6 default),
  and Kimi K3, vLLM/SGLang, fine-tuning, ExLlamaV3, TensorRT-LLM, and
  FP4 are all out of scope.
- No llama-server backend in the app and no engine switch: Ollama
  stays the default backend.
- No planner timeout or executor zero-tools fix (separate issues).
- No draft-then-verify for tool calls (see routing above).

## Verification

- `python -m py_compile` on every changed module.
- `backend/scripts/run_tests.py` (full backend suite).
- A real `qwen3.5:2b` chat turn against the running Ollama instance
  confirms the small model answers simple turns; the gateway itself
  was not started for verification (it was not running).
