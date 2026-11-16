# Integrations

One place to see what PockPock can connect to and whether each connection is
healthy: local models (Ollama), the OpenClaw agent, the NemoClaw sandbox,
cloud models, public research, browser automation, OpenClaw skills, and MCP
servers — plus 15 external connectors (GitHub, Gmail, Outlook, Google
Calendar/Drive/Docs/Sheets, Slack, Messenger, Notion, Instagram, Facebook,
Threads, Spotify). The desktop Integrations page reads this package's API;
the package itself owns the catalog, the live status rules, and the
enable/disable flags.

## Modules

- `catalog.py` — the static catalog of 23 integrations (8 internal, 15
  external). Each entry has an `id`, `name`, `category` (`Models`, `Agents`,
  `Tools`, or `Data`), a short `description`, `capabilities` (what it can
  do), a `setup_hint`, and a `manage_hint` (where it is managed, e.g.
  "Services page", "Cloud page"). Each entry also has `kind`
  (`internal`/`external`), `auth` (`local`/`oauth`/`api_token`), `scopes`,
  `connect_steps`, `featured` (GitHub, Gmail, Google Calendar), `group`
  (Productivity, Developer, Communication, Social — empty for internal
  entries), and `icon` (the icon key, equal to the entry id).
- `service.py` — `IntegrationService`. It takes every live probe as an
  injected callable so it never imports the gateway server, and so tests can
  stub everything. It maps probes to statuses, persists on/off flags and
  external-connector accounts, verifies GitHub tokens live, and performs
  the connect/disconnect steps that are safe to do here.
- `api.py` — `create_router(service, require_local)`, following the
  `agent_extensions` router shape: prefix `/api/integrations`, local-only
  requests, `IntegrationError` translated to an HTTP error.
- `test_integrations.py` — plain `unittest` suite with stubbed probes; no
  network, no gateway, no models.

## API contract

All routes are local-only (loopback requests from this PC).

| Method | Path | Body | Result |
| --- | --- | --- | --- |
| GET | `/api/integrations` | — | `{"integrations": [...]}` — all 23 entries with live status |
| GET | `/api/integrations/{id}` | — | One entry with live status |
| POST | `/api/integrations/{id}/toggle` | `{"enabled": bool}` | Entry after the flag is stored |
| POST | `/api/integrations/{id}/connect` | optional `{"account"?, "auth_method"?, "credential"?}` | Entry after the connect step, plus `note` |
| POST | `/api/integrations/{id}/disconnect` | — | Entry after the disconnect step, plus `note` |

Each entry is the catalog fields plus:

- `status`: `connected` | `not_connected` | `needs_setup` | `disabled`
- `detail`: a one-line human-readable explanation of the status
- `enabled`: whether the integration is switched on here
- `counts`: cheap counts where they exist (`models` for Ollama/cloud,
  `skills`/`mcp_servers` for skills/MCP), otherwise `{}`
- `account`: the connected account for external connectors, else `null`
- `auth_method`: how an external connector connected, else `null`
- `verified`: `true` only for GitHub after a successful live token check

Errors: unknown id → 404; invalid body → 422 (pydantic); an action that
belongs on another page → 409 with a message naming that page; a rejected
GitHub token → 409; a GitHub check that cannot reach GitHub → 503.

## Status rules

- **ollama** — `connected` when `/api/tags` answers, `not_connected` when it
  does not. `counts.models` is the number of installed models.
- **openclaw** / **nemoclaw** — from the bridge status dict: `ready` →
  `connected`; `available` false → `not_connected`; otherwise `needs_setup`,
  with the bridge's own `detail`. NemoClaw is probed with `probe=False`, so
  merely listing integrations never loads a sandbox model.
- **cloud** — `connected` when at least one cloud model is configured in the
  registry, otherwise `not_connected`.
- **research** — `connected` when the research provider is not `disabled`.
- **browser** — `connected` when the browser-automation service answers its
  `/health` check with `ok`; `needs_setup` when it does not answer or is not
  configured on the gateway.
- **skills** / **mcp** — `connected` when the extensions list reports
  `openclaw_ready`, otherwise `needs_setup` with the extensions detail.
- **External connectors** — `connected` when an account is stored, otherwise
  `not_connected`. Status comes from stored state, never a live call;
  GitHub is `verified` only after a successful token check at connect time.
- Any integration whose flag is off reports `disabled` and is not probed.
- A probe that raises degrades to `needs_setup`/`not_connected` with a
  generic detail instead of failing the whole list.

## Toggle, connect, disconnect

- **Toggle** is allowed for `ollama`, `openclaw`, `nemoclaw`, `cloud`,
  `research`, `browser`, and all external connectors. `skills` and `mcp`
  return 409: they are managed on the Skills / MCP servers pages, and this
  package deliberately builds no parallel enable/disable system for them.
- **Connect** performs the integration's connect step where one exists:
  `ollama` starts Ollama (via the gateway's existing start logic) and reports
  whether it was already running; `research` sets the provider to
  `named_host_fetcher`; `cloud` re-probes and points at the Cloud page;
  `openclaw`, `nemoclaw`, `browser`, `skills`, and `mcp` re-probe only and
  note that setup happens on the Services / Skills / MCP pages. No installs
  are attempted. Connecting a disabled integration returns 409.
- **Connect (external)**: `github` with a `credential` verifies it live
  against `GET https://api.github.com/user` — 200 stores the credential and
  the login with `verified: true`; 401/403 returns 409 "That token was
  rejected by GitHub" and stores nothing; a network error returns 503;
  no credential returns 409 naming the setup steps. Any other external
  connector with `account` and `auth_method` stores both with
  `verified: false` and says so honestly in the note; without them it
  returns 409 with the connector's connect steps. A credential supplied
  for a non-GitHub connector is not stored.
- **Disconnect**: `research` sets the provider to `disabled`; `cloud`
  switches its flag off; an external connector clears its stored account,
  auth method, credential, and verified flag; everything else returns 409
  naming the page that manages it (Services page, or Skills / MCP servers
  page). Disconnecting a disabled integration returns 409.

## Persistence

On/off flags live in the gateway settings table as
`integration_<id>_enabled` (`"1"`/`"0"`, default on). External-connector
accounts live there too, as `integration_<id>_account`,
`integration_<id>_auth_method`, and `integration_<id>_credential` (empty
string means cleared). Only a GitHub credential that passed the live check
is stored; `verified` is derived from a stored GitHub credential. Nothing
else is stored here: the research provider stays in
`frog_research_provider`, cloud models stay in the in-memory cloud
registry, and skills/MCP state stays with the extensions service.

## Security boundaries

- All routes are local-only, like the extensions routes.
- Probes never log anything and responses never include tokens, keys, or
  credentials. The cloud probe only sees model names from the registry,
  never API keys. External-connector credentials are stored only in the
  gateway settings table on this PC, never returned in any response, and
  never logged; the service's account store returns account/auth
  method/verified only. The GitHub token is sent only to `api.github.com`
  at connect time, with a 5 s timeout.
- Enabling public research is an explicit connect action; the response notes
  that requests leave this PC. The service never fetches a URL itself.
- Only GitHub is live-verified. Other external connectors record the
  connection and report `verified: false`; there is no real OAuth flow in
  this build.
- Rate limits (per minute, in the gateway): list 60, get 60, toggle 30,
  connect 10, disconnect 30.

## Verification

From `backend/` with the repo venv:

```sh
python -m py_compile projects/integrations/*.py
PYTHONPATH=backend python -m unittest discover -s projects/integrations -t . -p "test_*.py"
python backend/scripts/run_tests.py
```
