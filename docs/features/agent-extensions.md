# Agent engines, skills, and MCP servers

The PockPock Agent composer has four modes: **Chat**, and three agent engines (**PockPock Agent**, **OpenClaw**, **NemoClaw**). Skills and MCP servers can be added to the OpenClaw engine by pasting a link; PockPock shows what the link would install and waits for approval before anything is installed or run.

## Agent engines

| Engine | Where it runs | What it can touch | Details |
|---|---|---|---|
| **PockPock** | The PockPock gateway on this PC | A task workspace and the built-in agent tools | [Agent runs](agent-runs.md) |
| **OpenClaw** | An OpenClaw gateway on this PC, no sandbox | Anything your Windows account can, limited by the permission mode | [OpenClaw agent mode](openclaw-agent.md) |
| **NemoClaw** | OpenClaw inside a sandbox in WSL | Only the sandbox | [NemoClaw agent mode](nemoclaw-agent.md) |

1. Open the mode picker in the composer and choose **Chat**, **PockPock Agent**, **OpenClaw** or **NemoClaw**. An engine that is not installed is disabled and its line gives the reason.
2. The controls next to it change with the engine: permission (with the task-folder choice) and model pickers for PockPock Agent; the Ask first / Auto-approve safe / Full access picker and model picker for OpenClaw; none for NemoClaw. The chip above the composer shows the engine with a status dot.

The choice is saved in the app's settings file (`engine`, `agentPermission`, `clawPermission`, `chatModel`, `clawModel`). Each engine keeps its own memory of a chat: turns sent with one engine are not copied to another.

## Skills and MCP servers

- A **skill** is a folder with a `SKILL.md` file: instructions the agent follows for a kind of task, sometimes with scripts it can run.
- An **MCP server** gives the agent extra tools. It is either a program started on this PC (for example with `npx`) or a remote address.

Both are installed into **OpenClaw** and are used only by the OpenClaw engine. The PockPock engine and the NemoClaw sandbox do not see them.

### User flow

