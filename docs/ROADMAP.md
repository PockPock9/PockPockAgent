# PockPock AI agent capability roadmap

This roadmap prioritizes the four requested capability areas in this order: **3. computer and browser automation**, **2. internet research and information gathering**, **1. planning, reasoning, and decision-making**, and **19. multi-agent systems**. The order describes product priority; each stage still depends on shared reliability, permission, and observability foundations. Every capability below is planned unless explicitly labeled current.

The small implementation tasks, dependencies, statuses, agent pickup rules, and completion log are tracked in [TASKS.md](TASKS.md). Agents should use that queue to select work and update status in the same change as implementation.

## Current baseline

The agent can create and edit bounded project files in a task workspace, inspect user-attached text, create supported documents and images, validate project changes, fetch text from named public sites, and browse explicitly named public pages in an isolated Chromium context. Multi-page text fetching is limited to five same-host pages. Browser activity and screenshots appear in the replayable chat timeline. Basic browser actions use accessible targets and the current observation ID; Default and Auto-review pause for approval on each action except fixed scrolling, and high-impact-looking links always pause even in Full Access. Research supports configured source discovery and evidence-backed reports; structured plans can be approved, versioned, and revised from task outcomes; and the coordinator can execute bounded, isolated subtasks and synthesize their results. Durable worker-queue extraction remains outstanding. Signed-in Chrome connection, native desktop control, agent-invokable command-profile execution, and recurring schedules are not implemented. See [Agent runs](features/agent-runs.md), [Workspace validation](features/workspace-validation.md), [the browser runtime](features/browser-runtime.md), [Local workflow services](features/local-workflow-services.md), and the [planned local interaction and automation expansion](features/local-agent-automation.md).

## Delivery principles

- Deliver a useful end-to-end vertical slice before splitting additional processes. New components belong under `backend/projects/` only when they have a stable service contract and distinct operational ownership.
- Keep the local-first runtime. No cloud model, search service, or browser profile is used without an explicit provider/configuration and user-visible disclosure.
- Use scoped capabilities with structured inputs and outputs. Do not add an unrestricted shell or unrestricted desktop-control tool as a shortcut.
- Show the task plan, current activity, tool inputs/results, approvals, created files, and validation in the existing conversation timeline.
- Record plan versions, decisions, tool events, approvals, citations, and outcomes in the durable run history. Do not put prompt or private page content in prompt-free telemetry.
- Each milestone must update its feature documentation and architecture before it is considered shipped.
- Keep agent-invokable capabilities in the dedicated [`backend/projects/agent_tools/`](../backend/projects/agent_tools/) project, including schemas, permission metadata, implementations, and focused tests. Split mature capabilities into subpackages as they grow.

The small implementation queue and completion state live in [TASKS.md](TASKS.md). Tool-project setup and modular registry work have their own TOL task IDs; browser/research tools remain sequenced in their priority sections below.

## Agent tool platform (cross-cutting)

Agent tools are a continuing product capability, not just implementation plumbing. The dedicated [`backend/projects/agent_tools/`](../backend/projects/agent_tools/) package owns each tool's schemas, permission and side-effect metadata, implementation, and focused tests. **TOL-01 and TOL-02 are complete:** the tool catalog and tests live there, split into capability modules behind a typed registry. Every new browser, research, planning-support, or delegation capability must have a tracked task, a bounded contract, visible run events, documented permissions/failure behavior, and successful focused checks before its tracker item is marked Done.

## Priority sequence

| Priority | Capability | Target outcome | Prerequisite |
| ---: | --- | --- | --- |
| 1 | **3. Computer and browser automation** | Safely navigate pages and perform user-approved browser tasks with visible evidence | Run cancellation, browser session isolation, permission and approval records |
| 2 | **2. Internet research and information gathering** | Discover sources, compare evidence, and produce cited research artifacts | Search provider boundary, source/citation schema, bounded network policy |
| 3 | **1. Planning, reasoning, and decision-making** | Maintain an inspectable plan, adapt to results, and choose tools/models based on capability and evidence | Structured task state and reliable tool outcome reporting |
| 4 | **19. Multi-agent systems** | Delegate independent subtasks to specialized agents and merge verified results | Stable task contracts, concurrency limits, cancellation, shared event/artifact ownership |

