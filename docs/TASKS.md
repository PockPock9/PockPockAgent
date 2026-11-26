# Agent capability implementation tracker

This is the execution queue for [the agent capability roadmap](ROADMAP.md). An AI agent starting work should read this tracker, `AGENTS.md`, and the roadmap before editing code.

**Tracker updated:** 2026-11-21

**2026-11-15 change:** the web frontend (`frontend/app`) was removed; the only interface is the Electron desktop app in `desktop/`. Completion notes below that mention `frontend/app/...` files, the Conversations page or 390/1440 px browser checks describe work as it was done then; the same behaviour now lives in `desktop/src/` (see [desktop app](features/desktop-app.md)). New UI work targets the desktop app. The Chrome companion scaffold (`backend/projects/chrome_companion/`) was also removed, so the AUT-02 group (AUT-02B, B1–B3 and C) is blocked until signed-in browser access is reconsidered; OpenClaw now covers operating the user's real browser and PC.  
**Rule:** pick one task only: the highest-priority `Ready` task whose dependencies are all `Done`. If none is ready, report the blocking dependency. Do not start `Blocked`, `In progress`, or `Not started` work without explicitly coordinating with the current task owner.

## Status and agent handoff rules

- `Ready`: all listed dependencies are `Done`; work may start.
- `In progress`: an agent has begun the task. Record the owner/session and start date in the notes below before substantial edits.
- `Blocked`: work cannot proceed; record the blocking fact and the dependency or user decision needed.
- `Done`: implementation, acceptance checks, documentation, and verification are complete. Include links to changed files, commands/checks run, and any limitations in the completion note.
- `Not started`: dependencies are not complete or the task is later in the sequence.

When starting, change exactly one task from `Ready` to `In progress` and record the owner. When finishing, update it to `Done` only after checking every acceptance item. Update this file's tracker date, status table, and task completion note in the same change as the implementation. Recompute which dependent tasks are `Ready`; keep all other tasks `Not started`. Do not mark work `Done` based on a plan, stub, or unverified claim. Update the relevant feature docs and architecture as required by `AGENTS.md`.

If a task is too large, first split it into child IDs here and define their dependencies and acceptance checks. Preserve the parent as a tracking group, not a duplicate implementation task. Do not silently change priority order or relax a safety gate.

## Queue

Choose the first `Ready` task in this table. Priority order is computer/browser automation, internet research, planning/reasoning, multi-agent systems, then the planned local interaction and automation expansion. Foundation tasks enable the first priority and therefore come first.

| Order | ID | Task | Depends on | Status |
| ---: | --- | --- | --- | --- |
| 1 | TOL-01 | Move agent tool catalog and tests into the dedicated tools project | — | Done |
| 2 | FND-01 | Define typed tool and task-run contracts | TOL-01 | Done |
| 3 | TOL-02 | Split tools into capability modules and registry | TOL-01, FND-01 | Done |
| 4 | FND-02 | Add durable cancellation and timeout lifecycle | FND-01 | Done |
| 5 | FND-04 | Persist approvals and tool outcome events | FND-01, FND-02 | Done |
| 6 | BRW-01 | Add isolated browser runtime project and lifecycle | FND-02, FND-04 | Done |
| 7 | BRW-02 | Add bounded, read-only public navigation | BRW-01 | Done |
| 8 | BRW-03 | Show browser activity and evidence in the chat timeline | BRW-02 | Done |
| 9 | BRW-04 | Add state-bound click, type, select, scroll, and navigation actions | BRW-03, FND-04 | Done |
| 10 | BRW-05 | Add per-action approval and high-impact stop rules | BRW-04 | Done |
| 11 | BRW-06 | Browser workflow recipes (tracking group) | BRW-05 | Done |
| 11.1 | BRW-06A | Define local recipe schema and versioned storage | BRW-05 | Done |
| 11.2 | BRW-06B | Add recipe inspect, edit, and disable UI | BRW-06A | Done |
| 11.3 | BRW-06C | Safe recipe execution (tracking group) | BRW-06B, BRW-05 | Done |
| 11.31 | BRW-06C1 | Add deterministic runtime execution with checkpoints | BRW-06B | Done |
| 11.32 | BRW-06C2 | Orchestrate approved recipe runs and persist step events (tracking group) | BRW-06C1, FND-04 | Done |
| 11.321 | BRW-06C2A | Define versioned recipe-run event contract | FND-01 | Done |
| 11.322 | BRW-06C2B | Execute recipe steps through gateway approvals | BRW-06C2A, BRW-05 | Done |
| 11.323 | BRW-06C2C | Persist recipe evidence and terminal run outcomes | BRW-06C2B, BRW-06C1 | Done |
| 11.33 | BRW-06C3 | Add explicit run inputs, launch, and result UI | BRW-06C2 | Done |
| 12 | RES-01 | Define search provider and source contracts | BRW-02, FND-01 | Done |
| 13 | RES-02 | Add explicit provider configuration and disclosure | RES-01 | Done |
| 14 | RES-03 | Implement bounded search, fetch, and source deduplication | RES-02 | Done |
| 15 | RES-04 | Add evidence-backed citations and conflict reporting | RES-03 | Done |
| 16 | RES-05 | Export cited research artifacts | RES-04 | Done |
| 17 | RES-06 | Add task-scoped research collections and refresh | RES-05 | Done |
| 18 | PLN-01 | Define structured task brief and success-check schema | FND-01 | Done |
| 19 | PLN-02 | Preview, edit, and approve plans in chat | PLN-01, FND-04 | Done |
| 20 | PLN-03 | Persist versioned plans and decisions in run history | PLN-01, FND-01 | Done |
| 21 | PLN-04 | Add bounded evidence-driven replanning | PLN-02, PLN-03, FND-02 | Done |
| 22 | PLN-05 | Add capability-based model/tool routing evaluation | PLN-04 | Done |
| 23 | MAG-01 | Define parent/child run and delegation contracts | PLN-03, FND-01, FND-04 | Done |
| 24 | MAG-02 | Add coordinator and typed subtask planning | MAG-01, PLN-04 | Done |
| 25 | MAG-03 | Enforce delegate context, workspace, and permission isolation | MAG-02, BRW-05 | Done |
| 26 | MAG-04 | Run independent subtasks with bounded parallelism and cancellation (tracking group) | MAG-03, FND-02 | Done |
| 26.1 | MAG-04A | Add durable idempotent delegate scheduling and concurrency limits | MAG-03, FND-02 | Done |
| 26.2 | MAG-04B | Execute child tasks with scoped context, deadlines, and cancellation | MAG-04A | Done |
| 26.3 | MAG-04C | Surface delegate lifecycle and verify end-to-end behavior | MAG-04B | Done |
| 27 | MAG-05 | Synthesize results, surface conflicts, and validate merged changes (tracking group) | MAG-04, RES-04, PLN-04 | Done |
| 27.1 | MAG-05A | Synthesize typed delegate results and expose conflicts | MAG-04, RES-04, PLN-04 | Done |
| 27.2 | MAG-05B | Validate merged changes and report parent artifacts (tracking group) | MAG-05A | Done |
| 27.21 | MAG-05B1 | Export isolated child edits as reviewable patch proposals | MAG-05A | Done |
| 27.22 | MAG-05B2 | Apply approved patches, validate, and report artifacts | MAG-05B1 | Done |
| 28 | MAG-06 | Extract durable worker queue after local delegation is proven | MAG-05 | Not started |
| 29 | AUT-01 | Specify local interaction tool contracts and permission model | FND-04, BRW-05, BRW-06C3 | Done |
| 30 | AUT-06 | Add a shared browser engine adapter and Lightpanda support (tracking group) | AUT-01, BRW-01, BRW-05, BRW-06C3 | Done |
| 30.1 | AUT-06A | Add a browser engine interface with Playwright as the default | AUT-01, BRW-01 | Done |
| 30.2 | AUT-06B | Integrate and verify Lightpanda CDP capabilities | AUT-06A | Done |
| 31 | AUT-02 | Connect explicitly selected Chrome tabs to agent runs | AUT-01 | Blocked |
| 31.1 | AUT-02A | Add explicit Chrome tab pairing and revocation | AUT-01 | Done |
| 31.2 | AUT-02B | Bridge paired-tab operations to agent runs (tracking group) | AUT-02A | Blocked |
| 31.21 | AUT-02B1 | Add authenticated transient relay for a paired tab | AUT-02A | Blocked |
| 31.22 | AUT-02B2 | Add bounded page observation and screenshot evidence | AUT-02B1 | Blocked |
| 31.23 | AUT-02B3 | Add approval-bound tab actions and cancellation replay | AUT-02B2, FND-04 | Blocked |
| 31.3 | AUT-02C | Verify Chrome companion lifecycle and privacy guarantees | AUT-02B3 | Blocked |
| 32 | AUT-03 | Add approval-gated native desktop interaction | AUT-01 | Ready |
| 33 | AUT-04 | Add scoped command and filesystem workflows | AUT-01 | Ready |
| 34 | AUT-05 | Add user-managed recurring workflow schedules | AUT-02, AUT-03, AUT-04, MAG-06 | Not started |
| 35 | CAP-01 | Define typed service connectors and secure account handling | FND-01, FND-04, MAG-03 | Not started |
| 36 | CAP-02 | Implement the first user-selected service connector | CAP-01 | Not started |
| 37 | DOC-01 | Add bounded PDF, Office, spreadsheet, and optional OCR ingestion | TOL-02, FND-01 | Not started |
| 38 | OPS-01 | Notify users about approvals and unattended run outcomes | MAG-06, AUT-05, FND-04 | Not started |
| 39 | EVA-01 | Add privacy-safe tool evaluation and non-executing replay tests | FND-04, PLN-05, MAG-04C | Not started |
| 40 | LRN-01 | Make OpenClaw turns more reliable (guidance, stall watchdog, readable errors, browser choice) | AUT-01 | Done |
| 41 | LRN-02 | Learn lessons from failed-then-fixed steps and give them to agents | LRN-01, FND-04 | Ready |
| 42 | LRN-03 | Report button on replies and a local report store | LRN-01 | Done |
| 43 | LRN-04 | Maintenance Manager (tracking group) | LRN-03 | In progress |
| 43.1 | LRN-04A | Setup: choose the AI, connect GitHub, permission to clone (fork when needed) | LRN-03 | Done |
| 43.2 | LRN-04B | Fix a report in an isolated worktree with the chosen AI; validate checks and documentation; automatic mode | LRN-04A | Done |
| 43.3 | LRN-04C | Show the diff and PR text; on approval commit, push and open a draft PR; discard on reject | LRN-04B | In progress |
| 44 | LRN-05 | Turn tasks that worked into reusable skills or browser recipes | LRN-02, BRW-06C3 | Not started |
| 45 | SEQ-01 | Plan-and-Sequence (tracking group) | FND-01 | In progress |
| 45.1 | SEQ-01A | P0 — Subtask schema, plan validation, state capsule | FND-01 | Done |
| 45.2 | SEQ-01B | P1 — Measure the design targets | SEQ-01A | In progress |
| 45.3 | SEQ-01C | P2 — Code-first verifier, retry, re-plan trigger | SEQ-01A | Done |
| 45.4 | SEQ-01D | P3 — Router wiring (planner service plan-sequence endpoint) | SEQ-01A, PLN-05 | Done |
| 45.5 | SEQ-01E | P4 — OpenClaw as tool provider (subtask mode) | SEQ-01C, LRN-01 | In progress |
| 46 | UI-01 | Agent Studio desktop redesign (tracking group) | — | In progress |
| 46.1 | UI-01A | Tokens, shell layout, rail, task list, run bar, inspector, command palette; `usage` and `verifying` run events | — | Done |
| 46.2 | UI-01B | Plan card, thread cards, pickers; plan pre-check, "Allow for this task", answer choices for questions, install card, notes while a task runs, retry from step N | UI-01A | Done |
| 46.3 | UI-01C | Workshop pages (Models, Cloud models, Connectors with a drawer, MCP servers, Browser recipes, Research, Memory, Activity, Services, Maintenance) | UI-01A | Done |
| 46.4 | UI-01D | Settings with the theme picker, Setup, dialogs and toasts, themes | UI-01A | Done |
| 46.5 | UI-01E | Watch saved sources for changes | UI-01B | Done |
| 46.6 | UI-01F | Plan-step progress ("step 3 of 5") reported by the agent | UI-01B | Done |
| 46.7 | UI-01G | Activity charts: requests per minute, model share, 24 h / 7 d range | UI-01A | Ready |
| 46.8 | UI-01H | Terminal tabs: more than one terminal, New and Close terminal | UI-01A | Ready |
| 46.9 | UI-01I | Services: Restart all and each service's port | UI-01A | Ready |
| 46.10 | UI-01J | Models: Unload, purpose tags, slow-to-start note; skills: use counts and recent use | UI-01A | Ready |
| 46.11 | UI-01K | The last lines of a running command's output under its step | UI-01A | Ready |
| 46.12 | UI-01L | Research: View changes for a watched page; decide whether to add a saved site list | UI-01A | Ready |
| 46.13 | UI-01M | Browser recipes: show the running step (step N of M) | UI-01A | Ready |
## Task definitions and acceptance checks

### Foundation

#### TOL-01 — Move agent tool catalog and tests into the dedicated tools project

Give the current agent tools an owned home under `backend/projects/agent_tools/`. Move the schemas, implementation, and focused tests; update gateway, validator, documentation, and architecture references so runtime behavior remains the same.

**Done when:** all current agent tool call sites import from the new package; tool tests pass from the repository root; workspace root and path protections still resolve to the repository/task root correctly; stale `backend/scripts/agent_tools.py` references are removed; the project README explains where future tools and tests belong.

**Completion:** 2026-11-11. Moved the catalog and focused tests to `backend/projects/agent_tools/`, updated the gateway, validator, imports, and documentation, and removed a stale test for the retired Project Brain endpoint. Verification: `.venv\\Scripts\\python.exe -m py_compile backend\scripts\\pockpock_server.py backend\projects\\agent_tools\\__init__.py backend\projects\\agent_tools\\test_agent_tools.py backend\projects\\validator\\app.py` passed; `.venv\\Scripts\\python.exe -m unittest projects.agent_tools.test_agent_tools` passed (20 tests).

#### TOL-02 — Split tools into capability modules and registry

**Owner:** primary agent, completed 2026-11-11.

After FND-01 defines tool metadata, divide the package into cohesive modules such as `workspace`, `research`, `browser`, and `artifacts`, with one registry/dispatch interface. Keep contexts and public schemas compatible during migration.

**Done when:** dispatch no longer relies on one growing implementation module; each capability has focused tests and docs; registry metadata covers permissions, side effects, limits, timeout, and schemas; the gateway depends on the package interface only.

**Completion:** 2026-11-11. Split implementations into shared contexts, workspace, research, artifacts, and registry modules; reduced `__init__.py` to a compatibility facade; separated the focused workspace/research/artifact test suites. The gateway and validator still import through the package interface, and the registry continues to represent all 12 tools. Verification: `.venv\Scripts\python.exe -m py_compile backend\projects\agent_tools\common.py backend\projects\agent_tools\workspace.py backend\projects\agent_tools\research.py backend\projects\agent_tools\artifacts.py backend\projects\agent_tools\registry.py backend\projects\agent_tools\contracts.py backend\projects\agent_tools\__init__.py backend\projects\agent_tools\test_agent_tools.py backend\projects\agent_tools\test_research.py backend\projects\agent_tools\test_workspace.py backend\projects\agent_tools\test_artifacts.py backend\scripts\pockpock_server.py backend\projects\validator\app.py` passed; `.venv\Scripts\python.exe -m unittest projects.agent_tools.test_contracts projects.agent_tools.test_agent_tools projects.agent_tools.test_research projects.agent_tools.test_workspace projects.agent_tools.test_artifacts projects.run_store.test_event_contracts` passed (29 tests).