1. Open the **Skills** or **MCP servers** page in **Workshop** (the rail's second icon) (or **+** → **Skills…** / **MCP servers…** in the composer) and paste a link into the box at the top. In any agent mode you can also paste the link into the message box and send it. Accepted in the message box:
   - a GitHub link on its own (`https://github.com/owner/repo`, or a folder inside it such as `…/tree/main/skills/pdf`);
   - any link with a short request that names what it is, such as `install skill <link>` or `connect mcp <link>`.
2. PockPock downloads the repository from GitHub and reads it without running anything, then shows an **Approval required** card:
   - **Install skill**: every skill found under the link, with its description, size, and whether it includes scripts. Three or fewer are preselected; with more, tick the ones you want.
   - **Connect MCP server**: the exact command (editable arguments, one per line) or remote address, where the command came from, and a field for each setting the server asks for, such as an API key.
   - If the repository holds both, the card offers a link to show the other kind.
3. **Install** copies the selected skills into OpenClaw. **Connect** starts the server once to list its tools, and saves it only if that works. The card then lists the tool names.
4. The OpenClaw agent can use the new skill or tools from the next message. Start a new chat if an older thread does not pick them up.
5. The **Skills** and **MCP servers** pages list what is installed and control it; see the next section.

A bare GitHub link that contains no skill and no MCP server is sent to the agent as an ordinary message. A link with an explicit request shows an error instead.

Tools from a connected server go through the OpenClaw permission mode like any other tool: in **Ask first** and **Auto-approve safe** each call shows a card titled `Use MCP tool: <server> › <tool>`; in **Full access** nothing asks.

### The Skills and MCP servers pages

Skills and MCP servers each have their own page in **Workshop → Capabilities**. Both act on the OpenClaw engine.

**Skills** shows:

- **Added from links**: skills you installed, each with a switch and a remove button. Removing deletes the skill's files.
- **Built into OpenClaw**: the skills that ship with OpenClaw and are ready to use, each with a switch.
- A collapsed list of built-in skills that need extra software, with what each one needs. These have no switch, because switching them on would not make them work.

**MCP servers** shows every server in OpenClaw's config with a switch. Servers PockPock connected also have a disconnect button; servers added outside PockPock are labelled and can be switched off but not removed here.

A switch turns the skill or server off for the agent without deleting it: OpenClaw stops offering the skill to the model, or stops starting the server and exposing its tools. Switching it back on restores it. The change applies from the next message.

Each page covers loading (a spinner), empty (a note with what to do), error (the reason, including when the OpenClaw gateway is not running), and success (the list updates).

### How a link is recognized

| Link | Result |
|---|---|
| GitHub repository or folder containing `SKILL.md` files | Skills, one per folder (up to 60, each at most 400 files and 25 MB) |
| GitHub repository whose README has an `mcpServers` JSON block | MCP server using that block's command or URL. `npx`, then `uvx`, is preferred when several are documented |
| GitHub repository with a `package.json` that has a `bin` entry | `npx -y <package name>` (assumes the package is published to npm) |
| GitHub repository with a `pyproject.toml` that has scripts | `uvx <project name>` (assumes the package is published to PyPI) |
| Any other `https://` address, or `http://localhost` | Remote MCP server at that address (`…/sse` uses the older SSE transport). A local address is named after its path or port, such as `local-weather` or `local-18799` |
| A command that starts with an allowed launcher, such as `python3 C:\servers\weather_server.py` (MCP servers page only) | A stdio MCP server on this PC, named after its script or package. It is tested and saved the same way as a server from GitHub |
| A repository whose root documents no server but whose sub-folders do, such as `modelcontextprotocol/servers` | The card lists those folders; choosing one previews that folder's server |

A skill whose `SKILL.md` has no `name` or `description` header is still offered, with a note: OpenClaw silently skips such a skill, so PockPock adds the missing header on install (the folder name, and the first line of prose as the description). Existing header fields are kept.

The filesystem server (`@modelcontextprotocol/server-filesystem`) cannot start without a folder it may use; the card says so, and a failed test that reports no allowed directories asks for a folder argument.

When a repository has both skills and a README-documented MCP server, the server is shown first. A server guessed from `package.json` or `pyproject.toml` never takes priority over skills.

## Modules and data flow

```text
Desktop app: ChatPane / ExtensionCard / Skills and MCP pages
  │ POST /api/extensions/inspect {url}          → proposal (nothing installed)
  │ POST /api/extensions/install {proposal_id}  → skills copied, or MCP server tested and saved
  ▼
pockpock_server.py (same-PC check, rate limits)
  ▼
agent_extensions/service.py
  ├─ sources.py            parse link, download zip from codeload.github.com, find skills / MCP setup
  ├─ mcp_probe.py          start the server once (stdio) or call it (HTTP) and list tools
  ├─ gateway_config.mjs    Node helper: config.get / config.patch on the OpenClaw gateway (loopback WebSocket)
  └─ ~/.openclaw/skills/<slug>/                  installed skills
     ~/.openclaw/pockpock/extensions.json        what PockPock installed
```

| File | Responsibility |
|---|---|
| `backend/projects/agent_extensions/sources.py` | Link validation, GitHub download, skill discovery, MCP setup detection, safe extraction |
| `backend/projects/agent_extensions/mcp_probe.py` | One-time test connection that lists a server's tools |
| `backend/projects/agent_extensions/service.py` | Proposals, install, list, remove, the install manifest |
| `backend/projects/agent_extensions/gateway_config.mjs` | Reads and edits `mcp.servers` and `skills.entries.<name>.enabled`, and lists OpenClaw's skills, through the gateway |
| `backend/projects/agent_extensions/api.py` | `/api/extensions` routes |
| `desktop/src/components/ExtensionCard.tsx` | Link detection in the composer and the approval card |
| `desktop/src/pages/SkillsPage.tsx`, `McpPage.tsx`, `extensions.tsx` | The Skills and MCP servers pages and what they share: add from a link, switches, remove, the skills drawer and inbox |
| `desktop/src/components/ChatPane.tsx` | Mode picker; routes a pasted link to the approval card |
| `desktop/electron/setup.cjs`, `desktop/electron/openclaw-skills.json` | The setup skills choice: skills left out are installed but switched off |
| `backend/projects/openclaw_bridge/plugin/pockpock-permissions.ts` | Names the server and tool on MCP approval cards |

MCP servers are saved through the gateway because the OpenClaw CLI refuses MCP changes while the gateway is running. The helper connects the same way the chat helper does (token on loopback).

## API contract

All routes accept requests from this PC only (same check as agent runs) and return `{"detail": "<message>"}` on failure.

| Route | Body | Result |
|---|---|---|
| `GET /api/extensions` | – | `{skills:[{slug,key?,name,description,source,missing,enabled}], builtin_skills:[{key,name,description,enabled,ready,needs}], mcp:[{name,transport,target,source,managed,enabled}], openclaw_ready, detail}` |
| `POST /api/extensions/inspect` | `{url, prefer?: "skills"\|"mcp"}` | Proposal: `{id, kind, source, commit, also, expires_in, skills?: [...], mcp?: {...}}` |
| `POST /api/extensions/install` | `{proposal_id, skills?: [slug], args?: [string], env?: {KEY: value}, authorization?: string}` | `{kind:"skills", installed:[{slug,name}]}` or `{kind:"mcp", name, verified, tools:[{name,description}]}` |
| `POST /api/extensions/cancel` | `{proposal_id}` | `{ok:true}` |
| `POST /api/extensions/remove` | `{kind: "skill"\|"mcp", name}` | `{ok:true}` |
| `POST /api/extensions/toggle` | `{kind: "skill"\|"mcp", name, enabled}` (`name` is a skill's `key` or a server's name) | `{ok:true, enabled}` |

Rate limits per minute: list 60, inspect 10, install 10, cancel 30, remove 20, toggle 60.

Status codes: `400` invalid link or input, `404` not found on GitHub or not installed by PockPock, `409` name conflict or another install running, `410` proposal expired or already used, `413` repository over 80 MB, `422` nothing installable in the repository, `502` GitHub, the gateway, or the test connection failed, `503` OpenClaw gateway not reachable.

## Persistence

- Skills: `~/.openclaw/skills/<slug>/` (OpenClaw's managed skills folder).
- MCP servers: `mcp.servers.<name>` in `~/.openclaw/openclaw.json`, including any API key or Authorization value entered on the card.
- Switches: `skills.entries.<name>.enabled` and `mcp.servers.<name>.enabled` in `~/.openclaw/openclaw.json`.
- `~/.openclaw/pockpock/extensions.json`: names, source links, commit, and install time of what PockPock installed. No secrets.
- A previewed repository archive is kept in the system temp folder under `pockpock-extensions/` until it is installed, cancelled, or replaced by newer previews. Proposals expire after 15 minutes and at most four are kept.
- Nothing is written to telemetry or run tables.

## Security boundaries

- **Preview runs nothing.** `inspect` only downloads a zip from `codeload.github.com` (redirects outside GitHub are refused) and reads files inside it. A remote address is not contacted until you approve. A pasted command is only split into its launcher and arguments; it first runs when you press **Connect**, as the test connection. Commands are accepted only on the MCP servers page, never from a chat message.
- **You approve exactly what is installed.** `install` takes a proposal id, not a link. Skills are extracted from the archive that was previewed, at the commit shown on the card, never from a fresh download. A proposal can be used once.
- **Extraction is confined.** Symbolic links, absolute paths, `..`, and `.git` are refused. A skill is written to a staging folder and moved into place only when complete.
- **Only known launchers start MCP servers:** `npx`, `uvx`, `uv`, `node`, `python`, `python3`, `py`, `docker`, `bunx`, `bun`, `deno`, `pnpm`, `pipx`. The command itself cannot be edited; arguments can. On Windows, arguments containing `& | < > ^ % " !` are refused for `.cmd` launchers such as `npx`.
- **A failed test connection saves nothing.**
- **PockPock only replaces or removes what it installed.** A skill or server with the same name that it did not install is left alone and the install is refused. Switching on or off is allowed for any skill or server OpenClaw lists, because it deletes nothing and is undone with the same switch.
- **Secrets** are sent to the helper on stdin, stored only in OpenClaw's config, and never returned by the API or logged.
- **Remaining risk:** an approved skill or MCP server is third-party content. A skill's instructions steer the agent; a local MCP server is a program running with your account's access; a remote one receives whatever the agent sends it. The preview shows the source, commit, and command, but PockPock does not review the code. Install only from sources you trust, and prefer **Ask first** when trying a new one.

## Failure states

| What you see | Cause | What to do |
|---|---|---|
| "This repository holds N MCP servers, each in its own folder" | The root documents no server, but sub-folders do | Paste the link to one folder, or pick one from the list on the card |
| "found no skill … and no MCP server setup" | The repository has no `SKILL.md` and no recognizable MCP setup | Link to the folder that contains the skill, or connect the server's address directly |
| "GitHub has no public repository, branch or folder at that link" | Private repository, typo, or a branch name containing `/` | Use a public repository; link to the default branch |
| "`uvx` is not installed on this PC" (or another launcher) | The server needs a program that is missing | Install it, then paste the link again |
| "The server stopped before answering" with its last output | Wrong arguments, a missing key, or the package is not published | Fix the arguments or key on the card and connect again |
| "The server did not answer in time" | First run is still downloading the package | Try again in a minute |
| "The server requires sign-in or an access key" | Remote server returned 401 or 403 | Enter an Authorization value. Servers that need browser sign-in (OAuth) are not supported |
| "That preview has expired" | More than 15 minutes passed, or it was already used | Paste the link again |
| "OpenClaw already has … that PockPock did not install" | Name conflict with something added outside PockPock | Remove it in OpenClaw first |
| MCP list shows "The OpenClaw gateway is not running" | Gateway stopped | `openclaw gateway start` from PowerShell |
| "OpenClaw keeps each skill's on/off switch, and it is not available right now" | A skill was switched while OpenClaw is not set up or not running (an unknown name answers 404 instead) | Set up or start OpenClaw, then switch it |
| The agent does not use a new skill or tool | The thread started before it was added, or the small local model did not pick it up | Start a new chat and name the skill or tool in the request |

## Limits

- Skills and MCP servers apply to the OpenClaw engine only.
- Skill requirements (programs a skill expects, such as Python packages) are not installed.
- OAuth sign-in for remote MCP servers, and private GitHub repositories, are not supported.
- Servers using the older SSE transport are saved without a test connection.
- A guess from `package.json` or `pyproject.toml` assumes the package is published under that name; the test connection fails if it is not.

## Verification

```powershell
cd backend
..\.venv\Scripts\python.exe -m unittest projects.agent_extensions.test_extensions
node projects\openclaw_bridge\plugin\test_policy.mjs
cd ..\frontend\app; npm run build
```

Manual check: open **Skills**, paste `https://github.com/anthropics/skills/tree/main/skills/pdf`, approve the card, and confirm **pdf** appears under **Added from links** with its switch on. Switch it off and on, then remove it.
