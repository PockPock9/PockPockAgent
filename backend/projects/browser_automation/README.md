# Browser automation runtime

This local service owns browser processes and isolated, in-memory browser contexts for a single agent run. Playwright with Chromium is the default engine; optional Lightpanda CDP support is restricted to one active run context. `engines.py` owns engine lifecycle behind a small adapter. The service does not connect to the user's normal browser, load a profile, or persist cookies, credentials, cache, or local storage. Agent requests explicitly asking to open or show a browser use a visible Chromium window; ordinary inspection and research stay headless, and explicit headless/background instructions take precedence. Visible windows still use a fresh, isolated context and the same public-host/read-only restrictions. It supports bounded public-page observation and typed, state-bound actions; the gateway renders these actions in Agent Chat. It also stores explicit user-authored browser workflow recipes locally and exposes a deterministic internal executor that checks a page checkpoint after every step. The gateway owns approval-gated recipe execution and durable ordered run events; the Browser recipes page provides an explicit launch, transient input, progress, approval, and result view.

## Start and install

Install the service dependency and Chromium once into the repository virtual environment:

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
..\.venv\Scripts\python.exe -m playwright install chromium
..\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8774
```

The standard dashboard launcher installs dependencies from the shared project setup and starts this service alongside the other loopback workflow services. A missing Chromium installation is reported as an unhealthy/unavailable runtime in the service log; rerun the browser install command above.

## Engine selection

`POCKPOCK_BROWSER_ENGINE` defaults to `playwright`, which remains the recommended engine and supports concurrent run contexts. Unknown engine names fail service startup; the runtime never silently falls back.

Lightpanda 1.0.4 is an optional, user-installed CDP backend. On Windows, install and run it in WSL2 Ubuntu. The official installer verifies the release checksum and requires `curl`, `jq`, and `sha256sum`:

```bash
sudo apt-get update
sudo apt-get install -y curl jq
export PATH="$HOME/.local/bin:$PATH"
curl -fsSL https://pkg.lightpanda.io/install.sh | bash -s "1.0.4"
```

In a WSL terminal, start its CDP server on loopback with private-network blocking enabled and telemetry disabled:

```bash
export PATH="$HOME/.local/bin:$PATH"
LIGHTPANDA_DISABLE_TELEMETRY=true lightpanda serve --host 127.0.0.1 --port 9222 --block-private-networks
```

Then set the engine in PowerShell and launch the dashboard from that same session:

```powershell
$env:POCKPOCK_BROWSER_ENGINE = "lightpanda"
.\backend\scripts\start_frog_ai_dashboard.ps1
```

The runtime accepts only an HTTP CDP URL on `localhost` or a loopback IP; override the default `http://127.0.0.1:9222` with `POCKPOCK_LIGHTPANDA_CDP_URL` if needed. WSL2 localhost forwarding lets the Windows service connect to this endpoint. Lightpanda must report its identity and version at `/json/version`; an unavailable or non-Lightpanda endpoint fails startup without falling back.

Lightpanda currently permits only one active isolated context per server and cannot open a visible desktop window. The runtime rejects another context with HTTP 503 until the active run is closed. Lightpanda does not support JPEG screenshots, so this engine returns PNG evidence and saves artifacts with `.png`; the Playwright/Chromium default remains JPEG. Both engines use the same public-host, same-host request, GET/HEAD-only, per-run request/navigation, text-size, approval, and cleanup rules. Keep the CDP server bound to loopback and include `--block-private-networks`; never expose the CDP port to a network.

## HTTP contract

| Method and path | Authentication | Purpose |
| --- | --- | --- |
| `GET /health` | None; loopback only | Reports readiness, selected engine, active context count/cap, and that profile persistence is disabled |
| `POST /contexts` | Internal token | Body `{ "run_id": "<32 lowercase hex>", "visible": false }`; opens a fresh non-persistent context in the selected engine; `visible: true` requests headed Playwright Chromium |
| `POST /navigate` | Internal token | Body `{ "run_id": "...", "url": "https://..." }`; returns title, final URL, visible text, retrieval time, and an in-memory screenshot reference |
| `POST /actions` | Internal token | Body includes `run_id`, current `observation_id`, and one typed `click`, `type`, `select`, `scroll`, or same-host `navigate` action; returns a fresh observation and screenshot reference |
| `GET /recipes` | Internal token | Lists local browser workflow recipes |
| `POST /recipes` | Internal token | Creates a version 1 recipe with exact public host allowlists and validated typed steps |
| `GET /recipes/{recipe_id}` | Internal token | Reads one recipe |
| `GET /recipes/{recipe_id}/versions` | Internal token | Lists immutable recipe definition versions |
| `PUT /recipes/{recipe_id}` | Internal token | Saves an edit if `expected_version` matches; creates a new version |
| `POST /recipes/{recipe_id}/enabled` | Internal token | Enables or disables a recipe |
| `DELETE /recipes/{recipe_id}` | Internal token | Permanently deletes recipe and version history |
| `POST /recipes/{recipe_id}/execute` | Internal token | Executes an enabled current recipe version in a fresh context; body includes `version` and transient `inputs`; returns ordered checkpoint results and always closes the context |
| `GET /evidence/{run_id}/{evidence_id}` | Internal token | Returns the run-scoped JPEG (Playwright) or PNG (Lightpanda) screenshot with `Cache-Control: no-store` |
| `DELETE /contexts/{run_id}` | Internal token | Closes the run's context and any engine-owned browser process; repeated close is safe |
| `DELETE /runs/{run_id}` | Internal token | FND-02 cancellation hook; closes the run-owned browser context and engine-owned process |

