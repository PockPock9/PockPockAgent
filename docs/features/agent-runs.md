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
- Planner and critic calls request JSON with thinking off (`think: false`). Each call may take 120 s, or 300 s for models of 20B parameters or more (`planning_timeout`), because on a 12 GB GPU a 27B model runs partly on the CPU at about 4–5 tokens/s. The gateway waits up to 660 s for the planner.
- `backend/projects/planner/critic.py` performs a bounded model-based plan review and may trigger one plan revision; it does not execute tools or grant permissions.
- `%USERPROFILE%\PockPock AI Tasks\<run-id>\task-memory.md` stores the user-readable journal. When a user-selected folder is the working directory, the task output/journal remains in the task output folder while source changes stay in the selected workspace.

Research reports requested as Markdown, HTML, Word, Excel, or PowerPoint are rendered from the gateway-validated research answer and its source records. The generated artifact is sent through the ordinary `artifact` event and therefore appears in the replayable activity timeline and task-output download list.

Research source events carry an opaque workspace key so saved collection access remains scoped to both the task and its workspace after run history is replayed. A user can explicitly save an individual source, add notes, and refresh it on demand; the run store retains up to 200 KB of extracted text per changed snapshot and all versions until collection deletion. Refresh results and version history are displayed in the research timeline. The gateway does not automatically fetch or refresh saved sources.

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
- Invalid or missing run IDs return 404 for replay/open routes.
- The Stop control posts to the local cancel endpoint. The gateway persists the request, signals the live run, and cancels its active model/tool await. The user sees a `cancelled` terminal event and the run remains cancelled after reload.
- In Auto-review mode, proposed workspace file changes are staged and held behind a durable approval tied to the run, approval ID, and SHA-256 hash of the exact action summary and diff. The chat shows the diff with Approve and Reject controls; only the matching active pending action can be resolved. Full Access allows the staged workspace change to apply without a second prompt. Pending approval expires after five minutes; rejection, expiry, cancellation, or restart does not apply the staged patch. Approval requests and outcomes replay from the run event history.
- Runs have a 15-minute total deadline. The deadline follows the same durable cancellation path and ends as `timed_out`. Registered per-tool timeouts remain independently enforced.
- A dropped browser connection without an explicit cancellation is marked `interrupted` and receives a terminal event when the server finalizes the run.
- Once cancellation is requested or a run reaches any terminal state, late nonterminal events are discarded so they cannot change the final status.
- If an old task's persisted path is absent, the API checks the conventional task-output directory. If neither location exists, opening reports that the workspace is unavailable.
- A missing or deleted `task-memory.md` does not erase the SQLite event history.

## Verification and maintenance

- Keep event ordering, status mapping, and replay pagination compatible when changing the run-store schema.
- Update [ARCHITECTURE.md](../ARCHITECTURE.md) if persistence, ownership, replay, or deployment boundaries change.
- Update [README.md](../../README.md) and the [desktop app page](desktop-app.md) when user-visible flow or setup changes.
- Run the relevant Python syntax checks and agent validation after code changes; cover run creation, event status transitions, cancellation, cancellation replay, late-event rejection, replay pagination, duplicate IDs, and old-path fallback when adding or changing persistence behavior.