The shared reliability work below is scheduled before browser automation's first interactive milestone because browser actions require resumability and approval handling. It is enabling work, not a reordering of the four product priorities.

## Milestone 0 — Agent run foundation

**Purpose:** make long-running work reliable and auditable before adding actions that change external browser state.

### Scope

- Add run cancellation and timeouts that stop model calls and active tools.
- Persist task status, plan revisions, approval requests/decisions, tool start/finish, and artifact references with stable IDs.
- Add bounded retry policy, run timeouts, concurrency limits, and explicit behavior when a service is unavailable.
- Add a typed tool registry with capability tags, permission level, side-effect category, input schema, timeout, and output schema.
- Keep event replay compatible with existing conversations and display failures as recoverable timeline entries.

### Acceptance criteria

- Reloading or reconnecting reconstructs the same plan, approval state, tool outcome, and artifacts for an active or completed run.
- Cancellation reaches the active operation and marks the run cancelled/interrupted without falsely reporting success.
- Every dispatched tool call is authorized against the task's selected permission and has a bounded timeout/output size.
- Operational concurrency limits are visible in configuration and have deterministic failure messages.
- Existing run history and workspace recovery continue to work.

## Priority 1 — 3. Computer and browser automation

### 3.1 Read-only browser research session

Create an isolated browser adapter that can open public pages, follow links, read visible page content, capture screenshots, and return structured observations. Keep it separate from the user's ordinary browser profile; do not inherit saved cookies or credentials by default.

**Acceptance criteria:**

- User can request a browser-based task and see the active page, navigation, screenshot/evidence, and extracted content in the chat timeline.
- The tool only navigates to public HTTP/HTTPS pages under operational request, time, and page limits; private networks, local addresses, downloads, and unsafe schemes remain blocked.
- Every result includes the final URL, page title, timestamp, and an evidence reference; repeated navigation is deduplicated.
- Closing or cancelling a run closes its isolated browser context and releases all processes.
- If browser automation is unavailable, the agent explains that and offers the existing named-host research tool instead of claiming success.

### 3.2 User-approved page interaction

Add structured actions for click, type, select, scroll, and navigation using accessible element names/roles and current-page evidence. BRW-04 implements state-bound basic actions. BRW-05 now adds payload-bound approval for actions that can change page state.

**Acceptance criteria:**

- Each action is bound to the currently observed page and is rejected if navigation or page state invalidates its target.
- The transcript records the intended action, target description, approval decision, result, and a fresh post-action observation.
- Default and Auto-review require approval for each action except fixed scrolling. Full Access skips ordinary approvals, while accessible link names that suggest sending, submitting, purchasing, deleting, publishing, transfers, payments, or settings changes always require explicit per-action approval. Buttons and form submission remain unsupported.
- Credentials, cookies, local storage, and hidden form values are not read or persisted unless a future credential feature receives a separate design and explicit user consent.
- The browser cannot access local files, localhost/private network services, browser settings, or arbitrary operating-system controls.

### 3.3 Repeatable browser workflows

Let users save a reviewed workflow as a human-readable recipe with named inputs, allowed domains, expected checkpoints, and stop conditions. Execute each run afresh with visible progress; do not silently replay consequential actions.

**Acceptance criteria:**

- A recipe has a version, owner, domain allowlist, required input schema, and action-level approval policy.
- Each execution pauses at a failed checkpoint or unexpected page; it never guesses through a changed flow.
- Users can inspect and edit a recipe before running; disable/delete stops future runs.
- Evidence and a concise completion report are attached to that run's history.

## Priority 2 — 2. Internet research and information gathering

### 2.1 Search provider and source discovery

Add a provider interface for web search and page retrieval. Start with an explicitly configured provider (local metasearch or a user-selected API); keep the current named-host fetcher as a no-provider fallback. Search results are untrusted input and do not override system, user, workspace, or permission instructions.

**Acceptance criteria:**

