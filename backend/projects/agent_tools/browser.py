"""Scoped calls into the isolated local browser automation service."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit
import uuid

import aiohttp

from .common import AgentToolContext, AgentToolError
from .research import normalize_public_url


def _bounded_visible_text(value: object) -> str:
    encoded = str(value or "").encode("utf-8")[:22_000]
    return encoded.decode("utf-8", errors="ignore")


def _screenshot_extension(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    extensions = {"image/jpeg": ".jpg", "image/png": ".png"}
    extension = extensions.get(normalized)
    if extension is None:
        raise AgentToolError("The browser runtime returned an unsupported screenshot format.")
    return extension


async def browse_public_page(url: str, context: AgentToolContext) -> dict[str, object]:
    normalized = normalize_public_url(url)
    parsed = urlsplit(normalized)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or host not in context.allowed_hosts:
        raise AgentToolError("Browser navigation is limited to public hosts explicitly named in the task.")
    service_url = os.environ.get("POCKPOCK_BROWSER_AUTOMATION_URL", "http://127.0.0.1:8774").rstrip("/")
    token = os.environ.get("POCKPOCK_INTERNAL_TOKEN", "")
    if not token:
        raise AgentToolError("The local browser runtime is not configured. Restart PockPock AI after setup.")

    headers = {"X-PockPock-Internal-Token": token}
    timeout = aiohttp.ClientTimeout(total=50, connect=3)
    run_id = context.task_id
    created = False
    completed = False
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            async with session.post(
                f"{service_url}/contexts",
                json={"run_id": run_id, "visible": context.visible_browser},
            ) as response:
                payload = await response.json()
                if response.status >= 400:
                    raise AgentToolError(str(payload.get("detail", "Could not open an isolated browser context")))
                created = True
            async with session.post(
                f"{service_url}/navigate",
                json={"run_id": run_id, "url": normalized},
            ) as response:
                observation = await response.json()
                if response.status >= 400:
                    raise AgentToolError(str(observation.get("detail", "The public page could not be opened safely")))
            screenshot_ref = observation.get("screenshot_ref")
            if not isinstance(screenshot_ref, str) or not screenshot_ref.startswith(f"/evidence/{run_id}/"):
                raise AgentToolError("The browser runtime returned an invalid screenshot reference")
            async with session.get(f"{service_url}{screenshot_ref}") as response:
                if response.status >= 400:
                    raise AgentToolError("The browser screenshot could not be retrieved")
                screenshot_extension = _screenshot_extension(response.headers.get("Content-Type", ""))
                screenshot = await response.read()
            completed = True
        except aiohttp.ClientError as err:
            raise AgentToolError("The isolated browser runtime is unavailable. Check its local service health.") from err
        finally:
            if created and not completed:
                try:
                    async with session.delete(f"{service_url}/contexts/{run_id}"):
                        pass
                except aiohttp.ClientError:
                    pass

    output_dir = Path(context.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_name = f"browser-evidence-{uuid.uuid4().hex[:12]}{screenshot_extension}"
    artifact_path = output_dir / artifact_name
    artifact_path.write_bytes(screenshot)
    artifact = {
        "name": artifact_name,
        "path": str(artifact_path),
        "kind": "image",
        "url": f"/api/agents/artifacts/{run_id}/{artifact_name}",
    }
    context.artifacts.append(artifact)
    return {
        "observed": True,
        "visible": context.visible_browser,
        "name": artifact_name,
        "path": str(artifact_path),
        "kind": "image",
        "title": str(observation.get("title", ""))[:512],
        "url": str(observation.get("final_url", normalized))[:2048],
        "retrieved_at": str(observation.get("retrieved_at", ""))[:80],
        "observation_id": str(observation.get("observation_id", ""))[:32],
        "visible_text": _bounded_visible_text(observation.get("visible_text", "")),
        "screenshot_bytes": len(screenshot),
    }


async def apply_browser_action(arguments: dict[str, object], context: AgentToolContext) -> dict[str, object]:
    observation_id = arguments.get("observation_id")
    action = arguments.get("action")
    if not isinstance(observation_id, str) or not isinstance(action, str):
        raise AgentToolError("A current observation ID and typed browser action are required.")
    payload = {key: value for key, value in arguments.items() if value is not None}
    payload["run_id"] = context.task_id
    service_url = os.environ.get("POCKPOCK_BROWSER_AUTOMATION_URL", "http://127.0.0.1:8774").rstrip("/")
    token = os.environ.get("POCKPOCK_INTERNAL_TOKEN", "")
    if not token:
        raise AgentToolError("The local browser runtime is not configured. Restart PockPock AI after setup.")
    headers = {"X-PockPock-Internal-Token": token}
    timeout = aiohttp.ClientTimeout(total=50, connect=3)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            async with session.post(f"{service_url}/actions", json=payload) as response:
                observation = await response.json()
                if response.status >= 400:
                    raise AgentToolError(str(observation.get("detail", "The browser action was rejected")))
            screenshot_ref = observation.get("screenshot_ref")
            if not isinstance(screenshot_ref, str) or not screenshot_ref.startswith(f"/evidence/{context.task_id}/"):
                raise AgentToolError("The browser runtime returned an invalid screenshot reference")
            async with session.get(f"{service_url}{screenshot_ref}") as response:
                if response.status >= 400:
                    raise AgentToolError("The browser screenshot could not be retrieved")
                screenshot_extension = _screenshot_extension(response.headers.get("Content-Type", ""))
                screenshot = await response.read()
        except aiohttp.ClientError as err:
            raise AgentToolError("The isolated browser runtime is unavailable. Check its local service health.") from err
    output_dir = Path(context.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_name = f"browser-evidence-{uuid.uuid4().hex[:12]}{screenshot_extension}"
    artifact_path = output_dir / artifact_name
    artifact_path.write_bytes(screenshot)
    context.artifacts.append({
        "name": artifact_name,
        "path": str(artifact_path),
        "kind": "image",
        "url": f"/api/agents/artifacts/{context.task_id}/{artifact_name}",
    })
    action_result = observation.get("action") if isinstance(observation.get("action"), dict) else {"action": action}
    return {
        "observed": True,
        "visible": context.visible_browser,
        "action": action_result,
        "name": artifact_name,
        "path": str(artifact_path),
        "kind": "image",
        "title": str(observation.get("title", ""))[:512],
        "url": str(observation.get("final_url", ""))[:2048],
        "retrieved_at": str(observation.get("retrieved_at", ""))[:80],
        "observation_id": str(observation.get("observation_id", ""))[:32],
        "visible_text": _bounded_visible_text(observation.get("visible_text", "")),
        "screenshot_bytes": len(screenshot),
    }
