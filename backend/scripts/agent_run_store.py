"""Gateway repository client and task journal for agent executions.

When configured, run metadata and event persistence are delegated to the local
run-store service. Direct SQLite access remains available for legacy scripts
and inside the run-store process itself.
"""

import json
from contextlib import closing
import asyncio
import anyio
import hashlib
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import telemetry_store as telemetry

logger = logging.getLogger(__name__)


RUN_EVENT_CONTRACT_VERSION = 1
LEGACY_RUN_EVENT_CONTRACT_VERSION = 0
MAX_RESEARCH_SNAPSHOT_BYTES = 200 * 1024
MAX_RESEARCH_NOTE_CHARS = 2_000


class RunEventContractError(ValueError):
    """Raised when a run event uses a contract version this server cannot read."""


def _normalize_run_event(event: dict[str, Any], *, for_write: bool) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise RunEventContractError("A run event must be a JSON object.")
    normalized = dict(event)
    version = normalized.get("contract_version")
    if version is None:
        version = RUN_EVENT_CONTRACT_VERSION if for_write else LEGACY_RUN_EVENT_CONTRACT_VERSION
    if not isinstance(version, int) or isinstance(version, bool) or version < 0 or version > RUN_EVENT_CONTRACT_VERSION:
        raise RunEventContractError(
            f"Unsupported run event contract version {version!r}; this server supports versions 0 and {RUN_EVENT_CONTRACT_VERSION}."
        )
    normalized["contract_version"] = version
    recipe_event_contracts: dict[str, tuple[str, ...]] = {
        "recipe_run_started": ("recipe_id", "recipe_version", "approval_policy"),
        "recipe_step_started": ("recipe_id", "recipe_version", "step", "action", "observation_id"),
        "recipe_step_result": ("recipe_id", "recipe_version", "step", "action", "status", "checkpoint", "title", "url", "retrieved_at"),
        "recipe_run_finished": ("recipe_id", "recipe_version", "status"),
    }
    event_type = normalized.get("type")
    if event_type == "delegate_result":
        from projects.run_store.contracts import DelegationResult

        if version != RUN_EVENT_CONTRACT_VERSION:
            raise RunEventContractError("Delegation result events require the current run event contract version.")
        if not isinstance(normalized.get("parent_run_id"), str) or not re.fullmatch(r"[a-f0-9]{32}", normalized["parent_run_id"]):
            raise RunEventContractError("Delegation result events need a valid parent run ID.")
        try:
            normalized["result"] = DelegationResult.model_validate(normalized.get("result")).model_dump(mode="json")
        except Exception as err:
            raise RunEventContractError(f"Invalid delegation result: {err}") from err
    if isinstance(event_type, str) and event_type.startswith("recipe_"):
        required = recipe_event_contracts.get(event_type)
        if required is None:
            raise RunEventContractError(f"Unsupported recipe run event type {event_type!r}.")
        if version != RUN_EVENT_CONTRACT_VERSION:
            raise RunEventContractError("Recipe run events require the current run event contract version.")
        missing = [key for key in required if key not in normalized]
        if missing:
            raise RunEventContractError(f"Recipe run event is missing required fields: {', '.join(missing)}.")
        if not isinstance(normalized["recipe_id"], str) or not re.fullmatch(r"[a-f0-9]{32}", normalized["recipe_id"]):
            raise RunEventContractError("Recipe run events need a valid recipe ID.")
        recipe_version = normalized["recipe_version"]
        if not isinstance(recipe_version, int) or isinstance(recipe_version, bool) or recipe_version < 1:
            raise RunEventContractError("Recipe run events need a positive recipe version.")
        if "step" in normalized and (not isinstance(normalized["step"], int) or isinstance(normalized["step"], bool) or normalized["step"] < 1):
            raise RunEventContractError("Recipe step numbers must be positive integers.")
        if event_type == "recipe_run_started" and normalized["approval_policy"] != "each_run":
            raise RunEventContractError("Unsupported recipe approval policy.")
        if "action" in normalized and (not isinstance(normalized["action"], str) or normalized["action"] not in {"click", "type", "select", "scroll", "navigate"}):
            raise RunEventContractError("Recipe run event contains an unsupported browser action.")
        if event_type == "recipe_step_started":
            observation_id = normalized["observation_id"]
            if observation_id is not None and (not isinstance(observation_id, str) or not re.fullmatch(r"[a-f0-9]{32}", observation_id)):
                raise RunEventContractError("Recipe step observation IDs must be null or valid 32-character IDs.")
        if event_type == "recipe_step_result":
            if not isinstance(normalized["status"], str) or normalized["status"] not in {"passed", "checkpoint_mismatch", "failed"}:
                raise RunEventContractError("Unsupported recipe step result status.")
            if not isinstance(normalized["checkpoint"], dict):
                raise RunEventContractError("Recipe step results need a checkpoint object.")
            for key in ("title", "url", "retrieved_at"):
                if not isinstance(normalized[key], str):
                    raise RunEventContractError(f"Recipe step result {key} must be text.")
        if event_type == "recipe_run_finished" and (not isinstance(normalized["status"], str) or normalized["status"] not in {"completed", "failed", "checkpoint_mismatch", "cancelled", "timed_out"}):
            raise RunEventContractError("Unsupported recipe run terminal status.")

        forbidden_keys = {"input", "inputs", "input_values", "value", "credentials", "password", "authorization", "cookie", "secret", "token"}

        def reject_transient_values(value: Any) -> None:
            if isinstance(value, dict):
                if forbidden_keys.intersection(str(key).lower() for key in value):
                    raise RunEventContractError("Recipe run events must not persist input values, credentials, or browser secrets.")
                for child in value.values():
                    reject_transient_values(child)
            elif isinstance(value, list):
                for child in value:
                    reject_transient_values(child)

        reject_transient_values(normalized)
    if normalized.get("type") == "error":
        error = normalized.get("error")
        if error is None:
            message = str(normalized.get("message") or "The agent run failed.")
            normalized["error"] = {
                "contract_version": RUN_EVENT_CONTRACT_VERSION,
                "code": "agent_run_error",
                "message": message,
                "retryable": False,
            }
        elif not isinstance(error, dict):
            raise RunEventContractError("The error field on a run error event must be an object.")
        else:
            error_version = error.get("contract_version", RUN_EVENT_CONTRACT_VERSION)
            if error_version != RUN_EVENT_CONTRACT_VERSION:
                raise RunEventContractError(
                    f"Unsupported error contract version {error_version!r}; this server supports version {RUN_EVENT_CONTRACT_VERSION}."
                )
            required = ("code", "message", "retryable")
            if any(key not in error for key in required) or not isinstance(error.get("retryable"), bool):
                raise RunEventContractError("A run error must include code, message, and a boolean retryable field.")
            normalized["error"] = {"contract_version": RUN_EVENT_CONTRACT_VERSION, **error}
    return normalized