#### FND-01 — Define typed tool and task-run contracts

Create a single typed registry/schema for each tool's name, capability, permission level, side-effect class, input/output validation, timeout, and size limits. Add contract/version fields for run events and errors; document a compatibility policy for existing persisted run events.

**Done when:** all current tools are represented by the registry; dispatch validates input and output against their schemas; unsupported tool/contract versions fail with actionable errors; contract docs and relevant architecture pages are updated; existing run replay remains readable.

**Owner:** primary agent, started 2026-11-11.

**Completion:** 2026-11-11. Added a versioned typed registry for all 12 callable tools; the gateway now validates arguments/results and enforces permissions, per-tool timeouts, and serialized byte limits. New run events use version 1, old unversioned persisted events replay as version 0, run errors receive a typed envelope, and unsupported versions fail with actionable errors. Verification: `.venv\Scripts\python.exe -m py_compile backend\projects\agent_tools\contracts.py backend\projects\agent_tools\__init__.py backend\scripts\pockpock_server.py backend\scripts\agent_run_store.py backend\projects\run_store\app.py backend\projects\agent_tools\test_contracts.py backend\projects\run_store\test_event_contracts.py` passed; `.venv\Scripts\python.exe -m unittest projects.agent_tools.test_contracts projects.agent_tools.test_agent_tools projects.run_store.test_event_contracts` passed (29 tests).

#### FND-02 — Add durable cancellation and timeout lifecycle

**Owner:** primary agent, started 2026-11-11.

Persist cancellation requests and terminal cancelled/interrupted states. Propagate cancellation to model streams and active tools; enforce per-tool and total-run timeouts. Reopening a run must show its final status.

**Done when:** a user can cancel an active run; cooperative tool/model work stops within the documented timeout; final status/event survives reload; late events cannot turn a cancelled run into success; a manual end-to-end cancellation check passes.

**Completion:** 2026-11-11. Added authenticated durable cancellation, cooperative cancellation of active model/tool awaits, a 15-minute run deadline, explicit cancelled/timed-out/interrupted terminal events, late-event rejection, and startup recovery for runs abandoned by a gateway restart. The Stop control uses the cancel API and replay displays final states. Verification: Python compilation passed for the changed gateway/run-store modules; all 36 agent/tool/run-store tests passed, including a full mocked gateway stream cancellation and replay check; 
pm.cmd run build` passed; the dashboard and all four backend health endpoints returned HTTP 200 after restarting the run store and gateway.

#### FND-04 — Persist approvals and tool outcome events

Add durable approval-requested, approved, rejected, expired, and tool-started/completed/failed events with stable IDs and replay support. A resolved approval must be bound to the exact action payload and current run.

**Done when:** reload preserves pending and resolved decisions; approval cannot be replayed for a changed action; rejected/expired operations do not execute; UI clearly shows the pending decision and outcome; permission flow is documented.

**Completion:** 2026-11-11. Added persistent run-scoped approval records with SHA-256 payload binding, approval/resolve/expire endpoints, and Auto-review gating for staged workspace patches. The chat displays the exact proposed diff and approve/reject controls; outcomes replay with the run. Expired, rejected, cancelled, or interrupted approvals cannot apply the staged patch. Tool start/result events now carry stable call IDs. Verification: Python compile passed; 38 run-store, cancellation, and tool tests passed, including payload mismatch, expiration, and approval replay cases; 
pm.cmd run build` passed.

### Priority 1 — Computer and browser automation

#### BRW-01 — Add isolated browser runtime project and lifecycle

**Owner:** primary agent, started 2026-11-11.

Create `backend/projects/browser_automation/` with an independently launchable adapter, health/status contract, run-scoped browser context creation/cleanup, bounded process lifecycle, and dependency manifest. Do not use the user's normal browser profile or saved credentials.

**Done when:** the service starts through the standard launcher, reports health, creates and closes an isolated context, propagates FND-02 cancellation, and cannot read user profile/session data; setup and troubleshooting are documented.

**Completion:** 2026-11-11. Added the independently launched loopback browser runtime on port 8774, installed Playwright/Chromium through the local setup flow, and implemented token-authenticated run-scoped context create/close plus cancellation cleanup. Fresh contexts are non-persistent, do not use normal browser profiles, disable downloads and service workers, and close on service shutdown. Added setup, API, security, troubleshooting, architecture, and feature-index documentation. Verification: Python compilation passed; `projects.run_store.test_agent_cancellation` and `projects.run_store.test_event_contracts` passed (14 tests); manual launcher health checks returned HTTP 200 for gateway and all four internal services; authenticated context lifecycle reported 0 → 1 → 0 contexts; end-to-end local run cancellation also closed the browser context (1 → 0).

#### BRW-02 — Add bounded, read-only public navigation

**Owner:** primary agent, started 2026-11-11.

Expose structured open/observe/screenshot operations. Enforce HTTP/HTTPS, public IP/host checks on every redirect/navigation, operational time/page/byte limits, and block downloads, local/private addresses, and unsafe URL schemes.

**Done when:** allowed public pages return title, final URL, visible text, timestamp, and screenshot reference; blocked destinations are rejected before navigation; context and request safety limits are enforced and verified against local/private/redirect cases.

**Completion:** 2026-11-11. Added authenticated `/navigate` and `/evidence` APIs that return title, final URL, bounded visible text, retrieval timestamp, and an in-memory screenshot. Navigation is limited to public HTTP(S) on standard ports, rejects credentials and private/reserved DNS/IP answers, checks each request/redirect, blocks cross-host access, limits per-run navigation/request counts, and applies navigation, extraction, and screenshot ceilings. Verification: Python compilation passed; the standard launcher restarted the runtime; authenticated navigation of `https://example.com` returned title/text/screenshot (43,167 bytes); loopback target and cross-host target both returned HTTP 403; a public redirect attempt to loopback was blocked before navigation; closing the context removed all in-memory evidence and left zero active contexts.

#### BRW-03 — Show browser activity and evidence in the chat timeline

**Owner:** primary agent, started 2026-11-11.

Add event rendering for browser open/navigation/observation/screenshot and evidence links. Evidence lives with the task and remains scoped to that run.

**Done when:** a browser task shows each step as it happens and after reload; links open the cited page/evidence; unavailable browser service returns a truthful fallback; existing conversation layout and event replay remain intact.

**Completion:** 2026-11-11. Registered the read-only `browse_public_page` tool, connected it to the isolated runtime, saved screenshot evidence in the task output folder, added durable `browser_open`, `browser_observation`, and `browser_screenshot` run events, and rendered page text, metadata, and inline screenshot previews in Agent Chat. Verification: Python compilation passed; all 13 tool contracts registered including browser; direct tool invocation opened `https://example.com` and saved screenshot evidence; the local artifact route returned HTTP 200 with `image/jpeg` and inline disposition; `npm.cmd run build` passed; all five local service health checks returned HTTP 200 after gateway restart.

#### BRW-04 — Add state-bound browser actions

**Owner:** primary agent, started 2026-11-11.

Add click/type/select/scroll/navigation schemas using accessible roles/names and the current observation ID. Reject stale element targets after page changes. Do not implement arbitrary JavaScript execution.

**Done when:** actions validate against the latest observation and typed schema; each action produces a fresh observation and structured result; stale-target and malformed-action cases fail safely; user-visible tool detail is documented.

**Completion:** 2026-11-11. Added typed `browser_action` tool and authenticated runtime actions for named same-host links, named textboxes/searchboxes, named comboboxes, fixed scroll, and same-host navigation. Every action requires the latest observation ID and rotates it after a fresh page/text/screenshot result. Password fields, button clicks, form submission, arbitrary selectors/scripts, cross-host targets, and non-GET/HEAD network requests are blocked. Type/select require Full Access until BRW-05 adds per-action Auto-review approvals; typed values are redacted from durable tool activity. Verification: Python compilation and `npm.cmd run build` passed; all five local health endpoints passed after service restart; manual public-page interactions verified link click, typing, selection, scrolling, same-host navigation, fresh observation IDs, stale-ID rejection, Auto-review typing denial, screenshot evidence creation, and context cleanup to zero.

#### BRW-05 — Add per-action approval and high-impact stop rules

**Owner:** primary agent, started 2026-11-11.

Classify page actions by side effect. Require explicit approval before form submission or actions that send, purchase, delete, publish, change settings, or otherwise affect an account/external party. Make approval payload-bound and resumable.

**Done when:** no high-impact action occurs before approval; approval is invalidated if action or target changes; reject/cancel/timeout stops the action; the timeline records request and decision; manual tests cover approved and denied flows.

**Completion:** 2026-11-11. Added durable per-action approval for browser actions in Default and Auto-review, with fixed scrolling as the only auto-allowed action. Full Access skips ordinary approvals; high-impact-looking links still require approval. Approval hashes bind the validated action arguments and latest observation ID, typed values are redacted from approval details, and reject/expiry/cancellation prevents the browser tool from running. Buttons and form submission remain unsupported. Verification: Python compilation and `npm.cmd run build` passed; gateway, run-store, and browser-runtime health checks passed after gateway restart; manual run-store checks confirmed exact-hash approval, mismatched-hash rejection, and denial outcomes. The high-impact link classifier is based on accessible link names and is intentionally limited to the supported link-click action set.

#### BRW-06 — Browser workflow recipes (tracking group)

Implement user-reviewed browser workflow recipes through the child tasks below. Store recipes locally with domain allowlists, typed inputs, checkpoints, stop conditions, and approval requirements. Recipes are explicitly started and do not run on a schedule by default.

**Done when:** all child tasks are complete and the end-to-end recipe flow meets these criteria: users can inspect/edit/disable a recipe; execution stops at unexpected state; consequential actions request approval on every run; versions, evidence, and outcomes are replayable; deletion follows documented data-retention behavior.

#### BRW-06A — Define local recipe schema and versioned storage

**Owner:** primary agent, started 2026-11-11.

Define a versioned recipe contract and local persistence boundary. Recipes include a stable ID, name, domain allowlist, action steps with named inputs, checkpoints, stop conditions, approval policy, and created/updated metadata. Keep secrets out of recipes and provide safe CRUD/disable operations.

**Done when:** contract validation rejects unsafe/unsupported steps and malformed hostnames; CRUD and version history persist locally across restart; disabling/deleting is durable; data ownership and retention are documented; manual storage/validation checks pass.

**Owner:** primary agent, started 2026-11-11.

**Completion:** 2026-11-11. Added strict recipe/input/checkpoint/action schemas, exact hostname and public-destination validation, and authenticated local SQLite CRUD with immutable versions, optimistic version checks, enable/disable, and cascading delete. Recipes live under `%LOCALAPPDATA%\PockPock\browser-recipes.sqlite3` by default, store input declarations but never their values, require the first step to navigate and every step to include a title/text stop condition, and accept no arbitrary selectors/scripts or wildcard hosts. Verification: Python compilation passed; the browser service restarted and remained healthy; manual API flow created a recipe, read it, saved version 2, listed both versions, disabled and deleted it; localhost was rejected; a recipe remained available after restarting the service and was then deleted.

#### BRW-06B — Add recipe inspect, edit, and disable UI

**Owner:** primary agent, started 2026-11-11.

Add a local recipe manager for inspecting, creating, editing, versioning, disabling, and deleting recipes. Do not add scheduling or auto-run behavior.

**Done when:** users can review each step, domain, input, checkpoint, and approval rule before saving; edits create a version; disabled/deleted recipes cannot be launched; keyboard access and empty/error states work.

**Completion:** 2026-11-11. Added the Browser recipes workspace page, local-gateway API proxy, accessible editor for allowed hosts, typed inputs, supported action steps, required stop conditions, and the fixed approval policy, plus immutable version history, enable/disable, and confirmed delete. The UI explicitly says recipes do not run until started. Verification: `npm.cmd run build` passed; browser-based manual UI flow created and edited a recipe, verified version 2, disabled and deleted it, exercised a typed-input step, restarted the browser service and confirmed stored recipes remained available; empty/error/loading recovery states rendered correctly.

#### BRW-06C — Safe recipe execution (tracking group)

Implement explicit, user-started recipe execution in the child tasks below. Use a fresh isolated browser context, bind execution to an immutable recipe version, and stop on any checkpoint mismatch.

**Done when:** all children are complete; unexpected page state stops execution without guessing; each step and evidence item replays with its recipe version; approvals bind to the exact step and current observation; cancellation closes the browser context; no scheduled/background replay exists.

#### BRW-06C1 — Add deterministic runtime execution with checkpoints

**Owner:** primary agent, completed 2026-11-11.

Add an internal browser-runtime recipe executor. It accepts an enabled recipe ID/version and validated input values, creates a fresh isolated context, verifies every step's title/text stop condition, enforces exact allowed-host and input type rules, and closes on completion, failure, or cancellation. Do not expose arbitrary scripts or direct browser APIs.

**Done when:** every supported action can run through the typed browser API; mismatched/missing checkpoints stop before the next action; disabled or changed recipes are rejected; credentials are not persisted; a completed or failed run always leaves zero browser contexts.

**Completion:** 2026-11-11. Added an authenticated internal executor that runs the requested enabled recipe version in a fresh browser context, validates transient declared inputs, runs only typed browser actions, evaluates title/text checkpoints after every step, and stops at the first mismatch. The response omits input values; a `finally` cleanup closes the browser on completion, failure, mismatch, or cancellation. Verification: Python compilation passed; local browser service restarted healthy; manual public-page run completed, an intentionally mismatched checkpoint stopped at step 1, a disabled recipe was rejected, and health reported zero active contexts after both runs. Gateway approval and durable event replay are intentionally left for BRW-06C2 before user launch is exposed.

#### BRW-06C2 — Orchestrate approved recipe runs and persist step events

This tracking group is split into BRW-06C2A through BRW-06C2C.

**Owner:** primary agent, started 2026-11-11.

Route recipe execution through the gateway, bind the run to the recipe version and permission, request fresh action approval on every run, and persist step, checkpoint, evidence, approval, and terminal events.

**Done when:** approval is bound to recipe/version/step/observation and never reused; reject, timeout, cancellation, or service failure stops execution; reload replays the same ordered step results; no recipe step bypasses the BRW-05 gates.

**Completion:** 2026-11-12. Completed through BRW-06C2A-C: the run-store validates the event contract; the gateway performs per-step approvals; screenshots, checkpoint outcomes, and terminal states persist and replay. The Browser recipes page still needs the explicit run/input/results workflow tracked by BRW-06C3.

#### BRW-06C2A — Define versioned recipe-run event contract

**Owner:** primary agent, completed 2026-11-12.

Define validated, versioned durable event shapes for recipe start, step start, checkpoint result, and terminal outcome. Events must identify recipe/version/step and current observation where applicable, while excluding transient input values and credentials.

**Done when:** run-store writes reject incomplete or malformed recipe events; old run events remain readable; contract and privacy behavior are documented; validation checks pass.

**Completion:** 2026-11-12. Added run-store validation for versioned recipe start, step start, step result, and terminal events. It enforces recipe/version/step/action/status/checkpoint fields, validates observation IDs, and recursively rejects transient inputs and secret-bearing fields before persistence. Legacy run events remain unchanged. Verification: Python compilation passed; direct contract checks accepted valid start/result events and rejected invalid version, missing privacy, and unsupported status cases. Documented the event shapes and retained fields in the browser-runtime feature guide.

#### BRW-06C2B — Execute recipe steps through gateway approvals

**Owner:** primary agent, completed 2026-11-12.

Create a gateway-owned execution flow that runs each typed step against the browser service, binds a one-use approval to recipe/version/step/current observation, and stops on rejection, timeout, cancellation, or service failure.

**Done when:** every consequential recipe action uses the existing durable approval gate; changed payloads or observations invalidate approval; no direct user launch bypasses this route.

