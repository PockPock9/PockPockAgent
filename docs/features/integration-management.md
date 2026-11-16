# Integration Management

The **Connectors** page is one place to see every integration PockPock can
talk to, whether it is connected, and what it can do — without opening a
separate page per integration. It is a management view, not a second control
plane: each integration is still installed, started, or removed where it
already lives (Services, Setup, Skills, MCP servers, Cloud), and this page
says where that is.

## What it covers

The catalog has 23 entries: 8 internal integrations (things that run on
this PC or are managed on another PockPock page) and 15 external
connectors (third-party services connected from this page).

| Integration | Category | What it can do | Managed in |
| --- | --- | --- | --- |
| **Ollama** | Models | Serve the local models Chat and the agents use | Services |
| **OpenClaw** | Agents | Run the OpenClaw agent directly on this PC | Services / Setup |
| **NemoClaw** | Agents | Run OpenClaw inside a sandbox | Services / Setup |
| **Cloud models** | Models | Use NVIDIA NIM, OpenRouter, or Alibaba Model Studio models | Cloud |
| **Public research** | Data | Fetch public pages for research answers | Research (provider setting) |
| **Browser automation** | Tools | Drive an isolated browser for web tasks | Services |
| **Skills** | Tools | Extra instructions the OpenClaw agent follows | Skills |
| **MCP servers** | Tools | Extra tools the OpenClaw agent can call | MCP servers |

### External connectors

External connectors are grouped on the page (Productivity, Developer,
Communication, Social) and the three most-used — GitHub, Gmail, Google
Calendar — are marked **Featured**. Each entry declares its auth method
(`oauth` or `api_token`), the scopes it asks for, and the steps to connect
it. There are no trademarked logo files: the UI renders a letter/brand
tile from the entry's `icon` key (the connector id, e.g. `github`).

| Connector | Group | Auth | Scopes |
| --- | --- | --- | --- |
| **GitHub** | Developer | API token | Read repos/issues/PRs, write issues/PRs |
| **Gmail** | Communication | OAuth | Read/send mail, manage labels |
| **Outlook Mail** | Communication | OAuth | Read/send mail |
| **Outlook Calendar** | Productivity | OAuth | Read/create events |
| **Google Calendar** | Productivity | OAuth | Read/create events |
| **Slack** | Communication | OAuth | Read/post messages |
| **Messenger** | Communication | OAuth | Read/send messages |
| **Notion** | Productivity | API token | Read/write pages |
| **Google Drive** | Productivity | OAuth | Read/write files |
| **Google Docs** | Productivity | OAuth | Read/write documents |
| **Google Sheets** | Productivity | OAuth | Read/write spreadsheets |
| **Instagram** | Social | OAuth | Read profile/posts, publish posts |
| **Facebook** | Social | OAuth | Read profile/posts, publish posts |
| **Threads** | Social | OAuth | Read profile/posts, publish posts |
| **Spotify** | Social | OAuth | Read library/playlists, control playback |

Only **GitHub is live-verified**: connecting it calls
`GET https://api.github.com/user` with the pasted token and stores the
account only on a 200. Every other external connector records the account
and auth method from the connect form and reports `verified: false` — no
fake live OAuth. The Finance group currently has no connector; it is part
of the layout vocabulary for a future finance connector.

## User flow

1. Open **Connectors** from the sidebar (Customize group, above Skills).
   The header has a back arrow (back to Chat), a "Search connectors" box
   that filters the whole catalog by name or description as you type, and
   **Available** / **Connected** tabs with counts. Available shows every
   connector that is not connected; Connected shows only connected ones,
   with an empty state ("No connectors connected yet") when there are none.
2. **Featured** shows the three featured connectors (GitHub, Gmail, Google
   Calendar) as large cards: name and description on the left, a large icon
   tile on the right. Below it, the external connectors are grouped
   (Productivity, Developer, Communication, Social), four rows per group
   with a **See all >** expander. Each row has an icon tile, the name with
   a status badge — **Connected**, **Not connected**, **Needs setup**, or
   **Disabled** — a one-line description, and counts where they apply (for
   example "9 models", "3 skills · 2 MCP servers"). A line under a
   disconnected row names the reason. The **On this PC** section below the
   groups lists the eight on-device integrations the same way.
