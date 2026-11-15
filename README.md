# PockPock AI

PockPock AI is a local AI workspace for Windows. Its desktop app, **PockPock Agent**, chats with models running on your own PC and runs agents that plan and carry out tasks: reading and writing files, researching public websites, driving a browser, and, with the OpenClaw engine, operating the PC itself. Everything runs locally through [Ollama](https://ollama.com); prompts and replies are not sent to a cloud service or written to telemetry.

---

## Install

1. Download and run **`PockPock-Agent-Setup-<version>.exe`**. It installs for the current user without administrator rights, creates Desktop and Start-menu shortcuts, and opens the app.
2. The app opens on **Setup**. Choose what to install and press **Install**:

| Component | What it adds | Download |
|---|---|---|
| PockPock backend (always) | Python 3.12, the PockPock services, an isolated browser for agent web tasks | about 600 MB |
| Ollama and models | Ollama plus `qwen3.5:9b` (default model) and `qwen2.5:1.5b` (Smart Router classifier) | about 8 GB |
| OpenClaw engine | Node.js (if needed), OpenClaw, the PockPock permission plugin, and a list of OpenClaw skills you can untick | about 400 MB |
| NemoClaw engine | WSL with Ubuntu, Docker Desktop, and a NemoClaw sandbox | about 8 GB |

Setup skips anything already installed, so running it again repairs a broken install. NemoClaw needs administrator approval, may need a Windows restart, and asks you to create an Ubuntu username once; setup resumes where it stopped when you reopen the app.

**Requirements:** Windows 10 or 11 (64-bit), 16 GB RAM (32 GB recommended), an NVIDIA GPU with 8 GB or more of video memory for good speed (CPU-only works but is slow), and 20 GB free disk space (30 GB with NemoClaw). An internet connection is needed during setup only.

---

## Using PockPock Agent

The window has chats on the left, the conversation in the middle, the open folder's files on the right, and a terminal at the bottom.

- **Chats** are on the left. **Ctrl+N** starts one; they are saved on this PC.
- **The composer** has a mode picker:
  - **Chat** answers directly with the best local model.
  - **PockPock Agent** proposes a plan; you **Approve and run**, **Edit plan**, or **Decline**. It then works in a task folder (the open folder, or a new temporary one) and shows each step, changed files, sources it read, and files it produced.
  - **OpenClaw** is an agent that runs directly on this PC: commands, files, the browser, mouse and keyboard. Its permission picker sets what it may do without asking: **Ask first**, **Auto-approve safe**, or **Full access**.
  - **NemoClaw** runs OpenClaw inside a sandbox, so it cannot touch this PC.
- **Approvals** appear as cards in the conversation with **Allow once** and **Deny**.
- **Files** (right) shows the open folder; attach a file to the next message or open it. **Terminal** (**Ctrl+J**) is PowerShell in that folder.
- **Skills and MCP servers**: paste a GitHub link in the composer or on the **Skills** / **MCP servers** page. You see what would be installed and approve it first. Switch any of them off without removing it.
- **Browser recipes** saves web tasks you repeat; each step asks for approval when it runs.
- **Activity** shows which model handled each request and how long it took (no prompt text is stored).
- **Models**, **Memory** and **Research** control which local models are used, learned preferences, and whether agents may read public websites.
- **Services** starts, stops and restarts everything (Ollama, the backend services, OpenClaw, NemoClaw) all at once or one by one, shows their logs, and sets startup options. All services start when the app opens; a model loads into memory only when a message uses it.

Full guide: [PockPock Agent desktop app](docs/features/desktop-app.md).

---

## How it works

PockPock Agent is an Electron app that talks to a local API (the **gateway**, `127.0.0.1:8766`) backed by small services on loopback ports:

| Service | Port | Role |
|---|---|---|
| Gateway | 8766 | Chat, Smart Router, agent runs, approvals, files, skills and MCP |
| Planner | 8771 | Plans agent tasks, critic review, model choice |
| Validator | 8772 | Checks agent workspaces before a task is reported done |
| Run store | 8773 | Saves agent runs and their events |
| Browser automation | 8774 | Isolated Chromium for agent web tasks and browser recipes |
| Ollama | 11434 | Runs the models |
| OpenClaw gateway | 18810 | The OpenClaw engine (optional) |
| NemoClaw sandbox | 18789 | The NemoClaw engine in WSL (optional) |

### Smart Router

Chat and PockPock Agent requests go through the Smart Router, which picks a model for each request from the models switched on in **Models**:

1. A fast heuristic recognises code, math, and images.
2. For anything else, `qwen2.5:1.5b` classifies the intent, complexity (1–10) and confidence using the recent conversation.
3. Generation settings (temperature, top-p) and a role-specific system prompt are set for the task.
4. If the chosen model fails, the router falls back to another one without losing the conversation.

Typical roles on the reference PC (any installed models can be used):

| Role | Model | Used for |
|---|---|---|
| Router | `qwen2.5:1.5b` | Classifies every request |
| General / default | `qwen3.5:9b` | Everyday questions and agent work |
| Accurate, slow | `qwen3.5:27b` | Complex tasks (pick it in the model picker) |
| Coder | `qwen2.5-coder:7b`, `qwen2.5-coder:14b` | Code and DevOps |
| Reasoner | `deepseek-r1:14b` | Math and step-by-step logic |
| Vision | `llava:7b` | Screenshots and images |
| Tool calling | `mistral-nemo:12b`, `llama3.2:3b` | Agent tool loops |

### Agent safety

- Agent requests are accepted only from this PC. The desktop app reaches the gateway through its own loopback origin.
- **PockPock Agent** works only on attached files, public websites named in the task (private and local addresses are blocked), and its task folder. It has no general shell. **Default** permission is read-only; **Auto-review** asks before each file change; **Full access** applies changes inside the task folder without asking and allows the project's own build and test scripts.
- **OpenClaw** has no sandbox; its permission mode is enforced by the PockPock permission plugin inside OpenClaw, and unknown tools always ask. **NemoClaw** is confined to its sandbox.
- Skills and MCP servers are third-party content. PockPock shows the source, commit and exact command before installing, but does not review the code.

Details: [Architecture](docs/ARCHITECTURE.md) and the [feature index](docs/FEATURES.md).

---

## For developers

```text
Frog ai/
├── desktop/            PockPock Agent (Electron + React + Vite) and its installer
│   ├── electron/       main process: services, setup, local server, files, terminal
│   └── src/            the interface
├── backend/
│   ├── scripts/        gateway (frog_ai_server.py), Smart Router, telemetry, pockpock.py, run_tests.py
│   └── projects/       planner, validator, run_store, browser_automation, agent_core, agent_tools,
│                       agent_extensions, openclaw_bridge, nemoclaw_bridge, model_router, local_memory, observability
├── docs/               architecture, roadmap, task tracker, feature pages
├── design-system/      desktop design tokens and rules
└── AGENTS.md           rules for anyone (human or AI) changing this repository
```

Run from source (Windows, Python 3.12 and Node.js 24):

```powershell
py -3.12 backend\scripts\pockpock.py setup   # creates .venv, installs packages and Chromium
cd desktop
npm install
npm run build
npm run app                                    # starts the app; it starts the services
```

`npm run dev` runs the interface with hot reload. Without the desktop app, `py -3.12 backend\scripts\pockpock.py start` runs the backend services in the foreground (Ctrl+C stops them).

Checks:

```powershell
.venv\Scripts\python.exe backend\scripts\run_tests.py   # every backend test suite
cd desktop; npm run typecheck; npm run build
```

Build the installer with `npm run dist` in `desktop/`; it writes `desktop/release/PockPock-Agent-Setup-<version>.exe`. The installer is not code-signed, so Windows SmartScreen warns on first run.

Other tools can use the models directly through Ollama's OpenAI-compatible endpoint, `http://localhost:11434/v1` (Cursor, VS Code Continue, LangChain, n8n and others).

Planned work is in the [roadmap](docs/ROADMAP.md) and the [task tracker](docs/TASKS.md). Read [AGENTS.md](AGENTS.md) before contributing.

---

## Data and privacy

| What | Where |
|---|---|
| Desktop chats and settings | `%APPDATA%\PockPock Agent` |
| Backend data (runs, telemetry without prompts, recipes, memory) and service logs | `%LOCALAPPDATA%\FrogAI` and `%LOCALAPPDATA%\LocalAIObservability` |
| Installed Python environment (installer only) | `%LOCALAPPDATA%\PockPock\runtime` |
| Agent task folders | `%USERPROFILE%\PockPock AI Tasks` |
| Models | `%USERPROFILE%\.ollama` |
| OpenClaw config, skills and MCP servers | `%USERPROFILE%\.openclaw` |

Uninstalling the app keeps this data; delete the folders to remove it.

## Troubleshooting

| Problem | Fix |
|---|---|
| Status bar says a service is stopped | **Services** → **Start**, or **Start all**. The service's log is one click away. |
| "PockPock is not set up yet" | **Settings** → **Run setup**. |
| Chat or PockPock Agent does not answer | Check **Services** (Ollama and the gateway must run) and that the Smart Router is on in **Settings**. |
| OpenClaw is offline | **Services** → OpenClaw gateway → **Start**. Start it from the app or PowerShell, never from Git Bash. |
| A large model is very slow | Expected when it does not fit in video memory; use it for hard tasks and start a new chat for it. |

More: [desktop app](docs/features/desktop-app.md), [OpenClaw](docs/features/openclaw-agent.md), [NemoClaw](docs/features/nemoclaw-agent.md), [skills and MCP](docs/features/agent-extensions.md).
