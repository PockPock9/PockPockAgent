# Tool retrieval (progressive disclosure)

The agent loop used to send every permitted tool schema to the model on
every turn. Tool schemas are the largest fixed cost in the agent prompt:
the full registry is ~1,700 tokens of schemas before the user request is
even read, and the cost grows with every tool added. Small local models
also pick the wrong tool more often from a long flat list.

Tool retrieval fixes both by retrieving tools in the harness, before the
model call, instead of asking the model to choose from the whole list.

## How it works

1. **Index.** `backend/projects/agent_tools/tool_retriever.py` builds one
   short retrievable document per tool from the existing registry
   (`registered_tool_contracts()` in `registry.py`). Each document holds
   the tool name, one-line description, capability (category), parameter
   names/descriptions, and a few example user phrasings. The registry
   stays the single source of truth; the retriever never hand-maintains a
   second copy of the tools.
2. **Deterministic routing.** High-confidence intents are pinned by
   keyword/regex rules first (for example, a Word/Excel/PowerPoint
   request pins `create_office_document`, an image request pins
   `generate_local_image`). A rule fires only when both a verb and its
   object match, so vague requests fall through to retrieval.
3. **Hybrid retrieval.** BM25 over the tool documents (hand-rolled,
   stdlib only — no `rank-bm25` dependency) plus dense embeddings via
   Ollama `/api/embed` with `nomic-embed-text-v2-moe` when that model is
   installed. Without it, retrieval is keyword-only (BM25 + deterministic
   routing) and `ToolRetriever.status()` says so; the eval harness
   reports the same fallback note.
4. **Progressive disclosure.** The executor (`agent_core/executor.py`)
   shows the model a one-line index of every permitted tool plus the full
   schemas of only the top 8 retrieved tools, plus the always-on core
   tools (`list_project_files`, `read_selected_file`, when permitted).
   Delegated runs keep their pinned allowed-tool list and skip retrieval.
5. **Fallbacks.** If retrieval matches nothing with any confidence, or
   raises, the executor uses the full permitted tool list. A retrieval
   miss therefore costs tokens, never a failed task. Each retrieval is
   recorded as a `tool_retrieval` run event with the method, selected
   tools, schema tokens before/after, and latency.

Storage is in-memory brute force: 14 tools is a few hundred short
documents, scored in ~0.3 ms. No sqlite-vec, LanceDB, or Chroma is
needed at this scale and no new dependency was added. If the tool count
grows past a few hundred documents, the index build is the place to add
persistent storage — the `ToolRetriever` interface does not change.

## Configuration

- `POCKPOCK_TOOL_RETRIEVAL_ENABLED` environment variable, default `1`
  (on). Set to `0` to send the full permitted tool list as before.
- `ToolRetriever(top_k=...)` — default 8 full schemas. Measured on the
  eval set: top 5 keeps the same recall and saves more tokens, but 8 is
  the default for headroom on unseen phrasings.

## Verification

- Unit tests: `backend/projects/agent_tools/test_tool_retriever.py`
  (retrieval correctness, deterministic pins, core tools, low-confidence
  fallback, permitted filter, flag).
- Eval harness: `backend/scripts/evaluate_tool_retrieval.py` — 34
  held-out realistic task phrasings (written separately from the
  retriever's example phrases) covering all 14 tools. It reports
  Recall@5 / Recall@10, schema tokens per turn before/after, retrieval
  latency, and the method mix; it exits non-zero when Recall@5 < 0.90.
- Measured on 2026-11-18 (keyword-only path, no embedding model
  installed): **Recall@5 1.000, Recall@10 1.000**, schema tokens
  ~1,714 → ~1,050 per turn (−39%), retrieval latency mean 0.33 ms.
  The saving is modest because the registry has 14 tools; it grows as
  tools are added. Dense embeddings were not measured — the
  `nomic-embed-text-v2-moe` model is not installed in Ollama on this
  machine, so the hybrid path has not been exercised end to end yet.

## Failure states

- Embedding model missing: keyword-only retrieval, noted in status and
  eval output. Not an error.
- Retrieval raises (for example, Ollama unreachable during embedding):
  caught in the executor, logged, full tool list used.
- Retrieval matches nothing: `fallback-full` method, full tool list used.
- The model names a tool that was not selected: the executor's existing
  unavailable-tool retry tells it which tools it really has; it cannot
  call a tool whose schema it never saw, so a retrieval miss can still
  cost a turn. This is why the default top-k is 8, not 5, and why the
  eval gate is Recall@5 ≥ 0.90 on every registry change.

## Related work (not done here)

- Dense embeddings are implemented but untested live (no embed model
  installed). Install `nomic-embed-text-v2-moe` in Ollama and rerun the
  eval with `--embed` to measure the hybrid path.
- A tiny classifier reranker (TinyAgent-style) is the planned Phase 2
  upgrade over pure embedding retrieval.
- Fine-tuning a model on tool traces is deliberately deferred until
  retrieval and evals are measured — fine-tuning on top of bad retrieval
  bakes in bad habits.
