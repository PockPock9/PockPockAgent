# Agent runs, task memory, and workspace recovery

## Purpose

Agent Chat executes supported tasks in a local workspace and presents progress, tool calls, changes, and deliverables in the conversation. Each run has a durable identifier and event history so the transcript can be reconstructed after reload. Each task also receives a Markdown journal that makes its request and result easy to inspect outside the chat.

Run records may also express a parent/child delegation relationship. Child metadata contains the parent run ID, role, completed sibling dependencies, context labels, workspace/artifact scopes, and a timezone-aware deadline. The run store limits each parent to 16 direct children and delegation to three levels. Typed `delegate_result` events are replayed in the child run's ordered history. This milestone defines and persists the contract; the coordinator and isolation enforcement are separate future work.

## User flow

1. In PockPock Agent, the user chooses the **PockPock Agent** mode, asks for a supported task, and selects a permission mode.
2. The user may work in the open folder (permission picker → **Work in <folder>**). Otherwise the API creates a dedicated task directory beneath `%USERPROFILE%\PockPock AI Tasks\<run-id>`.
3. The planner prepares a structured task brief, execution plan, and model choice. A critic reviews scope, tool capability, step ordering, and success checks, and can request one bounded revision. The UI shows the review summary/findings alongside the resulting plan. The user can inspect and edit the plan and success checks, then approve or decline before any agent tool runs. The gateway checks a short-lived, one-use approval ticket against the exact run request and critic review.
4. The desktop app renders run events as they are produced (steps, approvals, research sources, changed files, produced files) and saves them with the chat. The gateway also keeps the full event history, readable through `GET /api/runs/{run_id}/events`.
5. Completion provides the task workspace and created files, with an action to open the workspace in the local file manager.

## Components and data flow

