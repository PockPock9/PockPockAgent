# Connectors

External apps the agent can use as tools: GitHub, email, Telegram, Slack, Discord and Notion. Only apps outside PockPock belong here.

- `catalog.py`: connectors, their connect forms and tools.
- `clients.py`: the credential check and tool calls for each app.
- `service.py`: `ConnectorService` (validation, in-memory credentials, tool calls).
- `api.py`: gateway routes and the MCP endpoint `/mcp/connectors`.
- `openclaw.py`: registers the MCP server `pockpock-connectors` in OpenClaw.

To add a connector: add it to `CATALOG`, add its `*_verify` function and tool handlers to `clients.py` (`VERIFY`, `HANDLERS`), mark tools that change something with `write=True`, and cover it in `test_connectors.py`. The credential check must make a real call to the app.

Full description: `docs/features/connectors.md`. Tests: `python -m unittest projects.connectors.test_connectors` from `backend`.
