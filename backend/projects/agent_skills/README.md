# Self-authored skill + reasoning memory

Phase 1 of the agentic-AI differentiation plan (research: §3, §5 item #1).
The agent gets better every week: after each run, a distiller extracts a
reusable skill, an abstracted workflow, and 1–3 reasoning tips; a
promotion gate decides what becomes usable; retrieval reuses the Tool-RAG
path. Raw episodic logs are input material, not the asset — what transfers
is the distilled, verified procedural unit.

Evidence this is modelled on (papers, not replicated here): Agent Workflow
Memory +24.6% Mind2Web / +51.1% WebArena; ReasoningBank WebArena 40.5% →
48.8%, SWE-bench 34.2% → 38.8%, steps −16%; Voyager 3.3× items. The local
target is direction, not magnitude: +10pp on the user's own repeated
tasks, −15% steps, ~0 regressions from added memories.

## What lives here

| Module | What it does |
|---|---|
| `skills.py` | Skill schema + validation, SKILL.md frontmatter, disk CRUD, retrieval (BM25 + optional Ollama dense embeddings, keyword-only fallback — same pattern as `agent_tools/tool_retriever.py`). |
| `memory.py` | ReasoningBank-style tips (title/description/content, incl. FAILURE tips) and a semantic fact store, both in local SQLite. Confidence, source run id, expiry on every item. |
| `distiller.py` | Drafts candidates from a run record: skill + workflow + tips. `StubDistiller` is deterministic/offline; `OllamaDistiller` uses the small local model with `think: false` and falls back to the stub on any failure. |
| `inbox.py` | **The promotion gate (build first).** Candidates sit in the skill inbox as `pending`; each ships with a verification test (script / Python / manual). `approve` requires a passed test or an explicit recorded human override. Unverified candidates are never retrieved. |
| `maintenance.py` | Contradiction detection (same task + same action, opposite kinds → lower-confidence tip invalidated, never overwritten) and pruning (disused / expired / low-confidence), every decision logged. |
| `service.py` | Facade: `AgentSkillsService` wires the pieces together; `retrieve_for_task` / `context_block_for_task` are what a live run sees. |

## Storage

- Skill files: `<app-data>/PockPock/agent-skills/<name>/SKILL.md` (plus
  optional `scripts/`, `references/`). Override with `POCKPOCK_SKILLS_DIR`.
- SQLite: `<app-data>/PockPock/agent-skills.sqlite3` — candidates,
  skill registry (lifecycle status), reasoning tips, facts, pruning log.
  Override with `POCKPOCK_SKILLS_DB`.
- No graph DB, no external service, no new dependency. No Mem0/Zep/
  Graphiti/Letta integration (their benchmark numbers are disputed).

## Lifecycle

```
draft (distilled) -> pending in inbox -> verified (test passed)
  -> promoted (human approved) -> retrieved into runs
  -> pruned / invalidated (maintenance or reviewer)
```

- A skill is retrievable only while `promoted`; a tip only while
  `active`. Retrieval filters on status *before* ranking, so a gate bug
  cannot leak an unverified candidate into a run.
- Contradiction: the loser is marked `invalidated`, never overwritten;
  the old value stays readable and the decision is in the pruning log.
- Facts: a new value for the same (subject, predicate) invalidates the
  old row (same rule), it never updates the value in place.

## Skill format (open Agent Skills format)

```markdown
---
name: "summarise-csv"
description: "Summarise a CSV file into a short markdown table."
version: "1.0.0"
verification: {"type": "python", "code": "assert 1 + 1 == 2"}
tags: ["csv"]
---

# Summarise a CSV

1. Read the CSV file.
2. Write a short markdown table.
```

`verification.type` is `script` (`{"command": [...]}` run in a fresh temp
dir, exit 0 passes), `python` (snippet, no exception passes), or `manual`
(no automated test — human approval is the verification).

## Inbox workflow

1. Distil a run: `python backend/scripts/distill_skill.py run.json`
   (or `POST /api/skills/distill`). Candidates appear in the inbox.
2. Review: `python backend/scripts/skill_inbox.py list`
   (or `GET /api/skills/inbox`).
3. Verify a candidate's test: `skill_inbox.py verify <id>`
   (or `POST /api/skills/inbox/<id>/verify`).
4. Approve: `skill_inbox.py approve <id> --reason "..."`
   (or `POST /api/skills/inbox/<id>/approve`). Reject with a reason the
   same way. Approval without a passed test needs `--force` and is
   recorded as an override in the decision reason.

## Live-run wiring (off by default)

Skill retrieval into agent runs is behind `POCKPOCK_SKILLS_ENABLED`
(default off). When on, the executor appends a short context block of
promoted skills + active tips (skill bodies truncated to 4,000 chars) to
the run's system prompt. Existing behaviour is unchanged while the flag
is off.

## Verification

Run `python -m unittest discover -s projects/agent_skills -t . -p "test_*.py"`
from `backend`. The suite includes a full lifecycle test: distil from a
fake run → candidate → verification → promotion → retrieval returns it,
and an unverified candidate is NOT retrieved.
