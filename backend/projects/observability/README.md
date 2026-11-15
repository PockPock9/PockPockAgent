# Observability contracts

Defines the prompt-free operational trace interface used by the gateway and the deterministic, synthetic routing evaluation used by the planner.

- Tracing: `TraceSink` and `PromptFreeTraceAdapter` reject top-level prompt, message, task, and content fields before sending events to the existing telemetry store. Durable agent run events remain a separate, user-visible replay record and may contain task context by design.
- Evaluation: `planner.evaluation.evaluate_routing` runs fixed synthetic task labels against synthetic model profiles and returns case IDs, selected/expected model names, pass count, and accuracy. It does not retain or emit prompts, workspace files, or model responses.
- Scope: telemetry remains prompt-free; evaluations are offline and deterministic rather than outcome-based.
- Verification: run `python -m unittest projects.observability.test_tracing projects.planner.test_routing` from `backend`.
