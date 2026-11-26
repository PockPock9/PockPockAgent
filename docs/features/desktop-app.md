# PockPock Agent desktop app

PockPock Agent is the PockPock interface: a desktop app (Electron) for Windows and macOS, laid out like a code-editor agent, with chats on the left, the conversation in the middle, the open folder's files on the right, and a terminal at the bottom. It installs and runs every PockPock service itself and talks to the local PockPock gateway, so every engine, approval and permission is enforced in one place.

## What it does

| Area | Behavior |
|---|---|
| Layout | An icon rail (**Tasks**, **Workshop**, **Activity**; **Services** and **Settings** at the bottom), the task list or the Workshop navigation (252 px), the task or page, and the inspector (320 px, tabs **Context**, **Files**, **Terminal**). The terminal opens under the composer. Below 1100 px the inspector opens over the content; below 860 px the rail and the task list open from the menu button in the title bar. **Ctrl+B** shows or hides the task list, **Ctrl+Shift+E** the inspector, **Ctrl+J** the terminal (⌘ on a Mac). |
| Tasks | Create (**Ctrl+N**, **⌘N** on a Mac), search, reopen and delete tasks (each is one conversation). The list groups them as **Needs you** (the running task is waiting for a plan or approval), **Running**, **Today**, **This week** and **Older**; each row says what its newest turn did, for example "Waiting for you · 4.1 s", "PockPock Agent · Done · 5:32 PM" or "Failed". The rail's Tasks icon shows a dot while a task needs you. Saved in the app's data folder; the newest 200 are kept. |
| Run bar | Above every task: the phases (PockPock Agent: **Understand**, **Plan**, **Act**, **Verify**; Chat: Understand, Write; OpenClaw and NemoClaw: Understand, Act), what is happening now, **Signal** (time since the run last sent anything), the elapsed time, and **Stop**. While PockPock Agent acts, **Step 3 of 5** in front of the status when the agent reported which plan step it is on (hover for the step's text); otherwise nothing, and the task list counts finished steps instead. Working: the mark's bolt pulses and a 2 px bar sweeps under the bar. Waiting for a plan or an approval: a solid accent bar, a still bolt, how long it has waited, and **Review**, which scrolls to the card. Slow (no event for 10 s): a note saying why and **Keep waiting** (hides the note for 30 s), **Use *model*** (stops the run and sends the same request again with the smallest switched-on local model smaller than the one in use, a loaded one first; Chat and PockPock Agent only) and **Stop**. Failed: a red bar, the error, what was kept (the plan, finished steps, saved files), **Retry** (sends the same request again), **Open Services** and **Report**. Finished, stopped and interrupted turns say so with the total time. Status text and elapsed time are always shown; with reduced motion the bar is solid and the bolt still. |
| Inspector | **Context**: engine, model and where it runs (this PC, loaded or not, or the cloud provider), **context used** (the newest model call's prompt tokens out of the loaded context, PockPock Agent only), the permission mode, the workspace, the task folder (known before the run starts: `<tasks folder>\<run id>`) and the files the run read, changed or saved. **Files**: the open folder. **Terminal**: opens the terminal under the composer. Tabs move with the arrow keys. |
| Command palette | **Ctrl+K** (⌘K), or the search box in the title bar: new task, show or hide the inspector or terminal, every page, every theme, and the 30 newest tasks. Arrow keys move, Enter runs, Escape closes and returns focus. |
| Modes | **Chat** (direct answer, no tools), **PockPock Agent** (plan, review, then run built-in tools), **OpenClaw** (agent on this PC with skills and MCP servers), **NemoClaw** (OpenClaw in a sandbox: WSL on Windows, Docker on a Mac). Chosen with the engine switch in the task header (since 0.2.12 the only engine selector; the composer's duplicate picker was removed). |
| Plan review | The plan card: what it delivers, the workspace, the task folder (known before the run starts), the reviewer's notes, **Plan checked** chips from the gateway's pre-check (files found, tools allowed, nothing unclear; a warning says what will go wrong), open questions (since 0.2.13 in a dialog that opens by itself when a plan has questions: one question per page with its suggested answers and a text box, **Back**/**Next**, dots to jump between questions, and one **Submit answers** on the last page; empty answers are left to the agent; closing keeps the answers, and **Answer questions** on the card opens it again; submitting plans the task again once, with all the answers; the replaced plan stays, marked as replaced), the steps and the success checks. **Edit plan** makes both lists editable: change, move up or down, remove, **Add a step** or **Add a check**. **Approve and run** or **Decline**. Nothing runs before approval. |
| Approvals | OpenClaw tool calls (Ask first / Auto-approve safe) and PockPock Agent file or browser actions show a card with the exact command, path, URL or diff and **Allow once**, **Allow for this task** (where the gateway supports it) and **Deny**. Actions allowed for the task are later shown as a step "Allowed for this task: …". |
| Notes while it works | While an approved PockPock Agent run works, the composer says **Add a note while it works** and sends notes to the run; each note shows under the reply as waiting, then **Given to the agent** when the model receives it before its next step. |
| Finished runs | A PockPock Agent task that finished and passed its checks ends with a result card: **Done, and the checks passed**, **Open demo** when the task made a web page (its `index.html` first, then any `.html` file it saved or changed; opens in the default browser) and **Open task folder**. A turn that finished but reported problems (for example OpenClaw actions that failed or were blocked) shows a warning under the reply, "Done with problems" in the task list and "Finished with problems" in the run bar. |
| Step and check status | A step line is green only when it finished: with Plan in steps, the attempt's lines end as the step's check says (failed checks and their retries are red), and a retry no longer marks earlier lines done. The plan card's checks are plain bullets until they run; with Plan in steps each step's check turns green or red when its result arrives (`stepChecks`). **Retry from step** starts at the first step that did not pass, and "finished steps" counts plan steps that passed, not activity lines. |
| Attachments in a chat | A message sent without its own document uses the documents attached to the most recent earlier message of the same chat; they are shown on the new message. Before 0.2.12 a follow-up such as "make the resume look nice" could not see a resume attached earlier. |
| Failed runs | A card under the reply: what stopped it, what is kept, **Retry from step N** (a new task for the remaining steps, planned and approved again) and **Report**. Every reply has **Copy**, **Retry** (send the same request again) and **Report a problem**. |
| Pickers | Above the composer: **This PC**, the folder, the permission (in the warning colour for Full access) and the engine with its state. In the composer: **+** (attach a file, add an image, choose a folder, Skills, MCP servers, report a problem), the engine (with Ready, Checking… or Not installed), the permission for PockPock Agent or OpenClaw, and the model (Smart route, local models with loaded or not and size, cloud models). Menus open with Enter, move with the arrow keys, Home and End, and close with Escape, returning focus to their button. |
| Permissions | PockPock Agent: Default, Auto-review, Full access, plus **Work in the open folder** or **Use a new temporary folder**. OpenClaw: Ask first, Auto-approve safe, Full access, Full auto, plus **Work in the open folder** or **Use OpenClaw's workspace** (where its commands run and relative paths resolve; see [OpenClaw](openclaw-agent.md#user-flow)). Full access is shown in amber. |
| Models | Chat and PockPock Agent: Smart route or any switched-on local model. OpenClaw: its default or any model in its config. Cloud models chosen on the Cloud models page are listed under their own heading in every engine's menu (NemoClaw: its sandbox-wide model). A model loads only when a message uses it. |
| Timing | Live counters (tenths of a second) while a reply is thinking, planning or running a step; each finished step's duration; the planning time on the plan card; and under every reply a breakdown: **Thinking** (or **Planning**), **Waiting for you**, **Writing** (Chat) or **Working**, and **Total**. |
| Plan in steps | PockPock Agent's model menu has a **Planning** section: **One model plans and works** (default) or **Plan in steps with** a connected cloud model or a local model. The **Plan in steps** card shows each step and its check, who plans and who works, and a note when a cloud model receives the request; it is approved as a whole. The run shows Step N of M, each check and retry, approval cards for changes, and ends with a short reply. See [Plan-and-Sequence](plan-and-sequence.md). |
| Agent results | A collapsible list of steps; research sources (with **Save**, then **Check for changes** and a **Watch for changes** switch; a reopened task shows what was saved and watched); changed files; produced files; and a button to open the task folder. |
| Attachments | Upload documents or images, drag them onto the chat, or attach a text file from the Files panel. OpenClaw and NemoClaw accept text and documents only. |
| Files | The inspector's **Files** tab: browse the open folder, attach files to the next message, open files or show folders in Explorer or Finder. |
| Reports | **Report** under a reply saves that exchange and your description, redacted, on this PC; **Maintenance** lists them. See [Problem reports and Maintenance](maintenance.md). |
| Themes | **Settings → Theme**: a grid of PockPock Dark (default), Volt, Storm, Feather (light) and System, each with a colour preview; click one or move with the arrow keys. Also in the command palette. Applied before the first paint. The title bar shows the PockPock mark; in the run bar its bolt pulses while a turn works. See [Themes and the brand mark](themes.md). |
| Terminal | PowerShell (or PowerShell 7 when installed) on Windows; the user's login shell (zsh by default) on a Mac. Opens in the open folder. **Ctrl+J** / **⌘J**. |
| Browser recipes | Saved, versioned browser workflows: the list beside the editor (allowed sites, inputs, steps and stop conditions); version history; switch on/off; run with per-step approval and screenshots. |
| Activity | Request totals, model calls, average time and chat models loaded now; per-model call counts, success rate and average time; recent routing events. No prompt text. |
| Skills | OpenClaw skills as cards, with tabs **All**, **On** and **Needs setup** (counts), search, a switch on each card, and a details drawer (source, what it needs, **Remove** for skills added from a link). **Learned from your tasks** lists skills PockPock Agent wrote after a task and left in the skill inbox (`/api/skills/inbox`): **Check it** runs the skill's own test, **Review and add** promotes it once the check passed, **Reject** drops it; the section is hidden when the inbox is empty. Adding from a link: see [agent extensions](agent-extensions.md). |
| MCP servers | Add from a GitHub link, a server address or a command on this PC (inspected and approved first); each server shows on or off, where it runs and how it was added; switch, disconnect. Servers added in PockPock run in Local MCP and also show their state (running with the number of tools, starts when used, error, Local MCP stopped), **Log** and **Restart**; see [Local MCP](local-mcp.md). |
| Connectors | Connect GitHub, email, Telegram, Slack, Discord or Notion with a key the app checks; the connected apps give the OpenClaw agent tools. **Available** and **Connected** tabs; a connector's details (what the agent can do, connecting, replacing the key, disconnecting) open in a drawer beside the list. See [Connectors](connectors.md). |
| Cloud models | Connect NVIDIA NIM, OpenAI, Claude (Anthropic) or Alibaba Cloud Model Studio; the chosen models join the model menus of every engine and are used only when picked. See [Cloud models](cloud-models.md). |
| Local models | A **Smart route** card (on or paused; local models only), then every model Ollama has: size, calls, success rate and average time (from routing telemetry), **Loaded**, **Idle** or **Switched off**, tags from Ollama's details (parameter size, quantization, Images, Embeddings) and a switch. **Refresh**; with no model installed, the install command and **Open terminal**. Models are never unloaded from this page. |
| Memory / Research | Memory: **Remember preferences** switch, saved preferences with **Remove**, **Forget all**. Research: one switch, **Allow reading public websites** (named public sites only; off makes no network requests). Saved sources stay with each task's sources card. **Watched pages**: every watched source with when it was checked, when it is checked next and a **Changed** badge, with **Check now**, **Mark as seen** and **Stop watching**; a note when checks are paused (research off, or `POCKPOCK_SOURCE_WATCH=0`). |
| Services | Every service with its state, **Start all** / **Stop all**, start/stop/restart each one, its log, and startup options. |
| Setup | Installs every prerequisite and the backend, Ollama and models, OpenClaw (with a skills choice) and NemoClaw, then starts and checks every service. Opens automatically on first launch. A stepper shows where it is: **Welcome**, **Choose**, **Install**, **Check** (the final service checks). |
| Settings | Sections **Theme**, **Smart Router** (switch), **Ollama and services**, **OpenClaw** (check, browser, slow local models), **NemoClaw** (sandbox check), **Updates** (a highlighted **Restart to update** row when a version is ready, automatic download) and **Setup**. |
| Toasts | Bottom right, above the status bar: **PockPock *version* is ready** with **Restart to update** and **Later**; **A watched page changed** (or *N* watched pages changed) with **Open Research** and **Later**, checked every minute while the gateway is ready; and problems that block every task, each with **Open Services**: the gateway stopped or could not start, or Ollama is not running. A toast hides with its close button (or **Later**) until its situation changes, and an error toast goes away by itself once the problem is fixed. |
| Dialogs | The report dialog and the Maintenance Manager setup dialog dim the window, keep focus inside until they close (Tab wraps), close with Escape, and return focus to the button that opened them. |
| Status bar | Gateway, Ollama (with how many chat models are loaded), Smart router, OpenClaw and NemoClaw state, and the names of the loaded models. Click it to open Services. |

## Installing

| | Windows | macOS |
|---|---|---|
| Installer | `PockPock-Agent-Setup-<version>.exe`, per-user (no administrator rights), installs under `%LOCALAPPDATA%\Programs\pockpock-agent`, Desktop and Start-menu shortcuts | `PockPock-Agent-<version>-mac-arm64.dmg` (Apple silicon) or `-mac-x64.dmg` (Intel); drag the app to Applications. macOS 12 or later |
| Signing | Not code-signed: SmartScreen warns on first run | Signed ad hoc (required for Apple silicon) but not notarized: the first launch needs **System Settings → Privacy & Security → Open Anyway** |
| Bundled backend | `resources\backend` | `PockPock Agent.app/Contents/Resources/backend` (Python bytecode writing is off there so the signature stays intact) |
| PockPock's own tools | `%LOCALAPPDATA%\PockPock\runtime` | `~/Library/Application Support/PockPock/runtime` (`venv`, `python` from uv, `node`, `npm-global`, `bin/uv`) |

On first launch the app opens **Setup** on a welcome screen made for people who are not technical: one **Set up PockPock** button, plain-language descriptions of what will be installed, this computer's memory and graphics card, the AI model chosen for it and why, the download size with an estimated time, and the free disk space. The button installs the recommended set: the backend, Ollama with the models, and OpenClaw. NemoClaw is not part of it, because it needs administrator approval, Docker and on Windows a restart and an Ubuntu account. **Customize** opens the full list, where each component except the backend can be ticked or unticked and the model can be chosen; NemoClaw is never ticked automatically. Setup installs every prerequisite itself; nothing has to be installed beforehand.

**Choosing the model** (`electron/hardware.cjs`). Setup reads the memory (`os.totalmem`), the graphics card (`nvidia-smi` on Windows; Apple silicon shares the system memory) and the free space on the drive holding the user's folder (`fs.statfsSync`). The default model is, in order: the model chosen at an earlier setup (`defaultModel` in `setup.json`); `qwen3.5:9b` or `qwen3.5:4b` if already downloaded; `qwen3.5:9b` with an NVIDIA card of 8 GB or more, or an Apple silicon Mac with 16 GB or more; otherwise `qwen3.5:4b` (about 3.4 GB instead of 6.6 GB), which keeps replies quick on computers without a suitable graphics card. **Customize** also offers `qwen3.5:27b`. The chosen model is downloaded, set as OpenClaw's default and used for a NemoClaw sandbox, and saved as `defaultModel` once setup succeeds.

**Before downloading**, setup estimates what is still missing (backend about 0.7 GB, Ollama about 1.2 GB, the model, the router model about 1 GB, OpenClaw about 0.4 GB, NemoClaw about 8 GB) and stops with a plain message if free space is below 1.5 times the download plus 2 GB, saying how much to free up. The welcome screen shows the same check and offers **Check again** instead of the setup button. While setup runs, Electron's `powerSaveBlocker` keeps the computer from sleeping, so a long download is not cut off.

| Component | Windows | macOS |
|---|---|---|
| PockPock backend | Find Python 3.12+ or install it (winget, else the python.org installer, per-user); create `runtime\venv`; install the backend packages; install Playwright Chromium | Use a Homebrew or python.org Python 3.12 if present, else download uv (checksum-verified) and install Python 3.12 into `runtime/python`; then the same venv, packages and Chromium. No password |
| Ollama and models | Install Ollama (winget, else `OllamaSetup.exe /VERYSILENT`); set `OLLAMA_CONTEXT_LENGTH=32768` for the user; start Ollama; download the chosen model and `qwen3.5:2b` with progress | Download `Ollama-darwin.zip` from Ollama's GitHub release (checksum-verified) and unpack Ollama.app into `/Applications` (or `~/Applications` if that is not writable). Its server runs directly from the bundle, so Ollama's own first-run window never appears. `launchctl setenv OLLAMA_CONTEXT_LENGTH 32768`; the same model downloads |
| OpenClaw engine | Install Node.js LTS if missing (winget); `npm install -g openclaw` | Use Node.js 22+ if present, else Node.js 24 from nodejs.org (checksum-verified) into `runtime/node`; `npm install -g openclaw` with the npm prefix set to `runtime/npm-global`, so no sudo |
| | Both: non-interactive onboarding against Ollama on port 18810 with a login item (Windows) or launch agent (macOS); the chosen model as default with a 64K window, `thinkingDefault low`, longer model and compaction timeouts, the full tool profile and desktop control; switch each listed skill on or off as chosen; add the browser and computer guidance to the OpenClaw workspace; install the PockPock permission plugin; restart the gateway | |
| NemoClaw engine | Install WSL with Ubuntu 24.04 (administrator prompt; may need a restart); the user creates the Ubuntu account in a terminal window; install and start Docker Desktop (administrator prompt); install NemoClaw in WSL | Apple silicon only. Xcode Command Line Tools (macOS shows its own install window); Docker Desktop from Docker's disk image, installed with `install --accept-license` after one macOS password prompt (Colima is used instead if already installed); install NemoClaw natively |
| | Both: onboard a `pockpock` sandbox against Ollama with the chosen model and a 32K context | |

**Final check.** After the components, setup starts every installed service (in the normal start order) and checks each one: the Python services must answer `/health` with their own name, the gateway `/api/health`, Ollama `/api/version`, the OpenClaw and NemoClaw ports must be open, and `qwen3.5:2b` must produce a short reply (it is unloaded straight after). Each check is a step in the progress list. Setup reports success only when every check passes; otherwise it names the failing services and keeps the plan so **Try again** repeats it. The result is saved as `verified` in `setup.json`.

The skills list is what `openclaw skills list --json` reports as eligible on this computer once OpenClaw is installed; before that, the bundled `desktop/electron/openclaw-skills.json` (19 skills for OpenClaw 2026.11.3). Unticked skills are installed but switched off and can be switched on later on the Skills page.

Setup skips anything already installed. The agent browser download is tried up to three times, and a model download whose error looks temporary (a timeout or a dropped connection) is tried again too; Ollama keeps what it already downloaded. A model name Ollama does not know fails at once. If it stops (failure, cancel, a needed restart, or a step the user must finish: the Ubuntu account, the Command Line Tools window, or Docker Desktop's first start), the plan is saved in `setup.json` and the next launch opens Setup with **Continue**. **Settings → Run setup** opens it any time to repair or add components.

Code: `setup.cjs` (shared steps and the final check), `hardware.cjs` (hardware check, model choice, download and disk estimates), `setup-win.cjs` and `setup-mac.cjs` (installers for each system), `platform.cjs` (process control, NemoClaw's shell and Docker for each system).

## Updates

The installed app updates itself from the project's GitHub releases (`electron/updater.cjs`, `electron-updater`, configured by `build.publish` in `desktop/package.json`). Running from source never checks.

| | Windows | macOS |
|---|---|---|
| Check | 15 seconds after the app opens, then every 4 hours, and with **Settings → Updates → Check for updates** | Same |
| New version | Downloads in the background (unless **Download updates automatically** is off; then **Download update**). The download is verified against the SHA-512 in `latest.yml` | Reported only, with **Open download page**: macOS refuses to replace an app that is signed only ad hoc, so the user installs the new DMG like the first time |
| Install | **Restart to update** (Settings or the status bar) installs and reopens the app; otherwise it installs silently when the app quits. Chats, settings and setup state are kept | Manual |

**Before the installer runs**, the app closes its terminals and stops the gateway and the four Python services, even when **Stop services when the app closes** is off: they run from inside the app folder (`resources\backend`), and Windows cannot replace files a running program holds. With that setting on, everything the app started is stopped as on a normal quit. The services start again when the new version opens.

**After an update**, the new version may need other Python packages. Setup saves a fingerprint of the backend's requirements files (`backendDeps` in `setup.json`) after installing the backend. When the installed app starts and the bundled requirements no longer match, it runs `pip install` for them and `playwright install chromium` before starting the services; the status bar shows "Updating PockPock's services for the new version…". Output goes to `logs\backend-update.log`. If it fails (for example offline), the services start anyway and the next start tries again. Running **Setup** also brings the packages up to date.

**Releases** (`.github/workflows/desktop-release.yml`) attach the update information read by installed copies: `latest.yml` and the installer's `.blockmap` (Windows) and `latest-mac.yml` (macOS). With a previous release's blockmap available, Windows downloads only the changed parts of the installer; otherwise the whole installer. Updater messages are written to `logs\updater.log`; failed checks are shown on the Settings page only.

Copies of 0.1.0 do not contain the updater; they update to a later version by downloading it once.

**Installing by hand stops PockPock's services first** (since 0.2.13). The background services keep running after the app closes. Their Python processes start from the Python runtime, not from the install folder, so electron-builder's running-app check cannot see them. But their scripts and working folders are inside `resourcesackend`, so Windows refused to replace those files, and every manual install stopped with "PockPock Agent cannot be closed". The installer's `customInit` (`desktop/installer/installer.nsh`, `pockpockStopServices`) now stops every process whose command line names the install folder, with its child processes (`taskkill /T`). It skips the app itself (the installer's own check closes it), the installer and its PowerShell. Ollama and OpenClaw are not affected. An in-app update already stops the services before it starts the installer, so this runs only for a manual install. The services start again with the app.

**Installing by hand over an earlier version asks how to install** (Windows, since 0.2.13). When the installer finds PockPock's services running or the old app's caches (`Cache`, `Code Cache` or the updater's downloads), it shows a Windows message box with three choices. **Yes** is **Repair**: keep the caches and replace the app. **No** is **Clean install**: remove the caches listed below and install fresh. **Cancel** installs nothing. The one-click installer can only show a standard message box, so the text says what each button does. Both choices stop the old services first. Chats, settings, keys, connectors, reports, logs, models and the Python environment are kept either way. Nothing is asked for a first install, or for an update installed from inside the app (that keeps the caches). A silent install (`/S`) does a clean install. The choice is made in `customInit` (`pockpockCountServices`, the cache checks, the message box) and applied in `customInstall` (`$pockpockClean`).

**What a clean install clears.** Before 0.2.13 every manual install did this without asking. Installing a version from a downloaded installer or DMG removes the old app's caches; an update installed from inside the app (**Restart to update**, or on quit) keeps them. Removed: the Chromium caches in the app's data folder (`Cache`, `Code Cache`, `GPUCache`, the Dawn and shader caches, `Shared Dictionary`, `Service Worker`, `blob_storage`, `Session Storage`) and the installers downloaded by the updater (`pockpock-desktop-updater` and the older `pockpock-ai-desktop-updater`, in `%LOCALAPPDATA%` on Windows and `~/Library/Caches` on macOS). Always kept: chats, settings, setup state, cloud keys, connectors, reports, Maintenance settings, `Local Storage`, logs, models and the Python environment.

| | Windows | macOS |
|---|---|---|
| How a manual install is told apart | The installer (`desktop/installer/installer.nsh`, `build.nsis.include`) clears the caches in its `customInstall` step unless electron-updater started it with `--updated` | There are no in-app installs on macOS, so every version change is a manual one: on the first start of a new version, before Chromium opens its caches, `electron/fresh-install.cjs` clears them and records the version in `installed-version.json` in the app's data folder |
| A cache in use | Left in place (the installer closes PockPock first) | Left for the next new version |

The two cache lists are kept in step by hand. Tests: `electron/fresh-install.test.cjs`.

## Running from source

Requirements: Python 3.12 (`py -3.12 backend\scripts\pockpock.py setup` on Windows, `python3.12 backend/scripts/pockpock.py setup` on a Mac, creates the repository `.venv`), Node.js 24+, and `npm install` inside `desktop/`.

```powershell
cd desktop
npm install
npm run build
npm run app            # or the "PockPock Agent" shortcut from scripts\create_shortcut.ps1
npm run dev            # Vite on port 5180 with hot reload, and the app against it
npm run dist:win       # Windows installer into desktop\release (on Windows)
npm run dist:mac       # macOS .dmg and .zip for Apple silicon and Intel (on a Mac)
```

macOS apps can only be built on a Mac. The **Desktop installers** GitHub Actions workflow (`.github/workflows/desktop-release.yml`) builds both installers on GitHub's runners: start it from the Actions tab or push a `v*` tag. The macOS job runs on an Intel Mac (`macos-15-intel`; GitHub's Apple silicon runners were too busy to pick up jobs in November 2026) and builds both the Apple silicon and the Intel version there. npm installs only the terminal component for the runner's own processor, so the job adds the other one, then checks the ad-hoc signature with `codesign --verify`. CI's macOS checks run on the same kind of machine.

`npm run app` and `npm run dev` clear `ELECTRON_RUN_AS_NODE`, which VS Code sets in its terminals and which would make Electron run as plain Node.

## Services

On start the app checks every service and, unless **Start services when the app opens** is off, starts the missing ones in order: Ollama, then the planner, validator, run store, browser automation and Local MCP together, then the gateway, OpenClaw, and NemoClaw (if **Include NemoClaw** is on). Services that are already running are adopted, not restarted.

| Service | Started with | Stopped with | Healthy when |
|---|---|---|---|
| Ollama | `ollama serve` | ending the process and the Ollama tray app | `GET :11434/api/version` |
| Planner, Validator, Run store, Browser automation, Local MCP | `python -m uvicorn app:app` in the service folder | ending the process tree (for Local MCP this also ends the MCP servers it runs) | `GET /health` returns its name |
| PockPock gateway | `python -u backend/scripts/pockpock_server.py` | ending the process tree | `GET :8766/api/health` |
| OpenClaw gateway | `node openclaw.mjs gateway start` | `node openclaw.mjs gateway stop` | port 18810 open |
| NemoClaw sandbox | Docker Desktop and Ollama, then `nemoclaw pockpock start` in WSL; if that fails or the port stays closed, `nemoclaw pockpock recover`; then `nemoclaw pockpock connect --probe-only` to re-establish inference | `nemoclaw pockpock stop` | port 18789 open |

Python services and Ollama keep running if the app crashes or is closed with **Stop services when the app closes** off. Ollama is started as a detached process. On Windows the Python services start through `backend/scripts/hidden_launch.py`, run by the interpreter the venv was made from (`pyvenv.cfg`): the helper has a hidden console, and the service and everything it starts share it. Started detached instead, they had no console, so the venv's `python.exe` (a launcher that starts the real interpreter as a child) made Windows Terminal open one window per service. The helper waits for its service and exits with the service's exit code, so crashes are still reported; it writes the service's output to the service log. If the base interpreter cannot be found, the app falls back to starting the service detached. On macOS the services are started detached as before. After a Windows restart the NemoClaw sandbox usually needs `recover` ("OpenShell is unavailable") and a probe before inference works; the app does both and writes each step to the NemoClaw log.

OpenClaw is run through Node with its JavaScript entry point, so it does not depend on PowerShell's script execution policy or shell quoting. Services get a PATH without Git for Windows' Unix tools, which would otherwise shadow Windows programs (for example `notepad`) for OpenClaw.

When the app closes it stops only the services it started (OpenClaw and NemoClaw with their stop commands, the rest by ending their processes), within 20 seconds. **Stop services when the app closes** turns this off. **Open PockPock Agent when I sign in** registers the app as a Windows login item.

Logs: the Python services and Ollama (when started by the app) write to `%LOCALAPPDATA%\PockPock\logs` (Mac: `~/Library/Application Support/PockPock/logs`); an Ollama started elsewhere logs to `%LOCALAPPDATA%\Ollama\server.log` (Mac: `~/.ollama/logs/server.log`); OpenClaw to `openclaw-<date>.log` in `%TEMP%\openclaw` (Mac: `/tmp/openclaw`). The Services page shows the last 200 lines of each.

## How it works

```text
Electron main process (desktop/electron/)
  main.cjs        window, IPC handlers, single instance, login item, quit behaviour
  services.cjs    service definitions, start/stop/health, logs
  platform.cjs    per-system process control (taskkill/netstat or process groups/lsof), NemoClaw's shell (WSL or bash), Docker
  setup.cjs       first-run and repair setup, resumable, ending with a check of every service
  setup-win.cjs   Windows installers (winget, python.org, OllamaSetup.exe, WSL)
  setup-mac.cjs   macOS installers (uv, Ollama.app, Node.js archive, Docker Desktop image), checksum-verified
  paths.cjs       where Python, the backend, data and tools are (development vs installed, Windows vs macOS); PATH for apps opened from Finder
  server.cjs      127.0.0.1:8790 (or a free port): serves desktop/dist and forwards /api/* to the gateway
  workspace.cjs   folder listing and file reads, confined to the open folder
  terminal.cjs    pseudo-terminal sessions (@lydell/node-pty)
  preload.cjs     window.pockpock bridge (named calls only)

Renderer (desktop/src/, React + Vite)
  App.tsx                      layout, turn orchestration, shortcuts, first-run routing
  lib/engines.ts               Chat, PockPock Agent, OpenClaw and NemoClaw turns; approvals and plan decisions
  lib/api.ts, lib/status.ts    API helpers, server-sent-event reader, live status (backend, services, OpenClaw, NemoClaw)
  lib/store.ts                 chats and settings persistence
  lib/runState.ts              a turn's phase and state (working, slow, waiting, failed, done) for the run bar and task list
  components/                  Shell (title bar, rail, Workshop navigation, status bar), TaskPanel, RunBar, Inspector,
                               CommandPalette, chat and composer, messages and cards, files, terminal
  components/page.tsx          page frame, switches, tabs with counts, stat tiles, side drawer, loading and error rows
  pages/                       one file per Workshop page (Skills, MCP servers, Connectors, Browser recipes, Research,
                               Local models, Cloud models, Memory, Services, Maintenance, Activity), Setup, Settings (SettingsPage.tsx)
```

The window loads the interface from the app's own loopback server, which also forwards `/api` to the gateway. The page therefore has a single `http://127.0.0.1` origin: the gateway's same-PC check accepts it and no cross-origin rules are needed. Streaming responses are piped through unbuffered, and closing a request (Stop, or closing the window) aborts the gateway request too. The forwarder drops `X-Forwarded-*` and `Forwarded` headers.

### Turns

| Mode | Calls |
|---|---|
| Chat | `POST /api/chat` with the chat history (documents inlined, images as base64), streamed. The newest user message needs text or an image (422 otherwise) |
| PockPock Agent | `POST /api/agents/plan` → plan card → `POST /api/agents/plans/{id}/decision` → `POST /api/agents/run` (streamed). Answering questions: the decision is sent as declined and `POST /api/agents/plan` runs again once, with every given answer appended to the request (`answerPlan(messageId, plan, answers)`). Approvals: `POST /api/runs/{run}/approvals/{id}` (`scope: once | task`). Notes: `POST /api/runs/{run}/notes`. Stop: `POST /api/runs/{run}/cancel`. Saving a source: `POST /api/agents/{task}/research-collection/sources` |
| OpenClaw | `POST /api/openclaw/chat` with `session_id = pockpock-<chat id>`, permission mode and model, streamed. Approvals: `POST /api/openclaw/approvals` |
| NemoClaw | `POST /api/nemoclaw/chat` with `session_id = pockpock-<chat id>`, streamed |
| Browser recipe run | `POST /api/browser-recipes/{id}/run` (streamed), approvals as for PockPock Agent |

One turn runs at a time across all chats; the send button is disabled while another chat is working. OpenClaw and NemoClaw keep their own memory per chat; switching mode inside a chat does not copy earlier turns into the other engine.

### Timing

`desktop/src/lib/timing.ts` times every turn in the renderer, as each stream event arrives (`Date.now()`, milliseconds). It therefore measures what the user waited for, including network and model load time, not model compute time alone.

- `runTurn` (`lib/engines.ts`) records `timing.startedAt` and `timing.endedAt` on the assistant message and wraps every message change in `stampTiming`. That gives each step a `startedAt` (when it first appeared) and an `endedAt` (when it stopped running), and each approval a `requestedAt` and `resolvedAt`. The time is taken when the event arrives, not inside React's state updater, which may run later. A step updated under the same id (OpenClaw tool events, NemoClaw status) keeps its start time.
- `timing.firstOutputAt` is the first token, step, plan or approval. Tokens are buffered for 50 ms before they are shown, but the first token's arrival time is recorded exactly.
- PockPock Agent also records `planReadyAt` (the plan card appeared) and `planDecidedAt` (approved, declined or stopped). Approval cards record `resolvedAt` at the click.
- `turnPhases` splits a finished turn into phases. Chat: **Thinking** (start to first token) and **Writing**. OpenClaw and NemoClaw: **Thinking** (start to first output) and **Working**. PockPock Agent: **Planning** (start to plan card) and **Working**. Time spent on the plan card and on approval cards is reported as **Waiting for you** and subtracted from the model's phases. Phases under 0.05 s are hidden; **Total** is always shown. A step's own duration includes any approval it waited for (a file change waits for its approval card); the breakdown under the reply counts that time as **Waiting for you**.
- Durations are shown as `12.3 s`, `2 min 5.0 s` or `1 h 2 min 5.0 s`, with tabular figures so live counters do not jitter. Live counters update every 100 ms.
- Timing is saved with the chat in `sessions.json`. Replies from before this feature have no timing and show none.
- `timing.lastEventAt` is the newest stream event of the turn. The run bar's **Signal** counts from it, and a live turn with no event for 10 s (`SLOW_AFTER_MS` in `lib/runState.ts`) is shown as slow.

### Run bar and inspector data

`lib/runState.ts` derives everything the run bar and the task list show from the message itself, so a finished or reopened task shows what it showed live:

| Shown | Source |
|---|---|
| Phase: Understand → Plan | PockPock Agent: the first step or the plan card |
| Plan → Act | The plan card is approved |
| Act → Verify | The gateway's `verifying` event (`{"type": "verifying", "checks": N}`), sent once when the agent stops calling tools and its answer is checked against the approved success checks |
| Step 3 of 5 | The gateway's `plan_step` event (`{"type": "plan_step", "step": 3, "total": 5, "label": "…"}`), sent when the agent calls `report_plan_step`. Shown in the run bar and the task list while it acts, as **Now** on that step of the plan card while the run is live, and as "It was on step 3 of 5." when a run fails or stops. Never guessed: a run whose agent reported nothing shows "3 steps" (finished tool steps) as before |
| Waiting | A pending plan card or approval card |
| Slow | A live turn with no event for 10 s |
| Failed / stopped | The reply's status (`error`, `stopped`); a reply still marked as streaming when the app opens was interrupted |
| Context used | The gateway's `usage` event after every agent model call: `prompt_tokens`, `completion_tokens`, and `context_window`, the context Ollama loaded the model with (from `/api/ps`; absent for cloud models) |
| Files touched | `read_project_file` results (read), applied patches (edited) and saved artifacts (new) |
| Task folder before the run | `/api/state` → `output_directory`; a run's folder is `<output_directory>/<run id>`, and the app chooses the run id before planning |

Test gateway: the main process, the service health check, connectors and cloud models all use `POCKPOCK_BACKEND_URL` when it is set (default `http://127.0.0.1:8766`), so the app can be pointed at a gateway on another port for testing without touching the installed one.

Saved tasks: `sessions.json` entries that are not a task (no string `id` or no message list) are skipped when the app loads, so one damaged entry no longer hides every other task, and the next save no longer drops them.

Not shown, because nothing reports it: which plan step a tool call belongs to (the bar shows the running step's label instead of "step 3 of 5"), and context use for Chat, OpenClaw and NemoClaw.

### Status

The renderer polls `/api/state` every 4 seconds and OpenClaw status and the skill and MCP counts every 30 seconds; the main process checks every service every 4 seconds and pushes changes. NemoClaw is asked only whether it is installed (`?probe=0`) unless NemoClaw is the selected mode, because the full sandbox check loads a model.

## Data

| What | Where |
|---|---|
| Chats | `%APPDATA%\PockPock Agent\sessions.json` (Mac: `~/Library/Application Support/PockPock Agent/sessions.json`) (newest 200; image bytes are not saved; turns cut off by closing the app are marked stopped and their pending approvals expired) |
| Settings (open folder, mode, permissions, models, panel layout, startup options) | `%APPDATA%\PockPock Agent\settings.json` |
| Setup progress | `%APPDATA%\PockPock Agent\setup.json` |
| Installed Python environment | `%LOCALAPPDATA%\PockPock\runtime\venv` (Mac: `~/Library/Application Support/PockPock/runtime/venv`) (installed app only; a source checkout uses `.venv`) |
| Service token and logs | `%LOCALAPPDATA%\PockPock` (Mac: `~/Library/Application Support/PockPock`) |
| Agent results, skills, MCP servers, memory | Owned by the backend, OpenClaw and NemoClaw as documented on their pages |

Uninstalling keeps all of this.

The backend data folder was called `FrogAI` before 2026-11-15. On start, the app (and `pockpock.py start`) moves anything in the old folder into `PockPock` that is not there yet, without overwriting, and removes the old folder once it is empty.

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
| PockPock Agent: "The planner model failed" | The planning model did not answer in time or Ollama returned an error | Check `%LOCALAPPDATA%\Ollama\server.log`; pick a smaller model for agent work, or wait for a large one to finish loading |
| "NemoClaw is not ready" right after starting it | The status had not refreshed yet | The app re-checks before refusing a message; if it still refuses, open **Services** → NemoClaw log |
| NemoClaw does not start | Docker Desktop not running or not set up for WSL | Start Docker Desktop, then **Services** → NemoClaw → **Start**; check its log |
| Send button greyed out with "Another chat is still working" | One turn at a time | Wait or press Stop in that chat |
| Run bar: "No new output for 14 s" | The model is loading, or a long step is running | **Keep waiting**, **Use *a smaller model*** or **Stop** |
| Run bar turns red: "Stopped: …" | The run failed; the bar says what was kept | **Retry**, **Open Services** to check the services, or **Report** |
| Terminal: "The terminal component could not be loaded" | `@lydell/node-pty` is missing | Reinstall the app, or `npm install` in `desktop/` |
| The window does not open when started from a VS Code terminal | VS Code sets `ELECTRON_RUN_AS_NODE` | Use `npm run app`, `npm run dev`, or the shortcut |

## Agent Studio design coverage

The redesign follows the Agent Studio design boards (21 boards: the shell, run states, plan review, thread cards, pickers, dialogs, files and terminal, every Workshop page, Settings and Setup). Every screen uses real app state; the boards' sample data (task names, model names, numbers) is not reproduced. Checked against the boards on 2026-11-22:

**Implemented, including the elements that first had no data behind them:** the rail, task list with Needs you and Running, run bar with phases, Signal, slow and failed states and **Step N of M**; the inspector with context used and files touched; the command palette; the plan card with pre-check, answer choices, editable steps and the task folder; approvals with **Allow for this task**; the skill and MCP install card in the thread; sources with **Save**, **Check for changes** and **Watch for changes**; notes while a run works; **Retry from step N**; message actions; the pickers; the report and Maintenance Manager dialogs; toasts; every Workshop page in the new frame; Settings with the theme grid; the Setup stepper.

**Not built yet** (tracked as UI-01G to UI-01M in `docs/TASKS.md`):

| Design element | Why it is missing |
|---|---|
| Activity: requests-per-minute chart, model-share chart, 24 h / 7 d range | The page lists calls by model and recent events; the charts are not drawn yet |
| Terminal tabs (**Terminal 1**, **Terminal 2**, **New terminal**) | The app has one terminal |
| Services: **Restart all** and each service's port | Services start, stop and restart one by one or all at start-up |
| Models: **Unload**, purpose tags (Coding, Reasoning), "slow to start" | Models are never unloaded from the app; tags come only from Ollama's details |
| Skills: use counts and **Recent use** | Skill use is not recorded |
| The last lines of a running command's output under its step | Tool events carry no streamed output |
| Research: **View changes** for a watched page, and a per-site list (**Add website**, read counts) | Snapshots are stored but no comparison is shown; research allows the sites named in each task, not a saved list |
| Browser recipes: **Running · step 3 of 4** in the list | The run shows Running, not which step |

## Verification

```powershell
cd desktop
npm run typecheck
npm run build
npm run dist:win  # optional: Windows installer (dist:mac on a Mac)
```

Watching saved sources, checked on 2026-11-22 (`feat/studio-watch-sources`): backend suite (8 watcher tests in `test_source_watch.py`; 5 store and gateway tests in `run_store/test_research_watch_store.py`, including the column migration and the 50-source limit; all suites pass except the known Developer-Mode symlink test); the watch routes through a real run-store service process; typecheck, build, 49 Electron tests, `check:contrast` 100/100 in every theme. The real app with a gateway from source and a seeded task (interval 15 min): **32 of 32 checks**. Saved and watched state shown after a reload, watching off by default, the switch turns it on, and the gateway's own background pass re-read the stale watched page (example.com, research on in the temp profile only), found the change and the **A watched page changed** toast appeared; **Later** hid it; the Research page marked it **Changed**; **Mark as seen**, **Check now** (a real 404 shown as "Check now failed: The website returned HTTP 404"), **Stop watching** and the paused note; all four themes at 1440 and 820 px; axe-core with no violations; no console errors besides that expected 502. Not verified: a long-running gateway over several intervals, macOS.

Plan-step progress, checked on 2026-11-21 (`feat/studio-step-progress`): backend suite (8 new `plan_progress` tests; all suites pass except the known Developer-Mode symlink test), typecheck, build, 49 Electron tests, `check:contrast` 98/98 in every theme; the real app with a run streamed event by event (no model): **19 of 19 checks**: no chip before the run, **Step 2 of 4** in the run bar with the step's text as its tooltip and in the announced status, **Now** on step 2 of the plan card, "Agent · Step 2 of 4" in the task list, an out-of-range step ignored, step 3 followed, nothing after the run finished, "It was on step 3 of 4." on a failed run and no step on one that reported none, axe-core with no violations in all four themes, no console errors. Live gateway runs with `qwen3.5:9b` (temp folder, Auto-review): with the final wording 3 of 4 runs reported every step (1, 2, 3, 4) and 1 reported none; all 4 runs finished with the right files. Earlier wordings (at the end of the system prompt, or "in the same reply as the step's first tool call") got no reports in 3 runs, because this model makes one tool call per reply.

Agent Studio settings, setup, dialogs and toasts, checked on 2026-11-21 (`feat/studio-settings`): typecheck, build, 49 Electron tests, `check:contrast` 96/96 in every theme; the real app (the gateway first absent, then started from source on :8866): **46 of 46 checks**. A stopped gateway showed its toast, which went away once the gateway ran; an "Ollama not running" toast (the state reply changed by the test, Ollama untouched) could be dismissed; an update-ready toast (the main process's update event sent by the test) with **Later**, and the matching Settings row; the theme grid by click and arrow keys, all five themes including System applied, at 1440 and 820 px; the report dialog kept focus inside and returned it on Escape; the Maintenance Manager setup dialog; the Setup stepper on **Choose** (nothing installed); axe-core with no violations; no console errors. Not verified: **Restart to update** with a real update, the Setup stepper through a real install.

Agent Studio Workshop pages, checked on 2026-11-21 (`feat/studio-workshop`): typecheck, build, 49 Electron tests, `check:contrast` 91/91 in every theme; the real app with a test gateway and the extension, skill-inbox, recipe and research calls answered by the test: **119 of 119 checks**. Covered: the skills tabs and their counts, arrow keys between tabs, search, the details drawer (Escape closes it and returns focus), **Check it** and **Review and add** in the inbox, a skill switch; the Smart route card and model rows; the research switch; the recipe editor beside its list; the connector drawer; every Workshop page in all four themes at 1440 px and six of them at 820 px with no horizontal overflow; axe-core on every page in PockPock Dark and Feather with no violations; no console errors.

Agent Studio thread (plan card, thread cards, pickers), checked on 2026-11-21 (`feat/studio-thread`): typecheck, build, 49 Electron tests, 12 OpenClaw helper tests; `check:contrast` 91/91 pairs in every theme; the real app with the agent calls answered by the test (no model): pre-check chips, the task folder before the run, an answer that plans again with the answer in the new request, reorder/remove/add steps, the note box and a note marked as given, **Allow for this task** sending `scope: "task"`, **Retry from step 2** sending only the remaining steps, keyboard on all four pickers, screenshots in every theme at 1440 and 820 px, axe-core with no violations, no console errors, and tasks still loading with a damaged `sessions.json` entry. A real run with `qwen3.5:9b`: the pre-check found the named file and passed; a note sent during the run reached the model before its next step; after **Allow for this task** on `a.md`, the change to `b.md` was allowed without asking, and both files were right. Not verified with a real model: answer choices (the model asked no question in three tries) and Retry from step N.

Agent Studio shell, checked on 2026-11-21 (`desktop/` at the `feat/studio-shell` branch): typecheck, build and the 49 Electron tests passed; `npm run check:contrast` passed 80 of 80 pairs in every theme (12 new pairs for the run bar, rail, palette and inspector). The real app was driven with Playwright's Electron driver, a throwaway data folder, and a gateway started from source on a test port (8866), in PockPock Dark, Volt, Storm and Feather at 1440×900 and 820 px: a finished task, a failed task, the Files tab, a Workshop page, the command palette (also used to switch every theme), and a live PockPock Agent turn whose planning and run requests were answered by the test (no model): working after 2.5 s, slow after 12 s, waiting with the plan card and the rail's needs-you dot, then done with **Context used** and **Files touched** filled from the `usage` and `tool_result` events; at 820 px the menu and inspector overlays. 56 screenshots, no console errors, no horizontal overflow. axe-core (WCAG 2.2 A/AA) found no violations on eight screens in PockPock Dark and Feather; Ctrl+K puts focus in the search box and Escape returns it; arrow keys move between inspector tabs. A real PockPock Agent run with `qwen3.5:9b` (gateway and planner from source) sent two `usage` events (2,211 and 2,442 prompt tokens of a 32,768-token context) and one `verifying` event. Not verified: the run bar's slow state in a real run, **Use *model*** and **Retry** with a real model, and anything on a Mac.

Checked on 2026-11-15 by driving the real app with Playwright's Electron driver and a throwaway data folder (`POCKPOCK_DESKTOP_USER_DATA`):

- From source: status bar shows the gateway ready; the Services page listed all eight services; the validator was stopped, started again and its log read; Activity, Browser recipes (list and editor), Research and Setup loaded; Setup with the backend and Ollama selected recognised both as installed and finished; no console errors.
- Earlier the same day: the Files panel listed and attached a file, the terminal echoed a command, all modes appeared in the mode picker, all Customize pages loaded, a skill switch turned off and on, and an 820 px window had no horizontal overflow.
- Packaged build (`release\win-unpacked`) as a first-time user: Setup opened automatically, the bundled backend was found under `resources\backend`, the 19 skills were listed, no console errors.

- After the macOS work (Windows PC): the app opened with services left alone; `setup:status` reported `platform: win32`, every component installed, NemoClaw supported, and 19 skills read live from OpenClaw; all eight services running; the Setup page showed the Windows wording; shortcut labels read `Ctrl+N`; no overflow at 820 px; no console errors. The macOS code paths were loaded in Node with the platform set to `darwin` (paths, PATH, NemoClaw command), and the Node.js and Ollama checksum parsers were run against the live checksum files.
- PockPock Agent end to end with `qwen3.5:27b` (planner thinking off, longer timeouts): plan, approval, `hello.txt` created with the right text, all three checks passed, 171 s.

Not verified:

- **Anything on a real Mac.** No Mac was available. Not run: the macOS installer build (`npm run dist:mac` or the GitHub workflow), first launch with Gatekeeper, setup on macOS (uv, Ollama.app, Node.js, OpenClaw onboarding, Docker Desktop's install and first start, NemoClaw on Apple silicon), the services and terminal on macOS, and the title bar with the macOS window buttons.
- The final check (`verify`) end to end: running setup again on this PC would have re-run onboarding and restarted the OpenClaw gateway while it was in use.
- A full install on a clean Windows PC (Python, Ollama, Node.js, OpenClaw, WSL and Docker Desktop all missing) and NemoClaw setup end to end.
