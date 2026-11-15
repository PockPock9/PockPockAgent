# PockPock Agent desktop app

PockPock Agent is the PockPock interface: a Windows desktop app (Electron) laid out like a code-editor agent, with chats on the left, the conversation in the middle, the open folder's files on the right, and a terminal at the bottom. It installs and runs every PockPock service itself and talks to the local PockPock gateway, so every engine, approval and permission is enforced in one place.

## What it does

| Area | Behavior |
|---|---|
| Chats | Create (**Ctrl+N**), search, reopen and delete chats. Saved in the app's data folder; the newest 200 are kept. |
| Modes | **Chat** (direct answer, no tools), **PockPock Agent** (plan, review, then run built-in tools), **OpenClaw** (agent on this PC with skills and MCP servers), **NemoClaw** (OpenClaw in a WSL sandbox). Chosen in the composer's mode picker. |
| Plan review | PockPock Agent shows its plan, success checks, deliverables, reviewer notes and task folder. **Approve and run**, **Edit plan**, or **Decline**. Nothing runs before approval. |
| Approvals | OpenClaw tool calls (Ask first / Auto-approve safe) and PockPock Agent file or browser actions show a card with **Allow once** / **Deny** and the exact command, path, URL or diff. |
| Permissions | PockPock Agent: Default, Auto-review, Full access, plus **Work in the open folder** or **Use a new temporary folder**. OpenClaw: Ask first, Auto-approve safe, Full access. Full access is shown in amber. |
| Models | Chat and PockPock Agent: Smart route or any switched-on local model. OpenClaw: its default or any model in its config. A model loads only when a message uses it. |
| Agent results | A collapsible list of steps; research sources (with **Save** and **Check for changes**); changed files; produced files; and a button to open the task folder. |
| Attachments | Upload documents or images, drag them onto the chat, or attach a text file from the Files panel. OpenClaw and NemoClaw accept text and documents only. |
| Files | Browse the open folder, attach files to the next message, open files or show folders in Explorer. |
| Terminal | PowerShell (or PowerShell 7 when installed) in the open folder. **Ctrl+J**. |
| Browser recipes | Saved, versioned browser workflows: editor with allowed sites, inputs, steps and stop conditions; version history; switch on/off; run with per-step approval and screenshots. |
| Activity | Request totals, per-model call counts, success rate and average time, and recent routing events. No prompt text. |
| Skills / MCP servers | Add from a link with a preview and approval, switch on or off, remove. See [agent extensions](agent-extensions.md). |
| Models / Memory / Research | Switch local models on or off; review and delete learned preferences; allow or block agent access to named public websites. |
| Services | Every service with its state, **Start all** / **Stop all**, start/stop/restart each one, its log, and startup options. |
| Setup | Installs or repairs the backend, Ollama and models, OpenClaw (with a skills choice) and NemoClaw. Opens automatically on first launch. |
| Status bar | Backend, Ollama, Smart Router, OpenClaw and NemoClaw state, and which models are loaded in memory. Click it to open Services. |

## Installing

`PockPock-Agent-Setup-<version>.exe` is a per-user installer (no administrator rights). It installs the app under `%LOCALAPPDATA%\Programs\pockpock-agent`, bundles the backend source in its `resources\backend` folder, creates Desktop and Start-menu shortcuts, and opens the app. The installer is not code-signed, so SmartScreen warns on first run.

On first launch the app opens **Setup**. Each component can be ticked or unticked except the backend:

| Component | Steps |
|---|---|
| PockPock backend | Find Python 3.12 or install it (winget, else python.org installer, per-user); create `%LOCALAPPDATA%\PockPock\runtime\venv`; install the backend packages; install Playwright Chromium; start the services |
| Ollama and models | Install Ollama (winget, else `OllamaSetup.exe /VERYSILENT`); set `OLLAMA_CONTEXT_LENGTH=32768` for the user if unset; start Ollama; download `qwen3.5:9b` and `qwen2.5:1.5b` with progress |
| OpenClaw engine | Install Node.js LTS if missing; `npm install -g openclaw`; non-interactive onboarding against Ollama on port 18810 with a login item; set the default model `qwen3.5:9b` with a 64K window, `thinkingDefault low`, longer model and compaction timeouts, the full tool profile and desktop control; switch each listed skill on or off as chosen; add the browser and PC guidance to the OpenClaw workspace; install the PockPock permission plugin; restart the gateway |
| NemoClaw engine | Install WSL with Ubuntu 24.04 (administrator prompt; may need a restart); let the user create the Ubuntu account in a terminal window; install Docker Desktop (administrator prompt) and start it; install NemoClaw and onboard a `pockpock` sandbox against Ollama with `qwen3.5:9b` and a 32K context |

The skills list comes from `desktop/electron/openclaw-skills.json`, the OpenClaw skills that work on Windows (19 for OpenClaw 2026.11.3). Unticked skills are installed but switched off and can be switched on later on the Skills page.

Setup skips anything already installed. If it stops (failure, cancel, a needed restart, or the Ubuntu account step), the plan is saved in `setup.json` and the next launch opens Setup with **Continue**. **Settings → Run setup** opens it any time to repair or add components.

