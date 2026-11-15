"""Isolated workspace validation service."""

import asyncio
from pathlib import Path
import sys

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from projects.internal_auth import require_internal_token
from projects.agent_tools import ProjectAgentContext, validate_project

app = FastAPI(title="PockPock Validator", docs_url=None, redoc_url=None)


class ValidationRequest(BaseModel):
    workspace_path: str = Field(min_length=1, max_length=1024)
    allow_execution: bool = False


@app.get("/health")
async def health():
    return {"ok": True, "service": "validator"}


@app.post("/validate", dependencies=[Depends(require_internal_token)])
async def validate(payload: ValidationRequest):
    try:
        workspace = Path(payload.workspace_path).expanduser().resolve(strict=True)
    except OSError as err:
        raise HTTPException(status_code=422, detail="The validation workspace does not exist") from err
    if not workspace.is_dir():
        raise HTTPException(status_code=422, detail="The validation workspace must be a directory")
    context = ProjectAgentContext(
        task_id="internal-validation",
        project_root=workspace,
        allow_execution=payload.allow_execution,
    )
    try:
        return await asyncio.to_thread(validate_project, context)
    except (OSError, ValueError, RuntimeError) as err:
        raise HTTPException(status_code=500, detail=f"Workspace validation failed: {err}") from err
