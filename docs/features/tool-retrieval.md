# Tool retrieval (progressive disclosure)

The agent loop used to send every permitted tool schema to the model on
every turn. Tool schemas are the largest fixed cost in the agent prompt:
the full registry is ~1,900 tokens of schemas before the user request is
even read, and the cost grows with every tool added. Small local models
also pick the wrong tool more often from a long flat list.

Tool retrieval fixes both by retrieving tools in the harness, before the
model call, instead of asking the model to choose from the whole list.

## How it works

1. **Permission/risk filtering, before any ranking.** `ToolRetriever`
   removes tools the run may not use from the candidate set first, so a
   forbidden tool can never be retrieved, pinned by deterministic routing,
   or shown in the one-line index however well it matches the query. Two
   rules (see `filter_permitted_tools` in
   `backend/projects/agent_tools/tool_retriever.py`):
   - *Permission:* tools whose contract requires full access are invisible
     to `default`-mode runs — the same rule the executor enforces at call
     time (`require_agent_tool_permission`), applied here so the model
     never sees the tool at all.
   - *Risk:* high-risk tools (`risk_level == "high"`, derived from the
     contract's side effect: `workspace_write` and
     `project_check_execution` — tools that mutate existing workspace files
     or execute project code) are excluded unless the run explicitly
     allows them: `auto-review` or `full-access` permission, or an
     explicit `allow_high_risk=True`. Unknown side effects fail closed to
     high risk. Each retrieval records what was filtered out and why
     (`Retrieval.filtered_out`).
   The executor always passes the run's permission mode to
   `select_tools`; callers without a run context (eval harness, unit
   tests) get the unfiltered set so retrieval measurements stay
   comparable.
2. **Index.** `backend/projects/agent_tools/tool_retriever.py` builds one
   short retrievable document per tool from the existing registry
   (`registered_tool_contracts()` in `registry.py`). Each document holds
   the tool name, one-line description, capability (category), parameter
   names/descriptions, and a few example user phrasings. The registry
   stays the single source of truth; the retriever never hand-maintains a
   second copy of the tools.
3. **Deterministic routing.** High-confidence intents are pinned by
   keyword/regex rules first (for example, a Word/Excel/PowerPoint
   request pins `create_office_document`, an image request pins
   `generate_local_image`, a write/fix verb aimed at a named code file
   pins `propose_project_patch` / `propose_project_edit`). A rule fires
   only when both a verb and its object match, so vague requests fall
   through to retrieval. One deliberate non-match: "Fetch API" is a
   product name, not the verb "fetch", so it does not pin
   `scrape_public_page`.
4. **Hybrid retrieval.** BM25 over the tool documents (hand-rolled,
   stdlib only — no `rank-bm25` dependency) plus dense embeddings via
   Ollama `/api/embed` with `nomic-embed-text-v2-moe` when that model is
   installed. Without it, retrieval is keyword-only (BM25 + deterministic
   routing) and `ToolRetriever.status()` says so; the eval harness
   reports the same fallback note.
5. **Progressive disclosure.** The executor (`agent_core/executor.py`)
   shows the model a one-line index of every permitted, filter-passing
   tool plus the full schemas of only the top 8 retrieved tools, plus the
   always-on core tools (`list_project_files`, `read_selected_file`, when
   permitted) and the `search_tools` escape hatch (below). Delegated runs
   keep their pinned allowed-tool list and skip retrieval.
6. **Fallbacks.** If retrieval matches nothing with any confidence, or
   raises, the executor uses the full permitted tool list. A retrieval
   miss therefore costs tokens, never a failed task. Each retrieval is
   recorded as a `tool_retrieval` run event with the method, selected
   tools, schema tokens before/after, and latency.

Storage is in-memory brute force: 15 tools is a few hundred short
documents, scored in ~0.4 ms. No sqlite-vec, LanceDB, or Chroma is
needed at this scale and no new dependency was added. If the tool count
grows past a few hundred documents, the index build is the place to add
persistent storage — the `ToolRetriever` interface does not change.

## The `search_tools` escape hatch

Upfront retrieval can miss — the right tool was not in the top 8, or the
task changed mid-run. `search_tools` is a read-only meta-tool registered
in the agent tool registry like any other tool (capability
`tool_discovery`, default permission, available in every task scope), so
the model can call it to search the one-line index of permitted tools
for a follow-up need. Its contract:

- Input: `query` (required, plain words), `top_k` (optional, 1–10,
  default 5). Output: the query, matching tools with one-line
  descriptions and scores, and the retrieval method.
- It only ever returns tools the run is already permitted to use: the
  executor sets `AgentToolContext.permitted_tools` from the run's
  capability filter, and the handler searches within that set under the
  run's permission mode. Without a run context (a direct registry call)
  it falls back to read-only tools only, so a context-free search can
  never surface a write or high-risk tool.
- It is never ranked against task tools — the retriever always appends
  its schema alongside the retrieved top-k, and a search never returns
  itself.

**Hydration.** After a successful `search_tools` call the executor adds
the full schemas of the matched tools to the model's tool list
(`hydrate_tools`), tells the model in the tool result that the schemas
are now available for the next turn, and records a
`tool_search_hydration` run event. The next model turn can then call a
tool it was never given up front. Hydration never adds a tool outside
the run's permitted set, even if the search result named one.

## Context compaction

The agent loop appends every tool result to the message history, so a
long run grows the prompt without bound. `backend/projects/agent_tools/
context_compaction.py` bounds it deterministically (no model call, so
compaction never invents facts), and the executor runs it before each
model call, recording a `context_compaction` run event when it acts:

