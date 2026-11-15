# Validator service

Runs deterministic syntax, asset-reference, and permission-gated project-script checks for an agent workspace. The validation policy is implemented in the `backend/projects/agent_tools` package; this service owns the HTTP boundary and process isolation.

- Entry point: `app:app`
- Local port: `8772`
- Routes: `GET /health`, authenticated `POST /validate`
- Configuration: `POCKPOCK_INTERNAL_TOKEN`; request `allow_execution` controls whether declared npm build/test scripts may run.
- Security: bind to `127.0.0.1`; non-health requests require `X-PockPock-Internal-Token`. Workspace checks are enforced by the shared tool implementation.
- Run from this folder with the repository environment: `..\..\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8772`.

Install the service dependencies listed in `requirements.txt` into the shared repository environment. This project depends on `backend/projects/agent_tools` and `backend/projects/internal_auth.py`.
