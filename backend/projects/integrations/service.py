"""Live status and enable/disable control for PockPock integrations.

The service takes every live probe as an injected callable so it never imports
the gateway server (which would be a cycle) and so tests can stub everything.
All probes are defensive: a failing probe degrades the status instead of
raising, and no probe result is ever logged, so tokens and keys cannot leak
into logs or responses.

External connectors (GitHub, Gmail, ...) keep their connection state
(account, auth method, verified flag, credential) in an account store. The
credential is write-only through this service: it is stored, never returned
in any entry dict and never logged. Only GitHub is live-verified, by calling
``GET https://api.github.com/user`` with the token; every other external
connector records the account and auth method and reports ``verified=False``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import urllib.error
import urllib.request
from typing import Any, Callable

from .catalog import CATALOG, KIND_EXTERNAL, get_integration

STATUS_CONNECTED = "connected"
STATUS_NOT_CONNECTED = "not_connected"
STATUS_NEEDS_SETUP = "needs_setup"
STATUS_DISABLED = "disabled"

# External connectors, derived from the catalog so adding one needs no
# service change. Their on/off switch lives here, like the internal
# toggleable integrations.
EXTERNAL_IDS = frozenset(item.id for item in CATALOG if item.kind == KIND_EXTERNAL)

# Integrations whose on/off switch lives here. Skills and MCP servers are
# managed on their own pages; this service deliberately has no parallel
# enable/disable system for them.
TOGGLEABLE_IDS = frozenset(
    {"ollama", "openclaw", "nemoclaw", "cloud", "research", "browser"} | EXTERNAL_IDS
)

_MANAGED_ELSEWHERE = {
    "skills": "Skills are managed on the Skills page, not here.",
    "mcp": "MCP servers are managed on the MCP servers page, not here.",
}

_DISCONNECT_ELSEWHERE = {
    "ollama": "Ollama is managed on the Services page; stop it there.",
    "openclaw": "OpenClaw is managed on the Services page; disconnect it there.",
    "nemoclaw": "NemoClaw is managed on the Services page; disconnect it there.",
    "browser": "Browser automation is managed on the Services page; stop it there.",
    "skills": "Skills are managed on the Skills page, not here.",
    "mcp": "MCP servers are managed on the MCP servers page, not here.",
}

_CONNECT_NOTE = {
    "openclaw": "OpenClaw is set up on the Services page.",
    "nemoclaw": "NemoClaw is set up on the Services page.",
    "browser": "Browser automation is set up on the Services page.",
    "skills": "Skills are installed and managed on the Skills page.",
    "mcp": "MCP servers are managed on the MCP servers page.",
}


class IntegrationError(Exception):
    """A request failed in a way the user can act on."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class GitHubTokenRejected(Exception):
    """A GitHub token was rejected by GitHub (HTTP 401/403)."""


def verify_github_token(token: str) -> str:
    """Live-check a GitHub token against ``GET /user``; return the login.

    Raises :class:`GitHubTokenRejected` on 401/403 (or an unusable
    response) and ``URLError``/``OSError`` on network failure. The token is
    only ever sent to api.github.com, never logged. Injectable through the
    service's ``github_probe`` parameter so tests never touch the network.
    """
    request = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "PockPockAgent",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        if err.code in (401, 403):
            raise GitHubTokenRejected("That token was rejected by GitHub.") from err
        raise
    if not isinstance(payload, dict) or not payload.get("login"):
        raise GitHubTokenRejected("That token was rejected by GitHub.")
    return str(payload["login"])


class MemoryEnabledStore:
    """In-memory enabled flags. The gateway wires in a settings-backed store."""

    def __init__(self) -> None:
        self._flags: dict[str, bool] = {}

    def get_enabled(self, integration_id: str) -> bool:
        return self._flags.get(integration_id, True)

    def set_enabled(self, integration_id: str, enabled: bool) -> None:
        self._flags[integration_id] = bool(enabled)


class MemoryAccountStore:
    """In-memory external-connector accounts. The gateway wires in a settings-backed store.

    ``get`` never returns the credential: entry dicts are built from it, so a
    credential can never leak into an API response. ``get_credential`` is
    for internal use only (a future verified re-check); nothing in this
    package logs its return value.
    """

    def __init__(self) -> None:
        self._accounts: dict[str, dict[str, Any]] = {}

    def get(self, integration_id: str) -> dict[str, Any] | None:
        record = self._accounts.get(integration_id)
        if record is None:
            return None
        return {
            "account": record.get("account"),
            "auth_method": record.get("auth_method"),
            "verified": bool(record.get("verified")),
        }

    def get_credential(self, integration_id: str) -> str | None:
        record = self._accounts.get(integration_id)
        return record.get("credential") if record else None

    def set(
        self,
        integration_id: str,
        account: str,
        auth_method: str,
        credential: str | None = None,
        verified: bool = False,
    ) -> None:
        self._accounts[integration_id] = {
            "account": account,
            "auth_method": auth_method,
            "credential": credential,
            "verified": bool(verified),
        }

    def clear(self, integration_id: str) -> None:
        self._accounts.pop(integration_id, None)


