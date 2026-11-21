"""HTTP boundary for durable agent run/event storage."""

import os
from pathlib import Path
import sys
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "projects"))
sys.path.insert(0, str(ROOT))  # agent_run_store imports projects.run_store / projects.agent_tools
os.environ["POCKPOCK_RUN_STORE_INTERNAL"] = "1"

from internal_auth import require_internal_token
import agent_run_store as store

app = FastAPI(title="PockPock Run Store", docs_url=None, redoc_url=None)
store.initialize_agent_store()


class NewRun(BaseModel):
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    conversation_id: str | None = Field(default=None, max_length=80)
    task_type: str = Field(min_length=1, max_length=40)
    task: str = Field(max_length=8_000)
    delegation: dict[str, Any] | None = None
    permission_level: str = Field(default="auto-review", pattern=r"^(default|auto-review|full-access)$")


class NewEvent(BaseModel):
    sequence: int = Field(ge=1)
    event: dict[str, Any]


class CancelRun(BaseModel):
    reason: str = Field(default="user", pattern=r"^(user|timeout)$")


class ClaimDelegate(BaseModel):
    parent_run_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class NewApproval(BaseModel):
    approval_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    action_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: dict[str, Any]
    expires_at: str


class ResolveApproval(BaseModel):
    action_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: str = Field(pattern=r"^(approved|rejected)$")


class ExpireApproval(BaseModel):
    action_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ResearchSourceSnapshot(BaseModel):
    workspace_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    source: dict[str, Any]
    text: str = Field(min_length=1, max_length=store.MAX_RESEARCH_SNAPSHOT_BYTES)
    truncated: bool
    notes: str = Field(default="", max_length=store.MAX_RESEARCH_NOTE_CHARS)


class ResearchSnapshotRefresh(BaseModel):
    workspace_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    source: dict[str, Any]
    text: str = Field(min_length=1, max_length=store.MAX_RESEARCH_SNAPSHOT_BYTES)
    truncated: bool


class ResearchSourceNote(BaseModel):
    workspace_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    notes: str = Field(max_length=store.MAX_RESEARCH_NOTE_CHARS)


@app.get("/health")
async def health():
    return {"ok": True, "service": "run-store"}


@app.post("/runs", dependencies=[Depends(require_internal_token)])
async def create_run(payload: NewRun):
    try:
        store.create_agent_run(payload.run_id, payload.conversation_id, payload.task_type, payload.task, payload.delegation, payload.permission_level)
    except store.RunAlreadyExists as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    except (store.InvalidRunRelationship, ValueError) as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return {"created": True, "run_id": payload.run_id}


