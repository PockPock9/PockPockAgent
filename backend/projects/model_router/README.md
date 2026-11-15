# Model router

Provider-neutral chat-completion request and response contracts with the local Ollama adapter.

- Interface: `ChatCompletionProvider.complete` accepts a typed `ChatCompletionRequest` and a caller-owned timeout.
- Local adapter: `OllamaChatCompletionAdapter` uses Ollama's native `/api/chat` endpoint for text-only requests (preserving JSON mode, context-window, and streaming options) and its OpenAI-compatible `/v1/chat/completions` endpoint when a tool list is supplied.
- Callers: planner and critic requests, agent model/tool calls, route classification, code-completeness review, and gateway chat streaming. The agent core receives the provider through its explicit `AgentCoreServices` dependency.
- Scope: Ollama is the only configured provider. The Open WebUI pipe accepts an optional injected provider using this contract; when none is injected, it uses its embedded native Ollama path and remains independently loadable without the backend package.
- Errors: provider and HTTP failures raise `ModelProviderError`; callers map them to their existing route or run failure behavior.
- Verification: run `python -m unittest projects.model_router.test_client` from `backend`.