3. Click a row (or a featured card) to expand its detail panel, or press
   its **Connect** / **View** button. The panel lists what the agent can
   do (scopes for external connectors, capabilities for on-device ones)
   and, for a connector that is not connected, the numbered connect steps.
4. **Connect** on an external connector shows the connect form: account,
   auth method (OAuth / API token, as applicable), and a token field only
   for API-token connectors, labelled that the token is stored only on
   this PC. Submitting sends the form to the backend, which checks a
   GitHub token live before storing anything and reports its own error
   message on a 409 (missing account, rejected token). A connected
   external connector shows "Connected as \<account\> via \<method\>" and
   a "Not verified" note when `verified` is false, plus **Disconnect**,
   which clears the stored account. After Connect or Disconnect the
   confirmation banner at the top is scrolled into view.
   **Connect** on an on-device integration performs that integration's
   connect step: it starts Ollama, enables the public research provider,
   or re-checks a cloud/OpenClaw/NemoClaw/browser integration and reports
   the result. It never installs software; setup still happens on the
   Services or Setup page, and the note under the result says so.
5. **Disconnect** (shown when connected) reverses it where that is safe:
   it disables public research or cloud models, or clears an external
   connector's stored account. For Ollama, OpenClaw,
   NemoClaw, and browser automation it refuses with a message naming the
   Services page, because stopping a service from here would also stop the
   rest of the app's work. Skills and MCP servers are disconnected on their
   own pages. Disconnecting a disabled integration returns 409.
6. The **switch** next to a row turns an integration off without removing
   it: a disabled integration is not offered anywhere until it is switched
   back on. Skills and MCP servers cannot be switched here — their switches
   live on the Skills and MCP servers pages, and attempting it shows that
   message instead of silently doing nothing. External connectors can be
   switched here.
7. **Add an integration** at the bottom of the page links to the two existing
   ways new integrations arrive: **Add a skill** (Skills page) and **Add an
   MCP server** (MCP servers page). There is no separate add form here, by
   design — a skill or server added anywhere else would otherwise appear in
   two places with two states.

The page covers loading (a spinner), empty (a note, which should not happen
— the catalog always has entries), error (the reason from the API, for
example when the gateway is not answering), and per-row busy state while an
action runs.

## Modules and data flow

```text
Desktop app: IntegrationsPage
  │ GET /api/integrations                    → 23 entries with live status
  │ POST /api/integrations/{id}/toggle       → enable / disable (persisted)
  │ POST /api/integrations/{id}/connect      → connect step, then fresh status
  │ POST /api/integrations/{id}/disconnect   → disconnect step, then fresh status
  ▼
pockpock_server.py (same-PC check, rate limits)
  ▼
backend/projects/integrations/
  ├─ catalog.py      the 23 static entries (id, name, category, description,
  │                   capabilities, setup_hint, manage_hint, kind, auth,
  │                   scopes, connect_steps, featured, group, icon)
  ├─ service.py      IntegrationService: live status from injected probes,
  │                   enable/disable, connect/disconnect rules, external
  │                   account store, GitHub token verification
  ├─ api.py          /api/integrations routes
  └─ test_integrations.py
Probes reuse existing calls; no probe is invented for this feature:
  Ollama /api/tags, OpenClaw/NemoClaw bridge status, ExtensionService.list(),
  the research-provider setting, CLOUD_REGISTRY.models(), the browser
  service /health, and the existing Ollama start endpoint. The one new
  live call is the GitHub token check, ``GET https://api.github.com/user``,
  made only at GitHub connect time.
```

| File | Responsibility |
| --- | --- |
| `backend/projects/integrations/catalog.py` | The static catalog: what exists, what it does, where it is managed |
| `backend/projects/integrations/service.py` | Status mapping, enable/disable, connect/disconnect rules; probes are injected callables so tests can stub them and the service never imports the gateway |
| `backend/projects/integrations/api.py` | `/api/integrations` routes |
| `desktop/src/pages/IntegrationsPage.tsx` | The Connectors page: search, tabs, Featured cards, grouped rows, detail panel with scopes/steps/connect form, On this PC section, add links |
| `desktop/src/components/Shell.tsx`, `desktop/src/App.tsx` | Sidebar entry and page routing |

