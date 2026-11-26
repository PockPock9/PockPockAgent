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
| **Full auto** (`full-auto`) | Everything, as Full access, and the run keeps going on its own | Nothing |

**Full auto** (since 0.2.10) is Full access for the permission plugin (the bridge records the session as `full`), plus three changes for unattended work: the turn may run up to 4 hours (`FULL_AUTO_TIMEOUT_SECONDS`, or `POCKPOCK_OPENCLAW_TIMEOUT_SECONDS` if longer) instead of 30 minutes; it is stopped as stalled only after 30 quiet minutes (`FULL_AUTO_STALL_SECONDS`) instead of 8; and `gateway_turn.mjs` adds a line to the message telling the agent not to stop to ask questions or for confirmation, to choose sensible defaults, and to list its assumptions at the end. It is marked **Risky** like Full access. Plan-and-Sequence subtasks are not changed by it.

Details that matter:

- **Read-only commands** are decided by a conservative allowlist in the plugin (`Get-ChildItem`, `Get-Content`, `Select-String`, `git status`/`log`/`diff`, `hostname`, `ollama list`, and similar). Every segment of a pipeline must be on the list. Any redirection (`>`), script block (`{}`), sub-expression (`()`, `$()`, backticks), `&`, a new line, `Invoke-Expression`, `Start-Process`, or an unknown program means the command asks instead. A command the list does not recognize is never auto-approved.
- **Tools reached through OpenClaw's tool search are checked under their own name.** `tool_search`, `tool_describe`, and the `dispatch_action` wrapper never ask; the tool that `dispatch_action` runs (for example `browser`) passes through the same hook and is asked about there, so one action produces one card.
- **Web access asks in Auto-approve safe.** An agent that can both read local files and reach the web without asking could be tricked by a web page into sending file contents out, so fetching is not treated as safe.
- **Approvals are per action or per turn.** Each card offers **Allow once**, **Allow for this task** or **Deny**. **Allow for this task** also allows, for the rest of this turn only, the exact same command (exec approvals) or the same tool (plugin approvals); those later requests are answered automatically and shown as a step "Allowed for this task: …". There is no permanent "always allow"; choose Full access for unattended work. A request that is not answered within 10 minutes is denied.
- **After web or MCP content, every action is asked on its own** (since 0.2.10, Ask first and Auto-approve safe). Text from a web page, a search result, the browser or an MCP server can contain instructions written by someone else (prompt injection). An agent that can read private files, read such content and send data out is exposed to it (the "lethal trifecta"). So once a turn has started a tool that brings in outside content (`readsUntrustedContent` in `turn_helpers.mjs`: `web_fetch`, `web_search`, `fetch`, `browser`, `http_request`, and MCP tools, whose names start with `mcp` or contain `__`), the helper stops applying **Allow for this task** grants automatically, and each later approval card carries `untrusted: true`: it shows "This task has read web or MCP content since it started. Text there can contain instructions from someone else. If you did not ask for this action, deny it." and offers only **Allow once** and **Deny**. Full access and Full auto never ask, so this does not apply to them.
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

