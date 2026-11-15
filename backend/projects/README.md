# Local workflow projects

These directories own workflow services and in-process packages. Services communicate through loopback HTTP APIs and are started together by `backend/scripts/pockpock.py`, which works on Windows, macOS, and Linux.

| Project | Responsibility | Port | Entry point |
| --- | --- | ---: | --- |
| [agent_core](./agent_core/README.md) | In-process agent execution orchestration | Gateway process | `create_agent_runner` |
| [agent_tools](./agent_tools/README.md) | Agent tool catalog, workspace/file capabilities, research and artifact tools | In-process package | `projects.agent_tools` |
| [model_router](./model_router/README.md) | Provider-neutral chat-completion contract and Ollama adapter | In-process package | `ChatCompletionProvider` |
| [local_memory](./local_memory/README.md) | Allowlisted local preference capture and user-controlled retention | In-process package | `LocalPreferenceMemory` |
| [observability](./observability/README.md) | Prompt-free trace sink contract and synthetic routing evaluation | In-process package | `TraceSink`, `evaluate_routing` |
| [planner](./planner/README.md) | Agent planning, critic review, and model selection | 8771 | `app:app` |
| [validator](./validator/README.md) | Workspace validation | 8772 | `app:app` |
| [run_store](./run_store/README.md) | Durable run and event persistence | 8773 | `app:app` |
| [browser_automation](./browser_automation/README.md) | Isolated run-scoped Chromium and read-only navigation | 8774 | `app:app` |
| [nemoclaw_bridge](../../docs/features/nemoclaw-agent.md) | Sends Conversations turns to a NemoClaw sandbox in WSL | Gateway process | `create_router`, `NemoClawBridge` |
| [agent_extensions](../../docs/features/agent-extensions.md) | Previews a pasted GitHub or MCP link, then installs skills into OpenClaw or tests and saves an MCP server after approval | Gateway process, plus a short-lived Node helper and one test start of the MCP server | `create_router`, `ExtensionService` |
| [openclaw_bridge](../../docs/features/openclaw-agent.md) | Sends Conversations turns to a native OpenClaw gateway on this PC, relays approvals, and ships the permission plugin | Gateway process, plus one Node helper per turn | `create_router`, `OpenClawBridge` |

`internal_auth.py` is a shared internal HTTP contract helper. These projects are separated by service ownership and runtime process, while remaining in one monorepo and using the root Python environment. They are not separately versioned distributions yet.
