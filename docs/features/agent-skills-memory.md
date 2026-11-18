# Self-authored skill + reasoning memory

Phase 1 of the agentic-AI differentiation plan: the agent gets better
every week by distilling its own runs into reusable skills, workflows,
and reasoning tips — stored locally, verified before use, and retrieved
into later runs. See `backend/projects/agent_skills/README.md` for the
module-level contract; this page is the feature-level contract.

## Purpose

A small local model will not out-reason a frontier model. It can
out-remember: procedures substitute for raw capability on the user's own
repeated tasks. The asset is the distilled, verified procedural unit —
not the raw run transcript. Paper evidence this is modelled on (not
replicated here): Agent Workflow Memory +24.6% Mind2Web / +51.1%
WebArena; ReasoningBank WebArena 40.5% → 48.8%, SWE-bench 34.2% →
38.8%, steps −16%; Voyager 3.3× items. Local target: +10pp success and
−15% steps on the user's repeated tasks, with ~0 regressions from added
memories.

## User flow

1. The agent finishes a run. Distillation drafts candidates — a skill
   (`SKILL.md`), an abstracted workflow, and 1–3 reasoning tips —
   into the skill inbox as `pending`. Nothing is usable yet.
2. The user (or a later automation step) reviews the inbox, runs each
   candidate's verification test, and approves or rejects it with a
   reason. Approval without a passed test is a recorded override.
3. Approved skills are retrievable into later runs (only while the
   `POCKPOCK_SKILLS_ENABLED` flag is on; default off). Approved tips
   are injected as short DO / DO NOT lines.
4. Maintenance runs periodically: contradictory tips are invalidated
   (never silently overwritten) and disused / expired / low-confidence
   items are pruned; every decision is logged.

## Modules involved

- `backend/projects/agent_skills/` — `skills.py` (library, SKILL.md
  format, BM25 + optional Ollama dense retrieval), `memory.py`
  (reasoning tips + fact store in SQLite), `distiller.py` (stub +
  Ollama `think: false` distiller), `inbox.py` (promotion gate +
  verification runner), `maintenance.py` (contradiction + pruning),
  `service.py` (facade).
- `backend/scripts/distill_skill.py`, `backend/scripts/skill_inbox.py`
  — CLI for distillation and inbox review.
- `backend/scripts/pockpock_server.py` — `/api/skills*` routes
  (list, inbox, distill, verify, approve, reject, retrieve, maintain).
- `backend/projects/agent_core/executor.py` — appends the retrieved
  skill/tip context block to a run's system prompt when
  `POCKPOCK_SKILLS_ENABLED` is set.

## Data and control flow

- Skill files live under `<app-data>/PockPock/agent-skills/<name>/SKILL.md`
  (override: `POCKPOCK_SKILLS_DIR`); candidates, the skill registry,
  tips, facts, and the pruning log live in
  `<app-data>/PockPock/agent-skills.sqlite3` (override:
  `POCKPOCK_SKILLS_DB`).
- Retrieval filters on lifecycle status *before* ranking: only
  `promoted` skills and `active` tips can reach a run. The promotion
  gate cannot be bypassed by a retrieval bug.
- Verification tests run in a fresh temp directory with a timeout:
  `script` (exit 0 passes), `python` (no exception passes), `manual`
  (human approval is the verification).

## Configuration

- `POCKPOCK_SKILLS_ENABLED` — skill retrieval into live runs; default
  off, so existing behaviour is unchanged.
- `POCKPOCK_SKILLS_DIR`, `POCKPOCK_SKILLS_DB` — storage locations.
- `POCKPOCK_DISTILL_MODEL` — distillation model (default
  `qwen3.5:2b`); `POCKPOCK_OLLAMA_URL` — Ollama base URL.

## Permission / security boundaries

- No external memory platform is integrated (no Mem0/Zep/Graphiti/
  Letta); everything is local files + SQLite.
- Verification scripts run via subprocess in a temp dir with a minimal
  environment. Only run verification for candidates from a trusted
  source (own runs, or human-reviewed inbox entries) — a malicious
  skill file could ship a malicious test.
- Skills never change task scope, permissions, tools, or safety
  behaviour; they are context only, and the executor still validates
  every tool call.
- Private run content is distilled into skills only from the user's own
  runs on their own machine; nothing leaves the machine.

## Failure states

- Distillation model unavailable or output unparsable → the
  deterministic stub distiller is used instead; distillation never
  fails a run (it runs after the run, not during it).
- No embedding model installed → retrieval is keyword-only (BM25) and
  says so; this is the normal state, not an error.
- Verification test fails or times out → the candidate stays `pending`
  and cannot be approved without a recorded force-override.
- Skill retrieval fails inside the executor → the run continues with
  no skill context; a miss costs context, never the task.

## Verification

- `python -m unittest discover -s projects/agent_skills -t . -p "test_*.py"`
  from `backend` (63 tests, including the full lifecycle test:
  distil → candidate → verification → promotion → retrieval returns
  it; unverified candidate is NOT retrieved).
- `python backend/scripts/run_tests.py` for the full backend suite.
- Lifecycle demo: `backend/scripts/distill_skill.py run.json`, then
  `backend/scripts/skill_inbox.py list / verify / approve`, then
  retrieve — see the package README.
