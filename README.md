# PockPock AI — Local Router

An autonomous, multi-model local AI hub with intelligent query routing, document Q&A (RAG), visual reasoning, and agentic workflows — running locally with GPU acceleration on your PC.

---

## 🖥️ System Hardware Profile

* **GPU:** NVIDIA GeForce RTX 4070 SUPER (12 GB GDDR6X VRAM) — CUDA accelerated
* **CPU:** AMD Ryzen 7 7800X3D (8 Cores / 16 Threads)
* **System RAM:** 32 GB DDR5
* **Storage:** 850+ GB free NVMe SSD
* **OS:** Windows 11 (x64)
* **Python:** 3.12

---

## 🧠 Ultra-Smart Cognitive Router (v2.0)

When you send a prompt, the **Ultra-Smart Router** applies a two-stage cognitive pipeline:
1. **Stage 1 (< 1ms Fast-Path Heuristic):** Instantly captures code blocks, syntax patterns, mathematical notation, LaTeX symbols, and multimodal image uploads.
2. **Stage 2 (Multi-Turn Semantic Intelligence):** If ambiguous, `qwen2.5:1.5b` analyzes the recent conversation context and classifies intent, task complexity (1–10), and routing confidence.
3. **Dynamic Hyperparameter Morphing:** Automatically adjusts runtime generation parameters (`temperature` 0.15–0.85, `top_p` 0.85–0.98) specifically tailored to the active task.
4. **Cognitive Persona Injection:** Injects specialized system directives (e.g. Principal Software Engineer, Formal Deduction Engine, Autonomous Agent).
5. **Circuit-Breaker Failover:** If a primary model encounters an interruption, it gracefully falls back without dropping your session.
6. **Telemetry HUD:** Renders an expandable status matrix showing model choice, confidence percentage, complexity score, and rationale.
7. **Optional Signal Room dashboard:** A separate, local-only view of routing decisions, model call counts, live runtime status, and a switch for pinning future requests to one model.

| Role | Model | Size | Purpose / Trigger |
| :--- | :--- | :--- | :--- |
| 🧭 **Router** | `qwen2.5:1.5b` | 1.0 GB | Ultra-fast classifier (runs invisibly on every prompt) |
| ⚡ **Quick** | `qwen2.5:7b` | 4.7 GB | Simple Q&A, definitions, translations, conversational queries |
| 💻 **Coder** | `qwen2.5-coder:7b` | 4.7 GB | Code generation, debugging, refactoring, API integration |
| 🏗️ **Heavy Coder / DevOps** | `qwen2.5-coder:14b` | 9.0 GB | Enterprise CI/CD pipelines, Docker, Kubernetes, Terraform, complex architecture |
| 🌐 **Generalist** | `qwen2.5:14b` | 9.0 GB | Deep writing, structured documents, high-precision instruction following |
| 🧮 **Reasoner** | `deepseek-r1:14b` | 9.0 GB | Complex logic, mathematics, multi-step chain-of-thought proofs |
| 👁️ **Vision** | `llava:7b` | 4.7 GB | Visual analysis, OCR, screenshots, diagrams, photos |
| 🔍 **Embeddings** | `nomic-embed-text` | 0.28 GB | Document vectors & semantic search for Open WebUI RAG |
| ⚡ **Autocomplete** | `qwen2.5-coder:1.5b` | 1.0 GB | Sub-second inline code completion for IDEs (VS Code / Cursor) |
| 🔓 **Uncensored** | `dolphin-mistral:7b` | 4.1 GB | Creative fiction, unconstrained roleplay, unfiltered tasks |
| 🤖 **Agentic** | `mistral-nemo:12b` | 7.1 GB | Structured function calling, API tools, autonomous multi-step execution |
| 🦾 **Light Agent** | `llama3.2:3b` | 2.0 GB | Fast agentic decision maker for tight loops |
| 📄 **Parser** | `reader-lm:1.5b` | 1.0 GB | Web page HTML to clean Markdown extraction |

---

## 📂 Project Directory Structure