## Running from source

Requirements: Python 3.12 (`py -3.12 backend\scripts\pockpock.py setup` creates the repository `.venv`), Node.js 24+, and `npm install` inside `desktop/`.

```powershell
cd desktop
npm install
npm run build
npm run app            # or the "PockPock Agent" shortcut from scripts\create_shortcut.ps1
npm run dev            # Vite on port 5180 with hot reload, and the app against it
npm run dist           # build the installer into desktop\release
```

`npm run app` and `npm run dev` clear `ELECTRON_RUN_AS_NODE`, which VS Code sets in its terminals and which would make Electron run as plain Node.

## Services

On start the app checks every service and, unless **Start services when the app opens** is off, starts the missing ones in order: Ollama, then the planner, validator, run store and browser automation together, then the gateway, OpenClaw, and NemoClaw (if **Include NemoClaw** is on). Services that are already running are adopted, not restarted.

| Service | Started with | Stopped with | Healthy when |
|---|---|---|---|
| Ollama | `ollama serve` | ending the process and the Ollama tray app | `GET :11434/api/version` |
| Planner, Validator, Run store, Browser automation | `python -m uvicorn app:app` in the service folder | ending the process tree | `GET /health` returns its name |
| PockPock gateway | `python -u backend/scripts/frog_ai_server.py` | ending the process tree | `GET :8766/api/health` |
| OpenClaw gateway | `node openclaw.mjs gateway start` | `node openclaw.mjs gateway stop` | port 18810 open |
| NemoClaw sandbox | Docker Desktop, then `nemoclaw pockpock start` in WSL | `nemoclaw pockpock stop` | port 18789 open |

OpenClaw is run through Node with its JavaScript entry point, so it does not depend on PowerShell's script execution policy or shell quoting. Services get a PATH without Git for Windows' Unix tools, which would otherwise shadow Windows programs (for example `notepad`) for OpenClaw.

When the app closes it stops only the services it started (OpenClaw and NemoClaw with their stop commands, the rest by ending their processes), within 20 seconds. **Stop services when the app closes** turns this off. **Open PockPock Agent when I sign in** registers the app as a Windows login item.

Logs: the Python services and Ollama (when started by the app) write to `%LOCALAPPDATA%\FrogAI\logs`; an Ollama started elsewhere logs to `%LOCALAPPDATA%\Ollama\server.log`; OpenClaw to `%LOCALAPPDATA%\Temp\openclaw\openclaw-<date>.log`. The Services page shows the last 200 lines of each.

## How it works

```text
Electron main process (desktop/electron/)
  main.cjs        window, IPC handlers, single instance, login item, quit behaviour
  services.cjs    service definitions, start/stop/health, logs, Docker Desktop for NemoClaw
  setup.cjs       first-run and repair setup, resumable
  paths.cjs       where Python, the backend, data and tools are (development vs installed)
  server.cjs      127.0.0.1:8790 (or a free port): serves desktop/dist and forwards /api/* to the gateway
  workspace.cjs   folder listing and file reads, confined to the open folder
  terminal.cjs    pseudo-terminal sessions (@lydell/node-pty)
  preload.cjs     window.pockpock bridge (named calls only)

Renderer (desktop/src/, React + Vite)
  App.tsx                      layout, turn orchestration, shortcuts, first-run routing
  lib/engines.ts               Chat, PockPock Agent, OpenClaw and NemoClaw turns; approvals and plan decisions
  lib/api.ts, lib/status.ts    API helpers, server-sent-event reader, live status (backend, services, OpenClaw, NemoClaw)
  lib/store.ts                 chats and settings persistence
  components/                  title bar, sidebar, status bar, chat and composer, messages and cards, files, terminal
  pages/                       Skills, MCP servers, Models, Memory (Pages.tsx); Research; Browser recipes; Activity; Services; Setup; Settings
```

The window loads the interface from the app's own loopback server, which also forwards `/api` to the gateway. The page therefore has a single `http://127.0.0.1` origin: the gateway's same-PC check accepts it and no cross-origin rules are needed. Streaming responses are piped through unbuffered, and closing a request (Stop, or closing the window) aborts the gateway request too. The forwarder drops `X-Forwarded-*` and `Forwarded` headers.

### Turns

| Mode | Calls |
|---|---|
| Chat | `POST /api/chat` with the chat history (documents inlined, images as base64), streamed |
| PockPock Agent | `POST /api/agents/plan` → plan card → `POST /api/agents/plans/{id}/decision` → `POST /api/agents/run` (streamed). Approvals: `POST /api/runs/{run}/approvals/{id}`. Stop: `POST /api/runs/{run}/cancel`. Saving a source: `POST /api/agents/{task}/research-collection/sources` |
| OpenClaw | `POST /api/openclaw/chat` with `session_id = pockpock-<chat id>`, permission mode and model, streamed. Approvals: `POST /api/openclaw/approvals` |
| NemoClaw | `POST /api/nemoclaw/chat` with `session_id = pockpock-<chat id>`, streamed |
| Browser recipe run | `POST /api/browser-recipes/{id}/run` (streamed), approvals as for PockPock Agent |