## API contract

All routes accept requests from this PC only (same check as agent runs) and
return `{"detail": "<message>"}` on failure.

| Route | Body | Result |
| --- | --- | --- |
| `GET /api/integrations` | – | `{"integrations": [{id, name, category, description, capabilities, status, detail, enabled, manage_hint, setup_hint, counts?, kind, auth, scopes, connect_steps, featured, group, icon, account, auth_method, verified}]}` |
| `GET /api/integrations/{id}` | – | One entry with live status |
| `POST /api/integrations/{id}/toggle` | `{"enabled": bool}` | The entry after the flag is stored |
| `POST /api/integrations/{id}/connect` | optional `{"account"?, "auth_method"?, "credential"?}` | The entry after the connect step, plus `note` (and `started` for Ollama) |
| `POST /api/integrations/{id}/disconnect` | – | The entry after the disconnect step, plus `note` |

`status` is one of `connected`, `not_connected`, `needs_setup`, or
`disabled`. `counts` carries `models` for Ollama and cloud models, and
`skills` / `mcp_servers` for skills and MCP servers. `kind` is `internal`
or `external`; `auth` is `local`, `oauth`, or `api_token`. For external
entries `account` is the connected account (or `null`), `auth_method` how
it connected (or `null`), and `verified` is `true` only for GitHub after a
successful live token check. `featured` is `true` for GitHub, Gmail, and
Google Calendar; `group` is one of Productivity, Developer, Communication,
Social (empty for internal entries); `icon` is the icon key, equal to the
entry id. No response ever contains a credential.

Rate limits per minute: list 60, get 60, toggle 30, connect 10,
disconnect 30.

Status codes: `404` unknown integration, `409` the action is not supported
for that integration (with a message naming where it is managed instead),
`422` invalid body, `503` a connect step failed (for example Ollama could
not be started).

## Status rules

- **Ollama**: connected when `/api/tags` answers; otherwise not connected.
  Connect starts Ollama through the existing start endpoint.
- **OpenClaw / NemoClaw**: connected when the bridge reports ready;
  not connected when unavailable on this PC; otherwise needs setup.
  Listing never loads a sandbox model — NemoClaw status is probed with the
  sandbox check off.
- **Cloud models**: connected when at least one cloud model is configured;
  otherwise not connected.
- **Public research**: connected when the research provider is not
  `disabled`; connect enables the named-host fetcher, disconnect disables
  it again.
- **Browser automation**: connected when the browser service answers
  `/health` with `ok`; otherwise needs setup.
- **Skills / MCP servers**: connected when OpenClaw is ready, with counts
  from the extensions list; otherwise needs setup.
- **External connectors**: connected when an account is stored, otherwise
  not connected. Status comes from stored state, never a live call. GitHub
  reports `verified: true` only after a successful token check at connect
  time; every other external connector is `verified: false`.
- **Disabled** wins over live status: a switched-off integration reports
  `disabled` until it is switched back on, whatever the probe says.
- A probe that fails degrades that integration's status instead of failing
  the whole list.

## Connect / disconnect rules for external connectors

- **GitHub + credential**: the token is checked live with
  `GET https://api.github.com/user` (5 s timeout). 200 stores the
  credential and the account (the login), `verified: true`, status
  `connected`. 401/403 returns 409 "That token was rejected by GitHub" and
  stores nothing. A network error returns 503. No credential without a
  token returns 409 naming the setup steps.
- **Other external + account and auth method**: stores both,
  `verified: false`, status `connected`, with the note "Connected as
  \<account\> via \<auth_method\>. Not verified against \<Service\> in this
  build — add credentials in Settings to verify." A credential supplied
  here is not stored unverified. Missing account or auth method returns
  409 with the connector's connect steps.
- **Disconnect** clears the stored account, auth method, credential, and
  verified flag; status returns to `not_connected`.

