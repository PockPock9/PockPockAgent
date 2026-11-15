# Agent core

The in-process application layer for agent execution. The gateway owns public HTTP routes, local-origin checks, request validation, and response transport; this package owns the approved-run execution workflow, tool/model coordination, cancellation behavior, delegation, and finalization.

- Entry point: `create_agent_runner(services)` in `executor.py`
- Runtime: invoked by `backend/scripts/frog_ai_server.py` in the gateway process; this is a code ownership boundary, not a separately supervised service.
- Contracts: `AgentCoreServices` declares the gateway-owned state and adapter functions that execution uses, including the provider-neutral model client. The gateway constructs it for each request so current run state and test overrides are visible.
- Security: the gateway verifies the local request and router state before invoking the core. The core rechecks the approved plan ticket and permission at execution; tool dispatch remains scoped by the task workspace, approved capabilities, and permission mode. There is no general shell tool.
- Streaming and persistence: the core returns the existing SSE response and uses the durable run-store interface; the run store remains the replay source after reconnect.
- Model calls: tool-capable requests use the `ChatCompletionProvider` contract from `projects/model_router`; Ollama is the only configured adapter.
- Preferences: the gateway injects only allowlisted, user-reviewable local style preferences. They are advisory and cannot affect permissions or task scope.
- Verification: run `python -m unittest projects.planner.test_plan_gate projects.run_store.test_agent_cancellation projects.run_store.test_delegation_scheduler` from `backend`.
