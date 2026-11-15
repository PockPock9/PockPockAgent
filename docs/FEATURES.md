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

## Other product areas

- Conversations, model selection, local routing, and the overview dashboard are implemented in the web app and API. Their current setup and operating behavior is documented in [README.md](../README.md). Add focused pages here as those features receive significant behavior or contract changes.
- The standalone YourBrand marketing and dashboard concept is documented in [YourBrand marketing and workspace demo](features/yourbrand-marketing-demo.md); it runs from `frontend/site/` and uses local mock data only.
- Open WebUI integration and prompt-free Signal Room telemetry are documented in [README.md](../README.md) and their adapters under `backend/scripts/`.
