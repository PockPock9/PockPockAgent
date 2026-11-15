# PockPock Agent desktop app

PockPock Agent is a Windows desktop app (Electron) for working with the PockPock agents. It has its own interface, separate from the web dashboard, laid out like a code-editor agent: chats on the left, the conversation in the middle, the open folder's files on the right, and a terminal at the bottom. It talks to the same local PockPock backend, so every engine, approval and setting behaves as it does in the web app.

## What it does

| Area | Behavior |
|---|---|
| Chats | Create, search, reopen and delete chats. Chats are saved to the app's data folder and survive restarts. |
| Response modes | **Chat** (direct answer, no tools), **PockPock Agent** (plan, review, then run built-in tools), **OpenClaw** (agent on this PC with skills and MCP servers), **NemoClaw** (OpenClaw in a WSL sandbox). Chosen from the mode picker in the composer. |
| Plan review | PockPock Agent shows its plan, success checks, reviewer notes and task folder. **Approve and run**, **Edit plan**, or **Decline**. Nothing runs before approval. |
| Approvals | OpenClaw tool calls (Ask first / Auto-approve safe) and PockPock Agent file or browser actions show an approval card with **Allow once** / **Deny**. |
| Permissions | PockPock Agent: Default, Auto-review, Full access, plus whether to work in the open folder or a new temporary folder. OpenClaw: Ask first, Auto-approve safe, Full access. Full access is shown in amber. |
| Models | Chat and PockPock Agent: Smart route or any switched-on local model. OpenClaw: its default or any model in its config. Models load only when a message uses them. |
| Activity | Each agent turn shows a collapsible list of steps (tools, browser actions, commands), produced files, and a button to open the task folder. |
| Attachments | Upload documents or images, drag them onto the chat, or attach a text file from the Files panel. OpenClaw and NemoClaw accept text and documents only. |
| Skills and MCP | Paste a skill or MCP link into the composer, or use the **Skills** and **MCP servers** pages: preview, approve, switch on or off, remove. |
| Files | Browse the open folder, attach files to the next message, open files or show folders in Explorer. |
| Terminal | PowerShell (or PowerShell 7 when installed) in the open folder. |
| Customize pages | Skills, MCP servers, Models (switch local models on or off), Memory (learned preferences), Settings (backend, Ollama, Smart Router, OpenClaw and NemoClaw checks, link to the web dashboard). |
| Status bar | Backend, Ollama, Smart Router, OpenClaw and NemoClaw state, and which models are loaded in memory. |

Not in the desktop app yet: browser recipes, saved research collections, request history and the overview dashboard. Settings has a button that opens the web dashboard for those.

## Running it

Requirements: the PockPock repository with its `.venv` (see the main README), Node.js 24+, and `npm install` inside `desktop/`.

```powershell
cd desktop
npm install
npm run build
npm run app          # or use the "PockPock Agent" shortcut
```

`powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1` creates **PockPock Agent** shortcuts on the Desktop and in the Start menu. They start `node_modules\electron\dist\electron.exe` with the `desktop` folder, so rebuild (`npm run build`) after changing the interface.

For interface work, `npm run dev` starts Vite on port 5180 with hot reload and opens the app against it.

On start the app checks `http://127.0.0.1:8766/api/state`. If the backend is not running it starts `backend\scripts\pockpock.py start` with the repository's `.venv` and waits up to 90 seconds. A backend the app started is stopped when the app quits; one that was already running is left alone.

