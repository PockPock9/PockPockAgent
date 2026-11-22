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

When a model omits optional structured details, the planner supplies bounded compatibility defaults from the validated plan, while preserving the original request. Deterministic guards also correct the capability list: web capabilities are removed when the request never mentions the web, build requests get workspace read/write/validation (a request for a document about code, such as "write a report about the project" or "a summary of the test results", is not a build request: `has_build_intent` ignores a build verb and code noun with a report, summary, memo, overview or similar document word between them, unless that word only describes the thing built, as in "report page"; before this, such a report was planned with `project_validation` and treated as code work), and a request to save a file or document (a report, memo, spreadsheet, or a named `.md`, `.docx`, `.html` … file) gets `artifact_creation` unless it already has workspace write or public research. When the user opened a folder for the task and asks to read, review, summarize, check or list its files (or names a text file), the brief gets `workspace_read` — read-only access to that folder, shown in the plan the user approves; edits still need `workspace_write` in the plan. Without this, "read the reports in this folder and save a summary" planned `artifact_creation` only and the agent had no tool to read with.

The executor adds a final backstop. Tools are filtered by capability, so a task that needs a tool but was planned with no capability would reach the model with no tools. In that case the executor adds `artifact_creation`, and `attachment_read` when files are attached. These two only create files in the run's own task folder or read the user's attachments; workspace edits, web access and browser actions are never added outside the approved plan. With a folder open, files saved with `save_text_artifact` go to the run's task folder, not the open folder; a `read_project_file` call for a file this run saved, which the open folder does not have, reads the saved copy so the agent can check it. No other task-folder file is reachable that way. Invalid capability names, milestone shapes, oversized lists, unsupported versions, or inconsistent clarification fields fail validation.

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

The revision event is replayed from durable run history and shown in the chat timeline. This is bounded adaptation, not autonomous permission or scope expansion. The gateway enforces presence and status of each check report; evidence quality is assessed by the model, while workspace validation and required artifact checks are enforced directly by the gateway. A `PASS` is also refused when its check or evidence names browser evidence (page, screenshot, visible text) or research evidence (search results, sources, citations), a tool of that kind failed in the run, and no tool of that kind succeeded; that check counts as incomplete.

Other completion rules:

- A request that names a file to save (for example "save it as summary.html") is complete once that file is saved, even if the wording also reads like a workspace edit.
- An image request is never a success without an image; the error names the local image engines PockPock supports (ComfyUI on port 8188, Stable Diffusion WebUI on port 7860).
- Research runs whose search or page fetch retrieved no source end at once with "no source retrieved" instead of retrying the citation validation, which cannot pass without sources. The research answer format is given to the model whenever `public_research` is planned.

## Model routing

Planning receives only enabled local models whose runtime profile advertises tool-call support. The gateway also supplies each candidate's advertised context window and prompt-free average call latency. The planner estimates a bounded context budget from task length, excludes known undersized candidates, preserves the user-selected model when compatible, then uses the configured default or lowest measured latency. Unknown context remains eligible and missing latency history is treated as unknown. The timeline reason identifies whether the user preference, fallback, or measured latency drove selection.

Routing metrics use model names, tool/context capabilities, and numeric call duration only. They do not inspect prompts or responses. The fixed regression suite uses synthetic tasks and candidate profiles; real task content and model output are not included. Outcome-based metrics remain disabled until there is an explicit local opt-in design.

## Coordinator subtask proposals

The planner can return an optional `delegation_plan` with at most 16 typed subtasks. Each proposal names a role, purpose, expected result, dependency IDs, allowlisted tools, and maximum tool-call and duration budgets. Dependencies must reference earlier proposals, so the list is a topological order without cycles. Unsupported tools, duplicate IDs, forward dependencies, and values outside the operational bounds are rejected.

The chat plan preview displays each proposed subtask and its dependencies before the user approves the parent plan. The parent approval ticket binds the exact proposal. After approval the run history records the approved delegation plan and current `not_started` dispatch status. This milestone does not start child runs; dispatch and permission isolation belong to later milestones.

## User interface

The execution-plan timeline displays the desired outcome, selected permission, milestones, success checks, deliverables, and clarification questions alongside the generated prompt. Users can edit the steps and checks, approve the exact plan, or decline it. The gateway rejects execution unless the submitted plan, checks, source task, workspace, permission, and execution prompt match a still-valid one-use ticket. Tickets expire after ten minutes. Plan versions and decisions are currently retained in the browser transcript and short-lived gateway memory; durable plan history and recovery after a gateway restart are tracked separately in PLN-03.