@app.post("/runs/{run_id}/delegate/claim", dependencies=[Depends(require_internal_token)])
async def claim_delegate(run_id: str, payload: ClaimDelegate):
    if not _valid_id(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        claimed = store.claim_delegate_execution(run_id, payload.parent_run_id)
    except store.RunNotFound as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except store.InvalidRunRelationship as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return {"claimed": claimed}


@app.post("/runs/recover", dependencies=[Depends(require_internal_token)])
async def recover_runs():
    return {"recovered": store.recover_incomplete_agent_runs()}


@app.post("/runs/{run_id}/events", dependencies=[Depends(require_internal_token)])
async def append_event(run_id: str, payload: NewEvent):
    if not _valid_id(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    run, _ = store.get_run_events(run_id, 0, 1)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if payload.event.get("type") == "delegate_result":
        expected_parent = ((run or {}).get("delegation") or {}).get("parent_run_id")
        if not expected_parent or payload.event.get("parent_run_id") != expected_parent:
            raise HTTPException(status_code=422, detail="Delegation result parent does not match the child run relationship.")
    try:
        stored = store.store_agent_event(run_id, payload.sequence, payload.event)
    except store.RunEventContractError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    except store.InvalidRunRelationship as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return {"stored": stored, "sequence": payload.sequence}


@app.post("/runs/{run_id}/finish", dependencies=[Depends(require_internal_token)])
async def finish_run(run_id: str):
    if not _valid_id(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    run, _ = store.get_run_events(run_id, 0, 1)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    store.finish_incomplete_agent_run(run_id)
    return {"finished": True}


@app.post("/runs/{run_id}/cancel", dependencies=[Depends(require_internal_token)])
async def cancel_run(run_id: str, payload: CancelRun):
    if not _valid_id(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        return store.request_agent_run_cancel(run_id, reason=payload.reason)
    except store.RunNotFound as err:
        raise HTTPException(status_code=404, detail=str(err)) from err


@app.post("/runs/{run_id}/approvals", dependencies=[Depends(require_internal_token)])
async def create_approval(run_id: str, payload: NewApproval):
    if not _valid_id(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        return store.create_agent_approval(run_id, payload.approval_id, payload.action_hash, payload.action, payload.expires_at)
    except store.RunNotFound as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err)) from err


@app.post("/runs/{run_id}/approvals/{approval_id}", dependencies=[Depends(require_internal_token)])
async def resolve_approval(run_id: str, approval_id: str, payload: ResolveApproval):
    if not _valid_id(run_id) or not _valid_id(approval_id):
        raise HTTPException(status_code=404, detail="Approval not found")
    try:
        return store.resolve_agent_approval(run_id, approval_id, payload.action_hash, payload.decision)
    except store.RunNotFound as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err)) from err


@app.post("/runs/{run_id}/approvals/{approval_id}/expire", dependencies=[Depends(require_internal_token)])
async def expire_approval(run_id: str, approval_id: str, payload: ExpireApproval):
    if not _valid_id(run_id) or not _valid_id(approval_id):
        raise HTTPException(status_code=404, detail="Approval not found")
    try:
        return {"expired": store.expire_agent_approval(run_id, approval_id, payload.action_hash)}
    except store.RunNotFound as err:
        raise HTTPException(status_code=404, detail=str(err)) from err


@app.get("/conversations/{conversation_id}/runs", dependencies=[Depends(require_internal_token)])
async def list_runs(conversation_id: str):
    return {"runs": store.list_runs_for_conversation(conversation_id)}


@app.get("/runs/{run_id}/events", dependencies=[Depends(require_internal_token)])
async def read_events(run_id: str, after: int = 0, limit: int = 500):
    if not _valid_id(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    run, events = store.get_run_events(run_id, max(0, after), max(1, min(limit, 1000)))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run": run, "events": events}


@app.get("/runs/{run_id}/done-event", dependencies=[Depends(require_internal_token)])
async def done_event(run_id: str):
    if not _valid_id(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    event = store.get_completed_run_event(run_id)
    return {"event": event}


@app.get("/research-collections/{task_id}", dependencies=[Depends(require_internal_token)])
async def read_research_collection(task_id: str, workspace_key: str):
    if not _valid_id(task_id):
        raise HTTPException(status_code=404, detail="Research collection not found")
    try:
        return {"collection": store.get_research_collection(task_id, workspace_key)}
    except store.ResearchCollectionScopeError as err:
        raise HTTPException(status_code=404, detail="Research collection not found") from err
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@app.post("/research-collections/{task_id}/sources", dependencies=[Depends(require_internal_token)])
async def save_research_source(task_id: str, payload: ResearchSourceSnapshot):
    if not _valid_id(task_id):
        raise HTTPException(status_code=404, detail="Research collection not found")
    try:
        collection = store.add_research_collection_source(
            task_id,
            payload.workspace_key,
            payload.source,
            payload.text,
            payload.truncated,
            payload.notes,
        )
    except store.RunNotFound as err:
        raise HTTPException(status_code=404, detail="Research collection not found") from err
    except store.ResearchCollectionScopeError as err:
        raise HTTPException(status_code=404, detail="Research collection not found") from err
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return {"collection": collection}


@app.get("/research-collections/{task_id}/sources/{source_id}", dependencies=[Depends(require_internal_token)])
async def read_research_collection_source(task_id: str, source_id: str, workspace_key: str):
    if not _valid_id(task_id) or not _valid_hash(source_id):
        raise HTTPException(status_code=404, detail="Research source not found")
    try:
        return {"source": store.get_research_collection_source(task_id, source_id, workspace_key)}
    except store.ResearchCollectionScopeError as err:
        raise HTTPException(status_code=404, detail="Research source not found") from err
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@app.patch("/research-collections/{task_id}/sources/{source_id}", dependencies=[Depends(require_internal_token)])
async def update_research_source_note(task_id: str, source_id: str, payload: ResearchSourceNote):
    if not _valid_id(task_id) or not _valid_hash(source_id):
        raise HTTPException(status_code=404, detail="Research source not found")
    try:
        source = store.update_research_collection_note(
            task_id,
            source_id,
            payload.workspace_key,
            payload.notes,
        )
    except store.ResearchCollectionScopeError as err:
        raise HTTPException(status_code=404, detail="Research source not found") from err
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return {"source": source}


@app.post("/research-collections/{task_id}/sources/{source_id}/snapshots", dependencies=[Depends(require_internal_token)])
async def refresh_research_source(task_id: str, source_id: str, payload: ResearchSnapshotRefresh):
    if not _valid_id(task_id) or not _valid_hash(source_id):
        raise HTTPException(status_code=404, detail="Research source not found")
    try:
        result = store.add_research_collection_snapshot(
            task_id,
            source_id,
            payload.workspace_key,
            payload.source,
            payload.text,
            payload.truncated,
        )
    except store.ResearchCollectionScopeError as err:
        raise HTTPException(status_code=404, detail="Research source not found") from err
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    if result is None:
        raise HTTPException(status_code=404, detail="Research source not found")
    return result


@app.get("/research-collections/{task_id}/sources/{source_id}/snapshots/{snapshot_id}", dependencies=[Depends(require_internal_token)])
async def read_research_snapshot(task_id: str, source_id: str, snapshot_id: int, workspace_key: str):
    if not _valid_id(task_id) or not _valid_hash(source_id):
        raise HTTPException(status_code=404, detail="Research snapshot not found")
    try:
        snapshot = store.get_research_snapshot(task_id, source_id, snapshot_id, workspace_key)
    except store.ResearchCollectionScopeError as err:
        raise HTTPException(status_code=404, detail="Research snapshot not found") from err
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Research snapshot not found")
    return {"snapshot": snapshot}


@app.delete("/research-collections/{task_id}", dependencies=[Depends(require_internal_token)])
async def remove_research_collection(task_id: str, workspace_key: str):
    if not _valid_id(task_id):
        raise HTTPException(status_code=404, detail="Research collection not found")
    try:
        deleted = store.delete_research_collection(task_id, workspace_key)
    except store.ResearchCollectionScopeError as err:
        raise HTTPException(status_code=404, detail="Research collection not found") from err
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return {"deleted": deleted}


def _valid_hash(value: str) -> bool:
    import re

    return bool(re.fullmatch(r"[a-f0-9]{64}", value))


def _valid_id(run_id: str) -> bool:
    import re

    return bool(re.fullmatch(r"[a-f0-9]{32}", run_id))