**Completion:** 2026-11-12. Added a local-only gateway run stream that pins the enabled recipe version, validates declared transient inputs, requests a fresh durable approval before every step, hashes a redacted action summary bound to recipe/version/step/target/current observation and a keyed input fingerprint, and stops when approval is rejected, expires, the run is cancelled, or the browser service fails. Verification: Python compilation and frontend build passed; manual gateway streams verified approval then completion, rejection, cancellation, and durable event replay; no browser context remained after each run. The run endpoint is not yet linked from the recipe manager; BRW-06C3 supplies the user launch flow.

#### BRW-06C2C — Persist recipe evidence and terminal run outcomes

**Owner:** primary agent, completed 2026-11-12.

Persist step observations, checkpoint results, screenshot evidence, and terminal status to the parent agent run so the conversation can replay the recipe execution after reload.

**Done when:** event order is stable and complete; evidence resolves after browser-context cleanup; failures and cancellation produce terminal replay; input values remain absent from persisted records.

**Completion:** 2026-11-12. Copied each step screenshot into the task's local artifact folder before closing Chromium and emitted durable screenshot, checkpoint, approval, and terminal events. Run-store validation protects recipe event shapes and rejects transient input/secret fields. Verification: replay returned the same ordered recipe events after run completion; screenshot artifact remained readable as `image/jpeg` after context cleanup; an approved checkpoint mismatch replayed as a failed run with zero active contexts; cancellation replayed as cancelled and rejection replayed as failed. Input values are never included in persisted result events; approval uses an installation-keyed fingerprint.

#### BRW-06C3 — Add explicit run inputs, launch, and result UI

**Owner:** primary agent, completed 2026-11-12.

Add an explicit Run control to the recipe page. Prompt for declared inputs at run time, show the selected recipe version and approval steps, render progress/checkpoint/evidence, and display completion or stop reason.

**Done when:** disabled recipes cannot start; inputs remain transient and are not stored in recipe history; each run requires a user click; progress and results survive reload; there is no schedule or auto-start path.

**Completion:** 2026-11-12. Added a saved-version Run control, run-time-only declared inputs, approval actions, live step/checkpoint progress, completion/stop status, and screenshot previews. Recipe runs also append their durable events to the current Conversations thread; reload restores the chat timeline and selecting a recipe restores its latest saved result. Disabled recipes cannot start. Verification: TypeScript build passed; browser UI created a recipe, explicitly launched version 1, approved step 1, observed a passed checkpoint and screenshot, viewed the run in Conversations, reloaded the application, and confirmed the ordered transcript plus recipe result/evidence remained available. Runtime inputs are cleared from UI memory after each stream and are absent from local chat/run events; no schedule or auto-run control exists.

### Priority 2 — Internet research and information gathering

#### RES-01 — Define search provider and source contracts

**Owner:** primary agent, completed 2026-11-12.

Define provider-neutral search result and source evidence types, including canonical URL, title, snippet, provider, publication/retrieval times, and bounded supporting excerpt. Include provider errors/rate limits and source identity/deduplication rules.

**Done when:** contract schemas and error cases are versioned and documented; they support the current named-host fetcher and a future provider without leaking provider-specific shape into the agent loop.

**Completion:** 2026-11-12. Added provider-neutral version 1 source, bounded evidence, response, and provider-error schemas with canonical URL identities, stable IDs, and duplicate-source merging. The existing named-host fetcher now emits additive typed source and evidence records while retaining its original page fields. Canonicalization strips fragments/tracking parameters, preserves meaningful query data, rejects unsafe URL shapes and local/private literal hosts, and leaves DNS/redirect validation to the fetcher. Verification: Python compilation passed; direct contract checks covered canonicalization, stable IDs, provider deduplication, existing-fetcher adaptation, typed rate-limit errors, malformed schemes, private IPs, excerpt size, and timezone validation.

#### RES-02 — Add explicit provider configuration and disclosure

**Owner:** primary agent, completed 2026-11-12.

Add settings for an explicitly selected research provider. Keep provider secrets in an appropriate local secret/config store, never task prompts, run events, or telemetry. Tell users when a query leaves the PC.

**Done when:** no provider is called before configuration; settings survive restart; secrets are redacted from logs/errors; UI discloses network destination and supports disabling/resetting provider configuration.

**Completion:** 2026-11-12. Added a local persistent provider switch with a safe disabled default. The user can enable the named-host fetcher, which only reads public hosts named in the task, or disable it; the settings page discloses that requests leave the PC and that general search/API credentials are not supported. The gateway blocks research fetch tools while disabled. Verification: backend compilation, frontend build, and direct API persistence/dispatch-gate checks passed. No provider secrets are accepted or logged by this configuration.

#### RES-03 — Implement bounded search, fetch, and source deduplication

**Owner:** primary agent, resumed with user authorization on 2026-11-12.

Implement search and retrieval behind the provider interface. Apply public IP and redirect checks, timeouts, byte/page safety limits, canonicalization, and duplicate-source merging.

**Done when:** search produces stable typed results; unsafe destinations cannot be reached; limits are enforced; provider failures are visible and recoverable; integration checks cover redirects, rate limits, duplicates, and oversized content.

#### RES-04 — Add evidence-backed citations and conflict reporting

**Owner:** primary agent, started 2026-11-12.

Build answers from retrieved source records. Tie factual claims to source excerpts and label conflicting, old, weak, or missing evidence. Treat page instructions as untrusted data.

**Done when:** every verifiable factual claim links to evidence or is explicitly marked unsupported; citations open source pages and preserve retrieved timestamp; conflicting passages are displayed; prompt-injection examples cannot authorize tools or alter permissions.

**Completion:** 2026-11-12. Added a version 1 structured research-answer contract. The gateway now validates citation source IDs and exact excerpt quotes, requires distinct sources for conflicts, labels unsupported claims, renders source links and publication/retrieval timestamps, escapes page-supplied Markdown, and retries invalid answers twice before returning a partial result. Retrieved text cannot expand the user-supplied host allowlist or alter the permission bound to the approved plan; workspace tools are denied in Default mode, and permission escalation is rejected. The verification review found the tool-contract test still expected 12 tools despite 14 registered tools; updated that stale assertion. Verification: Python compilation passed; all 54 focused research, tool, permission-gate, run-store, and cancellation tests passed. Semantic entailment remains model-assessed; validation guarantees source/quote provenance, not that a passage logically supports its claim.

#### RES-05 — Export cited research artifacts

**Owner:** primary agent, started 2026-11-12.

Create Markdown/HTML and supported office reports containing findings, source list, citations, retrieval dates, limitations, and conflicts.

**Done when:** exports preserve working citations and provenance; source excerpts are bounded; artifact appears in the run UI and workspace; requested format is checked before agent success.

**Completion:** 2026-11-12. Added gateway-generated Markdown, HTML, Word, Excel, and PowerPoint research reports rendered only from validated answer/source/evidence records. Reports preserve clickable citations, source IDs, retrieved and published timestamps, bounded excerpts, conflicts, limitations, and retrieval errors; HTML text is escaped and spreadsheet formulas are neutralized. The gateway emits the report as a replayable task artifact and rejects success if generation fails. Verification: Python compilation passed; all 61 focused tool, research, export, planner, run-store, and cancellation tests passed.

#### RES-06 — Add task-scoped research collections and refresh

**Owner:** primary agent, started 2026-11-12.

Persist selected source snapshots and user notes by task/workspace. Refresh only when the user requests it; show changed content and retain prior versions under a documented policy.

**Done when:** collections are isolated per task/workspace, refresh compares snapshots, delete removes stored text/source data according to the retention policy, and there is no background polling without explicit configuration.

**Completion:** 2026-11-12. Added task/workspace-scoped local collections with explicit save, bounded UTF-8 text snapshots (200 KB each), notes, hash/timestamp metadata, user-triggered refresh, unchanged-content detection, added/removed text comparison, browsable retained versions, and collection-wide deletion. The API validates that saved URLs belong to the task's persisted research sources and reuses the bounded public-page fetcher. No background fetch or refresh is scheduled. Version history is retained until collection deletion, as requested. Verification: Python compilation and the focused run-store, cancellation, and research collection tests passed; the web UI production build passed.

### Priority 3 — Planning, reasoning, and decision-making

#### PLN-01 — Define structured task brief and success-check schema

Expand planner output with outcome, constraints, assumptions, required capabilities, permission, milestones, deliverables, and completion checks while preserving original user wording.

**Done when:** schema is validated, old planner clients fail compatibly, incomplete critical requests can be marked as needing clarification, and an example set demonstrates task versus ordinary chat classification.

#### PLN-02 — Preview, edit, and approve plans in chat

Render a structured plan in the existing timeline; let the user edit or approve before execution when required. Never change permission level from a plan suggestion.

**Done when:** execution starts only from the approved plan version; edits are visible; declined plans do not create side effects; small tasks can use a documented low-friction default; UI behavior is keyboard-accessible and replayable.

#### PLN-03 — Persist versioned plans and decisions

Store plan versions, approved version, assumptions, user decisions, and short rationale summaries as run events/data. Do not store hidden chain-of-thought.

**Done when:** plan history survives reload, versions link to the actions they authorized, decision events are queryable, private prompt content stays out of telemetry, and existing run history remains readable.

#### PLN-04 — Add bounded evidence-driven replanning

After failed checks, unavailable tools, changed constraints, or new evidence, revise only remaining work. Enforce FND-02 cancellation and bounded retry/time limits.

**Done when:** each revision records its trigger and remaining steps; repeated identical failures stop within a fixed retry limit; scope/permission changes require user approval; completion checks gate success.

**Completion:** 2026-11-12. Added in-run replanning events with trigger, completed tool steps, changed remaining action, and rationale. Identical failed tool calls stop after two attempts; tool-failure replanning stops after five revisions. Each approved success check must now receive an ordered evidence/status line; missing or incomplete reports receive at most two correction attempts and then end partial. Existing run deadlines, per-tool limits, approval gates, workspace validation, and required-artifact gates remain active. Updated the chat timeline, run memory, task brief feature doc, and architecture decision record. Verification: Python compilation passed; 22 planner/run-store tests passed; `npm.cmd run build` passed from `frontend/app/`.

#### PLN-05 — Add capability-based model/tool routing evaluation

Select models/tools per step using tool support, context, task capability, local availability, latency, and opt-in local outcome metrics. Respect compatible user model preference.

**Done when:** reasons/fallbacks are visible; incapable models are excluded; metrics are prompt-free by default; a fixed privacy-safe routing evaluation suite catches regressions and documents its limitations.

**Completion:** 2026-11-12. Planner routing now uses enabled tool-capable candidates, their advertised context windows, and prompt-free average call latency; it preserves compatible user preference, prefers the configured fallback, then ranks remaining candidates by measured latency. Task class and route reason are explicit. Added a synthetic fixed evaluation suite and documented its privacy and unknown-context limits; no prompt/response or opt-in outcome metrics are used. Verification: Python compilation passed; 28 planner/run-store tests passed.

### Plan-and-Sequence

#### SEQ-01 — Plan-and-Sequence (tracking group)

A strong model plans a task as 5–15 sequential steps and a small local
model executes one step at a time, with a code-first verifier between
steps and only a ≤400-token capsule passing forward (wiki page
`Plan-and-Sequence`). Built in gated phases P0–P4 below; the group is
complete only when every child is `Done`.

**Done when:** all child tasks are complete and the end-to-end flow
(plan → approve → run) works through the gateway with the Qwen3.6
planner / Qwen3.5-9B executor split on the RTX 4070.

#### SEQ-01A — P0: Subtask schema, plan validation, state capsule

Subtask schema (goal, tools_allowed, budget, typed done-condition,
inputs), plan validator, and state capsule format. No model calls yet.

**Done when:** invalid plans are rejected in unit tests; valid plans pass
through unchanged.

**Completion:** 2026-11-17. `backend/projects/plan_sequence/` holds the
Pydantic v2 schema (`contracts.py`, `extra="forbid"`), `validate_sequence_plan`
(5–15 steps, unique ids, registered tools only, typed done-conditions,
no dangling inputs), and `build_capsule` (≤400 tokens, ≤24 entries,
summaries then values trimmed first, pointer loss recorded). Verification:
the 84-test `plan_sequence` suite passes, including contract and capsule
tests that reject invalid plans.

#### SEQ-01B — P1: Measure the design targets

**Owner:** plan-sequence measurement wave, started 2026-11-17.

Run the sequenced path on PockPock's own task sample with real requests;
measure prompt tokens per step, step success rate, and end-to-end task
success vs the monolithic path.

**Done when:** the ~1,500-token-per-step and ≤400-token-capsule figures
are confirmed or corrected with real numbers, and end-to-end success vs
the monolithic path is measured. Do not proceed on unmeasured targets.

**Status (2026-11-17, not Done):** the harness exists and the token
targets are confirmed — `backend/scripts/evaluate_plan_sequence.py`
(6 hand-written reference plans, Measurements A–C) and
`backend/scripts/plan_sequence_eval.md`: max step prompt 390 tokens,
max capsule 109 tokens, fake-model runs 30/30 steps and 6/6 tasks
completed. Still open: the live run with real `qwen3.5:2b` was NOT
measured (the single bounded attempt exceeded its 120 s budget on this
VM), and end-to-end task success vs the monolithic path is NOT measured
(no monolithic runner exists to compare against). The feature doc
(`docs/features/plan-and-sequence.md`) records both as open limits.
Verification so far: `py_compile` passed; 84 `plan_sequence` tests and
5 eval-harness tests pass.

#### SEQ-01C — P2: Code-first verifier, retry, re-plan trigger

Code-first verifier, retry ≤2× with grounded error feedback, re-plan
trigger on repeated failure.

**Done when:** a deliberately wrong step is caught at its boundary in
tests; the run recovers instead of compounding.

