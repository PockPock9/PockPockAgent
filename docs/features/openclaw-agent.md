# OpenClaw agent mode

OpenClaw mode lets the PockPock Agent desktop app talk to an [OpenClaw](https://docs.openclaw.ai) agent that runs **directly on this Windows PC, with no sandbox**. It is one of the four modes in the composer, next to **Chat**, **PockPock Agent** and **NemoClaw**. The agent can run shell commands, read and change files anywhere your Windows account can, and use OpenClaw's other tools. What it may do without asking is set by a three-option permission picker in the composer.

In the composer it is the **OpenClaw** entry of the mode picker. Setup installs and configures it (Node.js, OpenClaw, onboarding against Ollama, the permission plugin, the skills you chose, and the gateway login item); the **Services** page starts and stops its gateway.

PockPock does not install OpenClaw or its gateway. It connects to an existing local gateway, sends each message, streams the reply, and shows approval requests.

## When to use it

| Mode | Who does the work | Boundary |
| --- | --- | --- |
| Chat | Smart Router picks a local Ollama model | No tools |
| Agent | PockPock planner, critic, and `agent_core` | PockPock's scoped tools in a task workspace, with plan approval |
| NemoClaw | OpenClaw inside the NemoClaw sandbox in WSL | The Linux sandbox and its network policy; cannot see Windows files |
| OpenClaw | OpenClaw on Windows | None except the permission mode you choose |

Use NemoClaw when the agent should be contained. Use OpenClaw when it must work on real files and programs on this PC.

## Permission modes

The picker appears in the composer when OpenClaw mode is selected. It is stored separately from Agent mode's permission setting and starts at **Ask first**.

| Mode | What runs without asking | What asks |
| --- | --- | --- |
| **Ask first** (`ask`) | Only internal bookkeeping tools (session status, goals, skill and memory lookups, and looking up a tool's description) | Every other tool call: commands, file reads and writes, web requests, browser control, messaging, anything new |
| **Auto-approve safe** (`auto`) | The above, plus local read-only work: `ls`, `read`, `view_image`, session history lookups, observing a running command, looking at an already open browser page (`snapshot`, `screenshot`, `text`, `tabs`), taking a desktop screenshot, and shell commands made only of known read-only commands | Everything else, including file writes and edits, any other command, and all web access |
| **Full access** (`full`) | Everything | Nothing |

Details that matter:

- **Read-only commands** are decided by a conservative allowlist in the plugin (`Get-ChildItem`, `Get-Content`, `Select-String`, `git status`/`log`/`diff`, `hostname`, `ollama list`, and similar). Every segment of a pipeline must be on the list. Any redirection (`>`), script block (`{}`), sub-expression (`()`, `$()`, backticks), `&`, a new line, `Invoke-Expression`, `Start-Process`, or an unknown program means the command asks instead. A command the list does not recognize is never auto-approved.
- **Tools reached through OpenClaw's tool search are checked under their own name.** `tool_search`, `tool_describe`, and the `dispatch_action` wrapper never ask; the tool that `dispatch_action` runs (for example `browser`) passes through the same hook and is asked about there, so one action produces one card.
- **Web access asks in Auto-approve safe.** An agent that can both read local files and reach the web without asking could be tricked by a web page into sending file contents out, so fetching is not treated as safe.
- **Approvals are per action.** Each card offers **Allow once** or **Deny**. There is no "always allow"; choose Full access for unattended work. A request that is not answered within 10 minutes is denied.
- **A missing record is treated as Ask first.** If PockPock cannot record the selected mode, the turn is not started.
- **The question tool is blocked.** OpenClaw's `ask_user` tool is refused in every mode because PockPock has no question prompt; the agent asks in its reply instead.
- **Only PockPock sessions are governed.** The plugin applies to sessions whose key contains `:pockpock-`. Sessions started from OpenClaw's own dashboard, CLI, or chat channels keep OpenClaw's configured policy, which is full access by default.

Full access means what it says: the agent can delete files, install software, and send data anywhere, using a small local model that makes mistakes. Prefer Ask first or Auto-approve safe unless you are watching the task.

## What the agent can operate

| Capability | Tool | Notes |
| --- | --- | --- |
| Programs, settings, processes, installs | `exec` (PowerShell) | For example `Start-Process notepad` or `Start-Process "ms-settings:display"` |
| Files anywhere on the PC | `read`, `write`, `edit`, `ls` | |
| Websites, including clicking and playing media | `browser` | Opens a separate Edge window with its own profile, so it is not signed in to your accounts |
| Mouse, keyboard, and screen in any desktop app | `computer` | Needs the bundled `cua-computer` plugin (`openclaw plugins enable cua-computer`) and a vision-capable model |
| Reading a web page as text | `web_fetch` | |
| Web search | `web_search` | Not configured by default. `openclaw plugins install @openclaw/duckduckgo-plugin`, then `openclaw configure --section web`, adds a key-free provider |

`~/.openclaw/workspace/AGENTS.md` holds standing instructions the agent reads every turn. It includes working argument shapes for the `browser` tool and guidance to prefer `exec` over `computer`, because a small local model otherwise guesses the arguments wrong or answers that it cannot browse.

## Prerequisites

- Node.js 24 or newer on `PATH`.
- OpenClaw installed on Windows and onboarded with a local gateway:

  ```powershell
  npm install -g openclaw@latest --allow-scripts=esbuild,protobufjs,openclaw
  openclaw onboard --non-interactive --accept-risk --mode local --auth-choice ollama --gateway-bind loopback --gateway-auth token --gateway-port 18810 --install-daemon --skip-channels --skip-skills --skip-search --skip-ui --skip-hooks
  openclaw config set agents.defaults.model.primary "ollama/qwen3.5:9b"
  openclaw config set agents.defaults.thinkingDefault low
  ```

  `thinkingDefault low` matters with `qwen3.5:9b`: with reasoning off it often replied without calling any tool. Port 18810 avoids the NemoClaw dashboard on 18789. The gateway listens on `127.0.0.1` only and requires its token.
- Enough model context. OpenClaw's native prompt is about 21K tokens. Set the model's `contextTokens` to `65536` so tool output fits (`openclaw config set "models.providers.ollama.models[0].contextTokens" 65536 --strict-json`, using the index of your model). With `qwen3.5:9b` this uses about 7.7 GB of GPU memory. OpenClaw requests this size per call, so Ollama reloads the model when you switch between OpenClaw and other PockPock modes.
- The PockPock permission plugin installed in OpenClaw:

  ```powershell
  .venv\Scripts\python.exe backend\projects\openclaw_bridge\install_plugin.py
  ```

  Rerun this after changing `plugin/pockpock-permissions.ts`. Run it, and `openclaw gateway restart`, from PowerShell or Command Prompt rather than Git Bash: the gateway inherits the PATH of the shell that restarts it, and Git Bash puts its own tools first (its `notepad` file makes `Start-Process notepad` show an 'Open with' dialog).
- Ollama running on Windows.

The gateway starts at sign-in from a Startup-folder item created by onboarding. Start, stop, or check it with `openclaw gateway start|stop|restart|status`.

## User flow

1. Open PockPock Agent. It calls `GET /api/openclaw/status` on start and every 30 seconds, and again when the OpenClaw gateway service comes up.
2. Choose **OpenClaw** in the composer's mode picker. The option is disabled when Node.js or the helper is missing or the integration is turned off; its line gives the reason.
3. The mode chip above the composer has a green dot when the gateway answers; the status bar shows OpenClaw's state, and **Services** shows details and the log.
4. Choose a permission mode from the permission picker. Full access is shown in amber. If the permission plugin is not loaded, Ask first and Auto-approve safe are disabled and only Full access can run.
5. Send a message. The reply streams as it is written. Each tool call appears as an activity line above the reply: running, completed, failed, denied, or stopped.
6. When an action needs approval, an **Approval required · OpenClaw** card appears with the action and its target (the command line, file path, or URL). Choose **Allow once** or **Deny**. The agent waits, then continues with the result.
7. **Stop** cancels the request, denies anything still waiting, and aborts the agent run in OpenClaw.

Skills and MCP servers can be added to this engine by pasting a link; see [Skills and MCP servers](agent-extensions.md#skills-and-mcp-servers). Tools from a connected MCP server ask for approval in Ask first and Auto-approve safe, on a card titled `Use MCP tool: <server> › <tool>`.

### Choosing the model

With the OpenClaw engine selected, the model picker lists **Default** (OpenClaw's configured model) and the other tool-capable Ollama models in OpenClaw's config. The choice is saved in the app's settings (`clawModel`) and sent with each message; PockPock sets it on the conversation's OpenClaw session before the turn. Choosing **Default** resets the session to OpenClaw's default. A name that is not in OpenClaw's list is refused.

A model is loaded by Ollama when a turn first uses it and unloaded after Ollama's idle period (five minutes unless `OLLAMA_KEEP_ALIVE` is set). Status checks do not load a model. Switching to a model that does not fit beside the loaded one makes Ollama unload the other first.

Large models that only partly fit on the GPU are slow, and OpenClaw's defaults assume a fast model. On this PC (RTX 4070 SUPER 12 GB, 31 GB RAM) `qwen3.5:27b` runs about half on the GPU at roughly 4 tokens per second, and reading a long conversation back in can take several minutes. Three settings in `~/.openclaw/openclaw.json` make that workable:

| Setting | Value | Why |
|---|---|---|
| `models.providers.ollama.models[]` entry for the model, with `contextTokens` | `65536` | The model must be listed to appear in the picker. A window smaller than the conversation forces OpenClaw to summarise the history on every turn, which is slower than reading it |
| `models.providers.ollama.timeoutSeconds` | `1800` | OpenClaw otherwise abandons a model request after 5 minutes, and Ollama keeps working on the abandoned request, blocking every other model |
| `agents.defaults.compaction.timeoutSeconds` | `900` | Same reason, for history summarisation |

PockPock's own per-turn limit (`POCKPOCK_OPENCLAW_TIMEOUT_SECONDS`) defaults to 30 minutes. If a model stays listed by `ollama ps` past its expiry time and other models stop answering, an abandoned request is still running: end the `llama-server.exe` process, or restart Ollama.

Switching model in the middle of a long conversation makes the new model read the whole history first. Start a new chat for a task meant for the large model.

Each PockPock conversation maps to one OpenClaw session (`pockpock-<conversation id>`), so the agent remembers earlier turns in the thread. Turns sent in Chat, Agent, or NemoClaw mode are not copied into it. The model picker is hidden because OpenClaw uses its own configured model. Images are not accepted; text and document attachments are.

## Modules and data flow

```text
PockPock Agent desktop app (OpenClaw mode)
  -> POST /api/openclaw/chat {session_id, message, permission_mode, model?}   (frog_ai_server.py, same-PC check)
  -> projects/openclaw_bridge/api.py -> OpenClawBridge.start_turn
       writes ~/.openclaw/pockpock/permissions.json  {session key: mode}
       spawns: node gateway_turn.mjs          (start request sent on stdin)
  -> gateway_turn.mjs -> ws://127.0.0.1:<gateway port>  (token from ~/.openclaw/openclaw.json)
       pockpock.permissions.status   confirm the plugin is loaded (required for ask/auto)
       sessions.patch permissionMode=full, chat.send
  -> OpenClaw agent loop -> before_tool_call hook in pockpock-permissions.ts
       reads the mode for the session -> allow, or requireApproval
  <- plugin.approval.requested -> SSE "approval" -> approval card
  -> POST /api/openclaw/approvals {approval_id, decision} -> helper stdin -> plugin.approval.resolve
  <- chat delta/final events -> SSE token / replace / tool / done
```

| Module | Responsibility |
| --- | --- |
| `backend/projects/openclaw_bridge/bridge.py` | Configuration, input validation, permission state file, helper process lifecycle, single active turn, approval relay, status probe and cache |
| `backend/projects/openclaw_bridge/api.py` | `/api/openclaw/status`, `/chat`, and `/approvals` routes; SSE framing; heartbeat; abort on disconnect |
| `backend/projects/openclaw_bridge/gateway_turn.mjs` | Node helper that speaks the OpenClaw gateway WebSocket protocol for one turn or one status check |
| `backend/projects/openclaw_bridge/plugin/pockpock-permissions.ts` | OpenClaw plugin that enforces the three modes on every tool call and exposes `pockpock.permissions.status` |
| `backend/projects/openclaw_bridge/install_plugin.py` | Copies the plugin into `~/.openclaw/policies/`, enables it, and reloads or restarts the gateway |
| `backend/projects/openclaw_bridge/test_bridge.py`, `plugin/test_policy.mjs` | Unit tests (no OpenClaw needed) |
| `backend/scripts/frog_ai_server.py` | Builds the bridge from environment configuration, mounts the router with the same-PC check, adds rate limits |
| `desktop/src/components/ChatPane.tsx`, `desktop/src/lib/engines.ts`, `desktop/src/components/MessageView.tsx` | Mode and permission pickers, status, send path, activity steps, approval cards |

OpenClaw's own session permission mode is set to `full` for PockPock sessions, and the plugin applies the PockPock mode instead. OpenClaw's built-in approval modes were not used because, on native Windows, they refuse any command that does not start with a resolvable program file, which rules out PowerShell cmdlets such as `Remove-Item` even when wrapped in `powershell -Command`.

## API contract

All routes accept requests only from a local browser on this PC (`require_local_agent_request`). Other callers receive `403`.

### `GET /api/openclaw/status[?refresh=1]`

Rate limit: 60 per minute. Cached for 15 seconds unless `refresh=1`.

```json
{
  "enabled": true, "available": true, "ready": true, "plugin": true,
  "agent": "main", "model": "qwen3.5:9b", "models": ["qwen3.5:9b", "qwen3.5:27b"], "modes": ["ask", "auto", "full"],
  "detail": "Ready"
}
```

`available` is false when the integration is disabled, Node.js is missing, or the helper script is missing. `ready` means the gateway answered. `plugin` means the permission plugin answered `pockpock.permissions.status`.

### `POST /api/openclaw/chat`

Rate limit: 12 per minute. Body:

```json
{"session_id": "pockpock-<1-70 chars [A-Za-z0-9_-]>", "message": "<1-16,000 chars>", "permission_mode": "ask | auto | full", "model": "<optional: one of status.models>"}
```

Validation failures return a JSON error before any stream opens: `400` (`invalid_session`, `empty_message`, `invalid_message`, `invalid_mode`), `413` (`message_too_long`), `409` (`busy`), `503` (`unavailable`), `500` (`permission_state`). Otherwise the response is `text/event-stream`:

| Event | Fields |
| --- | --- |
| `decision` | `model` (`OpenClaw`, then `OpenClaw · <model>`), `category: "openclaw"`, `source` |
| `status` | Heartbeat every 10 seconds; the UI ignores it |
| `token` | `content`: a piece of streamed reply text |
| `replace` | `content`: replaces the reply text so far (sent after tool calls and with the final text) |
| `tool` | `phase` (`start`/`end`), `id`, `name`, `title`, `status` (`running`/`completed`/`failed`/`blocked`), `error` |
| `approval` | `id`, `title`, `description`, `severity`, `tool_name` |
| `approval_resolved` | `id`, `decision` |
| `approval_error` | `id`, `message` (the gateway rejected a decision) |
| `done` | `duration_ms` |
| `error` | `code` (`plugin_missing`, `timeout`, `turn_failed`, `gateway_closed`, `aborted`, `bridge_failed`), `message` |

Only one OpenClaw turn runs at a time across the gateway.

### `POST /api/openclaw/approvals`

Rate limit: 120 per minute. Body: `{"approval_id": "<id from the approval event>", "decision": "allow-once | deny"}`. Returns `{"ok": true}`, `400` for an invalid id or decision, or `404` when that approval is not waiting in the active turn.

## Configuration

Set these for the gateway process before `backend/scripts/pockpock.py start`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `POCKPOCK_OPENCLAW_ENABLED` | `1` | `0`/`false`/`off` hides the integration |
| `POCKPOCK_OPENCLAW_AGENT` | `main` | OpenClaw agent id |
| `POCKPOCK_OPENCLAW_TIMEOUT_SECONDS` | `1800` | Per-turn limit, clamped to 30–3600; the run is aborted when it expires |
| `POCKPOCK_OPENCLAW_NODE` | `node` | Node.js executable used for the helper |
| `OPENCLAW_STATE_DIR` | `~/.openclaw` | OpenClaw state directory, if you moved it |

An invalid agent name disables the integration at startup and logs a warning.

## Persistence

- `~/.openclaw/pockpock/permissions.json`: the mode for up to 300 most recent PockPock sessions. Written by PockPock before each turn, read by the plugin.
- `~/.openclaw/policies/pockpock-permissions.ts`: the installed copy of the plugin.
- OpenClaw keeps its own session transcripts, memory, and workspace under `~/.openclaw/`. Clearing PockPock chats does not delete them; use `openclaw sessions` to manage them.
- The desktop app saves conversation text and activity steps in its chat file (`%APPDATA%\PockPock Agent\sessions.json`), as for other modes. The selected permission mode is saved in its settings (`clawPermission`).

## Security and privacy

- **No sandbox.** This mode exists to work on the real machine. The permission mode is the only gate, and Full access removes it.
- **Enforcement is inside OpenClaw.** The plugin runs in the gateway process before each tool call, so approval does not depend on the browser or PockPock staying connected. If the plugin is not loaded, PockPock refuses Ask first and Auto-approve safe turns instead of running them unprotected.
- **Fail closed.** Unknown tools, unrecognized commands, a missing or unreadable mode record, an unanswered approval, and a dropped connection all result in asking or denying, never in running.
- **No injection path.** The message, session id, and mode reach the helper as one JSON line on stdin. Nothing from the user is placed on a command line. Session ids must match `pockpock-…` so a request cannot target a session the plugin does not govern.
- **Same-PC only.** The routes reuse the gateway's agent-task locality check, so requests from other machines or origins cannot start turns or answer approvals. The OpenClaw gateway itself listens only on loopback with a token, which the helper reads from the local OpenClaw config and sends only to `127.0.0.1`.
- **No telemetry.** Messages, replies, commands, and approvals are not written to router telemetry, run tables, or PockPock logs. Unexpected bridge errors log a stack trace without request content.
- **Limits of the approval card.** You approve what the card shows: the command line, file path, or URL. It does not show a file's new contents. An agent with write access could also edit PockPock's or OpenClaw's own configuration, including the permission record, but in Ask first and Auto-approve safe that edit itself requires your approval.

## Failure states

| Symptom | Cause and fix |
| --- | --- |
| OpenClaw button disabled | Node.js not found, or `POCKPOCK_OPENCLAW_ENABLED=0` |
| `OpenClaw offline` | The gateway is not running. Run `openclaw gateway start`, then recheck |
| Ask first and Auto-approve safe are disabled, or `plugin_missing` | The permission plugin is not loaded. Run `install_plugin.py`, or `openclaw gateway restart` |
| `busy` | Another OpenClaw turn is still running. Wait or press Stop |
| `timeout` | The turn exceeded `POCKPOCK_OPENCLAW_TIMEOUT_SECONDS` and was aborted |
| A tool line shows **Denied** | You denied it, or the approval timed out after 10 minutes |
| `Context overflow` in a reply | The model's `contextTokens` is too small for the prompt plus tool output. Set it to `65536` as described under Prerequisites, then start a new conversation |
| The agent says it ran a command but no tool line appears | The local model answered without calling the tool. Ask it again, more directly |
| A program opens an 'Open with' dialog instead of starting | The gateway was restarted from Git Bash and inherited its PATH. Run `openclaw gateway restart` from PowerShell |
| The agent says it cannot browse or play media | The browser instructions are missing from `~/.openclaw/workspace/AGENTS.md`, or reasoning is off. See 'What the agent can operate' |
| `openclaw plugins reload` fails with `EPERM … symlink` | Windows blocks the in-place reload without symlink permission. Use `openclaw gateway restart` (the installer does this for you) |

## Verification

- Bridge unit tests: from `backend/`, run `..\.venv\Scripts\python.exe -m unittest projects.openclaw_bridge.test_bridge` (17 tests).
- Plugin policy tests: from the repository root, run `node backend/projects/openclaw_bridge/plugin/test_policy.mjs` (60 commands classified, plus mode behavior).
- Live: `GET /api/openclaw/status?refresh=1` returns `ready: true` and `plugin: true`.
- UI, Ask first: ask it to run `hostname`; an approval card appears; **Allow once** runs it and the reply contains the PC name. Ask it to write a file and choose **Deny**; the tool line shows **Denied** and the file does not exist.
- UI, Auto-approve safe: ask it to list a folder (runs without a card), then to delete something (a card appears).
- UI, Full access: the same delete runs with no card.
- Stop while a card is showing: the card disappears, the action does not run, and the next message is not rejected as busy.
