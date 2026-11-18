# Plan-and-Sequence P1 measurement report

Generated 2026-11-18 04:19 UTC by `backend/scripts/evaluate_plan_sequence.py`. Token counts use the repo's `estimate_tokens` (~4 chars per token), the same estimator the runner uses — they are estimates, not tokenizer counts.

## Method

- **Task sample:** 6 hand-written reference plans (NOT model output). Task (a) is the spec's Canva-invoices worked example, adapted: the spec's `gmail_search` / `read_message` / `calculator` / `write_file` tools do not exist in the registered catalog (15 tools), so the invoices arrive as an attached file and the addition is done by the executor. Tasks (b)–(f) come from `tool_retrieval_real_cases.md` (scenarios-1000 #233, #327, #477, #376, #239). Each plan has 5 steps, typed done-conditions, and 1 pinned tool per step.
- **Measurement A (deterministic, no model):** per-step prompt tokens via `build_step_prompt` with the real `ToolRetriever` specs and the capsule at each step boundary; scripted calls executed once through the real tool adapter in a scratch workspace so capsule entries are real.
- **Measurement B (fake model, real tools):** `SequenceRunner` over each plan with a scripted fake chat client (one scripted tool call per step, `think=False` asserted) and the real `execute_agent_tool` / `execute_project_tool` path against a temp workspace. This measures the harness (runner, verifier, capsule), NOT model ability — a real model would have to produce these calls itself.
- **Measurement C (live, bounded):** one sequenced run against local Ollama `qwen3.5:2b`, 120 s overall cap. See below.
- **Monolithic baseline:** the spec's own figure — PockPock's measured ~21K-token OpenClaw system prompt — plus the full 15-tool schemas measured here (1,909 tokens). Whether the 21K already includes tool schemas is not established, so both 21,000 (prompt only) and 22,909 (prompt + schemas) are reported.

## Measurement A — prompt tokens per step (deterministic)

| Task | Steps | Max step prompt | Total prompt | Max capsule | Steps > 1,500 |
| --- | ---: | ---: | ---: | ---: | ---: |
| canva-invoices | 5 | 311 | 1278 | 40 | 0 |
| expenses-csv | 5 | 326 | 1333 | 54 | 0 |
| report-summary | 5 | 340 | 1387 | 54 | 0 |
| data-scores | 5 | 339 | 1340 | 22 | 0 |
| policy-diff | 5 | 390 | 1418 | 109 | 0 |
| invoices-sheet | 5 | 346 | 1403 | 54 | 0 |

Per-step detail:

- **canva-invoices**: list-files=200 (capsule 1), read-invoices=237 (capsule 11), extract-amounts=311 (capsule 40), write-summary=278 (capsule 7), verify-summary=252 (capsule 7)
- **expenses-csv**: list-files=206 (capsule 1), read-expenses=255 (capsule 11), write-csv=326 (capsule 54), write-summary=283 (capsule 8), verify-summary=263 (capsule 9)
- **report-summary**: list-files=204 (capsule 1), read-report=250 (capsule 11), write-summary=332 (capsule 54), write-doc=340 (capsule 9), verify-summary=261 (capsule 9)
- **data-scores**: list-files=205 (capsule 1), read-data=236 (capsule 8), write-summary=299 (capsule 22), write-sheet=339 (capsule 9), verify-summary=261 (capsule 9)
- **policy-diff**: list-files=208 (capsule 1), read-old=260 (capsule 16), read-new=298 (capsule 54), write-diff=390 (capsule 109), verify-diff=262 (capsule 8)
- **invoices-sheet**: list-files=206 (capsule 1), read-invoices=253 (capsule 11), write-notes=335 (capsule 54), write-sheet=346 (capsule 9), verify-notes=263 (capsule 9)

Across all 6 tasks: max step prompt **390 tokens**, max capsule **109 tokens**, total sequenced prompt tokens **8159** over 30 steps (mean 272 per step). Monolithic baseline per call: 21,000 (prompt only) / 22,909 (prompt + schemas). A sequenced step prompt is ~1.7% of the monolithic per-call prompt at worst.

## Measurement B — runner end-to-end (fake model, real tools)

| Task | Status | Steps passed | Retries | Total prompt tokens | Final capsule |
| --- | --- | ---: | ---: | ---: | ---: |
| canva-invoices | completed | 5/5 | 0 | 1278 | 120 |
| expenses-csv | completed | 5/5 | 0 | 1333 | 134 |
| report-summary | completed | 5/5 | 0 | 1387 | 141 |
| data-scores | completed | 5/5 | 0 | 1340 | 103 |
| policy-diff | completed | 5/5 | 0 | 1418 | 190 |
| invoices-sheet | completed | 5/5 | 0 | 1403 | 140 |

Step success rate: **30/30 (100%)** with the scripted fake model. End-to-end task success: **6/6 tasks completed**. Retries used: 0. `think=False` on every chat call: True. No capsule dropped pointers: True.

## Measurement C — live run (Ollama qwen3.5:2b, bounded)

**Not measured — live run exceeded the 120s overall budget.**

No model was pulled and no service was restarted.
## Verdicts on the P1 targets

- **~1,500 tokens per step: confirmed (max 390 tokens over 30 steps, 0 steps over target).**
- **Capsule ≤ 400 tokens: confirmed (max 109 tokens at any step boundary; final capsules ≤ 190 tokens).**
- **Step success rate (sequenced, fake model): 30/30 passed. This measures the harness, not model ability — it says the runner, verifier, and capsule work when the executor makes the right calls.
- **End-to-end task success vs the monolithic path: NOT MEASURED. There is no monolithic runner to run the same tasks through, and no live monolithic comparison was attempted. Prior PockPock validation (Nov 2026) found qwen3.5:2b OpenClaw turns never completed against the ~21K-token prompt; that is prior evidence, not a P1 measurement.
- **Live executor behaviour (real qwen3.5:2b): NOT MEASURED — see Measurement C.**

## Findings beyond the targets

- **No in-repo adapter from the runner to the real tools.** `SequenceRunner` expects `execute_tool` to return `{"ok", "output", "exit_code", "error"}`, but `execute_agent_tool` / `execute_project_tool` return bare result dicts with no `ok`/`output` keys (a bare success would read as `ok=False` to the runner). This eval supplies the translation in `RealToolAdapter`; the repo needs a real one before the runner can run against live tools outside this harness.
- **The spec's worked-example tools do not exist.** `gmail_search`, `read_message`, `calculator`, and `write_file` are not among the 15 registered tools, so the Canva task as written in the spec cannot validate as a sequence plan. The adapted version (attached invoices, executor-side addition) is what was measured.
- **No gateway run-sequence endpoint exists.** The planner service has `POST /plan-sequence`; the gateway has no `/api/agents/plan-sequence` or `/api/agents/run-sequence` route, and `openclaw_bridge` does not send a subtask yet (subtask mode lives only in the Node helper). End-to-end sequenced runs through the product surface are therefore not yet possible.

## Limits of this measurement

- Token counts are `estimate_tokens` (~4 chars/token) estimates, not tokenizer counts; the same estimator is used on both sides of the comparison, so the ratio is more reliable than the absolute numbers.
- Reference plans are hand-written, not planner output: plan quality (decomposition correctness) is not measured here.
- Measurement B's fake model always makes the right call, so its 100% step success rate must not be quoted as model performance.
- The monolithic baseline's 21K figure is cited from the spec (PockPock's own Nov 2026 validation), not re-measured here.
