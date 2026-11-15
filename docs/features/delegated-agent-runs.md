# Delegated agent runs

Delegation lets an approved parent plan describe bounded subtasks and their dependencies. The gateway executes scheduled children locally with scoped context, allowlisted tools, bounded deadlines, durable cancellation, and typed results. Parent timeline replay and end-to-end lifecycle verification are complete; synthesis and conflict reporting are tracked by MAG-05A.

## Current flow and ownership

1. The planner returns a versioned `SubtaskPlan`; the gateway binds it to the one-use approval ticket and persists the approved plan in the parent run.
2. The run store validates child creation against the active parent and latest approved plan. Each child receives only its approved task instructions, explicit dependency results, allowlisted tools, isolated workspace scope, permission ceiling, and deadline.
3. `backend/projects/run_store/delegation_scheduler.py` starts only ready subtasks, enforces the configured concurrency limit, passes only declared dependency results, and cancels active callbacks when the parent cancellation event is set or an execution callback raises.
4. Child IDs are stable UUIDv5 values derived from the parent run ID and subtask ID. `create_or_load_delegate_run` returns the existing child record and event history when a retry repeats the same dispatch, rather than creating a second child run.
5. Before execution, the gateway atomically claims the durable child run. Duplicate dispatches and terminal children are rejected; the authenticated run-store route provides the same claim in remote-store mode.
6. Each child receives only its approved task and declared dependency results, runs with the approved tool allowlist and an isolated output workspace, and is bounded by both its subtask deadline and the parent run deadline.
7. Parent cancellation and child timeout stop active work and persist terminal child state. The parent records one versioned `DelegationResult` after child execution; non-completed statuses remain partial/failure outcomes and cannot be reported as success.
8. The parent timeline persists child status, purpose, selected model, execution scope, activity, and typed output. Reloaded events render the same lifecycle, and a retried dispatch shows an existing result instead of starting another child.
9. The coordinator receives bounded typed results keyed by subtask and exact child-run ID. Its synthesis instructions require source attribution, explicit disagreement reporting, and honest treatment of incomplete results; any failed or missing required child makes the parent run partial.
10. Child-created workspace files become bounded, child-attributed parent diff proposals; no parent file changes before approval. The parent approval is bound to the exact proposal, and application rechecks the target path and original hash.
11. The gateway compares project validation issues before and after the approved merge. Newly introduced issues fail validation and revert only files whose bytes still exactly match the applied child content; successful additions are persisted as parent patch and artifact events.

## Bounds and configuration

- Planner contracts accept at most 16 subtasks and require dependencies to refer to earlier nodes in topological order.
- `run_subtask_plan` reads `POCKPOCK_MAX_DELEGATE_CONCURRENCY` when no explicit limit is passed; the default is `3`, and supported values are `1` through `16`. Invalid values raise an explicit `ValueError`.
- The gateway consumes this configuration for the approved child plan.
- Run-store child creation enforces the parent permission ceiling, plan/tool/context scope, approved dependencies, active parent state, and existing child/depth limits. An atomic execution claim prevents a second gateway request from starting the same durable child.

## Persistence and retry behavior

Child identity is deterministic, while run status, delegation metadata, execution claims, and ordered events remain in the existing `agent_runs` and `agent_run_events` tables. A retry or reload queries that same run ID and reuses the saved status/events. It does not silently restart a child whose durable record already exists. Incomplete runs continue to use the run store's existing interrupted/cancellation lifecycle.

The scheduler does not add a queue, worker process, or additional database. MAG-06 owns any later queue extraction after local delegation is proven.

## Failure behavior and security

- Parent cancellation cancels active scheduler callbacks and prevents queued subtasks from starting.
- Callback exceptions are propagated after active siblings are cancelled; they are not converted into successful results.
- A typed partial/failed child result is data, not a scheduler exception, and can be passed only to dependent subtasks.
- Rejected, expired, changed, or stale child patches are not merged. Validation rollback leaves a file untouched if its contents changed after application.
- Context is limited by the MAG-03 contract. Arbitrary parent conversation context, sibling results, shared parent workspace writes, and unassigned artifacts are not provided.
- The gateway enforces each child's tool allowlist and deadline; an operational failure is recorded as a typed failed result rather than a successful fallback.

## Modules and verification

- `backend/projects/planner/contracts.py`: bounded, topologically ordered subtask plans.
- `backend/projects/run_store/contracts.py`: parent/child metadata and typed results.
- `backend/projects/run_store/delegation_scheduler.py`: stable identity, idempotent child create-or-load, concurrency configuration, and dependency scheduler.
- `backend/scripts/agent_run_store.py`: durable run, execution-claim, and event persistence.
- `backend/projects/run_store/app.py`: authenticated remote execution-claim route.
- `backend/projects/run_store/test_delegation_scheduler.py`: child execution/tool filtering, dependency ordering, concurrency, cancellation, service errors, configuration bounds, stable IDs, and typed-result retry replay.
- The same suite verifies approved child patch artifact reporting and rollback after validation failure; `backend/projects/agent_tools/test_workspace.py` covers stale/conflicting application and content-safe revert.
- `backend/projects/run_store/test_event_contracts.py`: atomic claim, duplicate dispatch, parent binding, and terminal-run rejection.
- `desktop/src/lib/engines.ts`: child status events become steps on the parent reply; child approval requests (`delegate_event`) appear as approval cards.

Focused verification: `py -m unittest projects.run_store.test_delegation_scheduler`.