All endpoints bind to `127.0.0.1`. Authenticated calls use `X-PockPock-Internal-Token`, shared with other local services. Context creation rejects malformed IDs and duplicate requests are idempotent. Navigation accepts HTTP/HTTPS on standard ports, rejects URL credentials and non-public DNS/IP destinations, and rechecks every browser request and final redirect; page requests are restricted to GET/HEAD. A run is restricted to its first hostname, has at most eight navigations and 100 same-host network requests, and returns at most 64,000 visible text characters. Navigation, DOM extraction, and screenshot capture have explicit timeouts; screenshots remain in memory and disappear when the run context closes. Every observation gets a new unpredictable ID; actions carrying an older ID are rejected. Click targets must be unique accessible links and stay on the same host; `_blank` and non-HTTP links are rejected. Typing targets named textboxes/searchboxes, never password fields, and selecting targets named comboboxes. In Default and Auto-review modes, each action except fixed scrolling requires approval; Full Access skips ordinary approvals, but high-impact links still pause. Approval is bound to the exact validated action and observation ID, expires after five minutes, and typed values are redacted from persisted approval details. Scroll distance is fixed; navigation is same-host. Form submission, buttons, arbitrary selectors, and arbitrary scripts are not exposed. Service shutdown closes every context, closes its Chromium processes, and disconnects from Lightpanda without stopping its externally managed server. Playwright Chromium launches disable extensions and sync, block service workers, and reject downloads. The service has no endpoint for arbitrary scripts or filesystem access.

Recipe records are stored outside the repository at `%LOCALAPPDATA%\FrogAI\browser-recipes.sqlite3` by default; `POCKPOCK_BROWSER_RECIPE_DB` can point to a local alternate path. The database contains user-authored recipe definitions and immutable definition versions, not browser state, cookies, credentials, run inputs, or page results. Recipe inputs are names and types only; a recipe step can reference an input but cannot store a typed value. Each update requires the current version number and appends the next version. Disabling preserves history. Deleting removes the recipe and all its versions immediately. Recipes allow exact hostnames only (no wildcards), and each navigation URL must match the allowlist. The recipe API supports only named click/type/select, fixed scroll, same-host navigation, required title/text stop conditions, and an `each_run` approval policy. The runtime executor rejects disabled or stale versions, undeclared/missing inputs, and URL inputs outside the exact host allowlist. Inputs are used only in the request and are not stored; returned step records omit input values. A checkpoint mismatch stops before the next step. Every execution closes its fresh context on success, mismatch, failure, or cancellation. The gateway local-only run route requests a fresh durable approval for every step, binds it to recipe/version/step/target/current observation and a keyed input fingerprint, saves screenshots under the task output folder, and persists ordered run events for replay. The Browser recipes page lets the user explicitly launch an enabled version, enter transient inputs, approve/reject each step, follow checkpoint results, and view saved screenshots. Runs also appear in Conversations and remain replayable after reload. There is no scheduled or automatic launch path.

## Safety and limitations

Cross-host redirects and subresource requests are blocked for the current run to keep its network scope tied to the initial host. Some pages may render without third-party assets. The gateway's FND-02 user-cancel route calls the internal run-close hook. Recipe execution is available through the gateway's local-only run route and Browser recipes UI. The current action set blocks buttons and form submission.

## Validation

From `backend/`, run `.venv\Scripts\python.exe -m unittest projects.browser_automation.test_engines` and `.venv\Scripts\python.exe -m unittest projects.browser_automation.test_scenarios -v`. The 20 deterministic scenarios cover URL and DNS policy, context lifecycle/capacity, bounded observations/evidence, redirects, request filtering/limits, state-bound accessible actions, and checkpoints. Compile with `.venv\Scripts\python.exe -m py_compile projects\browser_automation\app.py projects\browser_automation\engines.py`. For a live smoke check, start Lightpanda with the secured WSL command above, start the dashboard, verify `http://127.0.0.1:8774/health`, navigate to a user-approved test page, and retrieve its screenshot reference. Confirm private/cross-host requests are blocked and closing a run removes its context and screenshot evidence.
