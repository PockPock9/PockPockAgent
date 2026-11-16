# Model router

Provider-neutral chat-completion request and response contracts with the local Ollama adapter.

- Interface: `ChatCompletionProvider.complete` accepts a typed `ChatCompletionRequest` and a caller-owned timeout.
- Local adapter: `OllamaChatCompletionAdapter` uses Ollama's native `/api/chat` endpoint for text-only requests (preserving JSON mode, context-window, and streaming options) and its OpenAI-compatible `/v1/chat/completions` endpoint when a tool list is supplied.
- Thinking: `ChatCompletionRequest.think` sets Ollama's `think` flag on native requests; `None` (the default) leaves the model's own setting. The planner and critic pass `False`, because thinking tokens on a large model can take minutes before the JSON starts. Models without thinking support accept `False`.
- Callers: planner and critic requests, agent model/tool calls, route classification, code-completeness review, and gateway chat streaming. The agent core receives the provider through its explicit `AgentCoreServices` dependency.
- Cloud: `cloud.py` adds `CloudRegistry`, `OpenAICompatibleAdapter` and `RoutingChatCompletionProvider`; a model named `<provider>/<model>` (`nim/`, `openrouter/`, `alibaba/`) goes to its cloud provider, anything else to Ollama. `cloud_api.py` holds the gateway routes and the local `/cloud/v1` endpoint. Keys arrive from the desktop app and stay in memory. See `docs/features/cloud-models.md`. Run `python -m unittest projects.model_router.test_cloud` from `backend`.
- Scope: Ollama is the only local provider, and the only one automatic routing chooses. The Smart Router (`backend/scripts/smart_router.py`) receives the provider by injection; when none is injected, it uses its embedded native Ollama path and remains independently loadable without the backend package.
- Errors: provider and HTTP failures raise `ModelProviderError`; callers map them to their existing route or run failure behavior.
- Verification: run `python -m unittest projects.model_router.test_client` from `backend`.