- `desktop/src/lib/engines.ts` runs the plan → approve → run sequence and maps run events to the message; `desktop/src/components/MessageView.tsx` renders the plan card, approvals and results.
- `backend/scripts/pockpock_server.py` owns HTTP/SSE endpoints and local-request policy. `backend/projects/agent_core/executor.py` owns approved-run execution and coordination; `AgentCoreServices` makes the gateway's current run state and adapters explicit at the boundary.
- `backend/scripts/agent_run_store.py` is the gateway-side repository client and task journal projection. `backend/projects/run_store/app.py` owns the HTTP service boundary and durable SQLite operations.
- `backend/projects/agent_tools/` owns the agent tool catalog, workspace-scoped file operations, and research/artifact tools.
- Model choice (`backend/projects/planner/routing.py`): the model picked in the app is kept if it supports tools and has enough context; otherwise the configured fallback; otherwise the fastest measured tool-capable model of at least 3B parameters (`MIN_AGENT_BILLIONS`). Smaller models, such as the Smart Router's 1.5B classifier, are used only when nothing larger is enabled. The gateway supplies `parameter_billions` from Ollama's `/api/show`.
- The plan call sends a JSON schema (`PLAN_SCHEMA` in `planner/app.py`: `plan` as a list of strings, `execution_prompt`, `reason`, `task_brief`, optional `delegation_plan`) as Ollama's `format`, so a local model's output is constrained to that shape while it is generated; cloud planner models keep plain JSON mode. A reply that is still unusable (not JSON, or no steps) is retried once with the problem stated; a timeout or model error is not retried.
- Planner and critic calls request JSON with thinking off (`think: false`) and stream the reply, so a slow model that keeps writing is not cut off. A call stops after 240 s with no new text (`POCKPOCK_PLANNER_IDLE_SECONDS`) or 600 s in total, 900 s for models of 20B parameters or more (`POCKPOCK_PLANNER_TIMEOUT_SECONDS`), because on a 12 GB GPU a 27B model runs partly on the CPU at about 4–5 tokens/s. The gateway waits up to 1,860 s for the planner.
- **Plan pre-check** (`backend/projects/agent_core/precheck.py`): after the planner answers, the gateway adds `precheck` to the plan reply, a fixed check with no model call. **Files**: file names in the request (not attachments or deliverables) are looked for in the open folder, by relative path or by name below it (5,000 entries at most); no folder open is a warning. **Tools**: Default permission blocks the folder tools (`workspace_read`, `workspace_write`, `project_validation`), and a plan that needs `public_research` while research is switched off is a warning. **Questions**: open clarifying questions. Each result is `{id, status: pass | warn, label, detail}`; a warning never blocks approval.
- **Answer choices**: the planner is asked to give each clarifying question as `{question, options}`; the brief keeps `clarifying_questions` as text and adds `question_options` (up to 3 choices of 80 characters per question, in the same order). The plan card shows them as buttons, Yes/No for a yes/no question without choices, and a text box. Answering declines the current plan ticket and plans again with the request plus "Answers to the planner's questions"; the new plan is reviewed and approved like the first, and the replaced plan stays visible, marked "Replaced after your answer".
- **Allow for this task**: `POST /api/runs/{run}/approvals/{id}` takes `scope: "once" | "task"`. With `task`, the run remembers a grant for the rest of this run only: `workspace_change` (any later workspace change in Auto-review) or `browser:<action>` (the same browser action type; never a high-impact click such as submit, buy or delete). Granted actions are not asked again and the stream sends `approval_auto`. Approval cards that support it carry `grantable: true`; helper-merge and browser-recipe approvals stay one at a time.
- **Plan-step progress**: a run of an approved plan with two or more steps also offers the model `report_plan_step` (`{step}`, 1 to the number of steps; `backend/projects/agent_tools/plan_progress.py`). The gateway answers it itself: no tool card, no permission, not counted as a tool call, and each plan step adds one turn to the run's turn budget. A valid call becomes a `plan_step` event (`{"type": "plan_step", "step": 3, "total": 5, "label": "<the step's text, 160 characters>"}`), sent once per change; an out-of-range or malformed step is answered with the valid range and no event. The instruction sits after the numbered plan in the task message. Delegates never get it. `POCKPOCK_PLAN_STEP_REPORTS=0` turns it off. Small local models do not always call it (with `qwen3.5:9b`, 3 of 4 live runs reported every step), so the app shows a step only when one was reported.
- **Notes while it works**: `POST /api/runs/{run}/notes` with `{text}` (2,000 characters) queues a note for an active run (404 when it is not running; at most 10 waiting, 429 after that). Before its next model call the executor adds each note to the conversation as the user's words, "within the approved plan and permissions", and the stream sends `note`. In the app the composer becomes a note box while an approved PockPock Agent run works.
- **Retry from step N** (desktop): a failed run's card offers its approved plan's steps; retrying from step N sends a new PockPock Agent task: the original request, steps 1 to N−1 named as done, and steps N onward to do. It is planned and approved like any task and runs in a new task folder; files from the failed attempt stay in its own folder.
- Thinking off on tool-call turns: those go to Ollama's OpenAI-compatible `/v1/chat/completions`, which ignores `think: false` (Ollama 0.40.15), so the model client also sends `reasoning_effort: "none"`. Before this, every Qwen 3.5 tool step thought first: a `qwen3.5:9b` tool call took 4.6 s and 250 tokens instead of 1.5 s and 83, and across the nine `docs/experiments/measure-tool-calls.py` tasks the mean time to the tool call fell from 1.50 s to 0.61 s (Qwen3.6: 2.80 s to 1.01 s). Qwen 3.5, 3.6 and later `qwen3.` models, and Qwen 3, are treated as thinking by default (`THINKING_MODEL_PREFIXES` in `model_router/client.py`).
- `backend/projects/planner/critic.py` performs a bounded model-based plan review and may trigger one plan revision; it does not execute tools or grant permissions.
- `%USERPROFILE%\PockPock AI Tasks\<run-id>\task-memory.md` stores the user-readable journal. When a user-selected folder is the working directory, the task output/journal remains in the task output folder while source changes stay in the selected workspace.

Research reports requested as Markdown, HTML, Word, Excel, or PowerPoint are rendered from the gateway-validated research answer and its source records. The generated artifact is sent through the ordinary `artifact` event and therefore appears in the replayable activity timeline and task-output download list.

Research source events carry an opaque workspace key so saved collection access remains scoped to both the task and its workspace after run history is replayed. A user can explicitly save an individual source, add notes, and refresh it on demand; the run store retains up to 200 KB of extracted text per changed snapshot and all versions until collection deletion. Refresh results and version history are displayed in the research timeline. The gateway fetches a saved source by itself only when the user chose to watch it (below).

### Watching saved sources

A saved source can be **watched** (UI-01E). While the gateway runs, it re-reads each watched page in the background and records a new snapshot when the text changed, exactly like a manual refresh. This is network access while PockPock runs, so:

- It is off by default and turned on per source: **Watch for changes** on a saved source in the task's sources card. **Stop watching** on the Research page (or the switch) turns it off.
- It only happens while research (**Allow reading public websites**) is on. When research is off, the gateway fetches nothing and the Research page says checks are paused.
- At most 50 sources are watched; each is checked once per interval, `POCKPOCK_SOURCE_WATCH_MINUTES` (default 360, 15 to 10,080). The loop (`backend/scripts/research_watch.py`) wakes every minute, 30 s after the gateway starts, and checks at most 3 due sources, one at a time. `POCKPOCK_SOURCE_WATCH=0` turns the background checks off; **Check now** still works.
- A failed check is recorded with its message and retried after a full interval, not sooner.
- The fetch is the same as **Check for changes**: the saved URL's host only, with the research tool's public-address, time and size limits.