class IntegrationService:
    """Catalog entries plus live status, backed by injected probes.

    Probes may be plain callables or async callables; a probe returning an
    awaitable is awaited. Blocking probes run in a thread so the event loop
    is never stalled by a slow subprocess or HTTP call.
    """

    def __init__(
        self,
        *,
        ollama_tags: Callable[..., Any] | None = None,
        openclaw_status: Callable[..., Any] | None = None,
        nemoclaw_status: Callable[..., Any] | None = None,
        extensions_list: Callable[[], dict[str, Any]] | None = None,
        research_provider: Callable[[], str] | None = None,
        set_research_provider: Callable[[str], None] | None = None,
        cloud_models: Callable[[], list] | None = None,
        enabled_store: Any | None = None,
        ollama_start: Callable[..., Any] | None = None,
        browser_health: Callable[..., Any] | None = None,
        account_store: Any | None = None,
        github_probe: Callable[[str], str] | None = None,
    ) -> None:
        self._ollama_tags = ollama_tags
        self._openclaw_status = openclaw_status
        self._nemoclaw_status = nemoclaw_status
        self._extensions_list = extensions_list
        self._research_provider = research_provider
        self._set_research_provider = set_research_provider
        self._cloud_models = cloud_models
        self._enabled_store = enabled_store or MemoryEnabledStore()
        self._ollama_start = ollama_start
        self._browser_health = browser_health
        self._account_store = account_store or MemoryAccountStore()
        self._github_probe = github_probe or verify_github_token

    # ----- helpers -----

    async def _invoke(self, func: Callable[..., Any] | None, *args: Any) -> Any:
        if func is None:
            return None
        if asyncio.iscoroutinefunction(func):
            return await func(*args)
        result = await asyncio.to_thread(func, *args)
        if inspect.isawaitable(result):
            return await result
        return result

    def _enabled(self, integration_id: str) -> bool:
        try:
            return bool(self._enabled_store.get_enabled(integration_id))
        except Exception:
            return True

    def _account_fields(self, integration_id: str) -> dict[str, Any]:
        """account/auth_method/verified for an entry. Never includes a credential."""
        item = get_integration(integration_id)
        if item is None or item.kind != KIND_EXTERNAL:
            return {"account": None, "auth_method": None, "verified": False}
        try:
            record = self._account_store.get(integration_id)
        except Exception:
            record = None
        if not record:
            return {"account": None, "auth_method": None, "verified": False}
        return {
            "account": record.get("account"),
            "auth_method": record.get("auth_method"),
            "verified": bool(record.get("verified")),
        }

    def _bridge_status(self, status: Any) -> tuple[str, str]:
        """Map an OpenClaw/NemoClaw bridge status dict to (status, detail)."""
        if not isinstance(status, dict):
            return STATUS_NEEDS_SETUP, "Status is unavailable."
        detail = str(status.get("detail") or "")
        if status.get("ready"):
            return STATUS_CONNECTED, detail or "Ready."
        if not status.get("available", True):
            return STATUS_NOT_CONNECTED, detail or "Not available on this PC."
        return STATUS_NEEDS_SETUP, detail or "Not set up yet."

    async def _extensions(self) -> dict[str, Any] | None:
        try:
            result = await self._invoke(self._extensions_list)
        except Exception:
            return None
        return result if isinstance(result, dict) else None

    async def _probe(
        self, integration_id: str, extensions: dict[str, Any] | None = None
    ) -> tuple[str, str, dict[str, int]]:
        """Live (status, detail, counts) for one integration. Never raises."""
        try:
            return await self._probe_live(integration_id, extensions)
        except Exception:
            return STATUS_NEEDS_SETUP, "Status check failed.", {}

    async def _probe_live(
        self, integration_id: str, extensions: dict[str, Any] | None = None
    ) -> tuple[str, str, dict[str, int]]:
        item = get_integration(integration_id)
        if item is not None and item.kind == KIND_EXTERNAL:
            # External status comes from stored state, never a live call
            # (except the GitHub token check at connect time).
            fields = self._account_fields(integration_id)
            if not fields["account"]:
                return STATUS_NOT_CONNECTED, f"Not connected. {item.setup_hint}", {}
            if fields["verified"]:
                return STATUS_CONNECTED, f"Connected as {fields['account']} (verified with {item.name}).", {}
            return (
                STATUS_CONNECTED,
                f"Connected as {fields['account']} via {fields['auth_method']}. "
                f"Not verified against {item.name} in this build.",
                {},
            )

        if integration_id == "ollama":
            try:
                tags = await self._invoke(self._ollama_tags)
            except Exception:
                return STATUS_NOT_CONNECTED, "Ollama is not running. Connect to start it.", {}
            if not isinstance(tags, dict):
                return STATUS_NOT_CONNECTED, "Ollama is not running. Connect to start it.", {}
            models = tags.get("models") or []
            count = len(models) if isinstance(models, list) else 0
            return STATUS_CONNECTED, f"{count} local model{'s' if count != 1 else ''} installed.", {"models": count}

        if integration_id in {"openclaw", "nemoclaw"}:
            func = self._openclaw_status if integration_id == "openclaw" else self._nemoclaw_status
            status, detail = self._bridge_status(await self._invoke(func))
            return status, detail, {}

        if integration_id == "cloud":
            models = await self._invoke(self._cloud_models) or []
            count = len(models) if isinstance(models, list) else 0
            if count:
                return STATUS_CONNECTED, f"{count} cloud model{'s' if count != 1 else ''} connected.", {"models": count}
            return STATUS_NOT_CONNECTED, "No cloud models are connected. Add a provider on the Cloud page.", {"models": 0}

        if integration_id == "research":
            provider = await self._invoke(self._research_provider) or "disabled"
            if provider != "disabled":
                return STATUS_CONNECTED, "Public research is enabled (named-host fetcher).", {}
            return STATUS_NOT_CONNECTED, "Public research is disabled.", {}

        if integration_id == "browser":
            if self._browser_health is None:
                return STATUS_NEEDS_SETUP, "Browser automation is not configured on this gateway.", {}
            health = await self._invoke(self._browser_health)
            if isinstance(health, dict) and health.get("ok"):
                return STATUS_CONNECTED, "Browser automation service is running.", {}
            return STATUS_NEEDS_SETUP, "Browser automation service did not answer.", {}

        if integration_id in {"skills", "mcp"}:
            if extensions is None:
                extensions = await self._extensions()
            if extensions is None:
                return STATUS_NEEDS_SETUP, "Extension status is unavailable.", {}
            skills = extensions.get("skills") or []
            builtin = extensions.get("builtin_skills") or []
            servers = extensions.get("mcp") or []
            counts = {
                "skills": len(skills) + len(builtin) if isinstance(skills, list) and isinstance(builtin, list) else 0,
                "mcp_servers": len(servers) if isinstance(servers, list) else 0,
            }
            if extensions.get("openclaw_ready"):
                return (
                    STATUS_CONNECTED,
                    f"{counts['skills']} skill{'s' if counts['skills'] != 1 else ''}, "
                    f"{counts['mcp_servers']} MCP server{'s' if counts['mcp_servers'] != 1 else ''}.",
                    counts,
                )
            return STATUS_NEEDS_SETUP, str(extensions.get("detail") or "OpenClaw is not ready."), counts

        return STATUS_NEEDS_SETUP, "Unknown integration.", {}

    async def _entry(
        self, integration_id: str, extensions: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        item = get_integration(integration_id)
        if item is None:  # pragma: no cover - callers validate first
            raise IntegrationError(f"Unknown integration: {integration_id}", 404)
        account_fields = self._account_fields(integration_id)
        enabled = self._enabled(integration_id)
        if not enabled:
            return {**item.to_dict(), **account_fields, "status": STATUS_DISABLED, "detail": "Disabled. Turn it on to use it again.", "enabled": False, "counts": {}}
        status, detail, counts = await self._probe(integration_id, extensions)
        return {**item.to_dict(), **account_fields, "status": status, "detail": detail, "enabled": True, "counts": counts}

    def _require_known(self, integration_id: str) -> None:
        if get_integration(integration_id) is None:
            raise IntegrationError(f"Unknown integration: {integration_id}", 404)

    # ----- public API -----

    async def list_integrations(self) -> list[dict[str, Any]]:
        """Every catalog entry with live status. Extensions are fetched once."""
        extensions = await self._extensions()
        entries = await asyncio.gather(*(self._entry(item.id, extensions) for item in CATALOG))
        return list(entries)

    async def get(self, integration_id: str) -> dict[str, Any]:
        self._require_known(integration_id)
        return await self._entry(integration_id)

    async def set_enabled(self, integration_id: str, enabled: bool) -> dict[str, Any]:
        self._require_known(integration_id)
        if integration_id not in TOGGLEABLE_IDS:
            raise IntegrationError(_MANAGED_ELSEWHERE[integration_id], 409)
        self._enabled_store.set_enabled(integration_id, bool(enabled))
        return await self._entry(integration_id)

    async def connect(
        self,
        integration_id: str,
        account: str | None = None,
        auth_method: str | None = None,
        credential: str | None = None,
    ) -> dict[str, Any]:
        """Perform the integration's connect step, then return fresh status.

        For external connectors the optional ``account``/``auth_method``/
        ``credential`` come from the connect form. The credential is stored
        only after a successful verification (GitHub) and is never returned.
        """
        self._require_known(integration_id)
        if not self._enabled(integration_id):
            raise IntegrationError("That integration is disabled. Turn it on before connecting.", 409)
        item = get_integration(integration_id)
        if item is not None and item.kind == KIND_EXTERNAL:
            return await self._connect_external(item, account, auth_method, credential)
        note = ""
        started = None
        if integration_id == "ollama":
            if self._ollama_start is None:
                raise IntegrationError("Ollama cannot be started from here.", 409)
            try:
                result = await self._invoke(self._ollama_start)
            except Exception as err:
                raise IntegrationError(f"Could not start Ollama: {err}", 503) from err
            started = bool(result.get("started")) if isinstance(result, dict) else False
            note = "Ollama started." if started else "Ollama was already running."
        elif integration_id == "research":
            if self._set_research_provider is None:
                raise IntegrationError("The research provider cannot be changed from here.", 409)
            await self._invoke(self._set_research_provider, "named_host_fetcher")
            note = "Public research enabled (named-host fetcher). Requests leave this PC."
        elif integration_id == "cloud":
            note = "Cloud models re-checked. Connect a provider on the Cloud page."
        else:
            note = _CONNECT_NOTE[integration_id]
        entry = await self._entry(integration_id)
        entry["note"] = note
        if started is not None:
            entry["started"] = started
        return entry

    async def _connect_external(
        self,
        item: Any,
        account: str | None,
        auth_method: str | None,
        credential: str | None,
    ) -> dict[str, Any]:
        steps = " ".join(item.connect_steps)
        if item.id == "github":
            if not credential:
                raise IntegrationError(
                    f"GitHub needs a personal access token. {steps}", 409
                )
            try:
                login = await self._invoke(self._github_probe, credential)
            except GitHubTokenRejected as err:
                # Rejected token: store nothing.
                raise IntegrationError(str(err), 409) from err
            except Exception as err:
                raise IntegrationError(
                    f"GitHub could not be reached: {err}", 503
                ) from err
            self._account_store.set(item.id, login, "api_token", credential, verified=True)
            entry = await self._entry(item.id)
            entry["note"] = f"Connected as {login} (verified with GitHub)."
            return entry
        if not account or not auth_method:
            raise IntegrationError(
                f"{item.name} needs an account and auth method. {steps}", 409
            )
        # No live OAuth in this build: record the connection, unverified.
        # A credential, if one was supplied, is not stored unverified.
        self._account_store.set(item.id, account, auth_method, None, verified=False)
        entry = await self._entry(item.id)
        entry["note"] = (
            f"Connected as {account} via {auth_method}. "
            f"Not verified against {item.name} in this build — "
            "add credentials in Settings to verify."
        )
        return entry

    async def disconnect(self, integration_id: str) -> dict[str, Any]:
        self._require_known(integration_id)
        if not self._enabled(integration_id):
            raise IntegrationError("That integration is disabled. Turn it on before disconnecting.", 409)
        item = get_integration(integration_id)
        if item is not None and item.kind == KIND_EXTERNAL:
            self._account_store.clear(integration_id)
            entry = await self._entry(integration_id)
            entry["note"] = f"Disconnected from {item.name}."
            return entry
        if integration_id == "research":
            if self._set_research_provider is None:
                raise IntegrationError("The research provider cannot be changed from here.", 409)
            await self._invoke(self._set_research_provider, "disabled")
            entry = await self._entry(integration_id)
            entry["note"] = "Public research disabled."
            return entry
        if integration_id == "cloud":
            self._enabled_store.set_enabled(integration_id, False)
            entry = await self._entry(integration_id)
            entry["note"] = "Cloud models disabled."
            return entry
        raise IntegrationError(_DISCONNECT_ELSEWHERE[integration_id], 409)
