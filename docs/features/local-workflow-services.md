# Local workflow services

Planning, validation, run/event persistence, and isolated browser automation run in separate local processes with explicit HTTP contracts. Agent execution is an in-process package. The gateway coordinates these components and remains the only browser-facing API.

## Services

| Service | Entry point | Port | Contract |
| --- | --- | ---: | --- |
| Planner | `backend/projects/planner/app.py` | 8771 | `POST /plan`, `GET /health` |
| Validator | `backend/projects/validator/app.py` | 8772 | `POST /validate`, `GET /health` |
| Run store | `backend/projects/run_store/app.py` | 8773 | Run creation/status, ordered event append/replay, payload-bound approval decisions, cancellation request and stale-run recovery, `GET /health` |
| Browser automation | `backend/projects/browser_automation/app.py` | 8774 | Isolated run-scoped Chromium with authenticated create/navigate/state-bound actions/evidence/close/cancel, `GET /health` |
| Gateway | `backend/scripts/pockpock_server.py` | 8766 | Public UI API and transport; invokes the in-process agent core |

All internal services bind to loopback and require `X-PockPock-Internal-Token` for non-health routes. The cross-platform launcher generates or reuses the token, sets service URLs in the gateway environment, and writes logs under the per-user `PockPock` data directory: `%LOCALAPPDATA%\PockPock` on Windows, `~/Library/Application Support/PockPock` on macOS, or `${XDG_DATA_HOME:-~/.local/share}/PockPock` on Linux. Do not expose internal service ports on the LAN.

## Request flow

1. The browser sends an agent request to the gateway.
2. The gateway asks the planner for an execution plan and tool-capable model selection; the planner calls Ollama, then its critic checks scope, available capabilities, ordering, and verifiable checks. The critic may request one bounded revision. The user still reviews and approves the resulting plan before tools run.
3. `backend/projects/agent_core/` owns the execution loop and calls workspace-scoped tools. Validation is forwarded to the validator service.
4. Run metadata and ordered events are sent to the run-store service and persisted to SQLite before being returned to the browser.
5. The browser reads progress and completed results through the gateway's run APIs.

The gateway calls the internal authenticated `POST /runs/{run_id}/cancel` route when a user requests cancellation and `POST /runs/recover` during startup to finalize runs left active by a previous process. `POST /runs/{run_id}/finish` also resolves an active run as cancelled/timed out when a durable request exists, or interrupted after an unexpected disconnect.

The SQLite schema remains compatible. If `POCKPOCK_RUN_STORE_URL` is unset, the repository retains direct local-store fallback for legacy scripts. The standard launchers configure the URL so interactive runs use the separate process. Each service has its own folder and dependency manifest beneath `backend/projects/`; shared gateway libraries and the Python environment remain at the monorepo root.

## Operations and boundaries

- Run `backend/scripts/pockpock.py setup` once to create `.venv`, install all service dependencies, and download Playwright Chromium (tried up to three times, because one slow download should not fail setup). Run `backend/scripts/pockpock.py start` to supervise the API and workflow services; Ctrl+C stops the processes started by that command. The Windows PowerShell launchers remain available for existing Windows workflows.
- Health endpoints are `http://127.0.0.1:8771/health` through `http://127.0.0.1:8774/health`.
- Services currently share the repository and Python virtual environment. They are process-separated components, not independently versioned or packaged projects yet. Install and start the backend separately from the browser frontend; Ollama and model files are also separate optional installs.
- Agent execution now has an in-process application boundary in `backend/projects/agent_core/`; it shares the gateway process and runtime state. A separate worker service remains deferred until concurrency limits and durable run leases have a defined contract.
- Planning currently uses enabled local Ollama models only. The planner critic is a bounded model-based review, not a proof of correctness; user approval and deterministic tool/permission validation remain required.
- Ports are local defaults; update the service URLs and launch helper together if they change.
- Each service README documents its purpose, routes, configuration, security boundary, and manual launch command. The service folders are project boundaries within one repository, not independent source-control repositories or separately versioned packages.

## Verification

Run `python backend/scripts/pockpock.py check` to start the service stack, verify all five health endpoints, and stop only processes started by the check. On Linux, install Playwright's Chromium system libraries first if they are missing. Exercise planning and validation through the authenticated gateway/tool flow; frontend readiness alone does not establish internal service readiness.