One turn runs at a time across all chats; the send button is disabled while another chat is working. OpenClaw and NemoClaw keep their own memory per chat; switching mode inside a chat does not copy earlier turns into the other engine.

### Status

The renderer polls `/api/state` every 4 seconds and OpenClaw status and the skill and MCP counts every 30 seconds; the main process checks every service every 4 seconds and pushes changes. NemoClaw is asked only whether it is installed (`?probe=0`) unless NemoClaw is the selected mode, because the full sandbox check loads a model.

## Data

| What | Where |
|---|---|
| Chats | `%APPDATA%\PockPock Agent\sessions.json` (newest 200; image bytes are not saved; turns cut off by closing the app are marked stopped and their pending approvals expired) |
| Settings (open folder, mode, permissions, models, panel layout, startup options) | `%APPDATA%\PockPock Agent\settings.json` |
| Setup progress | `%APPDATA%\PockPock Agent\setup.json` |
| Installed Python environment | `%LOCALAPPDATA%\PockPock\runtime\venv` (installed app only; a source checkout uses `.venv`) |
| Service token and logs | `%LOCALAPPDATA%\FrogAI` |
| Agent results, skills, MCP servers, memory | Owned by the backend, OpenClaw and NemoClaw as documented on their pages |

Uninstalling keeps all of this.

## Security

- The renderer runs with context isolation, the sandbox on, and no Node.js access. It reaches the main process only through the named calls in `preload.cjs`, and every handler rejects calls from any page other than the app's own origin.
- File listing, reading and opening are limited to the folder the user opened; paths that resolve outside it are refused, and symbolic links are not listed. Reads are limited to 256 KB of text.
- `openPath` (used for task folders and produced files outside the open folder) opens only paths that exist; web links open in the default browser, and the window never navigates away from the app.
- A Content-Security-Policy allows scripts and connections only from the app's origin.
- The terminal and every service run with the user's own permissions. Setup asks Windows for administrator rights only for WSL and Docker Desktop.
- Setup downloads only from fixed addresses (winget, python.org, ollama.com, npm, nvidia.com for the NemoClaw installer) and shows every command in its log.
- Permission modes, approvals and the same-PC rule are enforced by the gateway and the OpenClaw plugin, not by this app, so the app cannot widen them.

## Failure states

| What you see | Cause | What to do |
|---|---|---|
| Setup opens on every start | The backend environment is missing or a previous setup did not finish | Press **Install** or **Continue**; read **Show details** if a step fails |
| Setup: "Python 3.12 could not be installed" | No winget and the python.org download failed | Install Python 3.12 from python.org, then run setup again |
| Setup stops with "Restart Windows" | WSL was just installed | Restart; setup continues on the next launch |
| Setup: "A terminal opened to finish setting up Ubuntu" | Ubuntu needs an account | Create it in that window, close it, press **Continue setup** |
| Status bar: a service stopped, or "Problem" on Services | It failed to start or exited | Open its log on **Services**, fix the cause, press **Start** |
| "The Smart Router is paused" / "Ollama is not running" | Router off or Ollama stopped | **Settings**: switch the router on; **Services**: start Ollama |
| "OpenClaw is not ready" | OpenClaw gateway stopped | **Services** → OpenClaw gateway → **Start** |
| NemoClaw does not start | Docker Desktop not running or not set up for WSL | Start Docker Desktop, then **Services** → NemoClaw → **Start**; check its log |
| Send button greyed out with "Another chat is still working" | One turn at a time | Wait or press Stop in that chat |
| Terminal: "The terminal component could not be loaded" | `@lydell/node-pty` is missing | Reinstall the app, or `npm install` in `desktop/` |
| The window does not open when started from a VS Code terminal | VS Code sets `ELECTRON_RUN_AS_NODE` | Use `npm run app`, `npm run dev`, or the shortcut |

## Verification

```powershell
cd desktop
npm run typecheck
npm run build
npm run dist      # optional: builds the installer
```

Checked on 2026-11-15 by driving the real app with Playwright's Electron driver and a throwaway data folder (`POCKPOCK_DESKTOP_USER_DATA`):

- From source: status bar shows the gateway ready; the Services page listed all eight services; the validator was stopped, started again and its log read; Activity, Browser recipes (list and editor), Research and Setup loaded; Setup with the backend and Ollama selected recognised both as installed and finished; no console errors.
- Earlier the same day: the Files panel listed and attached a file, the terminal echoed a command, all modes appeared in the mode picker, all Customize pages loaded, a skill switch turned off and on, and an 820 px window had no horizontal overflow.
- Packaged build (`release\win-unpacked`) as a first-time user: Setup opened automatically, the bundled backend was found under `resources\backend`, the 19 skills were listed, no console errors.

Not verified: a full install on a clean PC (Python, Ollama, Node.js, OpenClaw, WSL and Docker Desktop all missing), NemoClaw setup end to end, and Chat/PockPock Agent/OpenClaw turns through the rebuilt app on this PC (skipped because an OpenClaw task was running on the GPU at the time).
