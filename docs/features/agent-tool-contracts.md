# Agent tool and run event contracts

## Tool registry

`backend/projects/agent_tools/contracts.py` owns the current tool contract version and validation. `backend/projects/agent_tools/registry.py` owns the model schemas and dispatch; capability code lives in `workspace.py`, `research.py`, and `artifacts.py`. `registered_tool_contracts()` binds every callable tool to its model input schema, result schema, capability, required permission, side-effect class, timeout, and serialized input/output size limits. The gateway only dispatches registered tools; unknown tools fail with `unknown_tool`. The package `__init__.py` re-exports the stable Python interface for existing callers.

Inputs are validated before a tool starts. Outputs are validated before they are sent back to the model or shown as a successful result. Each call is bounded by its registered timeout and byte limits. Workspace tools are denied in Default mode; Auto-review permits scoped workspace work but requires a durable approval before applying each patch, while Full Access can apply patches without a second prompt. The selected permission is bound to the approved plan and checked again at tool dispatch, so retrieved page text cannot elevate it. Other tools retain their existing task-scoped access. Contract failures use an error object with `contract_version`, stable `code`, user-readable `message`, and `retryable`.

When adding a tool, add its input schema and dispatch implementation, output schema, metadata, focused success/failure tests, and docs together. Do not make an unbounded or arbitrary shell/filesystem/network tool. Permission and side-effect classifications are descriptive enforcement metadata; the gateway must check them before execution.

## Run events and compatibility

New persisted agent run events carry `contract_version: 1`. Run-level errors carry a typed `error` envelope while keeping the legacy `message` field for existing UI consumers. The event store accepts unversioned events as version 1 on write, stamps them before persistence, and reads previously stored unversioned events as legacy version 0. Existing event payload fields are preserved during replay.

Readers support versions 0 and 1. A future unsupported event or error version is rejected with an actionable contract error rather than being interpreted as the current schema. Changes that cannot be read compatibly require an explicit migration or a new versioned reader before writers emit that version. Event data remains in the run store and must not be copied into prompt-free telemetry.

Cancellation, timeout, and interruption each produce a version 1 terminal event. The run store rejects late events after a cancellation request or terminal status so replay cannot turn a cancelled run into success.

Approval events carry stable run and approval IDs and a SHA-256 hash of the exact action payload. The run-store approval record binds that hash and serialized action to the active run; a decision for a different payload, expired approval, or inactive run is rejected. `approval_requested`, `approval_approved`, `approval_rejected`, and `approval_expired` events are replayable. Tool start/result events carry a stable per-call ID and the result status/error.

Plan history uses `plan_version` events with monotonically increasing version numbers, proposed/approved status, explicit plan steps and success checks, a short user-facing rationale, and a hash bound to the task brief, model, workspace, permission, and plan content. `plan_decision` identifies the approved version and hash. These events contain no hidden chain-of-thought and are stored with the run, not prompt-free telemetry.

## Verification

Run `.venv\Scripts\python.exe -m unittest projects.agent_tools.test_contracts projects.agent_tools.test_agent_tools projects.agent_tools.test_research projects.agent_tools.test_workspace projects.agent_tools.test_artifacts projects.run_store.test_event_contracts projects.run_store.test_agent_cancellation` and compile the gateway, registry, run store, and service modules. Existing runs should replay without a database migration.