State lives in `research_collection_sources` (columns added in place: `watched`, `watch_changed_at`, `watch_unseen`, `watch_error`, `watch_error_at`). A background change sets `watch_unseen` until the user marks it seen; turning watching off clears it and the last error. A first snapshot is never a change. A manual check clears the last error and marks the change seen, since the user sees its result.

| Route | Purpose |
|---|---|
| `PUT /api/agents/{task}/research-collection/sources/{source}/watch` `{watched}` | Turn watching on or off for a saved source (404 when not saved; 422 at the 50-source limit) |
| `GET /api/research/watch` | `research_enabled`, `background`, `interval_minutes`, and every watched source with `title`, `url`, `last_checked_at`, `next_check_at` and `watch` (`watched`, `changed_at`, `unseen`, `error`, `error_at`); no workspace key |
| `POST /api/research/watch/{task}/{source}/seen` | Mark the latest change seen |

Each saved source in `GET /api/agents/{task}/research-collection` also carries its `watch` state. The run-store service has the matching `PATCH /research-collections/{task}/sources/{source}/watch` and `GET /research-watch`; all routes accept local requests only.

The browser event stream is not the persistence source. The server parses each SSE event, attaches the run ID and sequence, writes it to `agent_run_events`, and then forwards it. A reconnect reads events after a sequence number. The completed event may include `workspace_path`; for older task runs without that field, the open-folder endpoint falls back to the default task-output path if the task directory still exists.

## Persistence contract

`agent_runs` stores:

- `run_id`: unique 32-character hexadecimal run identity.
- `conversation_id`: browser conversation that owns the run, if provided.
- `task_type`: current execution category (`agent`).
- `status`: `running`, `cancelling`, `completed`, `partial`, `awaiting_approval`, `failed`, `cancelled`, `timed_out`, or `interrupted` as lifecycle events update it.
- `cancel_requested_at` and `cancel_reason`: durable request time and `user`/`timeout` reason, added in place for existing databases.
- `parent_run_id`, `delegate_role`, `dependency_ids`, `context_scope`, `workspace_scope`, `artifact_scope`, and `deadline_at`: optional child-run contract metadata. Root runs retain null/empty defaults; existing databases receive the columns in place.
- `created_at`, `updated_at`, and a bounded display `title`.

`agent_run_events` stores ordered JSON event payloads keyed by `(run_id, sequence)`, plus event type and creation time. The API limits event page sizes. Run/event tables currently share the local SQLite file used by the telemetry sidecar, but remain logically separate; agent event data may contain work details and must not be copied into prompt-free telemetry.

An approved run begins with versioned `plan_version` events for the proposed and approved plan, followed by a `plan_decision` event. Each version carries its steps, success checks, short rationale, permission, model, and payload hash. This run event history is the durable plan record and binds the approved version to subsequent work. Rejected plans do not create an agent run; their decision remains in the browser conversation transcript.

New events are stamped with contract version 1. Events written before versioning remain readable as legacy version 0, with their original fields preserved. New run-level error events include a versioned error object with a stable code, message, and retryability while retaining the top-level message used by older clients. See [agent tool and run event contracts](agent-tool-contracts.md) for the compatibility policy.

`delegate_result` is a version 1 event with a typed terminal status, summary, evidence references, artifact IDs, and incomplete checks. Its parent ID must match the child's persisted parent relationship. Dependency references must point to completed sibling runs. Delegation metadata and result events share the existing run-history retention and local access boundary.

The run-store public functions are in `backend/scripts/agent_run_store.py`; with the normal launcher they call the local run-store service. HTTP status mapping and local request validation remain in the API layer.

The run store also owns task/workspace-scoped `research_collections`, `research_collection_sources`, and `research_collection_snapshots` tables. Collection snapshots use the same local-only service boundary as run history; deleting a collection removes its source metadata, notes, and extracted-text versions.

## Permission and safety boundaries

- Agent runs are accepted from the local browser only.
- The permission selected and approved with the plan is rechecked at tool dispatch. Workspace tools are denied in Default mode; Auto-review keeps workspace changes behind exact-diff approval, while Full Access applies within the task workspace.
- A user-selected workspace is validated as an existing directory. Without one, the server creates a new per-task workspace.
- Project tools resolve relative paths under that workspace and reject traversal, disallowed secrets, and symbolic links.
- Network tools are bounded separately to public hosts supplied explicitly in the task.
- Opening a completed workspace calls the local API, which opens the resolved folder in the OS file manager; it does not upload or publish its contents.
- Task memory contains the task request and activity needed for the user to understand the work. Telemetry continues to omit prompt and response text.

## Failure and recovery behavior

