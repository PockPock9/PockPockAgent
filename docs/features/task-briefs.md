# Structured agent task briefs

## Contract

Planner responses use top-level `contract_version: 1` and a validated `task_brief` object. The version 1 schema lives in `backend/projects/planner/contracts.py` and contains:

- the unmodified `original_request` and concise `desired_outcome`;
- bounded `constraints` and `assumptions`;
- `required_capabilities` selected from the gateway's known workspace, validation, research, attachment, artifact, and local-image capabilities;
- the permission level already selected by the user;
- ordered milestones, each with a stable brief-local ID and observable completion check;
- expected deliverables and measurable success checks;
- `requires_clarification` and up to five clarifying questions.

The planner model cannot elevate permissions. The gateway validates the brief contract version and schema before returning it to the browser. A planner service that does not return version 1 receives a clear unavailable/unsupported-contract error; older browser consumers can ignore the additive `task_brief` response field while continuing to use the existing `plan` and `execution_prompt` fields.

When a model omits optional structured details, the planner supplies bounded compatibility defaults from the validated plan, while preserving the original request. Invalid capability names, milestone shapes, oversized lists, unsupported versions, or inconsistent clarification fields fail validation.

## Routing examples

| User request | Route | Brief behavior |
| --- | --- | --- |
| “Create a playable browser game and verify the files.” | Agent | Workspace write and validation capabilities; deliverable and observable behavior checks. |
| “Research the official documentation at example.com and summarize the API.” | Agent | Public research capability; named host is preserved as a constraint; citations/results become a check. |
| “What is a browser automation agent?” | Chat | It is a question and needs no side effect; do not manufacture an execution plan. |
| “Make it better.” | Agent only if context routes it as an action | Mark `requires_clarification` when the object or desired change is absent; ask what should change. |

These examples describe task versus ordinary-chat routing. They are not permission to infer a broader action than the user's words.

## Bounded replanning

During execution, the gateway records successful tool steps and tool failures. A failed or unavailable tool emits a durable `plan_revision` timeline event with its trigger, completed tool steps, the revised remaining action, and a short rationale. The model is instructed to revise only remaining work, keep the approved scope and permission, and report each approved success check on an ordered `[CHECK N: PASS]` or `[CHECK N: INCOMPLETE]` line with actual evidence. Missing or incomplete check reports get at most two correction attempts, after which the run ends partial. Existing project validation and required-artifact gates still block success when they fail.

The gateway stops after two identical tool failures or five failure-triggered revisions. It hashes tool arguments in memory to detect repeats and does not include arguments in the revision event. Existing per-tool timeouts, the 15-minute run deadline, the 20-model-call ceiling, and payload-bound approvals continue to apply. A stop is reported as a partial failure; a changed action may proceed only through the same tool permission and approval checks as before.

The revision event is replayed from durable run history and shown in the chat timeline. This is bounded adaptation, not autonomous permission or scope expansion. The gateway enforces presence and status of each check report; evidence quality is assessed by the model, while workspace validation and required artifact checks are enforced directly by the gateway.

## Model routing

Planning receives only enabled local models whose runtime profile advertises tool-call support. The gateway also supplies each candidate's advertised context window and prompt-free average call latency. The planner estimates a bounded context budget from task length, excludes known undersized candidates, preserves the user-selected model when compatible, then uses the configured default or lowest measured latency. Unknown context remains eligible and missing latency history is treated as unknown. The timeline reason identifies whether the user preference, fallback, or measured latency drove selection.

Routing metrics use model names, tool/context capabilities, and numeric call duration only. They do not inspect prompts or responses. The fixed regression suite uses synthetic tasks and candidate profiles; real task content and model output are not included. Outcome-based metrics remain disabled until there is an explicit local opt-in design.

## Coordinator subtask proposals

The planner can return an optional `delegation_plan` with at most 16 typed subtasks. Each proposal names a role, purpose, expected result, dependency IDs, allowlisted tools, and maximum tool-call and duration budgets. Dependencies must reference earlier proposals, so the list is a topological order without cycles. Unsupported tools, duplicate IDs, forward dependencies, and values outside the operational bounds are rejected.

The chat plan preview displays each proposed subtask and its dependencies before the user approves the parent plan. The parent approval ticket binds the exact proposal. After approval the run history records the approved delegation plan and current `not_started` dispatch status. This milestone does not start child runs; dispatch and permission isolation belong to later milestones.

## User interface

The execution-plan timeline displays the desired outcome, selected permission, milestones, success checks, deliverables, and clarification questions alongside the generated prompt. Users can edit the steps and checks, approve the exact plan, or decline it. The gateway rejects execution unless the submitted plan, checks, source task, workspace, permission, and execution prompt match a still-valid one-use ticket. Tickets expire after ten minutes. Plan versions and decisions are currently retained in the browser transcript and short-lived gateway memory; durable plan history and recovery after a gateway restart are tracked separately in PLN-03.