- The user can choose/configure the provider and see whether a request leaves the PC; no provider key is stored in task prompts, events, or telemetry.
- Each result includes title, canonical URL, snippet, provider, and retrieval time.
- Search and fetch requests have domain/IP checks, timeouts, response-size/page limits, and redirect checks.
- The browser timeline shows search terms and source links; private/local addresses and disallowed schemes cannot be fetched.

### 2.2 Evidence-based research workflow

Add a research tool that searches, fetches, extracts, and compares sources, with optional user-provided documents. The agent must distinguish source statements from its own synthesis and identify conflicting or weak evidence.

**Acceptance criteria:**

- Factual claims in a generated research answer link to one or more retrieved source passages.
- A citation includes source URL/title, retrieval time, and the passage or bounded excerpt supporting the claim.
- The output identifies missing evidence, publication dates, and conflicts; it does not invent citations.
- The user can open the source from chat and export a cited Markdown/HTML/Word report.
- Prompt-injection text in retrieved pages is treated as data and cannot authorize tools or change user intent.

### 2.3 Research collections and refresh

Allow a user to save selected sources to a task-scoped research collection and refresh them on demand. No background monitoring or recurring retrieval runs without explicit user setup.

**Acceptance criteria:**

- Each explicitly saved source records its URL, extracted text/hash, capture time, and user-supplied notes; each version is capped at 200 KB.
- Refresh runs only on user request, shows changes, and retains every version until the collection is deleted.
- Delete removes collection records and associated extracted text under the documented retention policy.
- Research collections are workspace-scoped and are never shared with another task or agent implicitly.

## Priority 3 — 1. Planning, reasoning, and decision-making

### 1.1 Structured task brief and inspectable plan

Expand the current one-shot planner response into a validated task brief: desired outcome, constraints, assumptions, milestones, required capabilities, permission level, and measurable completion checks. Preserve the original user wording alongside the plan. The first contract version and current plan-timeline display are tracked in [Structured agent task briefs](features/task-briefs.md); plan editing, approval, and history remain separate tasks.

**Acceptance criteria:**

- The plan is concise, editable/approvable in chat, and includes success checks and expected deliverables.
- Missing critical information is surfaced as a focused question; reasonable reversible defaults are recorded as assumptions.
- Model and tool choices include capability-based reasons and a fallback if the selected model/tool is unavailable.
- An approved plan version is persisted before execution; later changes create a new visible version.

### 1.2 Evidence-driven replanning

Introduce explicit task state and a bounded control loop: inspect outcomes, compare them to completion checks, revise remaining steps, and continue or stop. Preserve decisions and rationale as short user-facing summaries rather than hidden internal reasoning traces.

**Acceptance criteria:**

- Replanning is triggered by failed checks, unavailable tools, new evidence, or changed user constraints—not repeated open-ended model loops.
- Every plan revision identifies the trigger, completed steps, and changed steps.
- Operational step, retry, and time limits are enforced per run.
- The agent asks before expanding scope, changing permissions, or taking external side effects.
- Completion is tied to explicit checks/artifacts and reports any incomplete criteria.

### 1.3 Model/tool selection and evaluation

Route each step to the best enabled local model/tool combination using task type, tool-call support, available context, latency, and prior measured outcomes. Keep the user-selected model preference authoritative when compatible.

**Acceptance criteria:**

- Selection reasons and fallback behavior are visible in the run timeline.
- Per-task evaluation metrics exclude prompt and response text unless separately opted into a local evaluation dataset.
- A model with no required tool capability is not selected for that step.
- Routing can be tested against a fixed, privacy-safe task suite and regressions are reported before release.

## Priority 4 — 19. Multi-agent systems: agents working together

Multi-agent work starts after tool contracts, plan state, approvals, and cancellation are reliable. Multiple agents should solve independent bounded subtasks, not create an unobservable swarm.

### 19.1 Delegation protocol and coordinator

Add one coordinator that decomposes approved plans into typed subtasks. Each subtask has an owner/role, isolated context, allowed tools, workspace/artifact boundary, deadline, dependency list, and expected result schema.

**Acceptance criteria:**