```text
C:\workspace\Frog ai\
├── AGENTS.md                 # Required implementation and documentation rules for AI contributors
├── docs/
│   ├── ARCHITECTURE.md       # Current module boundaries and staged scale roadmap
│   ├── FEATURES.md           # Feature documentation index
│   └── features/             # Detailed behavior, contracts, permissions, and verification
├── README.md                 # User guide and architecture documentation
├── .vscode/
│   └── mcp.json              # Optional Chrome DevTools MCP launch configuration
├── frontend/                 # Everything that runs in the browser
│   ├── app/                  # PockPock AI dashboard and chat app (Vite + React)
│   └── site/                 # Standalone marketing site and demo (Next.js)
└── backend/                  # Everything that runs on this PC as a local service
    ├── projects/             # Separate local workflow service projects
    │   ├── agent_core/       # In-process agent execution and orchestration
    │   ├── agent_tools/      # Tool catalog, implementations, and focused tests
    │   ├── planner/          # Agent planning, critic review, and model selection (:8771)
    │   ├── validator/        # Workspace validation (:8772)
    │   ├── run_store/        # Durable agent runs and event history (:8773)
    │   ├── browser_automation/ # Isolated browser runtime (:8774)
    │   ├── nemoclaw_bridge/  # Conversations bridge to a NemoClaw sandbox in WSL
    │   ├── openclaw_bridge/  # Conversations bridge to OpenClaw on this PC, with permission modes
    │   ├── agent_extensions/ # Skills and MCP servers installed into OpenClaw from a pasted link
    │   ├── internal_auth.py  # Loopback service-to-service token check
    │   └── README.md         # Service project index and boundaries
    └── scripts/
        ├── smart_router_pipe.py  # Open WebUI Pipe function for automatic query dispatch
        ├── start_services.ps1    # Automated script to start Ollama & Open WebUI
        ├── frog_ai_server.py     # Independent loopback-only PockPock AI API and chat router
        ├── agent_run_store.py    # Durable agent run/event persistence and task journal client
        ├── pockpock.py           # Cross-platform backend setup and service supervisor
        ├── pockpock_paths.py     # Platform-specific per-user data directories
        ├── setup_frog_ai.ps1     # Isolated PockPock AI API dependency setup
        ├── start_frog_ai.ps1     # Start the PockPock AI API
        ├── start_frog_ai_dashboard.ps1 # Start PockPock AI API and dashboard together
        ├── configure_frog_ai_startup.ps1 # Enable or remove Windows sign-in startup
        ├── requirements-frog-ai.txt
        ├── observability_dashboard.py  # Standalone local telemetry sidecar
        ├── observability_dashboard.html # Signal Room dashboard interface
        ├── start_dashboard.ps1   # Optional dashboard launcher
        └── pull_batch2.ps1       # Background download script for auxiliary models
```

---

## 🚦 Quick Start & Operations

### 1. Start the Ollama Engine
```powershell
powershell -ExecutionPolicy Bypass -File .\backend\scripts\start_services.ps1
```
Or run directly:
```powershell
ollama serve
```
* API runs at: `http://localhost:11434`

### 2. Launch Open WebUI Dashboard
```powershell
& "C:\Users\kchan\AppData\Local\Programs\Python\Python312\python.exe" -m open_webui serve --port 3000
```
* Open in browser: `http://localhost:3000`

### PockPock AI dashboard and chat

PockPock AI is an optional local application accessed in a browser; it does not replace or modify Open WebUI. Install Python 3.12, then set up and start the local API and workflow services:

```powershell
py -3.12 backend\scripts\pockpock.py setup
py -3.12 backend\scripts\pockpock.py start
```

On macOS or Linux, use:

```sh
python3.12 backend/scripts/pockpock.py setup
python3.12 backend/scripts/pockpock.py start
```

`setup` creates the repository `.venv`, installs the backend dependencies, and downloads Playwright Chromium. `start` supervises the local API and workflow services in the foreground; press Ctrl+C to stop the processes it started. On Linux, install any system libraries required by Playwright Chromium using your normal package-management process. Ollama and its models remain separate optional installs.

Once the backend is running, use the browser UI:

```sh
npm --prefix frontend/app ci
npm --prefix frontend/app run dev
```

