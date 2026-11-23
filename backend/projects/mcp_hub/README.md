# Local MCP (`mcp_hub`)

Runs the MCP servers the user added in PockPock, once, and offers each one to the agents at
`http://127.0.0.1:8776/mcp/<name>` (streamable HTTP, single JSON replies, `Authorization: Bearer <hub token>`).
The gateway manages it at `/servers` with `X-PockPock-Internal-Token`. Full description:
[docs/features/local-mcp.md](../../../docs/features/local-mcp.md).

- Local port: `8776` (`POCKPOCK_MCP_HUB_PORT`). Data: `<PockPock data>/mcp-hub/servers.json` (`POCKPOCK_MCP_HUB_DIR`).
- Run from this folder: `..\..\..\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8776`
  (the desktop app's Services page and `backend/scripts/pockpock.py` start it).
- Tests: from `backend/`, `..\.venv\Scripts\python.exe -m unittest projects.mcp_hub.test_hub`.

| File | Role |
|---|---|
| `app.py` | FastAPI service: `/health`, `/servers…`, `/mcp/<name>` |
| `hub.py` | Saved servers, state, and answering or passing on client messages |
| `upstream.py` | One stdio process or remote server behind the hub |
| `store.py` | `servers.json`, sealed secrets, the hub token |
| `protect.py` | DPAPI on Windows; base64 in a user-only file elsewhere |
| `fake_server.py` | Stand-in stdio MCP server for the tests |