- The user sees each delegate's purpose, model, scope, status, and output in the parent run timeline.
- Delegates cannot change the parent permission level, read unrelated conversations, or access another delegate's private context.
- Subtasks can run in parallel only when declared independent; shared-file edits are serialized or merged as reviewable patches.
- Parent cancellation and operational deadlines propagate to every child run.
- Delegation is bounded by a configurable maximum agent count, depth, and duration.

### 19.2 Result synthesis and conflict resolution

Collect typed results and evidence; have the coordinator compare them against the approved plan and request a bounded follow-up only when a result is incomplete or inconsistent.

**Acceptance criteria:**

- Every synthesized claim or artifact can be traced to a child result or direct verification step.
- Conflicting results are shown with evidence and uncertainty; the coordinator does not hide disagreement.
- File changes from delegates are diffed, validated, and applied through the same workspace permission boundary as single-agent changes.
- Parent completion requires all required subtasks and validation checks to pass, or a clear partial status with remaining work.

### 19.3 Worker service extraction and scale

After the delegation protocol is proven locally, move task execution behind a durable worker queue with leases, idempotency, retries, cancellation, and process health. Keep planning/research and browser services independently scalable only when workload measurements justify it.

**Acceptance criteria:**

- Restarting a worker does not lose queued/running task state; leases recover stale work without duplicate side effects.
- Backpressure prevents unbounded queue growth and exposes queue wait/active counts.
- Run events retain stable ordering and parent/child relationships through restart and replay.
- Deployment, data retention, per-user isolation, and secrets are documented before allowing multi-user or remote execution.

## Post-priority expansion — Local interaction and automation

This is a planned expansion after the current capability roadmap, not a change to the four priorities above. The capability inventory, proposed boundaries, and task sequence are documented in [Local agent interaction and automation](features/local-agent-automation.md); implementation tasks AUT-01–AUT-06 are tracked in [TASKS.md](TASKS.md).

- Add an explicitly paired, selected-tab Chrome integration for signed-in user sessions without exposing profile credentials or cookies.
- Keep Playwright/Chromium as the isolated-browser default; the optional Lightpanda adapter remains limited to its verified CDP operations and one active context.
- Add user-visible, permission-gated native desktop observation and typed actions; this is separate from website automation.
- Extend scoped workspace operations with named, bounded command profiles, not arbitrary model-supplied shell commands.
- Add user-created recurring workflow schedules only after durable worker lifecycle, with explicit pause/disable, bounded retry/concurrency, and approvals that can pause for the user.
- Preserve isolated Chromium for public browsing. Do not silently substitute real-profile access for the existing isolated runtime.

## Supporting agent platform tools

These planned capabilities support the interaction tools and recurring workflows. Their boundaries and sequence are documented in [Agent platform supporting tools](features/agent-platform-expansion.md); MAG-06 and CAP-01–EVA-01 are tracked in [TASKS.md](TASKS.md).

- Complete MAG-06's durable worker queue before enabling recurring or unattended runs.
- Add minimal-content notifications for approval-required, completed, failed, and attention-required runs; notifications never approve an action.
- Add a typed, provider-specific connector framework with OS-protected credential storage and narrow scopes; do not expose generic arbitrary HTTP/API access.
- Extend explicit text attachment support to bounded PDF/Office/spreadsheet extraction and optional local OCR.
- Consolidate synthetic tool, permission, failure, cancellation, and replay checks into a privacy-safe evaluation suite; replay never re-executes side effects.

## Cross-cutting release gates

Every milestone must include:

1. Updated feature page, README behavior/setup summary where relevant, and architecture ownership/flow update.
2. Permission matrix, input/output limits, cancellation and failure behavior, and user-visible activity events.
3. Narrow validation for code changes plus contract and end-to-end checks for newly introduced side effects.
4. A demo task with expected steps, artifacts/evidence, approval points, and a known failure path.
5. A rollback/configuration path that leaves existing local chat and agent runs readable.

## Not scheduled in these priorities

General arbitrary shell access, hidden desktop control, unattended purchases or account changes, credential scraping, unconfigured/unbounded background activity, and unbounded multi-agent spawning are out of scope. Any future proposal needs a separate permission, abuse, audit, and recovery design.
