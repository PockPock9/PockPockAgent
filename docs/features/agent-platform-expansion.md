# Agent platform supporting tools

## Status

**Planned additions.** The product already has durable run events and replay, named public-site research, explicit text attachments, Office artifact generation, routing evaluation, and a scenario regression pack. This plan adds supporting capabilities without duplicating those systems: a durable worker queue, user notifications, narrowly scoped service connectors, broader document ingestion, and an automated privacy-safe tool evaluation suite.

The worker-queue extraction is already tracked as MAG-06 in [TASKS.md](../TASKS.md). The other work is tracked as CAP-01, CAP-02, DOC-01, OPS-01, and EVA-01.

## Capability inventory

| Capability | Proposed functionality | Existing baseline |
| --- | --- | --- |
| Durable jobs | Recover queued work after restart; use leases, idempotency, bounded retries/concurrency, cancellation, backpressure, and health reporting. | MAG-06 is planned. Delegation currently uses a bounded local scheduler and durable child records, not a separate worker queue. |
| Notifications | Surface approval requests and scheduled-run completion, failure, or attention-required status through the app and optional local desktop notifications. | Run outcomes and approvals are durable and visible in the app; there is no notification service for unattended runs. |
| Service connectors | Provide typed, provider-specific API operations with explicit account connection, narrow scopes, per-operation permission metadata, and user approval for writes. Start with one connector selected from actual use cases. | Public website research and local internal-service calls exist. There is no general external service connector framework or OAuth credential broker. |
| Document ingestion | Read supported text attachments today; extend bounded parsing to PDF, DOCX, XLSX/CSV and, if a local OCR engine is configured, scanned-image text. Preserve page/sheet and source references for extracted passages. | Explicit text attachments can be read; Word, Excel, and PowerPoint research artifacts can be generated. Broad PDF/Office/OCR ingestion is not implemented. |
| Tool evaluation and replay | Run deterministic synthetic scenarios against tool contracts and mocked services; check permission denials, limits, failure behavior, and output quality; replay recorded run events without re-executing side effects. | Planner routing evaluation, focused unit tests, event replay, and a manual agent scenario regression pack already exist. An integrated automated capability suite is not implemented. |

## Proposed implementation sequence

1. **MAG-06 — Durable worker queue.** Complete the existing worker extraction before enabling recurring workflows or unattended job notifications.
2. **CAP-01 — Connector contract and credential handling.** Define provider boundaries, local account connection, credential storage, scopes, audit events, revocation, and safe failure behavior.
3. **CAP-02 — First service connector.** Select the provider from validated user use cases; implement a small typed read-only slice first, then separately approved write operations if justified.
4. **DOC-01 — Bounded document ingestion.** Reuse attachment/workspace boundaries; add size/type limits, isolated parsers, source provenance, and optional local OCR without executing document content or macros.
5. **OPS-01 — Run and approval notifications.** Notify only from durable worker/run state; keep message content minimal and provide a direct route to review or pause the run.
6. **EVA-01 — Privacy-safe evaluation and replay harness.** Combine synthetic fixtures, mocked tool/service adapters, contract checks, and safe event replay. Extend the suite as new capability tasks ship.

## Proposed boundaries

### Jobs and notifications

- The queue is local-first and uses stable job/run IDs, leases, bounded concurrency and retries, cancellation, and idempotent dispatch. A restart must not duplicate an external side effect.
- Schedules remain user-created and user-controlled. Agents may propose a schedule but cannot enable or broaden it without confirmation.
- A run awaiting approval pauses; a notification informs the user but never approves or resumes the action.
- Notifications contain minimal details, avoid secrets and page/document content, and link back to the local run. Users can disable notification channels without losing run history.

### Service connectors

- Each connector exposes a fixed set of typed operations, approved hosts, schemas, limits, permission/side-effect metadata, stable errors, and focused tests. Do not expose arbitrary URLs, generic HTTP request tools, or unrestricted API scripting to the model.
- The user explicitly connects an account and grants the minimum provider scopes. Store refresh/access credentials only in an OS-protected local credential store; never put them in prompts, source files, run events, artifacts, or telemetry.
- Read operations are separately permissioned from writes. Consequential actions require payload-bound approval, and disconnect/revoke removes or disables the connector credential.
- Provider responses are untrusted input. They cannot change task intent or permission state.

### Document ingestion

- Reuse attachment and workspace authorization; accept only declared formats, with bounded bytes, pages/sheets, extracted characters, parser time, and memory.
- Run parsers without macros, embedded scripts, external references, or automatic link fetching. Reject malformed, encrypted, or over-limit inputs with an actionable error.
- Preserve source file, page/sheet, and bounded excerpt references so answers can cite the supplied material. OCR, if added, should be an explicitly configured local engine.
- Do not silently overwrite source files. Extracted text is task-scoped and follows the documented run/workspace retention policy.

### Evaluation and replay

- Use synthetic fixtures and mocked external services by default. A test must not send real messages, mutate real accounts, or access real credentials.
- Replay reconstructs recorded observations and events; it does not dispatch tools or repeat external side effects.
- Store case IDs, contract versions, status, and privacy-safe metrics. Do not retain prompts, responses, page contents, document excerpts, or credentials in aggregate telemetry by default.
- Measure both successful behavior and safe refusal: permission denial, stale approvals, unsupported formats, timeouts, cancellation, oversized inputs/outputs, and worker restart recovery.

## Release gates

- New connectors, parsers, notifications, and jobs use typed contracts with explicit permissions, input/output/resource limits, cancellation, stable failure states, and durable run visibility.
- Existing run history remains readable; event replay never becomes tool re-execution.
- Each shipped capability updates its tool documentation, architecture ownership, README where user setup/behavior changes, focused tests, and task completion record.
- A capability is not marked complete because its API exists: demonstrate expected success, denied/failed operation, cancellation/recovery, and privacy behavior using synthetic data.