class RunAlreadyExists(ValueError):
    """Raised when a caller attempts to reuse an existing run identifier."""


class RunNotFound(ValueError):
    """Raised when a cancellation request references a missing run."""


class InvalidRunRelationship(ValueError):
    """Raised when a parent, dependency, depth, or child-count constraint fails."""


class ResearchCollectionScopeError(ValueError):
    """Raised when a collection is accessed from a different task workspace."""


def _service_request(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    base_url = os.environ.get("POCKPOCK_RUN_STORE_URL", "").rstrip("/")
    if not base_url or os.environ.get("POCKPOCK_RUN_STORE_INTERNAL") == "1":
        raise RuntimeError("The run-store service is not configured")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-PockPock-Internal-Token": os.environ.get("POCKPOCK_INTERNAL_TOKEN", ""),
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(detail).get("detail")
        except (ValueError, AttributeError):
            message = None
        message = message if isinstance(message, str) and message.strip() else None
        if err.code == 409:
            if path == "/runs":
                raise RunAlreadyExists("This run ID has already been used. Start the task again.") from err
            raise ValueError(message or "The request conflicts with the run's current state.") from err
        if err.code == 404:
            raise RunNotFound(message or "Run not found") from err
        raise RuntimeError(f"Run-store service returned HTTP {err.code}: {detail[:500]}") from err
    except (URLError, TimeoutError, json.JSONDecodeError) as err:
        raise RuntimeError(f"Run-store service is unavailable: {err}") from err


def store_identity() -> str:
    """A short, path-free fingerprint of the database file this process uses for runs.

    The run-store service reports it on /health so the gateway can tell whether that service keeps
    runs in the same file the gateway would use itself.
    """
    resolved = str(Path(telemetry.DB_PATH).expanduser().resolve())
    if sys.platform in {"win32", "darwin"}:
        resolved = resolved.lower()
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


_REMOTE_CHECK_SECONDS = 30.0
_remote_check = {"at": -_REMOTE_CHECK_SECONDS, "matches": True}
_remote_check_lock = threading.Lock()


def _remote_store_matches() -> bool:
    """False only when the run-store service positively reports a different database file.

    The launchers reuse any healthy service already on the port. A run-store left over from another
    data folder (another checkout, a test run, a different LOCALAPPDATA or XDG_DATA_HOME) then held
    the runs, so history seemed to disappear after a restart and finished runs answered 404 for a
    while (issues #60, #61). An unreachable service keeps the old behaviour: the request fails loudly.
    """
    base_url = os.environ.get("POCKPOCK_RUN_STORE_URL", "").rstrip("/")
    try:
        with urlopen(f"{base_url}/health", timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return True
    remote = payload.get("store") if isinstance(payload, dict) else None
    if not isinstance(remote, str) or remote == store_identity():
        return True
    logger.warning(
        "The run-store service on %s keeps runs in a different database than this gateway; "
        "using this gateway's own run database instead. Stop the other PockPock services and start again.",
        base_url,
    )
    return False


def _use_remote_store() -> bool:
    if not os.environ.get("POCKPOCK_RUN_STORE_URL") or os.environ.get("POCKPOCK_RUN_STORE_INTERNAL") == "1":
        return False
    now = time.monotonic()
    with _remote_check_lock:
        if now - _remote_check["at"] >= _REMOTE_CHECK_SECONDS:
            _remote_check["at"] = now
            _remote_check["matches"] = _remote_store_matches()
        return _remote_check["matches"]


def initialize_agent_store() -> None:
    """Ensure the remote store is ready or create tables for local fallback."""
    if _use_remote_store():
        _service_request("/health")
        return
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS agent_runs (
            run_id TEXT PRIMARY KEY,
            conversation_id TEXT,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT ''
        )""")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(agent_runs)").fetchall()}
        if "cancel_requested_at" not in columns:
            connection.execute("ALTER TABLE agent_runs ADD COLUMN cancel_requested_at TEXT")
        if "cancel_reason" not in columns:
            connection.execute("ALTER TABLE agent_runs ADD COLUMN cancel_reason TEXT NOT NULL DEFAULT ''")
        delegation_columns = {
            "parent_run_id": "TEXT", "subtask_id": "TEXT NOT NULL DEFAULT ''", "delegate_role": "TEXT NOT NULL DEFAULT ''",
            "dependency_ids": "TEXT NOT NULL DEFAULT '[]'", "context_scope": "TEXT NOT NULL DEFAULT '[]'",
            "workspace_scope": "TEXT NOT NULL DEFAULT ''", "artifact_scope": "TEXT NOT NULL DEFAULT '[]'",
            "allowed_tools": "TEXT NOT NULL DEFAULT '[]'", "permission_level": "TEXT NOT NULL DEFAULT 'default'",
            "deadline_at": "TEXT", "max_tool_calls": "INTEGER NOT NULL DEFAULT 20",
            "max_duration_seconds": "INTEGER NOT NULL DEFAULT 900",
        }
        for name, declaration in delegation_columns.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE agent_runs ADD COLUMN {name} {declaration}")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_parent ON agent_runs(parent_run_id, created_at)")
        connection.execute("""CREATE TABLE IF NOT EXISTS agent_run_events (
            run_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (run_id, sequence),
            FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation ON agent_runs(conversation_id, created_at)")
        connection.execute("""CREATE TABLE IF NOT EXISTS agent_run_approvals (
            approval_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            action_hash TEXT NOT NULL,
            action_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            resolved_at TEXT,
            FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS research_collections (
            task_id TEXT PRIMARY KEY,
            workspace_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS research_collection_sources (
            task_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_json TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_checked_at TEXT NOT NULL,
            PRIMARY KEY (task_id, source_id)
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS research_collection_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            text TEXT NOT NULL,
            truncated INTEGER NOT NULL DEFAULT 0
        )""")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_snapshots_source "
            "ON research_collection_snapshots(task_id, source_id, snapshot_id DESC)"
        )


def create_agent_run(
    run_id: str,
    conversation_id: str | None,
    task_type: str,
    task: str,
    delegation: dict[str, Any] | None = None,
    permission_level: str | None = None,
) -> None:
    from projects.run_store.contracts import DelegationContract, delegate_task_prompt

    contract = DelegationContract.model_validate(delegation) if delegation is not None else None
    effective_permission = contract.permission_level if contract else permission_level or "auto-review"
    if contract and permission_level is not None and permission_level != contract.permission_level:
        raise InvalidRunRelationship("The child run permission must match its delegation contract.")
    if contract:
        deadline = contract.deadline_at
        if deadline.tzinfo is None:
            raise InvalidRunRelationship("Delegation deadlines must include a time zone.")
        remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0 or remaining > 24 * 60 * 60:
            raise InvalidRunRelationship("Delegation deadlines must be within the next 24 hours.")
    if _use_remote_store():
        _service_request("/runs", method="POST", payload={
            "run_id": run_id,
            "conversation_id": conversation_id,
            "task_type": task_type,
            "task": task,
            "delegation": contract.model_dump(mode="json") if contract else None,
            "permission_level": effective_permission,
        })
        return
    now = datetime.now(timezone.utc).isoformat()
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        if connection.execute("SELECT 1 FROM agent_runs WHERE run_id=?", (run_id,)).fetchone():
            raise RunAlreadyExists("This run ID has already been used. Start the task again.")
        if effective_permission not in {"default", "auto-review", "full-access"}:
            raise ValueError("Unsupported run permission level")
        if contract:
            parent = connection.execute(
                "SELECT run_id, conversation_id, parent_run_id, permission_level, status "
                "FROM agent_runs WHERE run_id=?",
                (contract.parent_run_id,),
            ).fetchone()
            if not parent:
                raise InvalidRunRelationship("The parent run does not exist.")
            if parent["status"] != "running":
                raise InvalidRunRelationship("The parent run must be active before it can create a delegate.")
            if parent["conversation_id"] != conversation_id:
                raise InvalidRunRelationship("Parent and child runs must belong to the same conversation.")
            permission_rank = {"default": 0, "auto-review": 1, "full-access": 2}
            if permission_rank[effective_permission] > permission_rank[parent["permission_level"]]:
                raise InvalidRunRelationship("A child run cannot exceed its parent's permission level.")
            approved_plan_row = connection.execute(
                "SELECT payload FROM agent_run_events WHERE run_id=? AND event_type='delegation_plan' ORDER BY sequence DESC LIMIT 1",
                (contract.parent_run_id,),
            ).fetchone()
            if not approved_plan_row:
                raise InvalidRunRelationship("The parent has no approved delegation plan.")
            approved_plan = json.loads(approved_plan_row["payload"])
            if approved_plan.get("status") != "approved":
                raise InvalidRunRelationship("The parent delegation plan has not been approved.")
            proposal = next((item for item in approved_plan.get("subtasks", []) if item.get("id") == contract.subtask_id), None)
            if not proposal:
                raise InvalidRunRelationship("The child does not match a subtask in the approved parent plan.")
            if proposal.get("role") != contract.role or not set(contract.allowed_tools).issubset(set(proposal.get("allowed_tools", []))):
                raise InvalidRunRelationship("The child role or tools exceed its approved subtask scope.")
            if (
                contract.max_tool_calls != proposal.get("max_tool_calls", 20)
                or contract.max_duration_seconds != proposal.get("max_duration_seconds", 900)
            ):
                raise InvalidRunRelationship("The child execution limits must match its approved subtask.")
            if task.strip() != delegate_task_prompt(proposal):
                raise InvalidRunRelationship("The child task must match its approved subtask instructions.")
            allowed_context = {"approved_task"}
            if proposal.get("depends_on"):
                allowed_context.add("dependency_results")
            if not set(contract.context_scope).issubset(allowed_context):
                raise InvalidRunRelationship("The child context exceeds its approved subtask scope.")
            if not set(contract.artifact_scope).issubset(set(proposal.get("artifact_scope", []))):
                raise InvalidRunRelationship("The child artifacts exceed its approved subtask scope.")
            if contract.workspace_scope != "isolated_task_workspace":
                raise InvalidRunRelationship("Delegates must use an isolated task workspace; parent workspace writes require a reviewed patch flow.")
            depth = 1
            ancestor_id = parent["parent_run_id"]
            while ancestor_id:
                depth += 1
                if depth > 3:
                    raise InvalidRunRelationship("Delegation depth cannot exceed three levels.")
                ancestor = connection.execute("SELECT parent_run_id FROM agent_runs WHERE run_id=?", (ancestor_id,)).fetchone()
                if not ancestor:
                    raise InvalidRunRelationship("The parent run has an invalid ancestor reference.")
                ancestor_id = ancestor["parent_run_id"]
            child_count = connection.execute("SELECT COUNT(*) FROM agent_runs WHERE parent_run_id=?", (contract.parent_run_id,)).fetchone()[0]
            if child_count >= 16:
                raise InvalidRunRelationship("A parent run cannot have more than 16 child runs.")
            expected_dependencies = set(proposal.get("depends_on", []))
            resolved_dependencies: set[str] = set()
            for dependency_id in contract.dependency_ids:
                dependency = connection.execute("SELECT parent_run_id, subtask_id, status FROM agent_runs WHERE run_id=?", (dependency_id,)).fetchone()
                if not dependency or dependency["parent_run_id"] != contract.parent_run_id:
                    raise InvalidRunRelationship("Every dependency must be a child of the same parent run.")
                if dependency["subtask_id"] not in expected_dependencies:
                    raise InvalidRunRelationship("A child may receive only dependency results approved for its subtask.")
                if dependency["status"] not in {"completed", "partial", "failed", "cancelled", "timed_out", "interrupted"}:
                    raise InvalidRunRelationship("A dependency must finish before its dependent child run starts.")
                resolved_dependencies.add(dependency["subtask_id"])
            if resolved_dependencies != expected_dependencies:
                raise InvalidRunRelationship("Every approved dependency must be present before the dependent child starts.")
        connection.execute(
            "INSERT INTO agent_runs(run_id, conversation_id, task_type, status, created_at, updated_at, title, parent_run_id, subtask_id, delegate_role, dependency_ids, context_scope, workspace_scope, artifact_scope, allowed_tools, permission_level, deadline_at, max_tool_calls, max_duration_seconds) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, conversation_id, task_type, "running", now, now, task.strip()[:160], contract.parent_run_id if contract else None,
             contract.subtask_id if contract else "", contract.role if contract else "", json.dumps(contract.dependency_ids) if contract else "[]",
             json.dumps(contract.context_scope) if contract else "[]", contract.workspace_scope if contract else "",
             json.dumps(contract.artifact_scope) if contract else "[]", json.dumps(contract.allowed_tools) if contract else "[]",
             effective_permission, contract.deadline_at.isoformat() if contract else None,
             contract.max_tool_calls if contract else 20, contract.max_duration_seconds if contract else 900),
        )


def claim_delegate_execution(run_id: str, parent_run_id: str) -> bool:
    """Atomically allow exactly one gateway execution attempt for an approved child run."""
    if _use_remote_store():
        result = _service_request(
            f"/runs/{quote(run_id, safe='')}/delegate/claim",
            method="POST",
            payload={"parent_run_id": parent_run_id},
        )
        return result.get("claimed") is True
    now = datetime.now(timezone.utc).isoformat()
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        run = connection.execute(
            "SELECT parent_run_id, status FROM agent_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not run:
            raise RunNotFound("Delegate run not found")
        if run["parent_run_id"] != parent_run_id:
            raise InvalidRunRelationship("Delegate execution claim does not match the recorded parent.")
        if run["status"] != "running":
            return False
        if connection.execute(
            "SELECT 1 FROM agent_run_events WHERE run_id=? AND event_type='delegate_execution_started' LIMIT 1",
            (run_id,),
        ).fetchone():
            return False
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM agent_run_events WHERE run_id=?",
            (run_id,),
        ).fetchone()["sequence"]
        event = {
            "contract_version": RUN_EVENT_CONTRACT_VERSION,
            "type": "delegate_execution_started",
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "started_at": now,
        }
        connection.execute(
            "INSERT INTO agent_run_events(run_id, sequence, created_at, event_type, payload) VALUES (?, ?, ?, ?, ?)",
            (run_id, sequence, now, "delegate_execution_started",
             json.dumps(event, ensure_ascii=False, separators=(",", ":"))),
        )
        connection.execute("UPDATE agent_runs SET updated_at=? WHERE run_id=?", (now, run_id))
        return True


def store_agent_event(run_id: str, sequence: int, event: dict[str, Any]) -> bool:
    event = _normalize_run_event(event, for_write=True)
    if _use_remote_store():
        result = _service_request(f"/runs/{quote(run_id, safe='')}/events", method="POST", payload={"sequence": sequence, "event": event})
        return result.get("stored") is True
    now = datetime.now(timezone.utc).isoformat()
    event_type = str(event.get("type", "progress"))[:40]
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        current = connection.execute(
            "SELECT status, parent_run_id FROM agent_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not current:
            raise RunNotFound("Run not found")
        current_status = current["status"]
        terminal = {"completed", "partial", "awaiting_approval", "failed", "interrupted", "cancelled", "timed_out"}
        terminal_delegate_result = (
            event_type == "delegate_result"
            and current["parent_run_id"]
            and event.get("parent_run_id") == current["parent_run_id"]
        )
        if current_status in terminal and not terminal_delegate_result:
            return False
        if current_status == "cancelling" and event_type not in {"cancelled", "timed_out", "recipe_run_finished"}:
            return False
        if event_type == "delegate_result":
            if not terminal_delegate_result:
                raise InvalidRunRelationship("A typed delegation result must belong to a child run and its recorded parent.")
            if connection.execute(
                "SELECT 1 FROM agent_run_events WHERE run_id=? AND event_type='delegate_result' LIMIT 1",
                (run_id,),
            ).fetchone():
                return False
        connection.execute(
            "INSERT OR REPLACE INTO agent_run_events(run_id, sequence, created_at, event_type, payload) VALUES (?, ?, ?, ?, ?)",
            (run_id, sequence, now, event_type, payload),
        )
        status = current_status
        if event_type == "done":
            status = "completed" if event.get("status") not in {"partial", "awaiting_approval"} else str(event.get("status"))
        elif event_type == "error":
            # An error that says the run ended partial (for example a research answer that could
            # not be validated) is stored as partial, matching the stream (issue #53).
            status = "partial" if event.get("status") == "partial" else "failed"
        elif event_type == "cancelled":
            status = "cancelled"
        elif event_type == "timed_out":
            status = "timed_out"
        elif event_type == "interrupted":
            status = "interrupted"
        elif current_status == "running":
            status = "running"
        if status in terminal:
            connection.execute(
                "UPDATE agent_run_approvals SET status='cancelled', resolved_at=? WHERE run_id=? AND status='pending'",
                (now, run_id),
            )
        connection.execute("UPDATE agent_runs SET status=?, updated_at=? WHERE run_id=?", (status, now, run_id))
    return True


def create_agent_approval(run_id: str, approval_id: str, action_hash: str, action: dict[str, Any], expires_at: str) -> dict[str, Any]:
    if _use_remote_store():
        return _service_request(f"/runs/{quote(run_id, safe='')}/approvals", method="POST", payload={
            "approval_id": approval_id, "action_hash": action_hash, "action": action, "expires_at": expires_at,
        })
    now = datetime.now(timezone.utc).isoformat()
    action_json = json.dumps(action, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if hashlib.sha256(action_json.encode("utf-8")).hexdigest() != action_hash:
        raise ValueError("The approval hash does not match its action payload")
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        run = connection.execute("SELECT status FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if not run:
            raise RunNotFound("Run not found")
        if run["status"] != "running":
            raise ValueError("Approvals can only be requested for an active run")
        try:
            connection.execute(
                "INSERT INTO agent_run_approvals(approval_id, run_id, action_hash, action_json, status, created_at, expires_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)",
                (approval_id, run_id, action_hash, action_json, now, expires_at),
            )
        except sqlite3.IntegrityError as err:
            raise ValueError("This approval ID has already been used.") from err
    return {"approval_id": approval_id, "run_id": run_id, "action_hash": action_hash, "action": action, "status": "pending", "created_at": now, "expires_at": expires_at}


def resolve_agent_approval(run_id: str, approval_id: str, action_hash: str, decision: str) -> dict[str, Any]:
    if decision not in {"approved", "rejected"}:
        raise ValueError("Approval decision must be approved or rejected")
    if _use_remote_store():
        return _service_request(f"/runs/{quote(run_id, safe='')}/approvals/{quote(approval_id, safe='')}", method="POST", payload={
            "action_hash": action_hash, "decision": decision,
        })
    now = datetime.now(timezone.utc).isoformat()
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        approval = connection.execute(
            "SELECT * FROM agent_run_approvals WHERE approval_id=? AND run_id=?", (approval_id, run_id)
        ).fetchone()
        if not approval:
            raise RunNotFound("Approval not found")
        if approval["action_hash"] != action_hash:
            raise ValueError("The approval does not match the requested action")
        if approval["status"] != "pending":
            return {"accepted": False, "status": approval["status"]}
        if approval["expires_at"] <= now:
            connection.execute("UPDATE agent_run_approvals SET status='expired', resolved_at=? WHERE approval_id=?", (now, approval_id))
            return {"accepted": False, "status": "expired"}
        run = connection.execute("SELECT status FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if not run or run["status"] != "running":
            return {"accepted": False, "status": "run_not_active"}
        connection.execute("UPDATE agent_run_approvals SET status=?, resolved_at=? WHERE approval_id=? AND status='pending'", (decision, now, approval_id))
        return {"accepted": True, "status": decision, "approval_id": approval_id, "run_id": run_id, "action_hash": action_hash}


def expire_agent_approval(run_id: str, approval_id: str, action_hash: str) -> bool:
    if _use_remote_store():
        result = _service_request(f"/runs/{quote(run_id, safe='')}/approvals/{quote(approval_id, safe='')}/expire", method="POST", payload={"action_hash": action_hash})
        return result.get("expired") is True
    now = datetime.now(timezone.utc).isoformat()
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        result = connection.execute(
            "UPDATE agent_run_approvals SET status='expired', resolved_at=? WHERE run_id=? AND approval_id=? AND action_hash=? AND status='pending' AND expires_at<=?",
            (now, run_id, approval_id, action_hash, now),
        )
        return result.rowcount == 1


def finish_incomplete_agent_run(run_id: str) -> None:
    if _use_remote_store():
        _service_request(f"/runs/{quote(run_id, safe='')}/finish", method="POST", payload={})
        return
    now = datetime.now(timezone.utc).isoformat()
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        run = connection.execute(
            "SELECT status, cancel_requested_at, cancel_reason FROM agent_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not run or run["status"] not in {"running", "cancelling"}:
            return
        if run["cancel_requested_at"]:
            status = "timed_out" if run["cancel_reason"] == "timeout" else "cancelled"
            event_type = status
            message = "The agent run exceeded its 15-minute time limit." if status == "timed_out" else "The agent run was cancelled."
        else:
            status = "interrupted"
            event_type = "interrupted"
            message = "The agent connection ended before the run completed."
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM agent_run_events WHERE run_id=?", (run_id,)
        ).fetchone()["sequence"]
        event = {
            "contract_version": RUN_EVENT_CONTRACT_VERSION,
            "type": event_type,
            "run_id": run_id,
            "sequence": sequence,
            "message": message,
        }
        connection.execute(
            "INSERT INTO agent_run_events(run_id, sequence, created_at, event_type, payload) VALUES (?, ?, ?, ?, ?)",
            (run_id, sequence, now, event_type, json.dumps(event, ensure_ascii=False, separators=(",", ":"))),
        )
        connection.execute(
            "UPDATE agent_run_approvals SET status='cancelled', resolved_at=? WHERE run_id=? AND status='pending'",
            (now, run_id),
        )
        connection.execute("UPDATE agent_runs SET status=?, updated_at=? WHERE run_id=?", (status, now, run_id))


def recover_incomplete_agent_runs() -> int:
    """Finalize runs left active by a gateway shutdown or process crash."""
    if _use_remote_store():
        result = _service_request("/runs/recover", method="POST", payload={})
        return int(result.get("recovered", 0))
    with closing(telemetry.connect_db()) as connection, connection:
        run_ids = [row["run_id"] for row in connection.execute(
            "SELECT run_id FROM agent_runs WHERE status IN ('running', 'cancelling')"
        ).fetchall()]
    for run_id in run_ids:
        finish_incomplete_agent_run(run_id)
    return len(run_ids)


def request_agent_run_cancel(run_id: str, *, reason: str = "user") -> dict[str, Any]:
    """Persist a cancellation request; callers separately signal the live task."""
    if reason not in {"user", "timeout"}:
        raise ValueError("Cancellation reason must be user or timeout")
    if _use_remote_store():
        return _service_request(f"/runs/{quote(run_id, safe='')}/cancel", method="POST", payload={"reason": reason})
    now = datetime.now(timezone.utc).isoformat()
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        run = connection.execute("SELECT status, cancel_reason FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if not run:
            raise RunNotFound("Run not found")
        if run["status"] == "running":
            connection.execute(
                "UPDATE agent_runs SET status='cancelling', cancel_requested_at=?, cancel_reason=?, updated_at=? WHERE run_id=? AND status='running'",
                (now, reason, now, run_id),
            )
            connection.execute(
                "UPDATE agent_run_approvals SET status='cancelled', resolved_at=? WHERE run_id=? AND status='pending'",
                (now, run_id),
            )
            return {"accepted": True, "status": "cancelling", "reason": reason}
        if run["status"] == "cancelling":
            return {"accepted": True, "status": "cancelling", "reason": run["cancel_reason"] or reason}
        return {"accepted": False, "status": run["status"], "reason": "run_already_finished"}


def write_agent_task_memory(
    run_id: str,
    task: str,
    workspace: Path,
    output_dir: Path,
    plan: list[str],
    final_answer: str = "",
) -> dict[str, str]:
    """Persist a readable task journal beside the run's durable event history."""
    _, saved_events = get_run_events(run_id, 0, 1000)
    events = [entry["event"] for entry in saved_events]
    lines = [
        f"# Task memory: {task[:160]}",
        "",
        f"- Run ID: `{run_id}`",
        f"- Workspace: `{workspace}`",
        f"- Saved: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Original request",
        "",
        task,
        "",
        "## Plan",
        "",
    ]
    lines.extend(f"{index}. {step}" for index, step in enumerate(plan, 1))
    if not plan:
        lines.append("No structured plan was returned by the planner.")
    lines.extend(["", "## Work log", ""])
    for event in events:
        kind = str(event.get("type", "activity"))
        if kind == "decision":
            lines.append(f"- Selected model: {event.get('model', 'unknown')}. {event.get('reason', '')}".rstrip())
        elif kind in {"tool_start", "tool_result", "command_start", "command_result", "patch", "artifact", "error", "status", "approval_requested", "approval_approved", "approval_rejected", "approval_expired", "plan_version", "plan_decision", "plan_revision", "delegation_plan", "cancelled", "timed_out", "interrupted"}:
            details = event.get("details")
            suffix = f" — {json.dumps(details, ensure_ascii=False)}" if isinstance(details, dict) else ""
            text = str(event.get("message") or event.get("path") or event.get("command") or event.get("tool") or "")
            lines.append(f"- {kind.replace('_', ' ').title()}: {text}{suffix}".rstrip())
            if kind == "tool_start" and isinstance(event.get("input"), dict) and event["input"]:
                lines.append(f"  - Inputs: `{json.dumps(event['input'], ensure_ascii=False)[:4000]}`")
            if kind == "patch" and isinstance(event.get("diff"), str) and event["diff"]:
                lines.extend(["", "```diff", event["diff"][:30_000], "```", ""])
    if final_answer.strip():
        lines.extend(["", "## Final report", "", final_answer.strip()])
    memory_path = output_dir / "task-memory.md"
    memory_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"name": memory_path.name, "path": str(memory_path.resolve()), "kind": "memory"}


async def track_agent_stream(run_id: str, source, encode_event):
    """Persist each complete SSE event before forwarding it to the client."""
    try:
        sequence = 0
        buffer = ""
        decoder = json.JSONDecoder()
        async for frame in source:
            buffer += frame
            while "\n\n" in buffer:
                raw, buffer = buffer.split("\n\n", 1)
                data = "\n".join(line[5:].lstrip() for line in raw.splitlines() if line.startswith("data:"))
                if not data:
                    continue
                try:
                    event = decoder.decode(data)
                except (json.JSONDecodeError, TypeError):
                    continue
                sequence += 1
                event["run_id"] = run_id
                event["sequence"] = sequence
                event = _normalize_run_event(event, for_write=True)
                stored = await asyncio.to_thread(store_agent_event, run_id, sequence, event)
                if stored:
                    yield encode_event(event)
        if buffer.strip():
            data = "\n".join(line[5:].lstrip() for line in buffer.splitlines() if line.startswith("data:"))
            try:
                event = decoder.decode(data)
            except (json.JSONDecodeError, TypeError):
                return
            sequence += 1
            event["run_id"] = run_id
            event["sequence"] = sequence
            event = _normalize_run_event(event, for_write=True)
            stored = await asyncio.to_thread(store_agent_event, run_id, sequence, event)
            if stored:
                yield encode_event(event)
    finally:
        # A disconnected client leaves this generator unfinished; close the run stream too, so
        # its own cleanup marks the run finished instead of leaving it "running" (issue #41).
        close = getattr(source, "aclose", None)
        if close is not None:
            with anyio.CancelScope(shield=True):
                await close()


def list_runs_for_conversation(conversation_id: str) -> list[dict[str, Any]]:
    if _use_remote_store():
        return _service_request(f"/conversations/{quote(conversation_id, safe='')}/runs")["runs"]
    with closing(telemetry.connect_db()) as connection, connection:
        rows = connection.execute(
            "SELECT run_id, conversation_id, task_type, status, created_at, updated_at, title, parent_run_id, subtask_id, delegate_role, dependency_ids, context_scope, workspace_scope, artifact_scope, allowed_tools, permission_level, deadline_at, max_tool_calls, max_duration_seconds FROM agent_runs WHERE conversation_id=? ORDER BY created_at",
            (conversation_id,),
        ).fetchall()
    return [_decode_run(row) for row in rows]


def get_run_events(run_id: str, after: int, limit: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if _use_remote_store():
        try:
            result = _service_request(f"/runs/{quote(run_id, safe='')}/events?after={max(0, after)}&limit={max(1, min(limit, 1000))}")
        except RunNotFound:
            # Same contract as the local store: an unknown run is "no run", which callers turn into
            # a 404. Letting it escape made the gateway answer 500 (issue #66).
            return None, []
        return result.get("run"), result.get("events", [])
    with closing(telemetry.connect_db()) as connection, connection:
        run = connection.execute(
            "SELECT run_id, conversation_id, task_type, status, created_at, updated_at, title, parent_run_id, subtask_id, delegate_role, dependency_ids, context_scope, workspace_scope, artifact_scope, allowed_tools, permission_level, deadline_at, max_tool_calls, max_duration_seconds FROM agent_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if not run:
            return None, []
        rows = connection.execute(
            "SELECT sequence, created_at, payload FROM agent_run_events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?",
            (run_id, max(0, after), limit),
        ).fetchall()
    events = [{"sequence": row["sequence"], "created_at": row["created_at"], "event": _normalize_run_event(json.loads(row["payload"]), for_write=False)} for row in rows]
    return _decode_run(run), events


def _validate_research_collection_args(task_id: str, workspace_key: str) -> None:
    if not isinstance(task_id, str) or not re.fullmatch(r"[a-f0-9]{32}", task_id):
        raise ValueError("A valid task ID is required.")
    if not isinstance(workspace_key, str) or not re.fullmatch(r"[a-f0-9]{64}", workspace_key):
        raise ValueError("A valid workspace scope is required.")


def _check_research_collection_scope(connection, task_id: str, workspace_key: str):
    collection = connection.execute(
        "SELECT workspace_key, created_at, updated_at FROM research_collections WHERE task_id=?",
        (task_id,),
    ).fetchone()
    if collection is None:
        return None
    if collection["workspace_key"] != workspace_key:
        raise ResearchCollectionScopeError("The research collection belongs to a different task workspace.")
    return collection


def _research_snapshot_dict(row, *, include_text: bool = False) -> dict[str, Any] | None:
    if row is None:
        return None
    snapshot = {
        "snapshot_id": row["snapshot_id"],
        "captured_at": row["captured_at"],
        "content_hash": row["content_hash"],
        "byte_count": row["byte_count"] if "byte_count" in row.keys() else len(row["text"].encode("utf-8")),
        "truncated": bool(row["truncated"]),
    }
    if include_text:
        snapshot["text"] = row["text"]
    return snapshot


def _research_collection_for_connection(connection, task_id: str, workspace_key: str) -> dict[str, Any] | None:
    collection = _check_research_collection_scope(connection, task_id, workspace_key)
    if collection is None:
        return None
    sources = []
    rows = connection.execute(
        "SELECT source_id, source_json, notes, created_at, updated_at, last_checked_at "
        "FROM research_collection_sources WHERE task_id=? ORDER BY created_at, source_id",
        (task_id,),
    ).fetchall()
    for row in rows:
        snapshot_rows = connection.execute(
            "SELECT snapshot_id, captured_at, content_hash, length(CAST(text AS BLOB)) AS byte_count, truncated "
            "FROM research_collection_snapshots WHERE task_id=? AND source_id=? ORDER BY snapshot_id",
            (task_id, row["source_id"]),
        ).fetchall()
        sources.append({
            "source": json.loads(row["source_json"]),
            "notes": row["notes"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_checked_at": row["last_checked_at"],
            "version_count": len(snapshot_rows),
            "versions": [_research_snapshot_dict(item) for item in snapshot_rows],
            "latest": _research_snapshot_dict(snapshot_rows[-1]) if snapshot_rows else None,
        })
    return {
        "task_id": task_id,
        "created_at": collection["created_at"],
        "updated_at": collection["updated_at"],
        "sources": sources,
    }


def get_research_collection(task_id: str, workspace_key: str) -> dict[str, Any] | None:
    _validate_research_collection_args(task_id, workspace_key)
    if _use_remote_store():
        return _service_request(
            f"/research-collections/{quote(task_id, safe='')}?workspace_key={quote(workspace_key, safe='')}"
        ).get("collection")
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        return _research_collection_for_connection(connection, task_id, workspace_key)


def get_research_collection_source(
    task_id: str,
    source_id: str,
    workspace_key: str,
) -> dict[str, Any] | None:
    _validate_research_collection_args(task_id, workspace_key)
    if not isinstance(source_id, str) or not re.fullmatch(r"[a-f0-9]{64}", source_id):
        raise ValueError("A valid research source ID is required.")
    if _use_remote_store():
        return _service_request(
            f"/research-collections/{quote(task_id, safe='')}/sources/{quote(source_id, safe='')}"
            f"?workspace_key={quote(workspace_key, safe='')}"
        ).get("source")
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        if _check_research_collection_scope(connection, task_id, workspace_key) is None:
            return None
        row = connection.execute(
            "SELECT source_json, notes, created_at, updated_at, last_checked_at "
            "FROM research_collection_sources WHERE task_id=? AND source_id=?",
            (task_id, source_id),
        ).fetchone()
        if row is None:
            return None
        snapshot_rows = connection.execute(
            "SELECT snapshot_id, captured_at, content_hash, length(CAST(text AS BLOB)) AS byte_count, truncated "
            "FROM research_collection_snapshots WHERE task_id=? AND source_id=? ORDER BY snapshot_id",
            (task_id, source_id),
        ).fetchall()
        return {
            "source": json.loads(row["source_json"]),
            "notes": row["notes"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_checked_at": row["last_checked_at"],
            "versions": [_research_snapshot_dict(item) for item in snapshot_rows],
            "latest": _research_snapshot_dict(snapshot_rows[-1]) if snapshot_rows else None,
        }


def get_research_snapshot(
    task_id: str,
    source_id: str,
    snapshot_id: int,
    workspace_key: str,
) -> dict[str, Any] | None:
    _validate_research_collection_args(task_id, workspace_key)
    if not isinstance(source_id, str) or not re.fullmatch(r"[a-f0-9]{64}", source_id):
        raise ValueError("A valid research source ID is required.")
    if not isinstance(snapshot_id, int) or isinstance(snapshot_id, bool) or snapshot_id < 1:
        raise ValueError("A valid snapshot ID is required.")
    if _use_remote_store():
        return _service_request(
            f"/research-collections/{quote(task_id, safe='')}/sources/{quote(source_id, safe='')}"
            f"/snapshots/{snapshot_id}?workspace_key={quote(workspace_key, safe='')}"
        ).get("snapshot")
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        if _check_research_collection_scope(connection, task_id, workspace_key) is None:
            return None
        row = connection.execute(
            "SELECT snapshot_id, captured_at, content_hash, text, truncated "
            "FROM research_collection_snapshots WHERE task_id=? AND source_id=? AND snapshot_id=?",
            (task_id, source_id, snapshot_id),
        ).fetchone()
        return _research_snapshot_dict(row, include_text=True)


def _validate_research_snapshot(text: str, truncated: bool) -> tuple[str, str]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("A research snapshot must contain extracted text.")
    if not isinstance(truncated, bool):
        raise ValueError("The snapshot truncation flag must be boolean.")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as err:
        raise ValueError("The extracted text is not valid UTF-8.") from err
    if len(encoded) > MAX_RESEARCH_SNAPSHOT_BYTES:
        raise ValueError("A research snapshot cannot exceed 200 KB.")
    return hashlib.sha256(encoded).hexdigest(), datetime.now(timezone.utc).isoformat()


def add_research_collection_source(
    task_id: str,
    workspace_key: str,
    source_data: dict[str, Any],
    text: str,
    truncated: bool,
    notes: str = "",
) -> dict[str, Any]:
    _validate_research_collection_args(task_id, workspace_key)
    if not isinstance(notes, str) or len(notes) > MAX_RESEARCH_NOTE_CHARS:
        raise ValueError("Research notes must be at most 2,000 characters.")
    from projects.agent_tools.research_contracts import SourceRecord

    source = SourceRecord.model_validate(source_data)
    content_hash, captured_at = _validate_research_snapshot(text, truncated)
    source_json = source.model_dump_json()
    if _use_remote_store():
        return _service_request(
            f"/research-collections/{quote(task_id, safe='')}/sources",
            method="POST",
            payload={
                "workspace_key": workspace_key,
                "source": json.loads(source_json),
                "text": text,
                "truncated": truncated,
                "notes": notes,
            },
        ).get("collection")
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        if not connection.execute("SELECT 1 FROM agent_runs WHERE run_id=?", (task_id,)).fetchone():
            raise RunNotFound("Run not found")
        collection = _check_research_collection_scope(connection, task_id, workspace_key)
        if collection is None:
            connection.execute(
                "INSERT INTO research_collections(task_id, workspace_key, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (task_id, workspace_key, captured_at, captured_at),
            )
        existing = connection.execute(
            "SELECT source_json, notes FROM research_collection_sources WHERE task_id=? AND source_id=?",
            (task_id, source.source_id),
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO research_collection_sources(task_id, source_id, source_json, notes, created_at, updated_at, last_checked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (task_id, source.source_id, source_json, notes, captured_at, captured_at, captured_at),
            )
        else:
            existing_source = SourceRecord.model_validate_json(existing["source_json"])
            if existing_source.canonical_url != source.canonical_url:
                raise ValueError("The saved source ID is already bound to another URL.")
            connection.execute(
                "UPDATE research_collection_sources SET source_json=?, updated_at=?, last_checked_at=? "
                "WHERE task_id=? AND source_id=?",
                (source_json, captured_at, captured_at, task_id, source.source_id),
            )
            if notes:
                connection.execute(
                    "UPDATE research_collection_sources SET notes=? WHERE task_id=? AND source_id=?",
                    (notes, task_id, source.source_id),
                )
        latest = connection.execute(
            "SELECT content_hash FROM research_collection_snapshots "
            "WHERE task_id=? AND source_id=? ORDER BY snapshot_id DESC LIMIT 1",
            (task_id, source.source_id),
        ).fetchone()
        if latest is None or latest["content_hash"] != content_hash:
            connection.execute(
                "INSERT INTO research_collection_snapshots(task_id, source_id, captured_at, content_hash, text, truncated) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, source.source_id, captured_at, content_hash, text, int(truncated)),
            )
        connection.execute(
            "UPDATE research_collections SET updated_at=? WHERE task_id=?",
            (captured_at, task_id),
        )
    return get_research_collection(task_id, workspace_key) or {}


def add_research_collection_snapshot(
    task_id: str,
    source_id: str,
    workspace_key: str,
    source_data: dict[str, Any],
    text: str,
    truncated: bool,
) -> dict[str, Any] | None:
    _validate_research_collection_args(task_id, workspace_key)
    if not isinstance(source_id, str) or not re.fullmatch(r"[a-f0-9]{64}", source_id):
        raise ValueError("A valid research source ID is required.")
    from projects.agent_tools.research_contracts import SourceRecord

    source = SourceRecord.model_validate(source_data)
    if source.source_id != source_id:
        raise ValueError("The refreshed source ID does not match the saved source.")
    content_hash, captured_at = _validate_research_snapshot(text, truncated)
    source_json = source.model_dump_json()
    if _use_remote_store():
        return _service_request(
            f"/research-collections/{quote(task_id, safe='')}/sources/{quote(source_id, safe='')}/snapshots",
            method="POST",
            payload={
                "workspace_key": workspace_key,
                "source": json.loads(source_json),
                "text": text,
                "truncated": truncated,
            },
        )
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        if _check_research_collection_scope(connection, task_id, workspace_key) is None:
            return None
        saved = connection.execute(
            "SELECT source_json FROM research_collection_sources WHERE task_id=? AND source_id=?",
            (task_id, source_id),
        ).fetchone()
        if saved is None:
            return None
        saved_source = SourceRecord.model_validate_json(saved["source_json"])
        if saved_source.canonical_url != source.canonical_url:
            raise ValueError("A refresh cannot change the saved source URL.")
        previous_row = connection.execute(
            "SELECT snapshot_id, captured_at, content_hash, text, truncated "
            "FROM research_collection_snapshots WHERE task_id=? AND source_id=? "
            "ORDER BY snapshot_id DESC LIMIT 1",
            (task_id, source_id),
        ).fetchone()
        changed = previous_row is None or previous_row["content_hash"] != content_hash
        if changed:
            cursor = connection.execute(
                "INSERT INTO research_collection_snapshots(task_id, source_id, captured_at, content_hash, text, truncated) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, source_id, captured_at, content_hash, text, int(truncated)),
            )
            current_row = connection.execute(
                "SELECT snapshot_id, captured_at, content_hash, text, truncated "
                "FROM research_collection_snapshots WHERE snapshot_id=?",
                (cursor.lastrowid,),
            ).fetchone()
        else:
            current_row = previous_row
        connection.execute(
            "UPDATE research_collection_sources SET source_json=?, updated_at=?, last_checked_at=? "
            "WHERE task_id=? AND source_id=?",
            (source_json, captured_at, captured_at, task_id, source_id),
        )
        connection.execute(
            "UPDATE research_collections SET updated_at=? WHERE task_id=?",
            (captured_at, task_id),
        )
        return {
            "changed": changed,
            "source": source.model_dump(mode="json"),
            "previous": _research_snapshot_dict(previous_row, include_text=True),
            "current": _research_snapshot_dict(current_row, include_text=True),
        }


def update_research_collection_note(
    task_id: str,
    source_id: str,
    workspace_key: str,
    notes: str,
) -> dict[str, Any] | None:
    _validate_research_collection_args(task_id, workspace_key)
    if not isinstance(source_id, str) or not re.fullmatch(r"[a-f0-9]{64}", source_id):
        raise ValueError("A valid research source ID is required.")
    if not isinstance(notes, str) or len(notes) > MAX_RESEARCH_NOTE_CHARS:
        raise ValueError("Research notes must be at most 2,000 characters.")
    if _use_remote_store():
        return _service_request(
            f"/research-collections/{quote(task_id, safe='')}/sources/{quote(source_id, safe='')}",
            method="PATCH",
            payload={"workspace_key": workspace_key, "notes": notes},
        ).get("source")
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        if _check_research_collection_scope(connection, task_id, workspace_key) is None:
            return None
        cursor = connection.execute(
            "UPDATE research_collection_sources SET notes=?, updated_at=? WHERE task_id=? AND source_id=?",
            (notes, datetime.now(timezone.utc).isoformat(), task_id, source_id),
        )
        if cursor.rowcount != 1:
            return None
    return get_research_collection_source(task_id, source_id, workspace_key)


def delete_research_collection(task_id: str, workspace_key: str) -> bool:
    _validate_research_collection_args(task_id, workspace_key)
    if _use_remote_store():
        return _service_request(
            f"/research-collections/{quote(task_id, safe='')}?workspace_key={quote(workspace_key, safe='')}",
            method="DELETE",
        ).get("deleted") is True
    with telemetry.DB_LOCK, closing(telemetry.connect_db()) as connection, connection:
        if _check_research_collection_scope(connection, task_id, workspace_key) is None:
            return False
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("DELETE FROM research_collection_snapshots WHERE task_id=?", (task_id,))
        connection.execute("DELETE FROM research_collection_sources WHERE task_id=?", (task_id,))
        connection.execute("DELETE FROM research_collections WHERE task_id=?", (task_id,))
        return True


def _decode_run(row) -> dict[str, Any]:
    run = dict(row)
    delegation = None
    if run.get("parent_run_id"):
        delegation = {
            "parent_run_id": run["parent_run_id"], "subtask_id": run["subtask_id"], "role": run["delegate_role"],
            "dependency_ids": json.loads(run["dependency_ids"]),
            "context_scope": json.loads(run["context_scope"]),
            "workspace_scope": run["workspace_scope"], "artifact_scope": json.loads(run["artifact_scope"]),
            "allowed_tools": json.loads(run["allowed_tools"]), "permission_level": run["permission_level"],
            "deadline_at": run["deadline_at"], "max_tool_calls": run["max_tool_calls"],
            "max_duration_seconds": run["max_duration_seconds"],
        }
    run["delegation"] = delegation
    return run


def get_completed_run_event(run_id: str) -> dict[str, Any] | None:
    if _use_remote_store():
        return _service_request(f"/runs/{quote(run_id, safe='')}/done-event").get("event")
    with closing(telemetry.connect_db()) as connection, connection:
        row = connection.execute(
            "SELECT payload FROM agent_run_events WHERE run_id=? AND event_type='done' ORDER BY sequence DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    return _normalize_run_event(json.loads(row["payload"]), for_write=False) if row else None