**Completion:** 2026-11-17. `verify_done_condition` checks typed
done-conditions against files and the recorded step result (never the
model's claim, never raising); `SequenceRunner` retries a failed step
≤2× with the failure detail fed back, then stops with
`status="needs_replan"` for the remaining steps only. Verification: the
84-test `plan_sequence` suite passes, including wrong-step retry →
`needs_replan`, tool-outside-allowed rejection, and prompt-over-budget
cases.

#### SEQ-01D — P3: Router wiring (planner service plan-sequence endpoint)

**Owner:** plan-sequence routing wave, started 2026-11-17.

Smart Router sends planning turns to the strong model and execution turns
to the small model; the Tool-RAG retriever supplies each step's pinned
tools. Planner service endpoint `POST /plan-sequence` returns a validated
plan (one fix-up attempt, then 502; planner timeout surfaced as a
re-plan trigger).

**Done when:** end-to-end tasks complete on the RTX 4070 with the
Qwen3.6 planner / Qwen3.5-9B executor split.

**Done (2026-11-22):** two tasks completed end to end on the RTX 4070 with the `qwen3.6:35b-a3b` planner and `qwen3.5:9b` steps, through the new gateway routes and the desktop's Plan in steps (see docs/features/plan-and-sequence.md, Verification).

**Earlier status (2026-11-17, not Done):** the code is built and unit-tested —
`choose_planner_model` / `choose_executor_model` in
`backend/projects/plan_sequence/routing.py` and `POST /plan-sequence` in
`backend/projects/planner/app.py` — but the pass condition (end-to-end
tasks on the RTX 4070 with that model split) has NOT been verified; no
live run on that hardware has happened. The gateway
`/api/agents/plan-sequence` and `/api/agents/run-sequence` routes and
any runner caller do not exist yet.

#### SEQ-01E — P4: OpenClaw as tool provider (subtask mode)

**Owner:** plan-sequence OpenClaw wave, started 2026-11-17.

OpenClaw mode executes subtasks handed to it, with the step's small
prompt and pinned tools.

**Done when:** OpenClaw completes multi-step tasks with qwen3.5:2b/9B
that previously never completed (the ~21K-prompt failure case).

**Status (2026-11-17, not Done):** subtask mode is implemented in the
Node helper only — `validateSubtask` / `buildSubtaskMessage` /
`subtaskTimeoutSeconds` in
`backend/projects/openclaw_bridge/turn_helpers.mjs`, wired into
`gateway_turn.mjs` (invalid subtask fails fast; `subtaskId` echoed on
started/final events) — but `openclaw_bridge` does not send a subtask
yet, no runner caller exists, and the pass condition (live multi-step
OpenClaw tasks on small models) has NOT been verified. Pinning in
subtask mode is prompt-level only; OpenClaw has no tool allow-list API.

### Priority 4 — Multi-agent systems

#### MAG-01 — Define parent/child run and delegation contracts

Extend durable run IDs/events with parent, child, role, dependency, isolated context, workspace/artifact scope, deadline, and typed result fields.

**Done when:** parent-child relationships and ordered events replay after restart; old runs still load; invalid cross-run references and excessive depth/count are rejected; contracts document ownership and retention.

**Completion:** 2026-11-12. Added typed delegation metadata and result contracts. Run rows persist parent, role, dependencies, context/workspace/artifact scopes, and timezone-aware deadline; replay returns the relationship and `delegate_result` events remain in ordered history. The store rejects cross-conversation parents, invalid/incomplete dependency links, deadlines outside the next 24 hours, more than 16 children, and more than three levels. Existing tables migrate in place and old runs remain root runs. Updated run-store and feature documentation and architecture boundaries. Verification: Python compilation passed; 25 planner/run-store tests passed; frontend build passed from `frontend/app/`.

#### MAG-02 — Add coordinator and typed subtask planning

Allow one coordinator to propose independent subtasks with purpose, expected result, dependencies, allowed tools, and operational limits. Require parent plan approval before dispatch.

**Done when:** user can inspect the delegation tree; dependent work is ordered; invalid/unbounded plans are rejected; no child starts before parent approval; planning decisions and failure paths are visible.

**Completion:** 2026-11-12. Planner responses may now include a validated subtask graph with role, purpose, expected result, prior-node dependencies, allowlisted tools, call count (1–20), and duration (30–900 seconds). The graph is shown in the plan preview and bound into the one-use parent plan approval ticket. Invalid tool names, duplicate IDs/dependencies, forward dependencies, and oversized graphs fail validation. After approval, the durable run timeline records the approved proposal with dispatch marked not started; child execution remains for MAG-04. Verification: Python compilation passed; planner/run-store tests passed; frontend build passed.

#### MAG-03 — Enforce delegate context, workspace, and permission isolation

**Owner:** primary agent, started 2026-11-12.

Give each delegate only its assigned task context, artifacts, and tools. Keep the parent permission ceiling immutable; isolate file edits as patches until reviewed.

**Done when:** delegates cannot access sibling/private conversation context or widen permissions; shared-file writes conflict safely; patch validation uses existing workspace safety rules; isolation tests cover cross-task access.

**Completion:** Child creation is bound to an active parent’s latest approved plan and enforces the approved purpose/expected-result prompt, role, tool allowlist, complete dependency set, and parent permission ceiling. The context builder exposes only the assigned task and approved dependency results; workspace scope is isolated, while artifact access is denied until the plan can explicitly assign artifacts. File changes continue through the existing staged-patch conflict and safety validation. Focused run-store tests, workspace tests, and Python compilation passed.

#### MAG-04 — Run independent subtasks with bounded parallelism and cancellation

Dispatch only independent subtasks concurrently under configured local concurrency limits. Propagate cancellation, deadlines, and service errors to all children.

This is a tracking group; implementation is split into MAG-04A, MAG-04B, and MAG-04C. It is complete only when all three are done.

#### MAG-04A — Add durable idempotent delegate scheduling and concurrency limits

Implement a bounded scheduler for the approved dependency graph, with stable child identities and durable dispatch state so retries/reloads cannot launch duplicate work.

**Done when:** only ready independent subtasks run concurrently; the configured concurrency ceiling is enforced; repeated scheduling returns existing child state instead of creating duplicates; dependencies and partial/failed outcomes are represented and tested.

**Owner:** primary agent, started 2026-11-12.

**Completion:** Added dependency-aware scheduling that enforces the configured concurrency ceiling, passes only declared dependency results, and cancels active callbacks on cancellation or infrastructure errors. Stable UUIDv5 child IDs plus create-or-load behavior replay existing run state/events on retry instead of creating duplicates. Partial and failed typed results remain available to dependent subtasks. Verification: 45 focused scheduler/run-store/workspace/planner tests passed; Python compilation passed.

#### MAG-04B — Execute child tasks with scoped context, deadlines, and cancellation

Run each scheduled child with the MAG-03 context/tool/workspace contract. Enforce each subtask's deadline and propagate parent cancellation and operational errors to every child.

**Done when:** child execution uses only approved context/tools; parent cancellation stops active and queued children; deadlines and service failures produce durable terminal child results; partial failure does not become success.

**Owner:** primary agent, started 2026-11-12.

**Completion:** Connected the bounded dependency scheduler to gateway child execution. Child payloads use only approved subtask/dependency context and allowlisted tools, with isolated output, call/deadline limits, parent cancellation propagation, and durable typed completion/failure results. Added an atomic one-time child execution claim in local and authenticated remote run-store modes. Verification: Python compilation passed; 77 focused run-store, delegation, cancellation, planner, and agent-tool tests passed, including child gateway execution/tool filtering/result persistence, idempotent claims, scheduler cancellation of active work without starting queued work, and sibling cancellation on service errors; all 40 tests discovered under `backend/projects/` passed.

#### MAG-04C — Surface delegate lifecycle and verify end-to-end behavior

Expose child purpose, model, scope, status, and output in the parent timeline and verify replay/retry behavior across reload.

**Done when:** the UI shows child status and typed results; retry/reload does not duplicate dispatch; tests cover independent/blocked subtasks, partial failures, cancellation, and replay.

**Owner:** primary agent, started 2026-11-12.

**Completion:** Added replayable parent timeline cards for child purpose, model, context/workspace scope, status, activity, and typed output. Gateway integration now emits those child lifecycle events to the durable parent stream; stable child IDs and atomic execution claims prevent duplicate dispatch, and retries project the saved typed result. Verification: Python compilation passed; 77 focused delegation/run-store/cancellation/planner/tool tests passed, including mocked parent-to-child execution and replay; all 40 project-discovered tests passed; `npm.cmd run build` passed.

#### MAG-05 — Synthesize results, surface conflicts, and validate merged changes

Have the coordinator reconcile typed results with plan checks, expose disagreements and evidence, and apply only reviewable validated patches.

**Done when:** outputs cite their child source; conflicts are not hidden; failed required child/check yields partial/failure, not success; merged code is validated and artifacts are listed in parent run.

This is a tracking group; implementation is split into MAG-05A and MAG-05B.

**Owner:** primary agent, started 2026-11-12.

#### MAG-05A — Synthesize typed delegate results and expose conflicts

Reconcile typed child results with the approved parent success checks. Attribute evidence and outputs to child runs, surface contradictory results instead of silently choosing one, and prevent incomplete required children/checks from becoming parent success.

**Done when:** the parent synthesis cites each child source; conflicting evidence and incomplete checks are explicit; any failed required child or unmet check produces a non-success parent status; synthesis is covered by focused tests.

**Owner:** primary agent, started 2026-11-12.

**Completion:** The coordinator now receives bounded typed results carrying stable child-run IDs, with explicit instructions to cite each source and expose conflicting evidence. Missing or non-completed required children force a partial parent outcome even if the remaining checks are reported as passing. Verification: Python compilation and frontend production build passed; 78 focused delegation/run-store/cancellation/planner/tool tests passed, including parent-to-child synthesis context and failed-child parent status; all 40 project-discovered tests passed.

#### MAG-05B — Validate merged changes and report parent artifacts

Merge only reviewable child changes through the existing workspace patch/conflict safeguards, run the applicable project validators, and report resulting artifacts in the parent run.

**Done when:** child edits are never silently applied over conflicts; approved merged changes pass the appropriate validator; parent history lists each resulting artifact; focused tests cover conflicts, validation failures, and artifact reporting.

This is a tracking group; implementation is split into MAG-05B1 and MAG-05B2.

**Owner:** primary agent, started 2026-11-12.

#### MAG-05B1 — Export isolated child edits as reviewable patch proposals

Collect child workspace edits as bounded patch proposals linked to the child run, without exposing the parent workspace to delegates or applying edits directly to it.

**Done when:** child changes are attributed to their child run and exact files; parent-visible diffs are bounded and path-validated; proposals do not write to the parent workspace; stale or overlapping changes are rejected safely.

**Owner:** primary agent, started 2026-11-12.

**Completion:** Applied child-created workspace files are now copied only into bounded, parent-side pending patch proposals, with child/subtask attribution and a generated diff. Existing targets, duplicate pending paths, unsafe paths, symlinks, invalid text, and oversized files are rejected; parent files are not changed during proposal creation. Verification: Python compilation passed; focused gateway/patch-staging and workspace collision tests passed, including a mocked parent-to-child patch event that remained unapplied in the parent workspace.

#### MAG-05B2 — Apply approved patches, validate, and report artifacts

Apply only parent-approved child patches through the existing project path and hash checks, run the relevant validator, and persist the merged artifact list in the parent run.

**Done when:** an unapproved or altered patch cannot apply; stale targets and overlapping changes conflict without overwriting; accepted changes pass validation; resulting files are visible as parent-run artifacts.

**Completion:** Child-created additions are staged as parent-visible diffs, then applied only after a parent approval bound to the exact proposal. Path/hash checks reject stale targets; validation compares new issues against the pre-merge baseline and reverts only unchanged additions on failure. Successful files are emitted as parent patch/artifact events. Verification: Python compilation passed; 40 focused delegation, run-store, and workspace tests and all 43 project-discovered tests passed; the frontend production build passed. Coverage includes approved artifact reporting, stale/conflicting paths, and validation-failure rollback.

#### MAG-06 — Extract durable worker queue after local delegation is proven

Move execution into a worker service/queue with leases, idempotency, bounded retry, cancellation, backpressure, health, and durable parent-child event state. This is a prerequisite for recurring schedules (AUT-05) and unattended run notifications (OPS-01).

**Done when:** worker restart recovers work without losing events or repeating unsafe side effects; stale lease behavior and backpressure are exercised; deployment and data-isolation docs exist before remote/multi-user enablement.

### Planned expansion — Local interaction and automation

The inventory and proposed contracts are in [Local agent interaction and automation](features/local-agent-automation.md). These tasks do not change the current browser/workspace behavior until implemented and verified.

#### AUT-01 — Specify local interaction tool contracts and permission model

**Owner:** primary agent, started 2026-11-13.

Finalize the typed contracts, platform support, capability/side-effect matrix, consent and approval rules, privacy/retention policy, resource bounds, and service ownership for connected Chrome, native desktop, scoped command execution, and recurring workflows. Prefer a paired Chrome extension with per-tab/per-origin grants; do not access or export browser profile credentials. Keep arbitrary model-supplied shell commands out of scope. Define how schedules pause for required user approval and how the durable worker queue is used.

**Done when:** the feature design identifies supported and excluded operations; each surface has a trust boundary, failure/cancellation behavior, data-retention rule, and permission flow; Chrome integration, native-platform support, and browser-engine compatibility choices are explicit; the AUT-02–AUT-06 dependencies and release gates are documented without weakening existing contracts.

**Completion:** 2026-11-13. Finalized the local-automation v1 design: Chrome Stable on Windows 11 x64 via an explicitly paired Manifest V3 extension and Native Messaging host (no remote debugging, debugger permission, or profile extraction); Windows 11 x64 foreground-window automation; Playwright/Chromium as the isolated default with Lightpanda only behind verified capabilities; a side-effect/permission matrix; run/resource ceilings; named command profile policy and limitations; and user-controlled schedules that skip missed occurrences and pause for approval. Documented service ownership, failure behavior, and exclusions. Verification: reviewed the design against AUT-01 acceptance items and checked referenced documentation paths; no code or runtime behavior changed, so no tests were required.

#### AUT-06 — Add a shared browser engine adapter and Lightpanda support

The current isolated runtime uses Playwright with Chromium. Define a runtime adapter that preserves this default and can select Lightpanda for operations it actually supports. Verify protocol/API compatibility before implementation; do not assume complete Playwright parity. Keep the existing browser tool and recipe contracts stable.

This tracking group is split into AUT-06A and AUT-06B.

**Done when:** both children are complete; the shared engine contract preserves Playwright behavior; Lightpanda passes focused tests for every capability it advertises; unsupported operations fail explicitly; no backend silently bypasses the common host/IP restrictions, limits, approvals, cancellation, or privacy guarantees.

**Completion:** 2026-11-13. Added an opt-in Lightpanda CDP engine while preserving Playwright/Chromium as the default. Verified and documented its one-context limit, loopback-only connection, required private-network blocking, and PNG screenshot format. Both child tasks and the shared browser-runtime safety matrix are complete.

#### AUT-06A — Add a browser engine interface with Playwright as the default

Extract the current Playwright/Chromium lifecycle behind a typed engine interface without changing routes or result shapes. Keep fresh per-run browser/context ownership, cancellation cleanup, and the current request guard.

**Owner:** primary agent, started 2026-11-13.

**Done when:** Playwright remains the default; all existing behavior and health/readiness semantics are preserved; engine lifecycle/selection tests cover startup, context creation, close, and unsupported configuration; existing focused browser/tool/run-store tests and browser service smoke checks pass.

**Completion:** 2026-11-13. Added `BrowserEngine` lifecycle contract and `PlaywrightChromiumEngine`, routed per-run launch/cleanup through the adapter, exposed the selected engine in health, and rejected unknown engines without fallback. Updated runtime/architecture docs. Verification: 5 engine tests passed; 29 agent tool/contract/run-event regression tests passed; Python compilation passed; Playwright smoke navigation to `https://example.com` returned the expected title and screenshot and cleanup left zero active contexts.

#### AUT-06B — Integrate and verify Lightpanda CDP capabilities

Add an opt-in connection to a user-installed local Lightpanda CDP server. Verify support for context isolation, request interception, accessible targets, typed actions, screenshots/evidence, recipe checkpoints, and cleanup before advertising each capability. Do not bundle the Lightpanda binary or silently fall back to another engine.

**Completion:** 2026-11-13. Installed the official Lightpanda 1.0.4 Linux x86_64 release into WSL2 Ubuntu 24.04 after verifying its published SHA-256. Added an opt-in Playwright-over-CDP adapter that accepts only loopback endpoints and verifies Lightpanda identity/version; Lightpanda contexts are limited to one active run, and its PNG screenshot format is preserved through evidence and task artifacts. The server must be launched on `127.0.0.1` with `--block-private-networks` and telemetry disabled. Verification: 20 deterministic browser automation scenarios and all 49 project-discovered regressions passed; the 30 focused browser engine/scenario tests and Python compilation passed; real Lightpanda checks verified public navigation, interception of POST and cross-host requests, private-host denial, accessible link/textbox/combobox actions, PNG evidence, sequential context cleanup/state isolation, one-context rejection, and clean adapter shutdown without terminating the user-installed CDP server.

**Done when:** a real Lightpanda instance passes focused tests for every advertised capability; unsupported capabilities are explicitly disabled or fail closed; connection endpoint validation restricts to local loopback; the adapter preserves the existing request, host/IP, size, timeout, approval, cancellation, and evidence boundaries; installation/operation instructions and tested version are documented.
#### AUT-02 — Connect explicitly selected Chrome tabs to agent runs

**Owner:** primary agent, started 2026-11-13.

Add a user-paired Chrome companion boundary for one explicitly selected tab at a time. Support bounded page/accessible-content observation, screenshots, navigation, typed page actions, and filling named form fields, plus bounded user-started silent recording. Keep console and network diagnostics out of v1; add them only under a separately reviewed permission and data-minimization task. Reuse run events and approval infrastructure without sharing the normal browser profile with the isolated Chromium runtime.

This tracking group is split into AUT-02A, AUT-02B, and AUT-02C.

**Done when:** all children are complete; connection is user initiated and revocable; per-tab/origin scope is enforced; cookies, credentials, local storage, authorization headers, and request/response bodies are not extracted or persisted; action approvals bind to the current tab observation; form submission requires separate explicit confirmation; console/network diagnostics remain outside v1 unless separately reviewed; disconnect, cancellation, permission revocation, extension failure, and stale-tab errors are explicit and replayable.

#### AUT-02A — Add explicit Chrome tab pairing and revocation

**Owner:** primary agent, started 2026-11-13.

Create a minimally permissioned Manifest V3 extension and Windows Native Messaging host. The user starts pairing from the extension popup; keep one tab ID and exact HTTP(S) origin in memory only. Validate the extension caller and bounded Native Messaging frames. Do not read page content or expose browser actions in this pairing slice.

**Done when:** the extension uses only `activeTab` and `nativeMessaging`; the host accepts only the registered extension ID and a bounded one-tab/origin handshake; disconnect, tab closure, origin change, and host failure clear the pairing; focused protocol/permission tests pass; setup and removal are documented.

**Completion:** 2026-11-13. Added the toolbar pairing UI, in-memory tab/origin scope, origin-change/tab-close revocation, a bounded Native Messaging host, and a per-user Windows registration script. Chrome end-to-end validation remains pending because Chrome is not installed in the current environment.

#### AUT-02B — Bridge paired-tab operations to agent runs

Add the scoped local relay and typed agent-tool contract for paired-tab observations and actions. Bind every action approval to the current tab and observation; preserve typed-value redaction, explicit confirmation for form submission/high-impact effects, cancellation, and durable run events. Do not add console/network diagnostics.

This tracking group is split into AUT-02B1, AUT-02B2, and AUT-02B3.

**Done when:** an agent run can use only the tab explicitly paired for that run; observation and action results are bounded and nonpersistent by default; stale observations, denied approvals, disconnects, and unsupported actions fail explicitly and replay correctly.

#### AUT-02B1 — Add authenticated transient relay for a paired tab

**Owner:** primary agent, started 2026-11-13.

Connect the Native Messaging host to an authenticated loopback relay owned by the local gateway. Keep one selected tab/origin pairing in memory, bind its use to one run at a time, and clear all pending requests when the host disconnects or the gateway restarts. Relay only bounded, typed messages; do not persist page content or expose the relay to web origins.

**Done when:** host registration, bounded request delivery/response, single-run ownership, timeout, cancellation, revocation, and failure behavior are covered by focused tests; internal routes require the per-install token; relay state is memory-only.

#### AUT-02B2 — Add bounded page observation and screenshot evidence

Use the explicitly granted tab access to return a bounded visible-page observation and screenshot evidence. Exclude password/credential fields, cookies, storage, authorization headers, hidden form values, and network/console diagnostics. Keep page text and screenshots ephemeral unless the user explicitly requests a saved artifact.

**Done when:** extension permission and tab/origin checks are tested; the observation result is bounded; sensitive form controls are excluded; screenshot retrieval is run-scoped and nonpersistent by default.

#### AUT-02B3 — Add approval-bound tab actions and cancellation replay

Add typed navigation, click, type, select, and named-field fill operations. Bind approvals to the paired tab, exact origin, current observation, and full action payload; require separate confirmation for form submission and high-impact effects. Keep entered values redacted from events and clear transient state on cancellation/disconnect.

**Done when:** stale observations and wrong-tab requests are rejected; Default/Auto-review approvals and high-impact confirmation are durable and exact-payload-bound; cancellation, disconnect, approval rejection/expiry, and run replay tests pass.

#### AUT-02C — Verify Chrome companion lifecycle and privacy guarantees

Add focused adversarial and end-to-end tests for pairing scope, permission revocation, navigation, cancellation, host/extension failure, privacy exclusions, approvals, and replay. Verify supported behavior in Chrome Stable on Windows 11 x64 and update the operations and support matrix.

**Done when:** all AUT-02 acceptance checks pass in the supported Windows/Chrome environment; tests confirm no profile/credential access and no console/network diagnostics; user-facing setup, removal, and failure handling are documented.

#### AUT-03 — Add approval-gated native desktop interaction

Add a local native-automation adapter for explicitly selected foreground windows, with bounded screenshot/accessibility observations and typed pointer, text, scroll, and shortcut actions. Expose OS permission state and target selection; do not add background control, keylogging, arbitrary scripts, or implicit access to websites.

**Done when:** platform support is documented; OS permission and selected-window scope are enforced; target changes invalidate observations and pending approvals; destructive or external effects require explicit confirmation; cancellation and unavailable/revoked automation permissions fail visibly; evidence and outcomes replay in the run timeline.

#### AUT-04 — Add scoped command and filesystem workflows

Extend the existing workspace capabilities with narrowly typed file operations and named command profiles. A profile uses a fixed executable and working-directory scope with declared typed inputs, environment policy, timeout, resource/output bounds, and cancellation; it is not an arbitrary shell string. Preserve existing workspace path, symlink, secret-file, permission, and validation rules.

**Done when:** reads/writes remain inside the selected workspace; overwrite/delete require approval; command execution only invokes an enabled named profile; process cancellation and nonzero exit are explicit; output is bounded and persisted only according to the documented privacy policy; path traversal, symlink, secret-file, timeout, and denied-permission cases are tested.

#### AUT-05 — Add user-managed recurring workflow schedules

Let users create schedules from saved, versioned, reviewed workflows with an explicit local cadence/time zone, run window, input policy, and capability allowlist. Use MAG-06's durable worker lifecycle, idempotency, bounded retries/concurrency, cancellation, and restart recovery. Agents may propose a schedule but cannot enable one without user confirmation.

**Done when:** users can inspect, pause, resume, edit, and delete schedules; each launch creates a durable run with replayable status and artifacts; pause/disable prevents future launches; retries cannot duplicate unsafe side effects; a required approval pauses and notifies rather than proceeding; time-zone, missed-run, restart, and overlapping-run behavior is documented and tested.

### Learning and maintenance

The user asked (2026-11-15) for agents that learn from use and errors, and for a Maintenance Manager that turns user reports into validated draft pull requests. Decisions recorded with the user: learning covers lessons, self-fixes through PRs, and reusable skills; a fix is written and tested locally and pushed as a **draft PR only after the user approves**, never merged automatically; fixes are attempted with the largest local model first, and the Maintenance Manager can connect Claude Code, OpenAI Codex or GitHub Copilot; it asks the user to connect GitHub. Any user can set it up (2026-11-15 clarification): choose the AI, connect GitHub, then give permission to clone the PockPock repository to a folder on the PC; the Maintenance Manager works in that clone. Users without push rights open PRs from a fork in their own GitHub account. The project owner reviews the open PRs weekly and merges or rejects them. Every fix includes the matching documentation update.

#### LRN-01 — Make OpenClaw turns more reliable

Evidence (user's OpenClaw chats and OpenClaw logs, 2026-11-15): invalid browser tool arguments with no retry, bash syntax sent to Windows PowerShell 5.1, a non-existent tool called, a turn ending after announcing the next step, a prompt of about 67K tokens against a 49K budget for `qwen3.5:9b`, a plugin approval failing with "requester authority changed" followed by a 15-minute stall, and tool errors whose shown detail is OpenClaw's external-content preamble.

**Done when:** the OpenClaw workspace guidance is versioned and refreshed on existing installs (not only at first setup) and covers PowerShell 5.1 syntax, the browser tool's actions, correcting and retrying a failed call, using only listed tools, finishing the task, and keeping browser output compact; a turn with no OpenClaw activity for a bounded time and no pending approval stops with a clear message instead of waiting for the 30-minute timeout; tool error details shown in the app omit the external-content preamble; OpenClaw's browser can use Brave or another installed Chromium browser when the user chooses it; tests cover the guidance refresh, the watchdog and error cleanup; a real OpenClaw turn is checked on this PC.

#### LRN-02 — Learn lessons from failed-then-fixed steps

When a tool step fails and a later step in the same turn succeeds with a corrected call (or the user's correction fixes it), record a short, generalised lesson (no personal data, paths or page content), deduplicated, with a count and last-used date. Give the relevant lessons to OpenClaw and PockPock Agent as guidance. Show, disable and delete lessons on the Memory page.

**Done when:** lesson extraction is deterministic and tested; lessons are bounded in number and size and never include secrets, prompts or file contents; users can review, disable and delete them; agents receive at most a small, relevant set; docs describe the data flow.

#### LRN-03 — Report button and local report store

Every assistant reply gets **Report**. It captures that exchange (the user message, reply, steps, approvals, errors, timing, engine, model and app version) plus the user's own description and category (hang, failed, wrong result, other), and stores it locally. The user can review, edit and delete reports before anything is shared.

**Done when:** reports are stored in the app data folder with a size limit; attachments and personal paths are excluded or redacted by default and shown to the user; reports can be listed, viewed, edited and deleted; nothing leaves the PC; tests cover capture and redaction.

#### LRN-04 — Maintenance Manager

A page that lists reports and resolves them. Setup, in order: (1) choose the AI that does the maintenance work: the largest local model by default, or Claude Code, OpenAI Codex or GitHub Copilot when installed and signed in; (2) connect GitHub (sign-in through the GitHub CLI); (3) ask permission to clone the PockPock repository into a folder the user can see and change (default under the app data folder), forking it to the user's GitHub account when they cannot push to it. Then, per report: reproduce the problem in an isolated git worktree of that clone, write a fix on a branch together with the matching documentation update (feature page, README or architecture as `AGENTS.md` requires), run the project's checks, and show the diff, check results and pull-request text. Only after the user approves does it push the branch and open a **draft** pull request against `PockPock9/PockPockAgent`; it never merges. If a fix does not pass the checks it says so and leaves a write-up instead. The project owner reviews the open PRs weekly and merges or rejects them.

Split (2026-11-15): **LRN-04A** setup (AI detection and choice with a data notice for cloud agents, GitHub sign-in through the GitHub CLI, explicit clone permission and folder, fork when the user cannot push, local git identity using the GitHub no-reply email); **LRN-04B** per-report fix run (git worktree on a `fix/report-…` branch from the latest `main`, the chosen AI edits the worktree, the Manager runs the matching checks itself and requires a documentation change); **LRN-04C** review and approval (diff, check results and PR text; on approval commit, push and `gh pr create --draft`; on reject remove the worktree and branch; report status and PR link updated).

**Done when:** setup asks for each step explicitly (AI, GitHub, clone permission and location) and can be undone; external coding agents are opt-in with a clear notice of what is sent; all edits stay in a worktree until approved; every proposed fix includes a documentation change or states why none is needed; the PR text is redacted and shown before pushing; PRs from users without push rights come from their fork; tests and an end-to-end check against a sample report pass.

#### LRN-05 — Turn tasks that worked into reusable skills or recipes

Offer to save a successful multi-step OpenClaw task as an OpenClaw skill, or a successful browser workflow as a browser recipe, reviewed and edited by the user before it is saved.

**Done when:** the saved skill or recipe is generalised (inputs instead of hard-coded values), reviewed by the user, and can be listed, edited and removed like other skills and recipes.

### Planned expansion — Agent platform supporting tools

The inventory and boundaries are documented in [Agent platform supporting tools](features/agent-platform-expansion.md). MAG-06 is the prerequisite for durable recurring work; these tasks add connectors, document ingestion, notifications, and an integrated evaluation/replay harness.

#### CAP-01 — Define typed service connectors and secure account handling

Define provider-specific typed operations, approved hosts, local account connection and revocation, least-privilege scopes, OS-protected credential storage, side-effect permissions, payload-bound write approvals, audit events, and stable errors. Do not expose arbitrary URLs, generic HTTP requests, or model-authored API scripts.

**Done when:** the connector contract documents account ownership and token lifecycle; secrets are excluded from prompts, run events, artifacts, source files, and telemetry; read and write permissions are distinct; provider responses remain untrusted input; mock-based tests cover scope denial, revocation, malformed responses, limits, and write approval.

#### CAP-02 — Implement the first user-selected service connector

Choose one provider based on a validated user workflow. Start with a narrow read-only operation set; add writes only as separately typed and payload-approved operations. Use CAP-01's credential and permission boundary.

**Done when:** the chosen provider and minimum scopes are documented; connection, refresh/revocation, timeout, rate limit, and provider error behavior are covered; tool outputs are bounded and attributed; reads and approved writes have mocked tests; no generic endpoint or arbitrary API-call capability is exposed.

#### DOC-01 — Add bounded PDF, Office, spreadsheet, and optional OCR ingestion

Extend explicitly attached and workspace-authorized inputs with safe extraction for selected PDF, Word, spreadsheet, and CSV formats. Add OCR only through an explicitly configured local engine. Preserve page/sheet provenance, and treat document contents as untrusted data.

**Done when:** allowed types, encryption behavior, parser sandboxing, byte/page/sheet/text/time limits, and retention are documented; macros, embedded scripts, external links, and automatic network fetches are never executed; malformed, encrypted, unsupported, or oversized inputs fail explicitly; extracted passages retain source/page/sheet references; focused synthetic fixtures cover success and rejection cases.

#### OPS-01 — Notify users about approvals and unattended run outcomes

Send minimal-content in-app and optional local desktop notifications for pending approvals, completed/failed runs, and scheduled runs that need attention. Read state from the durable run/worker records; never approve or resume an action through notification delivery.

**Done when:** notification delivery is idempotent and linked to the durable run; users can disable channels and still inspect history; payloads exclude prompts, credentials, page/document content, and sensitive tool outputs; delivery failure does not alter run status; pause, approval-needed, completion, failure, cancellation, and restart/recovery cases are tested.

#### EVA-01 — Add privacy-safe tool evaluation and non-executing replay tests

Consolidate synthetic end-to-end capability cases with typed-contract, permission, size/resource-limit, timeout, cancellation, and failure checks. Add replay tests that reconstruct event views without dispatching tools or repeating external side effects. Extend the existing scenario regression pack and planner routing evaluation rather than replacing them.

**Done when:** a deterministic suite reports case/build/contract versions and pass/fail evidence; external APIs/browser sessions use mocks or synthetic fixtures by default; replay is proven not to execute tools; privacy-safe metrics exclude prompts, responses, page/document content, and credentials by default; representative regression cases cover browser/runtime selection, document parsing, connector denial/revocation, scheduled-run recovery, and notification failure.

### Agent Studio desktop redesign

The user asked (2026-11-21) for the "Agent Studio" redesign of the desktop app from a design canvas of 21 boards, as a UI and information-architecture change that keeps every page, behaviour and the main-process boundary, and then (same day) for PockPock to support every element of the design, adding the backend events and features some elements need. Split into reviewable pull requests:

- **UI-01A** — the shell. **Done when:** a 56 px icon rail (Tasks, Workshop, Activity, Services, Settings), a 252 px task list or Workshop navigation, the task or page, and a 320 px inspector (Context, Files, Terminal) with the terminal under the composer; overlays below 1100 px (inspector) and 860 px (rail and task list); a run bar above every task with phases, current step, signal, elapsed time, Stop and a 2 px bar, and distinct working, slow (10 s), waiting and failed states that never look hung (reduced motion included); every existing page reachable; a command palette; the gateway sends `usage` and `verifying` events; contrast, axe and screenshots checked in every theme at 1440 and 820 px.
- **UI-01B** — thread and composer: plan card (delivers, workspace, task folder, reviewer, questions with answer choices, editable step list, success checks), thread cards (collapsed steps, approvals with "Allow for this task", install from a link, saved sources, message actions, failed step with "Retry from step N"), pickers. Needs: a plan pre-check, run-scoped approval grants, structured answer choices with re-planning, notes accepted by a running task, and a resumable run from step N.
- **UI-01C** — the Workshop pages in the new layout with their empty, loading and error states.
- **UI-01D** — Settings, Setup, dialogs, toasts and themes.
- **UI-01E** — watching saved sources for changes (network access while PockPock runs, off by default, per source).
- **UI-01F** — plan-step progress reported by the agent, shown only when reported.
- **UI-01G to UI-01M** — design elements not built yet, listed in [Agent Studio design coverage](features/desktop-app.md#agent-studio-design-coverage). Ready, not started.

## Completion log

TOL-01, FND-01, TOL-02, FND-02, FND-04, PLN-01, PLN-02, PLN-03, BRW-01, BRW-02, BRW-03, BRW-04, BRW-05, BRW-06, BRW-06A, BRW-06B, BRW-06C, BRW-06C1, BRW-06C2, BRW-06C2A, BRW-06C2B, BRW-06C2C, BRW-06C3, RES-01, RES-02, RES-03, RES-04, RES-05, RES-06, MAG-01, MAG-02, MAG-03, MAG-04A, MAG-04B, MAG-04C, MAG-05A, MAG-05B, AUT-01, AUT-06A, AUT-06B, AUT-06, SEQ-01A, and SEQ-01C are complete. Operational controls such as cancellation, timeouts, and payload limits remain to keep local runs reliable.

| Date | Task ID | Agent/owner | Result and verification | Changed files |
| --- | --- | --- | --- | --- |
| 2026-11-25 | Planner schema and repeat guard (user request: Gen AI topics research, not a roadmap task) | Primary agent | From a review of a 45-topic Gen AI research page against the code (most of its top items already existed: compaction, tool-output truncation, streaming, run deadlines, interrupted runs, Tool-RAG, eval harness, a LoRA recipe). Built the two real gaps that fit: (1) structured output for `/plan` — `PLAN_SCHEMA` sent as Ollama `format` through the new `ChatCompletionRequest.json_schema` (cloud payloads unchanged), and one retry with the error when the reply is unusable; (2) repeated tool calls — `agent_core/repeat_guard.py` refuses a third identical call with no state-changing call in between and stops the run after three refusals (`agent_tool_repeat_refused` event). Verification: 2 planner tests, 1 client test, 5 repeat-guard tests; agent_core, planner and model_router suites 117 passed. Not verified: a live plan from a real model with the schema (no model was loaded; loading one needs the user's OK), a live run that repeats. | `backend/projects/{planner/app.py,planner/test_planner_stream.py,model_router/client.py,model_router/test_client.py,agent_core/repeat_guard.py,agent_core/test_repeat_guard.py,agent_core/executor.py}`, `backend/scripts/telemetry_store.py`, docs |
| 2026-11-22 | OpenClaw works in the chosen folder (user report, not a roadmap task) | Primary agent | OpenClaw ignored the open folder and always worked in `~/.openclaw/workspace`. The desktop app now sends `workspace_path` to `/api/openclaw/chat`; the bridge checks it (full path, existing folder: `invalid_workspace`), and the helper calls the gateway's `sessions.create {key, cwd}` before every turn (an existing session keeps its transcript and takes the new folder; no folder resets it to `agents.defaults.workspace`). The permission picker's **Task folder** section now shows for OpenClaw too, with **Use OpenClaw's workspace**. Verification: 3 new bridge tests (29 passed), 13 Node helper tests, typecheck, build; live against a temporary OpenClaw 2026.11.3 gateway with a stand-in model: `exec` ran in the chosen folder and a relative `write` landed there, a changed folder applied on the next turn of the same session, and no folder went back to OpenClaw's workspace; the real app's menu at 1440 px, no console errors. Not verified: a real model's turn. | `backend/projects/openclaw_bridge/{api,bridge,gateway_turn.mjs,test_bridge}`, `desktop/src/lib/engines.ts`, `desktop/src/components/{Pickers,Inspector}.tsx`, docs |
| 2026-11-22 | Local MCP, step 1 (user request, not a roadmap task) | Primary agent | New service `mcp_hub` (Local MCP, :8776) runs the MCP servers added in PockPock once and serves each at `/mcp/<name>` (streamable HTTP, hub token); stdio processes shared by all clients with hub-side request ids, restarted after a crash and held after three in a minute; remote servers with the saved headers; `ping`/`roots/list` from servers answered by the hub. Secrets sealed with DPAPI on Windows. The gateway installs into it and gives OpenClaw only the hub address and token; at start it moves servers installed earlier (keys read from OpenClaw's config file, since its gateway shows them redacted), re-points changed entries and removes orphans. MCP page: state badges, Log, Restart, Local MCP stopped note; Services lists Local MCP. Verified: `mcp_hub` 11/11, `agent_extensions` 49/49, backend suite (only the Windows symlink test fails, as before), desktop tests, typecheck, build; live: filesystem and Playwright servers via npx through the hub, OpenClaw's own MCP client through it (and refused with a wrong token), the move against a real OpenClaw gateway on a temp config (real secret moved, OpenClaw file cleaned, switch kept, foreign server untouched, second run no-op), stop by process tree leaves no server; the app with all of it isolated: 15/15 incl. axe and 820 px. Not verified: a full OpenClaw chat turn calling a hub tool; macOS/Linux beyond CI. Steps 2-4 (PockPock Agent, smarter use, NemoClaw) planned in the feature page. | `backend/projects/mcp_hub/*`, `agent_extensions/hub_client.py`, `service.py`, `api.py`, `gateway_config.mjs`, `test_extensions.py`, `scripts/pockpock_server.py`, `scripts/pockpock.py`, `scripts/run_tests.py`, `desktop/electron/services.cjs`, `main.cjs`, `desktop/src/pages/McpPage.tsx`, `extensions.tsx`, `docs/features/local-mcp.md`, `agent-extensions.md`, `desktop-app.md`, `docs/ARCHITECTURE.md`, `docs/FEATURES.md`, `README.md` |
| 2026-11-22 | Cloud providers: OpenAI and Claude (user request, not a roadmap task) | Primary agent | OpenRouter removed; OpenAI (`api.openai.com`, Bearer key, model list as key check, chat models only, newest-GPT fallback) and Claude by Anthropic (model list with `x-api-key` and `anthropic-version`, chat through Anthropic's OpenAI-compatible endpoint) added. The gateway's `adapt_body` drops what Claude refuses (`temperature`, `top_p`, forced `tool_choice`, non-strict `response_format`) and renames `max_tokens` for OpenAI reasoning models, on its own requests and on `/cloud/v1`. Disconnecting a service, or switching a model off, cleans up: gateway pushed, OpenClaw's provider rewritten, NemoClaw moved back to its local model when it used a removed model, and saved chat, OpenClaw and planner choices cleared (`useCloudCleanup`); a saved OpenRouter key is deleted at start. Verified: `cloud.test.cjs` 14/14, `test_cloud.py` and `test_bridge.py` 30/30, typecheck and build; real app with a temp data folder: made-up keys refused by the real OpenAI and Anthropic APIs (401) and nothing saved, stale `anthropic/`, `openai/` and `openrouter/` choices cleared at start, the Cloud page lists the four services and passes axe. Not verified: a real OpenAI or Anthropic key. | `desktop/electron/cloud.cjs`, `cloud.test.cjs`, `desktop/src/lib/cloudCleanup.ts`, `App.tsx`, `types.ts`, `pages/CloudPage.tsx`, `backend/projects/model_router/cloud.py`, `cloud_api.py`, `test_cloud.py`, `README.md`, `nemoclaw_bridge/bridge.py`, `test_bridge.py`, `docs/features/cloud-models.md`, `README.md`, `docs/ARCHITECTURE.md`, `docs/FEATURES.md`, `docs/features/desktop-app.md` |
| 2026-11-22 | SEQ-01D (Plan in steps) | Primary agent | PockPock Agent can plan in steps: the model menu's Planning section picks the planner (a connected cloud model such as NVIDIA NIM, or a local one); the composer's model does each step. The gateway's plan-sequence takes `planner_model`; run-sequence now runs file tools, shows file changes for approval in Auto-review (step budget paused while waiting) and applies them, reports saved files, and turns runner events into Step N of M, checks, retries and a reply. Live fixes: tool text from `content`/`files`/`matches`; a writing step gets the earlier reading tool; "in this folder" writes into the open folder; `file_contains` ignores case. Verification: runner, verifier, gateway, event and repair tests; backend suite (except the known Developer-Mode symlink test); 49 Electron tests; typecheck; build; 17/17 app checks with stand-in replies; live: two tasks completed with the Qwen3.6 planner and Qwen3.5-9B steps. Not verified: a cloud planner with a real NIM key; OpenClaw as the step runner (next PR). | `backend/projects/plan_sequence/{runner,contracts,verifier,ui_events}.py` and tests, `backend/projects/planner/app.py`, `backend/scripts/{pockpock_server,test_plan_sequence_gateway}.py`, `desktop/src/lib/{engines,types}.ts`, `desktop/src/components/{PlanCard,Pickers,ChatPane}.tsx`, `desktop/src/App.tsx`, `desktop/src/styles.css`, docs |
| 2026-11-22 | OpenClaw tool retrieval (user request, not a roadmap task) | Primary agent | Before each OpenClaw turn, PockPock ranks the usable skills and MCP servers against the message (BM25 plus embeddings when installed, stopwords ignored), keeps up to 6 skills, the matching servers and what the conversation used in its last 3 turns, and hides the rest for that session with OpenClaw's `sessions.patch toolOverrides` (false entries only; null clears). Not filtered below 8 skills or with one server; any failure offers everything. A `tool_selection` event shows "Offered OpenClaw n of m skills". Verification: 7 selection tests, 2 bridge tests, 1 Node test, backend suite (except the known Developer-Mode symlink test), typecheck. Not measured live yet: the user was running an OpenClaw turn (`qwen3.6:35b-a3b`, a 21,089-token prompt in Ollama's log); the before/after prompt size is to be read from Ollama's log in two short turns when OpenClaw is idle. Expected saving on this PC: about 800 of about 21,000 tokens. | `backend/projects/openclaw_bridge/{tool_selection,test_tool_selection,bridge,api,gateway_turn.mjs,turn_helpers.mjs,turn_helpers.test.mjs,test_bridge}`, `backend/scripts/pockpock_server.py`, `desktop/src/lib/engines.ts`, docs |
| 2026-11-22 | Find on mcpservers.org (user request, not a roadmap task) | Primary agent | MCP servers and Skills pages search mcpservers.org: its curated list (awesome-mcp-servers README, about 500 servers with descriptions and GitHub links; Preview and install through the normal preview) always, and its whole site from its sitemaps on request (about 13,000 servers, 8,000 skills; names, Open on mcpservers.org). The site's pages and /api/ are not used (browser check, robots.txt). Cached daily (curated) and weekly (index). A server PockPock cannot start from its link says why under the result. Verification: 6 backend tests; live: curated search 0.1 s, full index downloaded in 3.2 s, cache 747 KB; 15/15 app checks with a test gateway and a temporary OpenClaw folder (search, full index, Open on mcpservers.org, a failed and a working preview, skills, empty result, axe-core). Not verified: installing a server found this way. | `backend/projects/agent_extensions/{directory,test_directory,api}.py`, `desktop/src/pages/{DirectorySearch,McpPage,SkillsPage,extensions}.tsx`, `desktop/src/styles.css`, docs |
| 2026-11-22 | OpenClaw model list (user report, not a roadmap task) | Primary agent | `qwen3.6:35b-a3b` did not appear in the OpenClaw model picker: OpenClaw's Ollama model list was written once at setup. The app now keeps it in step with Ollama (new models added with settings from `/api/show`, uninstalled ones removed, the default kept). Verification: 3 node tests; on this PC the sync added `qwen3.6:35b-a3b` (tools, 64K context) and removed 5 uninstalled models, and `openclaw models list` showed `ollama/qwen3.6:35b-a3b`. Not run: an OpenClaw turn with it. | `desktop/electron/openclaw-models{,.test}.cjs`, `desktop/electron/main.cjs`, `docs/features/openclaw-agent.md` |
| 2026-11-22 | LRN-04A (accounts, user report) | Primary agent | A Claude Code that was only signed in on the PC (from an editor) showed as Connected and was chosen, so fixes ran on the user's Claude account without them connecting it. Now PockPock itself is the default; an account (Claude, OpenAI Codex, Copilot) is used only after **Connect this account** here, shows which account, and can be disconnected; an account that is not connected or stops working falls back to PockPock itself, with the reason shown. OpenAI Codex can be installed and signed in from the app. A note explains the optional account. Verification: 3 new and 3 changed node tests (53 desktop tests), typecheck, build, 11/11 app checks in a temporary profile. Not verified: a real OpenAI sign-in, a run that falls back mid-fix. | `desktop/electron/maintenance{,-connect,-fix}.cjs`, `maintenance.test.cjs`, `preload.cjs`, `main.cjs`, `desktop/src/components/MaintenanceSetup.tsx`, `desktop/src/lib/types.ts`, `desktop/src/styles.css`, `docs/features/maintenance.md`, `README.md` |
| 2026-11-22 | UI-01E | Primary agent | Watching saved sources: per source, off by default; the gateway re-reads watched pages in the background (every 6 h by default, `POCKPOCK_SOURCE_WATCH_MINUTES`, at most 3 per minute, only while research is on, at most 50 sources) and records changes like a manual refresh; failed checks are recorded and retried after a full interval. Routes to watch, list and mark seen; run-store columns added in place, with matching service routes. Desktop: **Watch for changes** switch on saved sources (the card now loads what was saved), **Watched pages** on Research (Check now, Mark as seen, Stop watching, paused note), and an **A watched page changed** toast. Verification: 13 new backend tests, backend suite (except the known Developer-Mode symlink test), the routes through a real run-store service, typecheck, build, 49 Electron tests, contrast 100/100, 32/32 app checks including a real background pass that found a change on example.com, axe-core 0 violations. Not verified: a gateway running over several intervals; macOS. | `backend/scripts/{research_watch,test_source_watch,agent_run_store,pockpock_server,run_tests}.py`, `backend/projects/run_store/{app,test_research_watch_store}.py`, `desktop/src/lib/watch.ts`, `desktop/src/components/{ThreadCards,Toasts}.tsx`, `desktop/src/pages/ResearchPage.tsx`, `desktop/src/App.tsx`, `desktop/src/styles.css`, `desktop/scripts/check_contrast.mjs`, docs |
| 2026-11-21 | UI-01F | Primary agent | Plan-step progress: the agent gets `report_plan_step` (progress only, handled by the gateway, not counted as a tool call; one extra turn per plan step) and each valid call becomes a `plan_step` event; the run bar shows **Step 3 of 5** with the step's text, the task list "Agent · Step 3 of 5", the plan card marks the current step **Now**, and a failed or stopped run says which step it was on. Shown only when reported. Verification: 8 new backend tests, backend suite (except the known Developer-Mode symlink test), typecheck, build, 49 Electron tests, contrast 98/98, 19/19 app checks with a streamed run in all four themes at 1440 and 820 px, axe-core 0 violations. Live `qwen3.5:9b` gateway runs: 3 of 4 reported every step, 1 reported none; all finished correctly. | `backend/projects/agent_tools/{plan_progress,test_plan_progress}.py`, `backend/projects/agent_core/executor.py`, `desktop/src/lib/{runState,engines,types}.ts`, `desktop/src/components/{RunBar,PlanCard}.tsx`, `desktop/src/styles.css`, `desktop/scripts/check_contrast.mjs`, docs |
| 2026-11-21 | UI-01D | Primary agent | Settings in sections with a theme radio grid; toasts for update ready, gateway stopped or failed, and Ollama not running; a shared Modal (focus kept inside, Escape, focus returned) used for the Maintenance Manager setup; the report dialog now returns focus and no longer refocuses its first field on every render; Setup stepper (Welcome, Choose, Install, Check). Pages.tsx renamed SettingsPage.tsx. Verification: typecheck, build, 49 Electron tests, contrast 96/96, 46/46 app checks (toasts driven by a stopped gateway, a changed state reply and the updater's event; themes by click and arrow keys; dialogs; stepper), axe-core 0 violations. Not verified: Restart to update with a real update; the stepper through a real install. | `desktop/src/pages/SettingsPage.tsx`, `desktop/src/pages/{SetupPage,MaintenancePage}.tsx`, `desktop/src/components/{Modal,Toasts,ReportDialog}.tsx`, `desktop/src/App.tsx`, `desktop/src/styles.css`, `desktop/scripts/check_contrast.mjs`, docs |
| 2026-11-21 | UI-01C | Primary agent | Workshop pages: shared page kit (frame, switches, tabs with counts, stat tiles, drawer), one file per page; Skills as tabbed cards with search, a details drawer and the skill inbox (Check it, Review and add, Reject); Local models with the Smart route card, per-model calls, success and time from telemetry, load state and tags from Ollama's details; Connectors details in a drawer; Research as one switch; recipes list beside the editor; MCP, Memory, Activity, Services, Cloud and Maintenance in the new frame. The app's connectors and cloud calls follow `POCKPOCK_BACKEND_URL`. Verification: typecheck, build, 49 Electron tests, contrast 91/91, 119/119 app checks in all four themes at 1440 and 820 px, axe-core 0 violations, no console errors. Not shown (no data): skill use counts, model purpose tags beyond Ollama's details, Unload (models are not unloaded from the app), watched sources (UI-01E). | `desktop/src/components/page.tsx`, `desktop/src/pages/*`, `desktop/src/App.tsx`, `desktop/src/styles.css`, `desktop/electron/{main,connectors,cloud}.cjs`, docs |
| 2026-11-21 | UI-01B | Primary agent | Plan card (pre-check badges, task folder, answer choices that re-plan, editable steps and checks), thread cards (steps, approvals with Allow for this task, sources, failed step with Retry from step N, message actions, notes), pickers with keyboard navigation; gateway: `precheck` on the plan reply, `question_options` in the brief, approval `scope: task` grants per run (agent) and per turn (OpenClaw `allow-task`), `POST /api/runs/{run}/notes`. Install card reused (ExtensionCard). Damaged `sessions.json` entries are skipped on load. Verification: backend suite (8 pre-check, 3 note, 1 question-options, bridge allow-task tests), 12 OpenClaw helper tests, typecheck, build, 49 Electron tests, contrast 91/91, app checks 29/29 with mocked agent calls in every theme, axe 0 violations; real `qwen3.5:9b` run: pre-check, note given, task grant auto-allowed the second file change. Not verified live: answer choices, Retry from step N. | `backend/projects/agent_core/{precheck,executor}.py`, `backend/projects/planner/{contracts,app}.py`, `backend/projects/openclaw_bridge/{bridge.py,gateway_turn.mjs,turn_helpers.mjs}`, `backend/scripts/pockpock_server.py`, `desktop/src/components/{PlanCard,ThreadCards,Pickers,MessageView,ChatPane,ui}.tsx`, `desktop/src/lib/{engines,types,store}.ts`, `desktop/src/App.tsx`, `desktop/src/styles.css`, docs |
| 2026-11-21 | UI-01A | Primary agent | Agent Studio shell: rail, task list with Needs you / Running groups, Workshop navigation (all page ids kept), run bar (`lib/runState.ts`: working, slow after 10 s, waiting, failed with what was kept, stopped, done), inspector (Context with context used and files touched, Files, Terminal), command palette; gateway `usage` and `verifying` events and `output_directory` in `/api/state`. Verification: backend suite and 3 new helper tests pass (except the known Developer-Mode symlink test); typecheck, build, 49 Electron tests; `check:contrast` 80/80 in every theme; 56 screenshots in all four themes at 1440 and 820 px with mocked agent calls (no console errors, no overflow); axe-core 0 violations on 16 screens; a real `qwen3.5:9b` run emitted `usage` and `verifying`. | `desktop/src/App.tsx`, `desktop/src/components/{Shell,TaskPanel,RunBar,Inspector,CommandPalette,ChatPane,FilesPanel,ui}.tsx`, `desktop/src/lib/{runState,permissions,engines,types}.ts`, `desktop/src/styles.css`, `desktop/electron/services.cjs`, `desktop/scripts/check_contrast.mjs`, `backend/projects/agent_core/executor.py`, `backend/scripts/pockpock_server.py`, docs |
| 2026-11-17 | SEQ-01A | Plan-sequence wave | P0 schema + validation + capsule: `SequencePlan` / `SequenceStep` / `DoneCondition` / `StateCapsule` (Pydantic v2, `extra="forbid"`), `validate_sequence_plan` (5–15 steps, unique ids, registered tools only, typed done-conditions, no dangling inputs), `build_capsule` (≤400 tokens, ≤24 entries, pointer-loss flag). Verification: 84-test `plan_sequence` suite passes, including invalid-plan rejection and capsule-trimming tests. | `backend/projects/plan_sequence/contracts.py`, `capsule.py`, `__init__.py`, `README.md` |
| 2026-11-17 | SEQ-01C | Plan-sequence wave | P2 verifier + retry: `verify_done_condition` checks typed done-conditions against files and the recorded step result (never the model's claim, never raises); `SequenceRunner` retries a failed step ≤2× with grounded feedback, then stops with `needs_replan` for the remaining steps only; executor always called with `think=False`; pinned tools harness-enforced. Verification: 84-test `plan_sequence` suite passes, including wrong-step retry → `needs_replan`, tool-outside-allowed rejection, and prompt-over-budget cases. Not yet wired: no in-repo runner caller, no adapter to the real tools, no run-store persistence of runner events. | `backend/projects/plan_sequence/verifier.py`, `runner.py`, `__init__.py`, `README.md` |
| 2026-11-16 | LRN-04A, LRN-04B | Claude Code (user session) | Setup (AI detection for PockPock itself, GitHub Copilot, Claude Code and Codex with data notices; GitHub CLI sign-in; clone or fork after an explicit Allow; no-reply git identity) verified end to end in the real app with a real clone. Fix runs in git worktrees with the Manager's own checks and a required documentation change; "PockPock itself" is a native tool loop on Ollama (`maintenance-agent.cjs`) after an OpenClaw-based attempt stalled on a hung tool for 21 minutes; automatic mode works through open reports one at a time. Real run: automatic mode picked up a documentation report, `qwen3.5:9b` produced a fix with a docs update in 1.8 min, all four desktop checks passed, the run reached "ready for review", and discard removed the worktree and branch. 23 node tests. The watchdog in `gateway_turn.mjs` now counts only real progress. Not yet exercised: approval opening a real draft PR (LRN-04C). | `desktop/electron/maintenance*.cjs`, `desktop/src/components/MaintenanceSetup.tsx`, `FixPanel.tsx`, `desktop/src/pages/MaintenancePage.tsx`, `backend/projects/openclaw_bridge/gateway_turn.mjs`, `docs/features/maintenance.md` |
| 2026-11-16 | LRN-04B (option) | Claude Code (user session) | "PockPock itself" can optionally run through OpenClaw so it can run commands (build, tests, the app) while fixing. In a real run with `qwen3.5:9b` OpenClaw looped for 34 minutes without a tool call or file change, and its watchdog did not stop it because each finished model call counts as progress. Added `idleGuard`: a run with no tool call for 10 minutes is stopped and marked failed. 24 node tests, typecheck and build pass. Not re-run end to end with a larger model; the file-only agent stays the default. | `desktop/electron/maintenance*.cjs`, `MaintenanceSetup.tsx`, `FixPanel.tsx`, `docs/features/maintenance.md`, `README.md` |
| 2026-11-16 | LRN-04B (cloud AIs) | Claude Code (user session) | Real run with GitHub Copilot CLI 1.0.107: worktree created from the latest `main`, Copilot started in it, and it stopped with "You have exceeded your monthly quota"; the run failed cleanly with that message and discard removed the worktree and branch. The same review found that Claude Code and Codex, installed by npm as `.cmd` launchers, were started through `cmd.exe` with the report text on the command line (unescaped, so `&` in a report could run commands, and the allowed-tools list split at spaces). `agentCommand` now sends their prompt on stdin and quotes the fixed arguments; 25 node tests. A successful cloud-AI fix is still not verified. | `desktop/electron/maintenance-fix.cjs`, `maintenance-fix.test.cjs`, `docs/features/maintenance.md` |
| 2026-11-16 | LRN-04A (connect) | Claude Code (user session) | Setup can install and sign in to Claude Code and GitHub Copilot from a button (winget or Homebrew, then npm; `claude auth login` / `copilot login`), and shows each as Connected, Not signed in or Not installed. Real run in the app on Windows: **Install and connect Claude Code** installed 2.1.318 with winget; the first attempt then also installed it with npm because winget's portable package folder was not searched, which was fixed (the npm copy was removed) and re-checked. Claude Code was already signed in through its VS Code use, so the sign-in step of either tool has not been exercised, and macOS is untested. Real fix run with Claude Code as the Maintenance Manager: it wrote a correct documentation fix in 50 s, then hit its 5-hour usage limit before writing the PR text; the run reached ready, which exposed that an early stop was not flagged, so a ready fix now carries a warning when the AI stopped with an error. 29 node tests, typecheck and build pass; 1440 px and 820 px windows checked. | `desktop/electron/maintenance-connect.cjs`, `maintenance.cjs`, `MaintenanceSetup.tsx`, `docs/features/maintenance.md`, `README.md`, `docs/ARCHITECTURE.md` |
| 2026-11-16 | Cloud models (user request, not a roadmap task) | Claude Code (user session) | New **Cloud models** page: connect NVIDIA NIM, OpenRouter or Alibaba Cloud Model Studio with an API key (checked with the service, stored encrypted with `safeStorage`), choose models, and pick them in the model menus of Chat, PockPock Agent, OpenClaw and NemoClaw. The gateway holds the keys in memory, routes `<provider>/<model>` names to the provider, and serves `/cloud/v1`, a local OpenAI-compatible endpoint used by the planner, OpenClaw (provider `pockpock-cloud`) and NemoClaw (OpenShell provider `pockpock-cloud`), so no cloud key enters their configuration. Automatic routing stays local. Verified: 37 desktop node tests, all backend suites (model_router 11, nemoclaw_bridge 21), typecheck and build; model-list parsing against the public OpenRouter and NVIDIA lists; a made-up key refused by all three real services; chat, the local endpoint and a PockPock Agent plan through a stand-in provider on an isolated gateway and planner (13 checks); the Cloud page and every model menu in the real app at 1440 and 820 px (22 checks, connected states with stand-in data). **Not verified:** a real key on any service, a real OpenClaw or NemoClaw turn on a cloud model (the user's local model was in use, so their OpenClaw and sandbox were not touched), a full agent run with tools, macOS. | `desktop/electron/cloud.cjs`, `cloud-openclaw.cjs`, `desktop/src/pages/CloudPage.tsx`, `ChatPane.tsx`, `backend/projects/model_router/cloud.py`, `cloud_api.py`, `backend/projects/nemoclaw_bridge/`, `backend/projects/openclaw_bridge/gateway_turn.mjs`, `docs/features/cloud-models.md` |
| 2026-11-16 | Connectors (user request, not a roadmap task; replaces PR #72) | Claude Code (user session) | New **Connectors** page for external apps only: GitHub, email (IMAP/SMTP), Telegram, Slack, Discord, Notion. Each credential is checked with the app, stored encrypted with `safeStorage`, and pushed to the gateway's memory; the gateway serves the connected apps' 22 tools at `/mcp/connectors` and registers them in OpenClaw as `pockpock-connectors`. PR #72 listed 8 internal items and recorded 14 of its 15 external connectors without connecting; none of that is kept. Verified: backend `connectors` 10 tests (routes over a real socket, tools listed by the repo's MCP client), desktop 41 node tests, typecheck and build; a made-up credential refused by the real GitHub, Telegram, Slack, Discord, Notion and Gmail; 30 checks in the real app against an isolated gateway with a stand-in GitHub account. **Not verified:** a real account on any app, a real OpenClaw chat using the tools (the OpenClaw registration was recorded, not applied, in the test), macOS. PockPock Agent and NemoClaw do not get the tools yet. | `backend/projects/connectors/`, `desktop/electron/connectors.cjs`, `desktop/src/pages/ConnectorsPage.tsx`, `docs/features/connectors.md` |
| 2026-11-15 | LRN-03 | Claude Code (user session) | Report button under every assistant reply opens a modal dialog (category, description, redacted preview); reports are stored by the main process as redacted JSON in `<userData>/reports` (max 200) and listed, edited and deleted on the new Maintenance page. 5 node tests (redaction, sanitising, store, id checks). Real-app check in PockPock Dark and Feather at 1440 and 820 px: focus kept in the dialog, Escape closes, preview and stored file free of the home folder, email and attachment contents, status edits persist, delete works, no overflow or console errors. Limitation: redaction is pattern-based and cannot catch every personal detail in free text; the preview is shown for that reason. | `desktop/electron/reports.cjs`, `desktop/src/components/ReportDialog.tsx`, `desktop/src/pages/MaintenancePage.tsx`, `desktop/src/lib/reports.ts`, `docs/features/maintenance.md` |
| 2026-11-15 | LRN-01 | Claude Code (user session) | Versioned OpenClaw guidance block refreshed at app start and setup (`openclaw-guidance.cjs`, 6 node tests); stall watchdog and readable tool errors in the turn bridge (`turn_helpers.mjs`, 4 node tests; both run in CI); OpenClaw browser choice (Settings, `browsers.cjs`, IPC validated against installed browsers). Real turns on `qwen3.5:9b` before/after the new guidance: checking a global npm package went from 2 min 16 s and a script-policy failure to 32 s with `npm.cmd` and a correct answer; reading the heading of example.com went from three invalid browser calls and a wrong answer to three valid calls and "Example Domain" (in Brave). Backend suite, typecheck and build pass. Not covered: reproducing OpenClaw's "requester authority changed" approval failure itself; the watchdog limits its effect to 8 minutes. | `backend/projects/openclaw_bridge/` (`workspace-guidance.md`, `gateway_turn.mjs`, `turn_helpers.mjs`), `desktop/electron/` (`openclaw-guidance.cjs`, `browsers.cjs`, `main.cjs`, `setup.cjs`, `preload.cjs`), `desktop/src/pages/Pages.tsx`, `.github/workflows/ci.yml`, `docs/features/openclaw-agent.md` |
| 2026-11-11 | TOL-01 | Primary agent | Moved the current tool catalog/tests into the dedicated project; Python compilation passed; 20 focused unit tests passed. | `backend/projects/agent_tools/`, `backend/projects/validator/`, `backend/scripts/pockpock_server.py`, `docs/`, `README.md` |
| 2026-11-11 | FND-01 | Primary agent | Added versioned per-tool runtime contracts and run-event/error compatibility; Python compilation passed; all 29 focused/current agent and event-contract tests passed. | `backend/projects/agent_tools/contracts.py`, `backend/scripts/agent_run_store.py`, `backend/scripts/pockpock_server.py`, `backend/projects/run_store/`, `docs/`, `README.md` |
| 2026-11-11 | TOL-02 | Primary agent | Split tool implementation and focused tests into capability modules behind a compatibility facade; Python compilation passed; all 29 focused/current agent and event-contract tests passed. | `backend/projects/agent_tools/`, `backend/projects/validator/`, `backend/scripts/pockpock_server.py`, `docs/`, `README.md` |
| 2026-11-11 | FND-02 | Primary agent | Added persistent cooperative cancellation, 15-minute total timeout, terminal replay, late-event rejection, and stale-run recovery; Python compilation and frontend build passed; all 36 focused suites passed, including an end-to-end mocked gateway cancellation check. | `backend/scripts/pockpock_server.py`, `backend/scripts/agent_run_store.py`, `backend/projects/run_store/`, `frontend/app/src/App.tsx`, `docs/`, `README.md` |
| 2026-11-11 | BRW-01 | Primary agent | Added isolated Playwright Chromium runtime, authenticated run context lifecycle, standard launcher/setup integration, and run cancellation cleanup; Python compilation passed, 14 focused tests passed, all five local service health checks passed, and create/close plus cancellation lifecycle checks passed. | `backend/projects/browser_automation/`, `backend/projects/internal_auth.py`, `backend/scripts/frog_ai_service_helpers.ps1`, `backend/scripts/setup_frog_ai.ps1`, `backend/scripts/pockpock_server.py`, `backend/projects/README.md`, `backend/projects/agent_tools/README.md`, `docs/` |
| 2026-11-11 | BRW-02 | Primary agent | Added safe public-page navigation, structured observations, run-scoped screenshots, and private/cross-host request blocking; Python compilation passed; manual public navigation, evidence retrieval, loopback/cross-host rejection, redirect blocking, and cleanup checks passed. | `backend/projects/browser_automation/app.py`, `backend/projects/browser_automation/README.md`, `docs/features/browser-runtime.md`, `docs/features/local-workflow-services.md`, `docs/ARCHITECTURE.md`, `README.md`, `docs/TASKS.md` |
| 2026-11-12 | RES-04 | Primary agent | Added structured research claim validation and rendering with exact source-excerpt matching, timestamped source links, distinct-source conflict passages, explicit unsupported claims, safe rendering of page text, and bounded invalid-answer retries. Added workspace permission dispatch enforcement and plan-permission immutability coverage. Corrected the stale registry-count assertion from 12 to 14. Python compilation and all 54 focused tests passed. | `backend/projects/agent_tools/research_answers.py`, `backend/projects/agent_tools/test_research_answers.py`, `backend/projects/agent_tools/test_contracts.py`, `backend/projects/agent_tools/__init__.py`, `backend/scripts/pockpock_server.py`, `backend/projects/planner/test_plan_gate.py`, `backend/projects/agent_tools/README.md`, `docs/features/research-provider-contracts.md`, `docs/features/agent-tools.md`, `docs/features/agent-tool-contracts.md`, `docs/features/agent-runs.md`, `docs/ARCHITECTURE.md`, `README.md`, `docs/TASKS.md` |
| 2026-11-12 | RES-05 | Primary agent | Added validated Markdown/HTML and clickable Word/Excel/PowerPoint research exports, gateway artifact events and extension checks, safe page-text rendering, spreadsheet formula protection, and focused writer/gateway tests. Python compilation and all 61 focused tests passed. | `backend/projects/agent_tools/research_exports.py`, `backend/projects/agent_tools/test_research_exports.py`, `backend/projects/agent_tools/__init__.py`, `backend/scripts/pockpock_server.py`, `backend/projects/agent_tools/README.md`, `docs/features/research-provider-contracts.md`, `docs/features/agent-runs.md`, `README.md`, `docs/TASKS.md` |
| 2026-11-12 | RES-06 | Primary agent | Added task/workspace-scoped collections, explicit 200 KB text snapshots, notes, manual refresh with hash-based versioning and text comparisons, retained version history, and collection deletion. Store/API tests, Python compilation, and the web production build passed. | `backend/scripts/agent_run_store.py`, `backend/scripts/pockpock_server.py`, `backend/projects/run_store/app.py`, `backend/projects/run_store/test_research_collections.py`, `frontend/app/src/App.tsx`, `frontend/app/src/App.css`, `docs/features/research-provider-contracts.md`, `docs/features/agent-runs.md`, `backend/projects/run_store/README.md`, `README.md`, `docs/ROADMAP.md`, `docs/TASKS.md` |
| 2026-11-12 | MAG-04A | Primary agent | Added bounded dependency scheduling, configured concurrency validation, deterministic child run IDs, and idempotent durable child create-or-load; 45 focused tests passed and Python compilation passed. | `backend/projects/run_store/delegation_scheduler.py`, `backend/projects/run_store/test_delegation_scheduler.py`, `backend/projects/run_store/README.md`, `docs/features/delegated-agent-runs.md`, `docs/FEATURES.md`, `docs/ARCHITECTURE.md`, `docs/TASKS.md` |
| 2026-11-12 | MAG-04B | Primary agent | Connected bounded scheduling to isolated child execution with tool/context limits, deadlines, parent cancellation, typed terminal results, and atomic local/remote execution claims; Python compilation passed; 77 focused tests and all 40 project-discovered tests passed. | `backend/scripts/pockpock_server.py`, `backend/scripts/agent_run_store.py`, `backend/projects/run_store/app.py`, `backend/projects/run_store/test_delegation_scheduler.py`, `backend/projects/run_store/test_event_contracts.py`, `backend/projects/run_store/README.md`, `docs/features/delegated-agent-runs.md`, `docs/ARCHITECTURE.md`, `docs/TASKS.md` |
| 2026-11-12 | MAG-04C | Primary agent | Added child status/model/scope/activity/result parent timeline events and typed-result retry replay; a mocked parent-to-child stream verified durable lifecycle events and isolated child tools; Python compilation, 77 focused tests, all 40 project-discovered tests, and frontend production build passed. | `backend/scripts/pockpock_server.py`, `backend/projects/run_store/test_delegation_scheduler.py`, `frontend/app/src/App.tsx`, `frontend/app/src/App.css`, `docs/features/delegated-agent-runs.md`, `docs/TASKS.md` |
| 2026-11-12 | MAG-05A | Primary agent | Added bounded synthesis context with stable child-run attribution and explicit conflict/incomplete-result instructions; incomplete required children cannot yield a successful parent run. Python compilation and frontend build passed; 78 focused tests and all 40 project-discovered tests passed. | `backend/scripts/pockpock_server.py`, `backend/projects/run_store/test_delegation_scheduler.py`, `docs/features/delegated-agent-runs.md`, `docs/ARCHITECTURE.md`, `docs/TASKS.md` |
| 2026-11-12 | MAG-05B1 | Primary agent | Child workspace changes now produce bounded, child-attributed parent diff proposals without writing to the parent; existing, duplicate, stale, and unsafe targets conflict safely. Python compilation and focused gateway/workspace checks passed. | `backend/scripts/pockpock_server.py`, `backend/projects/agent_tools/workspace.py`, `backend/projects/agent_tools/__init__.py`, `backend/projects/agent_tools/test_workspace.py`, `backend/projects/run_store/test_delegation_scheduler.py`, `docs/TASKS.md` |
| 2026-11-12 | MAG-05B2 | Primary agent | Added exact-proposal approval, hash-checked application, baseline-relative validation, safe rollback on new validation issues, and parent artifact reporting. Python compilation, 40 focused tests, all 43 project tests, and frontend production build passed. | `backend/scripts/pockpock_server.py`, `backend/projects/agent_tools/workspace.py`, `backend/projects/agent_tools/__init__.py`, `backend/projects/agent_tools/test_workspace.py`, `backend/projects/run_store/test_delegation_scheduler.py`, `docs/features/delegated-agent-runs.md`, `backend/projects/run_store/README.md`, `docs/TASKS.md` |
| 2026-11-11 | BRW-03 | Primary agent | Connected `browse_public_page` to Agent Chat, persisted page activity and screenshot events, and added replayable inline evidence preview; Python compilation, tool registration/direct invocation, local artifact route, and frontend build passed. | `backend/projects/agent_tools/browser.py`, `backend/projects/agent_tools/contracts.py`, `backend/projects/agent_tools/registry.py`, `backend/scripts/pockpock_server.py`, `frontend/app/src/App.tsx`, `frontend/app/src/App.css`, `backend/projects/agent_tools/README.md`, `docs/features/browser-runtime.md`, `README.md`, `docs/TASKS.md` |
| 2026-11-11 | BRW-04 | Primary agent | Added state-bound browser actions using accessible targets, observation rotation, strict host/method limits, and Full Access gating for typed/selected values; Python compilation/build and manual interactions for click/type/select/scroll/navigate, stale-ID rejection, Auto-review denial, and cleanup passed. | `backend/projects/browser_automation/app.py`, `backend/projects/agent_tools/browser.py`, `backend/projects/agent_tools/common.py`, `backend/projects/agent_tools/contracts.py`, `backend/projects/agent_tools/registry.py`, `backend/scripts/pockpock_server.py`, `frontend/app/src/App.tsx`, `backend/projects/browser_automation/README.md`, `backend/projects/agent_tools/README.md`, `docs/features/browser-runtime.md`, `docs/ROADMAP.md`, `README.md`, `docs/TASKS.md` |
| 2026-11-11 | BRW-05 | Primary agent | Added payload-bound per-action approval in Default/Auto-review, high-impact link approval in Full Access, redacted approval cards, and rejection/expiry/cancellation stops. Python compilation and frontend build passed; gateway/run-store/browser health passed; local approval API checks verified approve, reject, and changed-hash rejection. | `backend/scripts/pockpock_server.py`, `backend/projects/agent_tools/browser.py`, `frontend/app/src/App.tsx`, `backend/projects/browser_automation/README.md`, `backend/projects/agent_tools/README.md`, `docs/features/browser-runtime.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, `README.md`, `docs/TASKS.md` |
| 2026-11-11 | BRW-06A | Primary agent | Added versioned local recipe storage and validated authenticated CRUD; Python compilation passed, browser service restarted, and manual API checks verified create/read/version/update/disable/delete and local-host rejection. | `backend/projects/browser_automation/app.py`, `backend/projects/browser_automation/recipes.py`, `backend/projects/browser_automation/README.md`, `docs/features/browser-runtime.md`, `docs/ARCHITECTURE.md`, `docs/TASKS.md` |
| 2026-11-11 | BRW-06B | Primary agent | Added the Browser recipes page and local gateway proxy; build passed; browser manual flow verified recipe creation, editing/version history, disable/delete, typed inputs, stop conditions, empty-state refresh, and persistence across browser-service restart. | `frontend/app/src/BrowserRecipes.tsx`, `frontend/app/src/App.tsx`, `frontend/app/src/App.css`, `backend/scripts/pockpock_server.py`, `README.md`, `docs/features/browser-runtime.md`, `docs/ARCHITECTURE.md`, `docs/TASKS.md` |
| 2026-11-11 | BRW-06C1 | Primary agent | Added internal deterministic recipe execution with transient input validation, current-version checks, per-step stop conditions, and guaranteed context cleanup; Python compilation passed; manual public-page run, checkpoint mismatch, disabled-recipe rejection, and zero-context cleanup checks passed. | `backend/projects/browser_automation/app.py`, `backend/projects/browser_automation/README.md`, `docs/features/browser-runtime.md`, `docs/ARCHITECTURE.md`, `docs/TASKS.md` |
| 2026-11-12 | BRW-06C2A | Primary agent | Added validated durable recipe-run event types and recursive input/secret rejection; Python compilation and direct positive/negative event-contract checks passed. | `backend/scripts/agent_run_store.py`, `docs/features/browser-runtime.md`, `docs/TASKS.md` |
| 2026-11-12 | BRW-06C2B | Primary agent | Added gateway recipe execution with fresh per-step durable approvals bound to version, step, target, observation, and keyed transient-input fingerprint; manual success, rejection, cancellation, and replay checks passed. | `backend/scripts/pockpock_server.py`, `frontend/app/src/App.tsx`, `backend/projects/browser_automation/README.md`, `docs/features/browser-runtime.md`, `docs/TASKS.md` |
| 2026-11-12 | BRW-06C2C | Primary agent | Persisted screenshots under task artifacts and durable checkpoint/terminal events; manual replay confirmed screenshot retrieval after Chromium cleanup, checkpoint failure status, cancellation, and zero active contexts. | `backend/scripts/pockpock_server.py`, `docs/features/browser-runtime.md`, `docs/TASKS.md` |
| 2026-11-12 | BRW-06C3 | Primary agent | Added explicit recipe run inputs/launch, live approvals and step results, screenshot previews, conversation transcript events, and reload replay; TypeScript build and browser UI launch/approve/checkpoint/reload flow passed. | `frontend/app/src/BrowserRecipes.tsx`, `frontend/app/src/App.tsx`, `frontend/app/src/App.css`, `backend/scripts/pockpock_server.py`, `backend/projects/browser_automation/README.md`, `docs/features/browser-runtime.md`, `docs/ARCHITECTURE.md`, `docs/TASKS.md` |
| 2026-11-12 | RES-01 | Primary agent | Added versioned provider-neutral source, evidence, response, and error records with canonical URL identity and cross-provider deduplication; Python compilation and direct contract checks passed. | `backend/projects/agent_tools/research_contracts.py`, `backend/projects/agent_tools/__init__.py`, `docs/features/research-provider-contracts.md`, `docs/FEATURES.md`, `docs/ARCHITECTURE.md`, `backend/projects/agent_tools/README.md`, `docs/TASKS.md` |
| 2026-11-12 | RES-02 | Primary agent | Added a persistent research provider opt-in, local settings page with network disclosure, and a gateway gate that prevents research fetch calls while disabled; Python compilation, frontend build, and direct API persistence/gate checks passed. | `backend/scripts/pockpock_server.py`, `frontend/app/src/ResearchSettings.tsx`, `frontend/app/src/App.tsx`, `frontend/app/src/App.css`, `docs/features/research-provider-contracts.md`, `docs/features/agent-tools.md`, `docs/FEATURES.md`, `docs/ARCHITECTURE.md`, `README.md`, `backend/projects/agent_tools/README.md`, `docs/TASKS.md` |
| 2026-11-12 | RES-03 | Primary agent | Connected bounded named-host crawling to typed, deduplicated source records and excerpts; retained legacy page output; Python compilation, frontend build, and direct mocked fetch/source/evidence smoke checks passed. | `backend/projects/agent_tools/research.py`, `backend/projects/agent_tools/contracts.py`, `docs/features/research-provider-contracts.md`, `docs/features/agent-tools.md`, `docs/ARCHITECTURE.md`, `README.md`, `backend/projects/agent_tools/README.md`, `docs/TASKS.md` |
| 2026-11-13 | AUT-01 | Primary agent | Finalized local-automation v1 platform, ownership, side-effect/permission, privacy, resource, and failure contracts; documented Windows 11 x64 scope, paired Chrome extension/native messaging, named command profiles, and schedule behavior. Documentation review passed; no runtime behavior changed. | `docs/features/local-agent-automation.md`, `docs/TASKS.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md` |
| 2026-11-13 | AUT-06A | Primary agent | Added the Playwright browser-engine lifecycle adapter while preserving default runtime behavior; 5 adapter tests and 29 tool/contract/event regressions passed, Python compilation passed, and public navigation/screenshot/context-cleanup smoke check passed. | `backend/projects/browser_automation/app.py`, `backend/projects/browser_automation/engines.py`, `backend/projects/browser_automation/test_engines.py`, `backend/projects/browser_automation/README.md`, `docs/features/browser-runtime.md`, `docs/ARCHITECTURE.md`, `docs/TASKS.md` |
| 2026-11-13 | AUT-06B | Primary agent | Integrated Lightpanda 1.0.4 over loopback CDP; enforced a one-context ceiling and loopback endpoint validation, retained PNG evidence, and verified the host/method, action, private-network, isolation, and cleanup matrix against WSL2. Added 20 deterministic browser automation scenarios; the 30 focused browser tests, 49 project-discovered regressions, and Python compilation passed. | `backend/projects/browser_automation/engines.py`, `backend/projects/browser_automation/app.py`, `backend/projects/browser_automation/test_engines.py`, `backend/projects/browser_automation/test_scenarios.py`, `backend/projects/agent_tools/browser.py`, `backend/projects/agent_tools/test_browser.py`, `backend/scripts/pockpock_server.py`, `backend/projects/browser_automation/README.md`, `docs/features/browser-runtime.md`, `docs/features/local-agent-automation.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/TASKS.md` |