1. **Truncate at source.** Tool outputs over `POCKPOCK_MAX_TOOL_RESULT_CHARS`
   (default 50,000) are cut to head + tail with a marker giving the
   original size. When the full content lives on disk — a saved artifact,
   or the file that was read — the marker names that file as a pointer.
   Other results get a size marker only; the marker never claims the
   full text is stored somewhere it is not.
2. **Prune old tool results.** All but the most recent 3 tool messages
   become one-line stubs. The assistant messages that made the calls are
   kept, so the record of which tool was called with which arguments
   survives.
3. **Summarise the old portion.** If pruning is not enough, the oldest
   messages are replaced by a structured summary — user task, tools used,
   files mentioned, tool calls that errored as open items — while the
   system prompt and the most recent 6 messages stay intact. The cut is
   only made at a safe boundary (after a tool message, a user message,
   or an assistant message without tool calls), never between an
   assistant tool-call message and its tool results.

Compaction triggers when the estimated history passes 75% of the assumed
context window (32,768 tokens by default). All thresholds are named
constants in `context_compaction.py`, overridable by environment variable
without a restart: `POCKPOCK_CONTEXT_WINDOW_TOKENS`,
`POCKPOCK_COMPACT_AT_FRACTION` (default 0.75),
`POCKPOCK_KEEP_RECENT_MESSAGES` (default 6),
`POCKPOCK_MAX_TOOL_RESULT_CHARS` (default 50,000),
`POCKPOCK_TOOL_OUTPUT_HEAD_CHARS` (default 30,000),
`POCKPOCK_TOOL_OUTPUT_TAIL_CHARS` (default 10,000),
`POCKPOCK_PRUNE_KEEP_LAST_TOOL_RESULTS` (default 3).

## Configuration

- `POCKPOCK_TOOL_RETRIEVAL_ENABLED` environment variable, default `1`
  (on). Set to `0` to send the full permitted tool list as before.
- `ToolRetriever(top_k=...)` — default 8 full schemas. Measured on the
  eval set: top 5 keeps the same recall and saves more tokens, but 8 is
  the default for headroom on unseen phrasings.
- Context-compaction thresholds: see the previous section.

## Verification

- Unit tests: `backend/projects/agent_tools/test_tool_retriever.py`
  (retrieval correctness, deterministic pins, core tools, low-confidence
  fallback, permitted filter, permission/risk filtering, `search_tools`
  always-on + hydration, flag) and
  `backend/projects/agent_tools/test_context_compaction.py`
  (truncation, pruning, summarising, compaction stages, env override).
  `backend/projects/agent_tools/test_agent_tools.py` covers the
  `search_tools` handler (permitted-only results, bad input, read-only
  fallback without a run context).
- Eval harness: `backend/scripts/evaluate_tool_retrieval.py` — 34
  synthetic held-out phrasings plus 97 real user phrasings harvested from
  the project's own test runs (scenarios-1000, file-work, skills-mcp
  validation; each traced to its source in
  `backend/scripts/tool_retrieval_real_cases.md`), covering all 15 tools.
  It reports Recall@5 / Recall@10, schema tokens per turn before/after,
  retrieval latency, and the method mix, separately for the combined set
  and the real-only set; it exits non-zero when combined Recall@5 < 0.90.
- Measured on 2026-11-18 (keyword-only path, no embedding model
  installed): **combined Recall@5 0.992, Recall@10 1.000; real-only
  Recall@5 0.990, Recall@10 1.000**, schema tokens ~1,909 → ~1,227 per
  turn (−36%), retrieval latency mean 0.44 ms. The saving is modest
  because the registry has 15 tools; it grows as tools are added. The one
  real miss at @5 is scenarios-1000 #405 ("Using developer.mozilla.org,
  summarize what the Fetch API does and cite the page"), which ranks
  `search_public_site` 6th behind the single-page scrape tool — a
  genuinely ambiguous single-page vs multi-page research request.

## Dense embeddings — wired, untested live on this VM

The dense path is implemented (`OllamaEmbedder`, `/api/embed` with
`nomic-embed-text-v2-moe`, hybrid mean of normalised BM25 + cosine
scores) but has not been exercised end to end: the model is not
installed in Ollama on this machine, and three pull attempts on
2026-11-18 all failed at the manifest fetch (`pull model manifest:
context deadline exceeded` after the 60 s client deadline), even though
the registry itself answers curl. Running the eval with `--embed` falls
back to the keyword-only path and reports identical numbers — no dense
numbers exist yet, and none are claimed. To measure the hybrid path,
install the model (`ollama pull nomic-embed-text-v2-moe`, on a machine
where the registry manifest fetch succeeds) and rerun the eval with
`--embed`; expect Recall@5/Recall@10, latency, and token reduction for
dense on vs off to be recorded then.

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
  eval gate is Recall@5 ≥ 0.90 on every registry change. The
  `search_tools` escape hatch is the recovery path for a miss the model
  notices mid-task.
- Permission/risk filtering removes a tool the task seems to need: the
  tool is absent from both the index and the schemas, and the run event
  records it in `filtered_out` with the reason. That is the filter
  working as designed — a `default`-mode run must not be offered
  workspace-write tools — not a retrieval bug. Escalate by running with
  auto-review or full-access permission.
- Compaction cannot shrink a history enough (for example, a single huge
  tool result plus a tiny window): it prunes what it can and reports
  stage `pruned-only`; the run continues with the pruned history.

## Related work (not done here)

- A tiny classifier reranker (TinyAgent-style) is the planned upgrade
  over pure embedding retrieval.
- Fine-tuning a model on tool traces is deliberately deferred until
  retrieval and evals are measured — fine-tuning on top of bad retrieval
  bakes in bad habits.
