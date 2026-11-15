# Agent tool capabilities

## Purpose and user flow

The local agent performs supported work by requesting typed tools during an Agent Chat run. The gateway checks the selected permission and each registered tool contract, executes the capability with the run's scoped context, and records the result in the durable activity timeline. Created artifacts and workspace patches are surfaced as run outputs. There is no general-purpose shell tool.

## Module ownership

- `backend/projects/agent_tools/common.py` defines shared task contexts, safe task output paths, and bounded state.
- `backend/projects/agent_tools/workspace.py` lists, searches, and reads supported files under the selected workspace; stages reviewed edits; and calls the deterministic workspace validator. Path traversal, symlinks, secret files, and unsupported file types are rejected.
- `backend/projects/agent_tools/research.py` implements user-directed public-host discovery and bounded same-host text/page retrieval. It blocks private destinations and unapproved redirects.
- `backend/projects/agent_tools/research_contracts.py` defines provider-neutral, versioned source/evidence/error records and adapts existing named-host fetch results without changing the callable tool contract.
- The gateway stores research provider opt-in in the local settings table. The Research settings page discloses that named public-site requests leave the PC; the gateway denies fetch tools while the provider is disabled.
- Successful site crawls emit a replayable `research_sources` event. Conversations renders canonical source links, retrieval timestamps, snippets, bounded excerpts, and retrieval failures.
- `backend/projects/agent_tools/artifacts.py` creates task-scoped text/office deliverables and images using an already-running local image engine.
- `backend/projects/agent_tools/registry.py` exposes the model tool schemas and dispatches a registered name to its capability module.
- `backend/projects/agent_tools/contracts.py` validates schemas, capabilities, permission/side-effect metadata, timeouts, and input/output byte limits.
- `backend/projects/agent_tools/__init__.py` re-exports the stable package interface used by the gateway and validator.

## Permissions and persistence

Workspace tools are denied in Default mode; Auto-review permits scoped workspace work but requires a durable chat approval bound to the exact diff before applying, while Full Access applies without another prompt. Public research is read-only, disabled until explicitly enabled in Research settings, and limited to hosts named by the task; the settings page states requests leave the PC. Attachment reads only use explicitly attached files. Artifact creation writes into the task output directory. Tool progress/results are persisted as versioned run events; prompt-free telemetry does not receive tool content. Details of schema/event upgrades are in [Agent tool and run event contracts](agent-tool-contracts.md), and run replay/output recovery is in [Agent runs](agent-runs.md).

## Failure behavior

Unregistered tools fail with a stable `unknown_tool` error. Invalid input/output, missing permission, rejected capability, timeout, and tool failure use typed error codes and do not report a successful tool result. Output bounds are checked before returning a result to the model. Workspace validation results remain explicit and a failing check must be repaired or reported as incomplete.

## Verification and maintenance

Run `.venv\Scripts\python.exe -m unittest projects.agent_tools.test_contracts projects.agent_tools.test_agent_tools projects.agent_tools.test_research projects.agent_tools.test_research_answers projects.agent_tools.test_workspace projects.agent_tools.test_artifacts projects.planner.test_plan_gate projects.run_store.test_event_contracts`. Compile the changed capability modules and callers. Add new capabilities through `registry.py` and `contracts.py`, with focused tests and updated docs; keep the gateway dependent on the package facade/registry contract instead of importing implementation modules.