## Persistence

- On/off flags: gateway settings keys `integration_<id>_enabled`
  (default on). They are the only state this feature writes.
- External connector accounts: gateway settings keys
  `integration_<id>_account`, `integration_<id>_auth_method`, and
  `integration_<id>_credential` (empty string means cleared; the settings
  table has no delete). Only a GitHub credential verified live is stored;
  `verified` is derived from a stored GitHub credential, not stored
  separately.
- Public research connect/disconnect writes the existing
  `frog_research_provider` setting, the same setting the Research page
  uses — the two pages cannot disagree.
- Nothing else is persisted: no catalog copy, no status cache. Statuses are
  re-probed on every list call; external status is read from stored state.

## Security boundaries

- Same-PC only, like every other gateway route. The page reaches the
  gateway through the app's loopback origin.
- No credentials pass through this feature. Cloud API keys stay in the
  desktop app's encrypted storage and are never returned by the list.
- External-connector credentials live only in the gateway settings table on
  this PC (`integration_<id>_credential`). They are never returned in any
  API response, never logged (the gateway log was checked: a submitted
  token does not appear in it), and only a GitHub token that passed the
  live check is stored at all. A credential supplied for any other
  external connector is discarded, not stored unverified.
- The GitHub token is sent only to `api.github.com`, with a 5 s timeout,
  and only at connect time — listing integrations never calls GitHub.
- Connect never installs software, downloads anything, or runs a command
  the user did not already approve through Setup; the only process it can
  start is Ollama, through the existing start endpoint.
- A failing probe never leaks its error text into a response; the detail
  line is a fixed, user-readable sentence.

## Failure states

| What you see | Cause | What to do |
| --- | --- | --- |
| "…is managed on the Services page…" | Disconnect (or connect) was pressed for a service-managed integration | Use the Services page |
| "Skills are managed on the Skills page…" | Toggle or disconnect on skills / MCP servers | Use the Skills or MCP servers page |
| "That integration is disabled. Turn it on before connecting." | Connect pressed while the switch is off | Switch it on first |
| "That integration is disabled. Turn it on before disconnecting." | Disconnect pressed while the switch is off | Switch it on first |
| "That token was rejected by GitHub." | The pasted GitHub token got 401/403 | Check the token (fine-grained, repo/issues access) and paste it again; nothing was stored |
| "GitHub could not be reached…" | Network error during the GitHub token check | Check the connection and try again; nothing was stored |
| "\<Service\> needs an account and auth method. …" | Connect pressed for an external connector without account/auth method | Follow the connect steps shown in the message |
| "Ollama is not running. Connect to start it." | Ollama is down | Press Connect on the Ollama row |
| "No cloud models are connected…" | No cloud provider configured | Add a provider on the Cloud page |
| The page shows a spinner and never loads | The gateway is not answering | Open Services and check the gateway |

## Limits

- This page manages status and on/off flags only. Installing, signing in,
  and removing integrations still happen where they already did.
- Cloud models show a count only; which provider a model belongs to is on
  the Cloud page.
- Live turns through OpenClaw and NemoClaw are not tested from this page;
  it reports readiness, it does not run a turn.
- Only GitHub is live-verified. Other external connectors record the
  connection and are marked unverified; there is no real OAuth flow in
  this build, and the entry says so instead of pretending otherwise.

## Verification

```bash
cd backend
PYTHONPATH=. python -m unittest discover -s projects/integrations -t . -p "test_*.py"
python scripts/run_tests.py
cd ../desktop
npm run typecheck && npm run build && npm test
```

Manual check: open **Connectors** in the desktop app and confirm all
twenty-three integrations render with a status; search "git" and confirm
only GitHub matches; open the Connected tab with nothing connected and
confirm the empty state; switch public research off and on
and confirm the Research page agrees; press Connect on Ollama with Ollama
stopped and confirm it starts; press Disconnect on a skill and confirm the
error names the Skills page; connect GitHub with a bad token and confirm
the 409 and that nothing is stored; connect Gmail with an account and
confirm it shows connected and unverified.
