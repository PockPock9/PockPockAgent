# NemoClaw agent mode

NemoClaw mode lets the PockPock Agent desktop app talk to a sandboxed [NVIDIA NemoClaw](https://github.com/NVIDIA/NemoClaw) agent (OpenClaw harness inside an OpenShell sandbox) running on the same computer: inside WSL on Windows, natively with Docker on a Mac with Apple silicon. It is a third response mode next to **Chat** and **Agent**. PockPock does not install, onboard, or manage NemoClaw; it only sends turns to an existing sandbox and shows the reply.

In the composer it is the **NemoClaw** entry of the mode picker. Setup installs the prerequisites (Windows: WSL with Ubuntu and Docker Desktop; Mac: Xcode Command Line Tools and Docker Desktop), installs NemoClaw and onboards a `pockpock` sandbox against Ollama; the **Services** page starts and stops the sandbox (starting Docker Desktop first).

## When to use it

| Mode | Who does the work | Tools and boundary |
| --- | --- | --- |
| Chat | Smart Router picks a local Ollama model | No tools |
| Agent | PockPock planner, critic, and `agent_core` | PockPock's scoped tools in a Windows task workspace, with plan approval |
| NemoClaw | OpenClaw agent inside the NemoClaw sandbox | OpenClaw's own tools (including a shell) confined to the Linux sandbox and its OpenShell network policy |

NemoClaw mode has no PockPock plan approval or permission modes. The sandbox is the security boundary: the agent can run commands and write files inside its container, but cannot see Windows files or the PockPock task workspaces.

## Prerequisites

- Windows: WSL 2 with a distribution where NemoClaw is installed and a sandbox has been onboarded (default sandbox name `pockpock`). Mac: Apple silicon, NemoClaw installed natively (NVIDIA lists macOS as "tested with limitations"), Xcode Command Line Tools, and the same onboarded sandbox.
- Docker Desktop running (on Windows with WSL integration enabled for that distribution; on a Mac, Colima also works).
- Ollama running on Windows (NemoClaw uses it through Docker Desktop's `host.docker.internal` route). The OpenClaw system prompt needs roughly 14K tokens, so set the Windows user environment variable `OLLAMA_CONTEXT_LENGTH` to `32768` and restart Ollama; with Ollama's 4,096-token default, replies are truncated and the session forgets earlier turns.
- `nemoclaw <sandbox> status` in WSL reports `Phase: Ready` and `Inference: healthy`.

## User flow

1. Open PockPock Agent. It calls `GET /api/nemoclaw/status?probe=0` on start (a full check instead when NemoClaw is the selected mode).
   On load the page asks only whether NemoClaw is installed (`?probe=0`). The sandbox itself is checked when NemoClaw is selected, because that check makes the sandbox test its model, which loads the model into memory.
2. Choose **NemoClaw** in the composer's mode picker. The option is disabled when WSL is unavailable or the integration is turned off; its line shows the reason. Skills and MCP servers added through PockPock are not available inside the sandbox.
3. The mode chip above the composer shows a green dot when the sandbox is ready, a pulsing dot while it is being checked, and a grey dot otherwise; **Settings** → **Check sandbox** forces a fresh status check.
4. The model picker and permission chip are hidden in this mode, because NemoClaw uses its own configured model and sandbox policy.
5. Send a message. The transcript shows `NemoClaw · <model>` on the reply. Each PockPock conversation maps to one NemoClaw session (`pockpock-<conversation id>`), so the agent remembers earlier turns in the same thread.
6. Stop cancels the request and terminates the WSL process for that turn.

Switching an existing conversation into NemoClaw mode does not copy earlier Chat or Agent turns into the NemoClaw session; NemoClaw only sees turns sent in NemoClaw mode.

## Modules and data flow

```text
PockPock Agent desktop app (NemoClaw mode)
  -> POST /api/nemoclaw/chat {session_id, message}         (frog_ai_server.py, same-PC check)
  -> projects/nemoclaw_bridge/api.py  -> NemoClawBridge.run_turn (worker thread)
  -> wsl.exe [-d <distro>] --exec /bin/bash -c <fixed script>
       env NC_SANDBOX, NC_AGENT, NC_SESSION, NC_TIMEOUT, NC_MESSAGE forwarded via WSLENV
  -> nemoclaw <sandbox> agent --agent <agent> --session-id <id> --timeout <s> --json -m "$NC_MESSAGE"
  -> OpenClaw in the OpenShell sandbox -> Ollama on Windows
  <- JSON result -> parse_turn_output -> SSE decision/token/done events
```

| Module | Responsibility |
| --- | --- |
| `backend/projects/nemoclaw_bridge/bridge.py` | Configuration, input validation, WSL command and environment construction, process execution with timeout and cancellation, JSON/status parsing, single active turn, status cache |
| `backend/projects/nemoclaw_bridge/api.py` | `/api/nemoclaw/status` and `/api/nemoclaw/chat` routes, SSE framing, heartbeat events, disconnect cancellation |
| `backend/projects/nemoclaw_bridge/test_bridge.py` | Unit tests using a fake runner (no WSL needed) |
| `backend/scripts/frog_ai_server.py` | Builds the bridge from environment configuration, mounts the router with the gateway's same-PC request check, adds rate limits |
| `desktop/src/components/ChatPane.tsx`, `desktop/src/lib/engines.ts` | Mode picker, readiness check, NemoClaw send path, error and truncation notices |

## API contract

Both routes accept requests only from a local browser on this PC (`require_local_agent_request`: loopback client, loopback forwarding headers and `Origin`, and not the `*.ts.net` remote dashboard). Other callers receive `403`.

### `GET /api/nemoclaw/status[?refresh=1][&probe=0]`

`probe=0` never runs the sandbox check: it returns a recent cached result if there is one, otherwise `available: true, ready: false, checked: false`. `refresh=1` always runs the check. A checked result has `checked: true`.

Rate limit: 60 per minute. Results are cached for 20 seconds unless `refresh=1`. A status check runs `nemoclaw <sandbox> status` in WSL and usually takes 5–10 seconds.

```json
{
  "enabled": true, "available": true, "ready": true,
  "sandbox": "pockpock", "distro": "default",
  "phase": "Ready", "model": "qwen3.5:9b", "provider": "ollama-local",
  "agent_version": "OpenClaw v2026.10.5", "inference_healthy": true,
  "detail": "Ready"
}
```

`available` is false when the integration is disabled or `wsl.exe` is missing. `ready` requires `Phase: Ready` and healthy inference. `detail` is a user-facing explanation.

### `POST /api/nemoclaw/chat`

Rate limit: 8 per minute. Body: `{"session_id": "<1-80 chars [A-Za-z0-9_-]>", "message": "<1-16,000 chars>"}`. The response is `text/event-stream` using the same event shapes as `/api/chat`:

| Event | Fields |
| --- | --- |
| `decision` | `model` (`NemoClaw · <sandbox>`, then `NemoClaw · <model>` once known), `category: "nemoclaw"`, `source` |
| `status` | Heartbeat every 10 seconds while the agent works; the UI ignores it |
| `token` | `content`: the full reply text (NemoClaw does not stream tokens) |
| `done` | `duration_ms`, `truncated` (true when OpenClaw reports the output-token limit) |
| `error` | `code`, `message` |

Error codes: `invalid_session`, `empty_message`, `message_too_long`, `invalid_message`, `busy` (another NemoClaw turn is running), `unavailable`, `timeout`, `turn_failed`, `bad_output`, `empty_reply`, `bridge_failed`.

Only one NemoClaw turn runs at a time across the gateway, because the sandbox shares one local GPU model.

## Configuration

Set these environment variables for the gateway process before `backend/scripts/pockpock.py start`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `POCKPOCK_NEMOCLAW_ENABLED` | `1` | `0`/`false`/`off` hides the integration (status reports `available: false`) |
| `POCKPOCK_NEMOCLAW_DISTRO` | empty (WSL default distribution) | WSL distribution name, for example `Ubuntu-24.04` |
| `POCKPOCK_NEMOCLAW_SANDBOX` | `pockpock` | NemoClaw sandbox name |
| `POCKPOCK_NEMOCLAW_AGENT` | `main` | OpenClaw agent id passed to `--agent` |
| `POCKPOCK_NEMOCLAW_TIMEOUT_SECONDS` | `300` | Per-turn agent timeout, clamped to 30–900; the host process gets 45 extra seconds |

Invalid names (anything other than letters, digits, `.`, `_`, `-`) disable the integration at startup and log a warning.

## Security and privacy

- **No shell injection:** the bash script passed to `wsl.exe` is a fixed constant. The message, session id, and other values are forwarded as environment variables through `WSLENV` and quoted inside the script, so user text is never parsed as shell syntax or placed in the command line.
- **Same-PC only:** the routes reuse the gateway's agent-task locality check, so other machines and non-local origins cannot drive the sandboxed agent.
- **No telemetry:** messages and replies are not written to router telemetry, run tables, or logs. Unexpected bridge exceptions log a stack trace without request content. Browser conversation history stays in local storage as for other modes.
- **Persistence outside PockPock:** NemoClaw stores its own session transcripts and agent memory inside the sandbox (`/sandbox/.openclaw`). Clearing PockPock chats does not delete them; use NemoClaw's tools (`nemoclaw <sandbox> connect`, or `nemoclaw <sandbox> destroy`) to manage that data.
- **Agent capabilities:** OpenClaw can run shell commands and edit files inside its sandbox and reach the network destinations its OpenShell policy allows. Review that policy with `nemoclaw <sandbox> policy list` before giving it sensitive tasks.

## Failure states

| Symptom | Cause and fix |
| --- | --- |
| NemoClaw button disabled | WSL missing or `POCKPOCK_NEMOCLAW_ENABLED=0` |
| `Sandbox offline` | Docker Desktop not running, sandbox stopped, or wrong sandbox/distro name. Run `nemoclaw <sandbox> status` in WSL; `nemoclaw <sandbox> connect` or `nemoclaw onboard --resume` restarts it |
| Reply cut off, or the agent forgets the previous message | Ollama context too small. Set `OLLAMA_CONTEXT_LENGTH=32768` and restart Ollama |
| `Context overflow: prompt too large for the model` | OpenClaw's own `contextWindow` for the model (in the sandbox's `/sandbox/.openclaw/openclaw.json`) is smaller than the prompt. Onboarding may record 16,384, which leaves almost no room after the ~14K-token system prompt once a tool returns output. Set it to match Ollama's `OLLAMA_CONTEXT_LENGTH` (for example 32,768), or pass `NEMOCLAW_CONTEXT_WINDOW=32768` when onboarding or rebuilding, then start a new conversation |
| Web fetch returns `403` from the proxy | The OpenShell network policy blocks that host. List presets with `nemoclaw pockpock policy list`; enabling broad web access is a deliberate trust decision |
| `busy` error | Another NemoClaw turn is still running; wait or press Stop |
| `timeout` | The turn exceeded the configured timeout; raise `POCKPOCK_NEMOCLAW_TIMEOUT_SECONDS` or simplify the request |
| Images rejected | NemoClaw mode accepts text and document attachments only |

## Verification

- Unit tests: from `backend/`, run `..\.venv\Scripts\python.exe -m unittest projects.nemoclaw_bridge.test_bridge` (16 tests; no WSL required).
- Live bridge: `GET /api/nemoclaw/status?refresh=1` returns `ready: true`; two `POST /api/nemoclaw/chat` turns with the same `session_id` show the second reply recalling the first.
- UI: in PockPock Agent choose **NemoClaw**, confirm the mode chip's dot turns green, send a message, and confirm the reply's model label reads `NemoClaw · <model>`.
