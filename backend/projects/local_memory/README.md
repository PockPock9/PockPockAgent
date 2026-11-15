# Local preference memory

Automatically captures a narrow allowlist of reusable response-style preferences from the latest user request. It stores only normalized values such as “Prefer concise responses.”; source messages and arbitrary user text are never written to the preference table.

- Storage: `local_preferences` and the enable/disable setting in the existing local app SQLite database.
- Minimization: only fixed response-style and code-example-language values are recognized. No names, addresses, credentials, task content, or free-form notes are accepted.
- Runtime: the gateway adds stored preferences as optional style guidance for chat and agent model calls. They cannot change task scope, permissions, tools, or safety behavior.
- Controls: `GET /api/memory/preferences`, `PUT /api/memory/preferences/settings`, and DELETE routes support local review, disabling, individual deletion, and clearing all items. The React Memory page exposes these controls.
- Verification: run `python -m unittest projects.local_memory.test_preferences` from `backend`.