The browser development UI opens at [http://127.0.0.1:5173](http://127.0.0.1:5173). The API binds to `127.0.0.1:8766`, uses Ollama at `127.0.0.1:11434`, and shares the existing Signal Room telemetry database. From the Live Room or Model Room, use **Connect / Start Ollama** to connect to the existing Ollama service or start its local server, then load the installed-model inventory. **Refresh Inventory** re-reads all installed model metadata. Models stay on disk until routing needs them; PockPock AI does not load every model's weights into memory at once. Chat conversations remain in this browser's local storage; prompts and responses are not written to telemetry.

### Chat and Agent Tools

The planned development sequence for browser automation, internet research, agent planning, and multi-agent delegation is in the [Agent capability roadmap](docs/ROADMAP.md). The [implementation task tracker](docs/TASKS.md) gives other agents the next eligible task, dependencies, acceptance checks, and rules for updating progress after each task.

Open **Conversations** for the unified Agent Chat workspace. Ordinary questions stay in chat; supported work requests receive a structured plan that passes a bounded critic review before agent tools run. The review may request one revision, and the UI shows its summary/findings with the plan. You still inspect, edit, approve, or decline the plan before any tools run. The transcript shows model choice, progress, tool inputs and results, and created files with their local paths and download links. Run events are stored in the local `agent_runs` and `agent_run_events` tables so activity can replay after a reload; chat-only history remains in browser local storage.

For practical examples of how people can delegate work to an AI agent—including copy-ready requests and what a complete result should look like—see [Real-world agent use cases](docs/features/agent-use-cases.md). To exercise supported workflows repeatedly with observable pass criteria and a fix-and-rerun process, use the [Agent scenario regression pack](docs/features/agent-scenario-regressions.md). These are unrun test cases until individually verified; a task still depends on the agent having the relevant files, integrations, permissions, and tools.

Agent tool calls are checked against registered input/output schemas, permission requirements, timeouts, and payload limits. Tool failures return a visible error code and message. Run events use a versioned format while existing unversioned run history remains readable; see [Agent tool and run event contracts](docs/features/agent-tool-contracts.md).

The Agent Chat Stop control records a cancellation request and interrupts active model/tool work. Runs that exceed the 15-minute total deadline are marked timed out; a browser disconnect without a stop request marks the run interrupted. These final states survive reload and reject late updates.

Agent Tools can research public text pages whose hostnames you include in the request (a bare hostname such as `example.org` is accepted; HTTPS is tried by default), inspect and interact with an explicitly named public page through the isolated browser, analyze documents you attach, and create text/CSV/JSON/HTML or Word/Excel/PowerPoint deliverables. Enable **Named public websites** in **Research settings** before the agent can fetch pages; the setting is local and the page explains that these requests leave this PC. General Internet search and provider API credentials are not supported yet. Multi-page site research follows same-host text/HTML links only and is capped at five pages per task; results include canonical source IDs and bounded evidence excerpts, which the conversation timeline displays with links and timestamps. Research answers require source IDs and exact quotes from retrieved excerpts; conflicting claims show passages from distinct sources, and unsupported claims or evidence limitations are labeled. Invalid citations are retried and are not presented as verified if they still fail validation. This checks citation provenance, not semantic entailment. Research requests for Markdown, HTML, Word, Excel, or PowerPoint reports are exported from the validated claims and retrieved source records, with clickable citations, timestamps, bounded excerpts, conflicts, and limitations; the file appears in task outputs. You can explicitly save a research source to its task/workspace collection, add notes, and refresh it manually. Each changed snapshot stores up to 200 KB of extracted text, and all versions remain until you delete the collection; there is no background refresh. Retrieved page instructions remain untrusted data and cannot grant tools or change the approved permission level. Browser activity, visible page text, and screenshot evidence appear in the chat timeline and task output. Browser actions require the latest observed page state; clicks are limited to same-host links, typing/selecting require Full Access, and passwords, form submission, and button clicks are blocked. Neither research nor browser tools access login state or the normal browser profile. It chooses an enabled Ollama model that supports tool calls and shows its model selection and tool activity as the task runs.

Code tasks run the workspace-scoped `validate_project` tool before the agent can report completion. It checks Python and JavaScript syntax when the local runtimes are available and verifies local asset references in HTML. With **Full Access**, it also runs root `npm run build` and `npm run test` scripts declared by the project, with a 120-second timeout per script. These package scripts execute project code; the validator does not run them in other permission modes. A failed validation is sent back to the agent for repair and another validation attempt. Static checks do not simulate browser interactions; projects should provide useful build/test scripts for behavior-level validation. See [Workspace validation](docs/features/workspace-validation.md).

When a task explicitly requests a supported file format, the agent verifies that a matching artifact was created before reporting success. Research reports in Markdown, HTML, Word, Excel, or PowerPoint are generated from the validated research answer and source records rather than accepted from a model-authored file. If the model skips another deliverable, it gets one focused retry; a missing file is reported as incomplete rather than successful.

Agent runs are accepted only from a local browser on this PC, not from the Tailscale dashboard. Tools are restricted to user-attached file content, explicitly named public hosts (HTTP/HTTPS on standard ports; private/reserved IPs and cross-host redirects are blocked), and files in the selected task workspace. Workspace tools are denied in Default mode; Auto-review requires approval for each proposed patch, while Full Access applies workspace changes without another prompt. Without a selected workspace, the task receives a new folder under `%USERPROFILE%\PockPock AI Tasks\<task-id>`. Project tools enforce workspace-relative paths and exclude secrets. There is no general shell/PowerShell tool, arbitrary filesystem access, website login, form submission, bulk media download, or deployment tool. The validator's npm build/test calls are limited to project-declared scripts and are available only in Full Access mode. Requests to locate ways to bulk-download copyrighted streaming videos are declined. Attachments and task prompts are not written to router telemetry. See [Agent runs and workspaces](docs/features/agent-runs.md).

The local backend runs the planner, workspace validator, agent run/event store, and isolated browser runtime as separate loopback services, coordinated by the API gateway. The cross-platform setup installs Playwright and its local Chromium build; `backend/scripts/pockpock.py start` supervises the required services, and the dashboard stays on its existing URL. The browser runtime supports run-scoped public-page observation and state-bound basic interactions with same-host request checks, and Agent Chat renders browser activity and screenshot evidence in the replayable timeline. Default and Auto-review pause for approval on each action except fixed scrolling; high-impact-looking links pause even in Full Access. The Browser recipes page supports local recipe creation, editing, version review, disable/delete, and explicit runs with transient inputs, per-step approval, checkpoint evidence, and replay after reload. Service ports, health checks, authentication, request flow, and current interaction boundary are documented in [Local workflow services](docs/features/local-workflow-services.md), [the browser runtime](docs/features/browser-runtime.md), and [Architecture](docs/ARCHITECTURE.md). These components currently share the repository and virtual environment, and the agent execution loop remains in the gateway.

#### Agent engines

**Conversations** has two response modes, **Chat** and **Agent**. In Agent mode, the engine chip next to the switch chooses what runs the task: **PockPock** (the built-in planner and tools), **OpenClaw** (an agent on this PC with no sandbox), or **NemoClaw** (OpenClaw inside a sandbox in WSL). An engine that is not installed is disabled and says why. Switching to Chat and back returns to the last engine, and each engine keeps its own memory of a thread.

#### Skills and MCP servers

To give the OpenClaw engine a new skill or tool, paste a link in Agent mode: a GitHub link to a skill (a folder with a `SKILL.md` file) or to an MCP server, or the address of a remote MCP server. You can also paste it on the **Skills** or **MCP servers** page in the sidebar. PockPock reads the link without running anything and shows an **Approval required** card with what it found: the skills and whether they include scripts, or the exact command or address of the MCP server. Nothing is installed until you choose **Install** or **Connect**; an MCP server is saved only if a test connection lists its tools. The **Skills** and **MCP servers** pages list what is installed, with a switch to turn each one off without removing it and a button to remove what you added; the Skills page also lists the skills built into OpenClaw. Skills and MCP servers are third-party content that PockPock does not review, so add only ones you trust. They are used by the OpenClaw engine only. Details, limits, and troubleshooting are in [Agent engines, skills, and MCP servers](docs/features/agent-extensions.md).

#### OpenClaw engine

If OpenClaw is installed on Windows with a local gateway, Agent mode offers the **OpenClaw** engine. Unlike NemoClaw, this agent runs directly on your PC with no sandbox, so it can run commands and change real files. A permission chip in the composer controls what it may do without asking:

- **Ask first** (the default): every action waits for you to choose **Allow once** or **Deny** in the chat.
- **Auto-approve safe**: reading files and read-only commands run on their own; changes, other commands, and web access ask first.
- **Full access**: nothing asks. Use it only for tasks you are watching.

Setup needs Node.js 24+, `npm install -g openclaw@latest`, a one-time `openclaw onboard`, and the PockPock permission plugin (`.venv\Scripts\python.exe backend\projects\openclaw_bridge\install_plugin.py`). If the chip reads **OpenClaw offline**, run `openclaw gateway start`. Exact commands, the full rules for each mode, and troubleshooting are in [OpenClaw agent mode](docs/features/openclaw-agent.md).

#### NemoClaw engine

If NVIDIA NemoClaw is installed in WSL with an onboarded sandbox (default name `pockpock`) and Docker Desktop is running, Agent mode offers the **NemoClaw** engine. Messages go to the sandboxed OpenClaw agent, which keeps its own memory per conversation and can run commands and edit files only inside its sandbox; there is no PockPock plan approval in this mode, and it cannot see your Windows files or PockPock task workspaces. Text and document attachments are supported; images are not. A status chip shows whether the sandbox is ready; select it to recheck. NemoClaw needs a larger Ollama context than the default: set the Windows user environment variable `OLLAMA_CONTEXT_LENGTH=32768` and restart Ollama, or replies are cut off. Messages are not written to router telemetry. Optional settings (`POCKPOCK_NEMOCLAW_DISTRO`, `POCKPOCK_NEMOCLAW_SANDBOX`, `POCKPOCK_NEMOCLAW_ENABLED`, and others), the API contract, and troubleshooting are in [NemoClaw agent mode](docs/features/nemoclaw-agent.md).

Image generation uses an already-running local ComfyUI (`127.0.0.1:8188`) or Stable Diffusion WebUI API (`127.0.0.1:7860`). PockPock AI does not install an image engine or send prompts/images to a cloud service. If neither local engine is running, image generation is reported as unavailable.

### PockPock Agent desktop app

`desktop/` contains **PockPock Agent**, a Windows desktop app with its own interface: chats on the left, the conversation in the middle, the open folder's files on the right and a terminal at the bottom. It offers the same four modes as Conversations (Chat, PockPock Agent, OpenClaw, NemoClaw) with plan review, approval cards and permission pickers, plus Skills, MCP servers, Models, Memory and Settings pages. It starts the PockPock backend if it is not running.

```powershell
cd desktop
npm install
npm run build
npm run app
powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1   # optional Desktop/Start-menu shortcuts
```

Desktop chats are stored in `%APPDATA%\PockPock Agent` and are separate from the web dashboard's chats. Browser recipes, research collections and the overview stay in the web dashboard. Details and troubleshooting: [PockPock Agent desktop app](docs/features/desktop-app.md).

### Start PockPock AI automatically when you sign in

After installing the PockPock AI API and frontend dependencies once, add PockPock AI to the current Windows user's Startup folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\backend\scripts\configure_frog_ai_startup.ps1
```

At sign-in, PockPock AI starts its local API and dashboard and opens `http://127.0.0.1:5173` in your browser. This does not start, stop, or reconfigure Ollama, Open WebUI, or their Smart Router. To remove automatic startup:

```powershell
powershell -ExecutionPolicy Bypass -File .\backend\scripts\configure_frog_ai_startup.ps1 -Remove
```

To start PockPock AI manually without adding a startup entry, run `.\backend\scripts\start_frog_ai_dashboard.ps1`; add `-NoBrowser` to keep the dashboard running without opening a browser tab. Startup logs are written to `%LOCALAPPDATA%\FrogAI\logs`.

### Private remote access

PockPock AI is not published to the public internet. For access from your own remote devices, install and sign in to Tailscale on this PC and those devices, build the production dashboard, and configure Tailscale Serve:

```powershell
cd .\frontend\app
npm run build
cd ..
powershell -ExecutionPolicy Bypass -File .\backend\scripts\configure_frog_ai_remote_access.ps1
```

The script serves the production dashboard and API at `127.0.0.1:8766` through Tailscale Serve's private HTTPS endpoint. It refuses to overwrite an unrelated Serve configuration. Share the printed `https://…ts.net` address only with trusted devices on your tailnet. Do not use `tailscale funnel`, port-forward the service, or expose the Vite development server (`5173`).

Ollama (`11434`) and Signal Room (`8765`) remain loopback-only and are not proxied by the remote endpoint. PockPock AI also rejects oversized API requests and applies per-route request-rate limits. Agent Workbench task starts and downloads are additionally restricted to the local browser; remote task execution is not enabled. These limits reduce accidental or abusive load; private tailnet access is the primary network boundary, not a guarantee against all denial-of-service attacks. Review your Tailscale tailnet access policy and allow only trusted users/devices.

The sidebar control pauses or resumes request dispatch through the PockPock AI application only. It does not stop the API process, Ollama, Open WebUI, or the Smart Router inside Open WebUI. Model enablement only controls PockPock AI routing eligibility; it does not pull or remove Ollama weights or change Open WebUI access. File uploads support image input and extraction from PDF, DOCX, XLSX, PPTX, TXT, Markdown, CSV, JSON, XML, HTML, and LOG files.

### 3. Load the Smart Router in Open WebUI
1. Go to **Workspace** -> **Functions** (or **Pipes**) in Open WebUI.
2. Click **+** to add a new function.
3. Paste the contents of [`backend/scripts/smart_router_pipe.py`](./backend/scripts/smart_router_pipe.py).
4. Save and toggle **Enable**.
5. Select **🧭 Smart Router** from the model dropdown in chat.

### 4. Optional: Open the Signal Room dashboard

The dashboard is an independent sidecar; it does not replace, reconfigure, or start/stop Open WebUI. Start it only when you want the extra view:

```powershell
powershell -ExecutionPolicy Bypass -File .\backend\scripts\start_dashboard.ps1
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The service binds to loopback only and stores telemetry in `%LOCALAPPDATA%\LocalAIObservability\traces.sqlite3`. It records routing decisions and model-call timings/counts, but not prompt or response text. The model selector pins **future** Smart Router requests to an installed Ollama model; reset it to restore automatic routing.

To enable dashboard telemetry in an existing Open WebUI installation, update the Smart Router Pipe with the current `backend/scripts/smart_router_pipe.py`. If the dashboard is stopped or unavailable, the Pipe continues routing normally and telemetry is skipped.

---

## 🔌 Integrating with External Tools

* **OpenAI-Compatible Endpoint:** `http://localhost:11434/v1`
  * Works out-of-the-box with Cursor, VS Code Continue extension, Open Interpreter, LangChain, LlamaIndex, and n8n.
* **Open Interpreter:**
  ```powershell
  pip install open-interpreter
  interpreter --api_base http://localhost:11434/v1 --model mistral-nemo:12b
  ```

### 5. PockPock AI frontend (Vite + React)

The standalone dashboard and chat frontend lives in [`frontend/app/`](./frontend/app/README.md). It connects only to the local PockPock AI API and does not change Open WebUI:

```powershell
cd .\frontend\app
npm install
npm run dev
```

See the web project README for its local preview, production build, and motion-accessibility notes.

### 6. YourBrand marketing site and app demo (Next.js)

An independent marketing-site and dashboard concept is in [`frontend/site/`](./frontend/site/README.md). It does not replace or connect to the local PockPock AI UI. Start it with:

```powershell
cd .\frontend\site
npm install
npm run dev
```

It serves the landing page at `/` and a sample dashboard at `/app`. Dashboard values, testimonials, and example outcomes are illustrative mock content; this demo does not execute or persist workflows.

### UI/UX development toolchain

The project includes Copilot-compatible UI/UX guidance under `.agents/skills/` and `.github/prompts/`. Follow the [UI/UX workflow in `AGENTS.md`](./AGENTS.md#uiux-workflow) before changing the frontend. VS Code reads the project MCP configuration from `.vscode/mcp.json`; `.mcp.json` provides the equivalent project-scoped servers for Claude Code. Both configs include Playwright (configured for the installed Microsoft Edge channel) and Context7; Figma requires a one-time OAuth approval in the MCP client. The existing Chrome DevTools server remains configured in VS Code. This frontend currently uses Tailwind but not shadcn/ui, so no shadcn MCP server is enabled.