- Duplicate run IDs are rejected with HTTP 409.
- Invalid or missing run IDs return 404 for replay/open routes, the events route, research-collection routes and the run-store `finish` route. A reused approval ID returns 409, a delegation result posted to a run that is not delegated returns 422, and gateway errors keep the run-store's own message (for example "Approval not found").
- Starting agent runs is limited to 10 per minute for all local clients together (concurrent runs are limited separately); a 429 carries `Retry-After` and says how many seconds to wait.
- The Stop control posts to the local cancel endpoint. The gateway persists the request, signals the live run, and cancels its active model/tool await. The user sees a `cancelled` terminal event and the run remains cancelled after reload.
- In Auto-review mode, proposed workspace file changes are staged and held behind a durable approval tied to the run, approval ID, and SHA-256 hash of the exact action summary and diff. The chat shows the diff with Approve and Reject controls; only the matching active pending action can be resolved. Full Access allows the staged workspace change to apply without a second prompt. Pending approval expires after five minutes; rejection, expiry, cancellation, or restart does not apply the staged patch. Approval requests and outcomes replay from the run event history.
- Repeated tool calls (`agent_core/repeat_guard.py`): a tool called a third time with exactly the same arguments, with no write in between (`WRITE_SIDE_EFFECTS`: workspace, task-folder and local-artifact writes, and external interactions; since 0.2.14 running the project's checks no longer counts, so re-reading the same lines after each `validate_project` is refused), is not run; the model gets a tool result saying so and suggesting it use the earlier result, other arguments, another tool, or its final answer. After three such refusals the run stops with a `partial` error naming the tool ("Stopped: the agent kept repeating the same … call without making progress"). Each refusal is recorded as the `agent_tool_repeat_refused` telemetry event.
- Tool-call budget (since 0.2.14, `tool_call_budget` in `agent_core/executor.py`): 20 calls, plus 4 for every approved plan step beyond the third, at most 48 (a 6-step plan gets 32). A fixed 20 ended a 6-step website run on its last step (report 2026-11-26). Delegated runs keep their contract's `max_tool_calls`. The evidence retry after the final answer tells the agent to use the file contents and check results it already has and not to read an unchanged file again.
- Reading project files (since 0.2.14): `read_project_file` returns up to 600 lines and 20,000 characters per call (it was 160 lines and 12,000 characters, so a 455-line stylesheet took three reads). A file read in consecutive parts from line 1, with no change in between, counts as fully read (`read_coverage` in `ProjectAgentContext`), so it can be replaced with `propose_project_patch`; before, a file longer than one read could never be replaced.
- Robustness fixes from live end-to-end runs (since 0.2.15, 2026-11-27; one model plans and works, `qwen3.5:9b`, 1 of 4 tasks finished before, 4 of 4 after): a validator service that is not running returns a "not checked" result instead of an error, so two attempts no longer stop a finished run; a request that names a file in the open folder may read the folder (`names_folder_file`), and the attachment tool used on such a file reads it from the folder; plan steps and checks that wait for the user ("Wait for user input", "None pending user clarification") are dropped (`without_user_waits`), since the plan card asks the questions; the build review gives its game example only for a game and ignores game-only features and production steps ("Parse resume.txt content") reported as missing from other work; the planner's error says what the model provider answered.
- Runs have a 15-minute total deadline. The deadline follows the same durable cancellation path and ends as `timed_out`. Registered per-tool timeouts remain independently enforced.
- A dropped browser connection without an explicit cancellation is marked `interrupted` and receives a terminal event when the server finalizes the run. This also holds while a run waits for an approval: the stream's cleanup runs shielded from the server's disconnect cancellation, and the run-store wrapper always closes the run's own stream, so the run is finalized instead of staying `running`.
- Cancelling a run that no live stream is executing any more (for example its client went away) finalizes it at once, so it never stays `cancelling`.
- An approved plan is never edited in place, because its hash authorises the run. A second decision on it returns 409 saying the plan was already approved; create and approve a new plan from the edited request instead.
- Once cancellation is requested or a run reaches any terminal state, late nonterminal events are discarded so they cannot change the final status.
- If an old task's persisted path is absent, the API checks the conventional task-output directory. If neither location exists, opening reports that the workspace is unavailable.
- A missing or deleted `task-memory.md` does not erase the SQLite event history.

## Verification and maintenance

- Keep event ordering, status mapping, and replay pagination compatible when changing the run-store schema.
- Update [ARCHITECTURE.md](../ARCHITECTURE.md) if persistence, ownership, replay, or deployment boundaries change.
- Update [README.md](../../README.md) and the [desktop app page](desktop-app.md) when user-visible flow or setup changes.
- Run the relevant Python syntax checks and agent validation after code changes; cover run creation, event status transitions, cancellation, cancellation replay, late-event rejection, replay pagination, duplicate IDs, and old-path fallback when adding or changing persistence behavior.