Keyboard: **Ctrl+N** new chat, **Ctrl+B** sidebar, **Ctrl+J** (or Ctrl+\`) terminal, **Ctrl+Shift+E** files, **Enter** send, **Shift+Enter** new line, **Esc** closes menus.

Below 1100 px wide the Files panel, and below 860 px the sidebar, open over the content from their title-bar buttons instead of sitting beside it.

## How it works

```text
Electron main process (desktop/electron/)
  main.cjs        window, IPC handlers, single instance, link handling
  server.cjs      127.0.0.1:8790 (or a free port): serves desktop/dist and forwards /api/* to the backend
  backend.cjs     checks the backend, starts pockpock.py if needed, stops it on quit if it started it
  workspace.cjs   folder listing and file reads, confined to the open folder
  terminal.cjs    pseudo-terminal sessions (@lydell/node-pty)
  preload.cjs     window.pockpock bridge (named calls only)

Renderer (desktop/src/, React + Vite)
  App.tsx                     layout, turn orchestration, shortcuts
  lib/engines.ts              Chat, PockPock Agent, OpenClaw and NemoClaw turns; approvals and plan decisions
  lib/api.ts, lib/status.ts   API helpers, server-sent-event reader, live status
  lib/store.ts                chats and settings persistence
  components/                 title bar, sidebar, status bar, chat and composer, messages and cards, files, terminal
  pages/Pages.tsx             Skills, MCP servers, Models, Memory, Settings
```

The window loads the interface from the app's own loopback server, which also forwards `/api` to the backend. The page therefore has a single `http://127.0.0.1` origin: the backend's same-PC check accepts it and no cross-origin rules are needed. Streaming responses are piped through unbuffered, and closing a request (Stop, or closing the window) aborts the backend request too. The forwarder drops `X-Forwarded-*` and `Forwarded` headers.

### Turns

| Mode | Calls |
|---|---|
| Chat | `POST /api/chat` with the chat history (documents inlined, images as base64), streamed |
| PockPock Agent | `POST /api/agents/plan` → plan card → `POST /api/agents/plans/{id}/decision` → `POST /api/agents/run` (streamed). Approvals: `POST /api/runs/{run}/approvals/{id}`. Stop: `POST /api/runs/{run}/cancel` |
| OpenClaw | `POST /api/openclaw/chat` with `session_id = pockpock-<chat id>`, permission mode and model, streamed. Approvals: `POST /api/openclaw/approvals` |
| NemoClaw | `POST /api/nemoclaw/chat` with `session_id = pockpock-<chat id>`, streamed |

One turn runs at a time across all chats; the send button is disabled while another chat is working. OpenClaw and NemoClaw keep their own memory per chat; switching mode inside a chat does not copy earlier turns into the other engine.

### Status

`/api/state` is polled every 4 seconds, OpenClaw status and the skill and MCP counts every 30 seconds. NemoClaw is asked only whether it is installed (`?probe=0`) unless NemoClaw is the selected mode, because the full sandbox check loads a model.

## Data

| What | Where |
|---|---|
| Chats | `%APPDATA%\PockPock Agent\sessions.json` (newest 200; image bytes are not saved; turns cut off by closing the app are marked stopped and their pending approvals expired) |
| Settings (open folder, mode, permissions, models, panel layout) | `%APPDATA%\PockPock Agent\settings.json` |
| Agent results, skills, MCP servers, memory | Unchanged: owned by the backend, OpenClaw and NemoClaw as documented on their pages |

Desktop chats are separate from the web dashboard's chats, which live in that browser's storage.

## Security

- The renderer runs with context isolation, the sandbox on, and no Node.js access. It reaches the main process only through the named calls in `preload.cjs`, and every handler rejects calls from any page other than the app's own origin.
- File listing, reading and opening are limited to the folder the user opened; paths that resolve outside it are refused, and symbolic links are not listed. Reads are limited to 256 KB of text.
- `openPath` (used for task folders and produced files outside the open folder) opens only paths that exist; web links open in the default browser, and the window never navigates away from the app.
- A Content-Security-Policy allows scripts and connections only from the app's origin.
- The terminal runs with the user's own permissions, like any terminal. The Electron variable `ELECTRON_RUN_AS_NODE` is removed from its environment and from the backend's.
- Permission modes, approvals and the same-PC rule are enforced by the backend and the OpenClaw plugin, not by this app, so the desktop app cannot widen them.

## Failure states

| What you see | Cause | What to do |
|---|---|---|
| Status bar: "PockPock was not found next to this app" | The `desktop` folder was moved out of the repository, or `.venv` is missing | Keep `desktop/` inside the repository, or set `POCKPOCK_ROOT` to the repository path |
| Status bar: "The backend did not start" | `pockpock.py start` failed | Run it in a terminal to see the error, then **Settings → Try again** |
| "The Smart Router is paused" / "Ollama is not running" | Router off or Ollama stopped | **Settings**: switch the router on, or **Start** Ollama |
| "OpenClaw is not ready" | OpenClaw gateway stopped | `openclaw gateway start` from PowerShell, then **Settings → Check** |
| "The NemoClaw sandbox is still being checked" | First check after selecting NemoClaw (about a minute after a restart) | Wait, then send again |
| Send button greyed out with "Another chat is still working" | One turn at a time | Wait or press Stop in that chat |
| Files panel: "That path is outside the workspace" | A path left the open folder | Open the folder that contains the file |
| Terminal: "The terminal component could not be loaded" | `@lydell/node-pty` is missing | `npm install` in `desktop/` |
| The window does not open when started from a VS Code terminal | VS Code sets `ELECTRON_RUN_AS_NODE` | Use `npm run app` or the shortcut, which clear it |

## Verification

```powershell
cd desktop
npm run typecheck
npm run build
```

The app was checked end to end by driving the real Electron window with Playwright (`_electron`) using a throwaway data folder (`POCKPOCK_DESKTOP_USER_DATA`): status bar shows the backend ready, the Files panel lists the open folder and attaches a file, the terminal echoes a command, the mode menu lists all four modes, all five Customize pages load, a skill switch turns off and back on, and an 820 px window has no horizontal overflow. No console errors.
