# Feature documentation index

This index points to detailed feature contracts. Every new feature or change to user-visible behavior must update its feature page and any applicable README/architecture sections in the same change; see [AGENTS.md](../AGENTS.md).

## Project planning

- [Agent capability roadmap](ROADMAP.md)
- [Agent capability implementation tracker](TASKS.md)

## Agent Chat and workspaces

- [Real-world agent use cases](features/agent-use-cases.md)
- [Agent scenario regression pack](features/agent-scenario-regressions.md)
- [Agent runs, task memory, and workspace recovery](features/agent-runs.md)
- [Delegated agent runs](features/delegated-agent-runs.md)
- [Agent tool and run event contracts](features/agent-tool-contracts.md)
- [Agent tool capabilities](features/agent-tools.md)
- [Local agent interaction and automation (planned)](features/local-agent-automation.md)
- [Agent platform supporting tools (planned)](features/agent-platform-expansion.md)
- [Workspace validation](features/workspace-validation.md)
- [Local workflow services](features/local-workflow-services.md)
- [Isolated browser runtime](features/browser-runtime.md)
- [Research source and evidence contracts](features/research-provider-contracts.md)
- [NemoClaw agent mode](features/nemoclaw-agent.md)
- [OpenClaw agent mode and permission modes](features/openclaw-agent.md)
- [Agent engines, skills, and MCP servers](features/agent-extensions.md)
- [PockPock Agent desktop app](features/desktop-app.md)

## Desktop app and setup

- [PockPock Agent desktop app](features/desktop-app.md): interface, Windows and macOS installers, first-run setup with a final service check, services, data and security.
- [Problem reports and Maintenance](features/maintenance.md): the Report button under replies, what a report captures and redacts, and the Maintenance page.
- [Themes and the brand mark](features/themes.md): the five themes, the theme picker, how a theme is applied before the first paint, the title-bar mark and the working indicator.

## Other product areas

- Chat, model selection and the Smart Router are implemented in the gateway (`backend/scripts/pockpock_server.py`, `smart_router.py`) and documented in [README.md](../README.md#smart-router). Prompt-free routing telemetry is stored by `backend/scripts/telemetry_store.py` and shown on the desktop app's **Activity** page.
- The web dashboard, the Open WebUI pipe, the Signal Room dashboard, the Chrome companion scaffold and the YourBrand demo were removed on 2026-11-15; they remain in git history (commit `364820f`).