`~/.openclaw/workspace/AGENTS.md` holds standing instructions the agent reads every turn. PockPock manages one block in it, between `<!-- pockpock-guidance:start … -->` and `<!-- pockpock-guidance:end -->`, written from `backend/projects/openclaw_bridge/workspace-guidance.md` by `desktop/electron/openclaw-guidance.cjs`. The block is refreshed at every app start and by Setup, so improved guidance reaches existing installs; the rest of the file (OpenClaw's own sections and anything the user adds) is never changed, and the first, unmarked version of the block is removed once. The guidance was written from real failures with `qwen3.5:9b` and covers:

- finishing the task instead of ending a turn by announcing the next step;
- reading a tool error and correcting the arguments (up to two retries) before changing approach, and only calling tools that exist;
- Windows PowerShell 5.1 syntax for `exec` (no `&&` or `||`, which made commands fail);
- the `browser` tool's real actions and `act` kinds (the model invented `get_state`), `ref` instead of `targetId`, and keeping snapshots rare because they fill the model's context;
- preferring `exec` over `computer`, and not guessing documentation URLs for `web_fetch`.

**Browser.** By default OpenClaw starts its own managed profile of Chrome or Edge. **Settings → OpenClaw browser** can switch it to another installed Chromium browser, such as Brave for its ad blocking: the app sets `browser.executablePath` (or unsets it for the default) and stops OpenClaw's running browser so the next browser action starts the chosen one. Only browsers found in their standard install locations (`desktop/electron/browsers.cjs`) can be chosen.

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
5. Choose where it works in the permission picker's **Task folder** section (the same setting PockPock Agent uses). **Work in *folder*** (the open folder, chosen with **Open folder**): OpenClaw works in it: commands run there and files given without a full path are read and saved there. With no open folder, or **Use OpenClaw's workspace**, it works in its own workspace, `~/.openclaw/workspace`. The Inspector's **Workspace** row shows which. The folder is set on the OpenClaw session before every turn, so changing it mid-task applies to the next message and keeps the conversation. OpenClaw's own files (`AGENTS.md`, `SOUL.md` and the rest) stay in its workspace. This sets where OpenClaw starts, not a boundary: like any OpenClaw run it can still reach other paths unless the permission mode stops it.
6. Send a message. The reply streams as it is written. Each tool call appears as an activity line above the reply: running, completed, failed, denied, or stopped.
7. When an action needs approval, an **Approval required · OpenClaw** card appears with the action and its target (the command line, file path, or URL). Choose **Allow once** or **Deny**. The agent waits, then continues with the result.
8. **Stop** cancels the request, denies anything still waiting, and aborts the agent run in OpenClaw.

Skills and MCP servers can be added to this engine by pasting a link; see [Skills and MCP servers](agent-extensions.md#skills-and-mcp-servers). MCP servers added in PockPock run in [Local MCP](local-mcp.md); OpenClaw's configuration holds only each server's local address on it and the hub token. Tools from a connected MCP server ask for approval in Ask first and Auto-approve safe, on a card titled `Use MCP tool: <server> › <tool>`.

### Choosing the model

With the OpenClaw engine selected, the model picker lists **Default** (OpenClaw's configured model) and the other tool-capable Ollama models in OpenClaw's config. The choice is saved in the app's settings (`clawModel`) and sent with each message; PockPock sets it on the conversation's OpenClaw session before the turn. Choosing **Default** resets the session to OpenClaw's default. A name that is not in OpenClaw's list is refused.

**The list follows Ollama** (`desktop/electron/openclaw-models.cjs`, since 2026-11-22). OpenClaw writes its Ollama model list once, when it is set up, so a model pulled later (for example `qwen3.6:35b-a3b`) never appeared in the picker and removed models stayed in it. The app now compares the list with Ollama's installed models when OpenClaw comes up and then at most once a minute, and calls `openclaw config set models.providers.ollama.models` only when the installed models changed. A new model's entry comes from Ollama's `/api/show`: tools, thinking (with the thinking levels), image input, and the context length, with `contextTokens` set to 64K or the model's maximum if smaller. Existing entries keep their settings; entries for uninstalled models are removed (with `--replace`, which OpenClaw requires to drop entries), except the default model's. Models without tool support are listed but, as before, not shown in the picker. Tests: `openclaw-models.test.cjs`.

**Uncensored model** (since 0.2.10). Under **Uncensored · refusals removed**, the menu offers **Download Qwen 3.5 9B uncensored (6.6 GB)**: `huihui_ai/qwen3.5-abliterated:9b`, a community build of Qwen 3.5 9B with its refusal behaviour removed ("abliterated"), with tool support, the same size as `qwen3.5:9b`. PockPock itself adds no content filter in any mode; refusals come from the model, so this model does what it is asked, including what the normal model declines, and the user is responsible for its use. Nothing is downloaded until the item is pressed. The download runs in the main process (`desktop/electron/model-pull.cjs`, IPC `models:pullUncensored`, progress on `models:pull-progress`), which accepts only that model name; progress shows in the menu item. When it finishes, the OpenClaw model list is synced (`syncOllamaToOpenClaw(true)`), OpenClaw's status is refreshed and the model is chosen for OpenClaw. Afterwards it is listed as **Qwen 3.5 9B uncensored** in the same section. If Ollama is not running, the item says so. It is a normal Ollama model: remove it with `ollama rm huihui_ai/qwen3.5-abliterated:9b`. Tests: `model-pull.test.cjs`.

Cloud models chosen on the **Cloud models** page are listed below the local ones, under **Cloud · sends data to the provider**. They belong to the `pockpock-cloud` provider that PockPock writes into OpenClaw's configuration; its address is the PockPock gateway's local endpoint and its key is a local token, so no cloud API key is stored by OpenClaw. A chosen cloud model is set on the session as `pockpock-cloud/<provider>/<model>`. See [Cloud models](cloud-models.md).

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

## Tool retrieval: skills and MCP servers per turn

OpenClaw puts every usable skill (name, description, location) and every MCP server's tools into its prompt on every turn; its whole prompt is about 21,000 tokens, which a model that does not fit the graphics card reads at a few hundred tokens a second whenever it is not cached (Ollama's log showed 21,089 tokens at 469 tokens/s, about 45 s, with `qwen3.6:35b-a3b` on a 12 GB card). PockPock cannot change OpenClaw's built-in tools (commands, files, browser, computer control) per turn: OpenClaw's `chat.send` and `agent` requests take no tool list. It can change skills and MCP servers per session, through `sessions.patch {toolOverrides: {skills: {<key>: false}, mcpServers: {<name>: false}}}`.

Before each turn (`backend/projects/openclaw_bridge/tool_selection.py`):

1. The catalog: the usable, switched-on skills (added from links and built in) and MCP servers, from the same list as the Skills and MCP servers pages; read again after 5 minutes. PockPock's own connector server (`pockpock-connectors`) is never hidden.
2. Skills are ranked against the message with BM25 over each skill's name and description (common words such as "the" and "and" are ignored), plus embeddings when an Ollama embedding model is installed (`nomic-embed-text-v2-moe`, the same as PockPock Agent's tool retrieval). Up to 6 are offered: those that share a word with the message, then those whose embedding is clearly closer to the message than the average (0.08 above the mean similarity).
3. Skills and servers offered in the conversation's last 3 turns stay offered, so a follow-up keeps them.
4. Every other skill or server is hidden for this session. Only hiding is possible: the overlay carries `false` entries only (`sanitizeToolOverrides` in `turn_helpers.mjs` drops anything else), so a skill or server the user switched off is never switched on. The overlay goes into the `sessions.patch` that already sets the permission and model before `chat.send`; when nothing is hidden it is `null`, which clears an earlier overlay.

Not filtered: fewer than 8 skills, or a single MCP server (little to save). On any failure (OpenClaw not reachable for the list, an embedding error) the turn is sent with no overlay, so OpenClaw offers everything as before. Subtask turns (Plan-and-Sequence) are not filtered. `POCKPOCK_OPENCLAW_TOOL_RETRIEVAL=0` turns it off.

The task shows a step such as "Offered OpenClaw 4 of 22 skills that fit this request" (the `tool_selection` event).

**What it saves.** On this PC, the 22 usable skills take about 1,100 tokens of the roughly 21,000; offering 6 saves about 800 tokens (about 4%) per uncached turn. The saving grows with MCP servers: each tool definition is a few hundred tokens, so a server with dozens of tools adds thousands. Most of OpenClaw's prompt (its built-in tools and instructions) is unchanged; OpenClaw's global tool profile (`tools.profile`, set to `full` by Setup) is the only control over that part.

## Subtask mode (Plan-and-Sequence P4)

OpenClaw mode is demoted to tool provider under the Plan-and-Sequence design (`~/workspace/pockpock-test/wiki/Plan-and-Sequence.md`): instead of planning, it executes one subtask at a time, handed to it by the sequenced runner with a small prompt and pinned tools. This is what makes OpenClaw usable with small local models — the ~21K-token system prompt that made `qwen3.5:2b` turns never complete is replaced by a step message of well under ~1,500 tokens by construction.

The sequenced runner (separate work, not the `/api/openclaw/chat` route — `bridge.py` does not send a subtask yet) passes the subtask in the helper's start message on stdin:

```json
{"type": "start", "sessionId": "pockpock-<id>", "message": "<ignored in subtask mode>", "mode": "ask", "model": "<optional>", "agent": "main", "timeoutSeconds": 1800,
 "subtask": {"id": "step-2", "goal": "Read the two invoice messages and list their dates and amounts.",
             "tools_allowed": ["gmail_search", "read_message"], "budget_seconds": 120,
             "capsule_text": "Invoice message IDs: abc123, def456.", "model": "qwen3.5:9b"}}
```

| Field | Rule |
| --- | --- |
| `id` | Non-empty string (≤128 chars); echoed back as `subtaskId` so the parent can correlate steps |
| `goal` | Non-empty string, ≤500 chars — one sentence, what this step achieves and nothing else |
| `tools_allowed` | 1–3 unique non-empty tool names |
| `budget_seconds` | Optional, 30–900; replaces `timeoutSeconds` as the abort timer for this step |
| `capsule_text` | Optional state from earlier steps (pointers and short summaries, never full history); truncated to ~1,200 chars with a `[truncated]` marker |
| `model` | Optional; when given it replaces `start.model` and is still checked against the models OpenClaw knows, so an unknown name is refused with `unknown_model` |

An invalid subtask fails before connecting to the gateway: `{"type": "error", "code": "invalid_subtask", "message": "<clear reason>"}`.

The helper builds a small focused message for `chat.send` instead of the caller's full message:

```text
You are executing ONE subtask of a larger plan. Do only this subtask.

Goal: <goal>

Use only these tools: <tool1, tool2>.

State from earlier steps: <capsule text, when provided>

End with a single line "DONE: <evidence>" on success or "FAILED: <reason>" on failure.
```

It contains no long system prompt and no conversation history. The `started` and `final` events carry `subtaskId` alongside the usual fields; all other events are unchanged, and the non-subtask path behaves exactly as before.

**Honest limitation — the pinned tools are not hard-enforced here.** OpenClaw itself does not expose a tool allow-list, so the bridge cannot remove unlisted tools from the agent. The pin is enforced by the prompt above and by the PockPock permission plugin (Ask first / Auto-approve safe still ask for anything outside the safe set), not by the bridge. Harness-level enforcement — only making the pinned tools available to the call — lives in the Python sequenced runner, which is separate work. Treat a step that calls an unlisted tool as executor tool drift (see the Plan-and-Sequence failure-modes table): the verifier between steps, not this bridge, is what catches it.

## Modules and data flow

```text
PockPock Agent desktop app (OpenClaw mode)
  -> POST /api/openclaw/chat {session_id, message, permission_mode, model?}   (pockpock_server.py, same-PC check)
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
| `backend/projects/openclaw_bridge/gateway_turn.mjs` | Node helper that speaks the OpenClaw gateway WebSocket protocol for one turn or one status check; in subtask mode it validates the subtask, builds the small step message, and applies its budget as the turn timeout |
| `backend/projects/openclaw_bridge/plugin/pockpock-permissions.ts` | OpenClaw plugin that enforces the three modes on every tool call and exposes `pockpock.permissions.status` |
| `backend/projects/openclaw_bridge/install_plugin.py` | Copies the plugin into `~/.openclaw/policies/`, enables it, and reloads or restarts the gateway |
| `backend/projects/openclaw_bridge/test_bridge.py`, `plugin/test_policy.mjs` | Unit tests (no OpenClaw needed) |
| `backend/scripts/pockpock_server.py` | Builds the bridge from environment configuration, mounts the router with the same-PC check, adds rate limits |
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
{"session_id": "pockpock-<1-70 chars [A-Za-z0-9_-]>", "message": "<1-16,000 chars>", "permission_mode": "ask | auto | full", "model": "<optional: one of status.models>", "workspace_path": "<optional: an existing absolute folder>"}
```

`workspace_path` becomes the session's working folder: the helper (`gateway_turn.mjs`) calls the gateway's `sessions.create` with `{key, cwd}` before `sessions.patch` and `chat.send`. On an existing session this keeps the transcript and replaces the folder. Without `workspace_path` the folder is reset to `agents.defaults.workspace` from `openclaw.json` (default `~/.openclaw/workspace`); a failed reset does not stop the turn. Folders outside OpenClaw's configured workspaces need the `operator.admin` scope, which the helper's connection has.

Validation failures return a JSON error before any stream opens: `400` (`invalid_session`, `empty_message`, `invalid_message`, `invalid_mode`, `invalid_workspace`: the folder is not a full path or no longer exists), `413` (`message_too_long`), `409` (`busy`), `503` (`unavailable`), `500` (`permission_state`). Otherwise the response is `text/event-stream`:

| Event | Fields |
| --- | --- |
| `decision` | `model` (`OpenClaw`, then `OpenClaw · <model>`), `category: "openclaw"`, `source` |
| `status` | Heartbeat every 10 seconds; the UI ignores it |
| `token` | `content`: a piece of streamed reply text |
| `replace` | `content`: replaces the reply text so far (sent after tool calls and with the final text) |
| `tool` | `phase` (`start`/`end`), `id`, `name`, `title`, `status` (`running`/`completed`/`failed`/`blocked`), `error` |
| `approval` | `id`, `title`, `description`, `severity`, `tool_name`, `untrusted` (true when the turn read web or MCP content before this request) |
| `approval_resolved` | `id`, `decision` |
| `approval_error` | `id`, `message` (the gateway rejected a decision) |
| `tool_selection` | Sent after `decision` when skills or MCP servers were hidden for this turn: `skills_offered`, `skills_total`, `servers_offered`, `servers_total`, `tokens_saved` (estimate), `method` (`keyword` or `hybrid`) |
| `done` | `duration_ms` |
| `error` | `code` (`plugin_missing`, `timeout`, `stalled`, `turn_failed`, `gateway_closed`, `aborted`, `bridge_failed`, `workspace_failed`: the gateway refused the chosen folder), `message` |

Only one OpenClaw turn runs at a time across the gateway.

### `POST /api/openclaw/approvals`

Rate limit: 120 per minute. Body: `{"approval_id": "<id from the approval event>", "decision": "allow-once | allow-task | deny"}`. `allow-task` allows this request and, for the rest of the turn, later requests with the same key (`turn_helpers.mjs` `grantKey`: `exec:<command>` or `plugin:<tool>`); the turn resolves them with `allow-once` and emits `approval_auto`. Returns `{"ok": true}`, `400` for an invalid id or decision, or `404` when that approval is not waiting in the active turn.

## Configuration

Set these for the gateway process before `backend/scripts/pockpock.py start`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `POCKPOCK_OPENCLAW_ENABLED` | `1` | `0`/`false`/`off` hides the integration |
| `POCKPOCK_OPENCLAW_AGENT` | `main` | OpenClaw agent id |
| `POCKPOCK_OPENCLAW_TIMEOUT_SECONDS` | `1800` | Per-turn limit, clamped to 30–3600; the run is aborted when it expires |
| `POCKPOCK_OPENCLAW_NODE` | `node` | Node.js executable used for the helper |
| `POCKPOCK_OPENCLAW_TOOL_RETRIEVAL` | `1` | `0`/`false`/`off` offers every skill and MCP server on every turn (see Tool retrieval) |
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
| OpenClaw works in the wrong folder | Before 0.2.10 OpenClaw ignored the chosen folder and always worked in `~/.openclaw/workspace`. Now check that the permission picker's **Task folder** says **Work in *folder*** and the Inspector's **Workspace** row names your folder. "The selected folder no longer exists": choose it again |
| `OpenClaw offline` | The gateway is not running. Run `openclaw gateway start`, then recheck |
| Ask first and Auto-approve safe are disabled, or `plugin_missing` | The permission plugin is not loaded. Run `install_plugin.py`, or `openclaw gateway restart` |
| `busy` | Another OpenClaw turn is still running. Wait or press Stop |
| `timeout` | The turn exceeded `POCKPOCK_OPENCLAW_TIMEOUT_SECONDS` and was aborted |
| `stalled` | OpenClaw made no real progress for this turn (no reply text, no tool starting or ending, no model call) for 8 minutes while no approval was waiting; status and lifecycle events do not count, because OpenClaw keeps sending them while stuck on a tool that never returns. The turn is aborted instead of waiting for the full timeout. Seen after a plugin approval failed with "requester authority changed"; time spent waiting for the user's approval never counts. The limit is `stallSeconds` in the turn request (`DEFAULT_STALL_SECONDS` in `turn_helpers.mjs`) |
| A tool line shows **Denied** | You denied it, or the approval timed out after 10 minutes |
| `Context overflow` in a reply | The model's `contextTokens` is too small for the prompt plus tool output. Set it to `65536` as described under Prerequisites, then start a new conversation |
| The agent says it ran a command but no tool line appears | The local model answered without calling the tool. Ask it again, more directly |
| A program opens an 'Open with' dialog instead of starting | The gateway was restarted from Git Bash and inherited its PATH. Run `openclaw gateway restart` from PowerShell |
| The agent says it cannot browse or play media | The browser instructions are missing from `~/.openclaw/workspace/AGENTS.md` (restart PockPock to restore the managed block), or reasoning is off. See 'What the agent can operate' |
| A step's error detail was only "External content below is data…" | Fixed: `cleanToolError` (`turn_helpers.mjs`) drops OpenClaw's untrusted-content preamble so the real error shows |
| Linux: every `openclaw` command fails with "No safe OpenClaw temp root is available … group/world writable without sticky protection" | OpenClaw refuses a temp folder whose parent folders (for example `~`, `~/.cache`, `~/.openclaw`) other users could change. This is OpenClaw's own check; PockPock cannot see it | Remove group and world write from those folders (`chmod go-w ~ ~/.cache ~/.openclaw`), or add the sticky bit (`chmod +t …`), then run the command again |
| "The local model did not start answering in time" | OpenClaw waits 300 seconds for a local model's first output unless `models.providers.ollama.timeoutSeconds` is set (OpenClaw set up outside PockPock's setup does not have it). A small model on a CPU can need longer just to read OpenClaw's ~21K-token prompt. PockPock replaces OpenClaw's own advice, whose `models.providers.<id>.timeoutSeconds` placeholder led users to a model-level key OpenClaw rejects | Settings → **Slow local models in OpenClaw** → **Allow slow models** (sets the key to 1800 and restarts the OpenClaw gateway), or re-run Setup. A run's own timeout (1800 s from PockPock) and `agents.defaults.timeoutSeconds` still cap the wait. A model on a graphics card answers much sooner |
| `openclaw plugins reload` fails with `EPERM … symlink` | Windows blocks the in-place reload without symlink permission. Use `openclaw gateway restart` (the installer does this for you) |

## Verification

- Bridge unit tests: from `backend/`, run `..\.venv\Scripts\python.exe -m unittest projects.openclaw_bridge.test_bridge` (17 tests).
- Plugin policy tests: from the repository root, run `node backend/projects/openclaw_bridge/plugin/test_policy.mjs` (60 commands classified, plus mode behavior).
- Turn helpers (stall watchdog, error cleanup, subtask validation/message/timeout): `node --test backend/projects/openclaw_bridge/turn_helpers.test.mjs`. Guidance block merge: `npm test` in `desktop/`. Both run in CI.
- Live: `GET /api/openclaw/status?refresh=1` returns `ready: true` and `plugin: true`.
- UI, Ask first: ask it to run `hostname`; an approval card appears; **Allow once** runs it and the reply contains the PC name. Ask it to write a file and choose **Deny**; the tool line shows **Denied** and the file does not exist.
- UI, Auto-approve safe: ask it to list a folder (runs without a card), then to delete something (a card appears).
- UI, Full access: the same delete runs with no card.
- Stop while a card is showing: the card disappears, the action does not run, and the next message is not rejected as busy.
