"""HTTP boundary for the agent verifier: ledger reads, verification, rewind/resume.

Control plane only: the service owns the durable ledger, runs the external
verifiers, and hands out resume snapshots. Step *execution* stays
in-process (see harness.Harness / cli.py) — the HTTP layer never executes
agent steps itself, so a crashed executor cannot take the ledger down with it.

Local port: 8775. Non-health requests require X-PockPock-Internal-Token.
"""

import asyncio
import os
from pathlib import Path
import sys
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "projects"))
sys.path.insert(0, str(ROOT))

try:
    from agent_verifier.harness import Harness, RunLimits, new_run_id
    from agent_verifier.ledger import Ledger, LedgerError
    from agent_verifier.verifiers import list_verifiers, run_verifiers
except ImportError:  # running from inside backend/projects/agent_verifier/
    from harness import Harness, RunLimits, new_run_id
    from ledger import Ledger, LedgerError
    from verifiers import list_verifiers, run_verifiers

from projects.internal_auth import require_internal_token

app = FastAPI(title="PockPock Agent Verifier", docs_url=None, redoc_url=None)
LEDGER = Ledger()
HARNESS = Harness(LEDGER)


class NewRun(BaseModel):
    run_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    task: str = Field(min_length=1, max_length=8000)
    task_type: str = Field(default="", max_length=40)
    requirements: list[str] = Field(default_factory=list, max_length=50)
    plan: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    max_steps: int = Field(default=50, ge=1, le=500)
    max_retries: int = Field(default=2, ge=0, le=10)
    max_wall_seconds: int = Field(default=1800, ge=30, le=86400)


class VerifyRequest(BaseModel):
    workspace_path: str = Field(min_length=1, max_length=1024)
    spec: dict[str, Any]


class RewindRequest(BaseModel):
    step_index: int = Field(ge=0)


@app.get("/health")
async def health():
    return {"ok": True, "service": "agent-verifier", "verifiers": list_verifiers()}


@app.post("/runs", dependencies=[Depends(require_internal_token)])
async def create_run(payload: NewRun):
    run_id = payload.run_id or new_run_id()
    try:
        run = LEDGER.create_run(
            run_id, task=payload.task, task_type=payload.task_type,
            requirements=payload.requirements, plan=payload.plan,
            limits={"max_steps": payload.max_steps, "max_retries": payload.max_retries,
                    "max_wall_seconds": payload.max_wall_seconds},
        )
    except LedgerError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return {"created": True, "run_id": run_id, "run": run}


@app.get("/runs", dependencies=[Depends(require_internal_token)])
async def list_runs(status: str | None = None, limit: int = 50):
    try:
        return {"runs": LEDGER.list_runs(status=status, limit=limit)}
    except LedgerError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@app.get("/runs/{run_id}", dependencies=[Depends(require_internal_token)])
async def get_run(run_id: str):
    run = _get_run_or_404(run_id)
    return {"run": run, "steps": LEDGER.get_steps(run_id),
            "verdicts": LEDGER.get_verdicts(run_id),
            "file_diffs": LEDGER.get_file_diffs(run_id)}


@app.get("/runs/{run_id}/steps/{step_index}", dependencies=[Depends(require_internal_token)])
async def get_step(run_id: str, step_index: int):
    _get_run_or_404(run_id)
    step = LEDGER.get_step(run_id, step_index)
    if step is None:
        raise HTTPException(status_code=404, detail="Step not found")
    return {"step": step, "file_diffs": LEDGER.get_file_diffs(run_id, step_index=step_index)}


@app.post("/runs/{run_id}/verify", dependencies=[Depends(require_internal_token)])
async def verify_run(run_id: str, payload: VerifyRequest):
    """Run the external verifiers against a finished (or in-progress) run.

    Standalone-runnable: the verdict is computed from the workspace on disk
    plus the run's stored requirements — never from an executor transcript.
    A failing verdict is persisted and, when the run is otherwise finished,
    flips it to failed (see harness: done requires a verifier pass).
    """
    run = _get_run_or_404(run_id)
    try:
        workspace = Path(payload.workspace_path).expanduser().resolve(strict=True)
    except OSError as err:
        raise HTTPException(status_code=422, detail="The verification workspace does not exist") from err
    if not workspace.is_dir():
        raise HTTPException(status_code=422, detail="The verification workspace must be a directory")
    verdict = await asyncio.to_thread(run_verifiers, workspace, payload.spec, run=run)
    for check in verdict.checks:
        LEDGER.record_verdict(
            run_id, verifier=check.name,
            verdict="pass" if check.status == "passed" else
                    "fail" if check.status == "failed" else
                    "error" if check.status == "error" else "skipped",
            evidence=[check.evidence],
            failed_check=check.name if check.status != "passed" else None,
        )
    if verdict.verdict != "pass" and run["status"] == "running":
        LEDGER.set_status(run_id, "failed")
    return {"run_id": run_id, "verdict": verdict.to_dict()}


@app.post("/runs/{run_id}/rewind", dependencies=[Depends(require_internal_token)])
async def rewind_run(run_id: str, payload: RewindRequest):
    _get_run_or_404(run_id)
    try:
        return HARNESS.rewind_run(run_id, payload.step_index)
    except LedgerError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@app.post("/runs/{run_id}/resume", dependencies=[Depends(require_internal_token)])
async def resume_snapshot(run_id: str):
    """Return the resume snapshot (stored plan remainder + capsule + next step).

    The caller drives execution in-process via Harness.resume_run; this
    endpoint never re-plans, so resume works even when the planner is down.
    """
    try:
        return HARNESS.resume_snapshot(run_id)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


def _get_run_or_404(run_id: str) -> dict:
    import re

    if not re.fullmatch(r"[a-f0-9]{32}", run_id or ""):
        raise HTTPException(status_code=404, detail="Run not found")
    run = LEDGER.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
