"""Preview, install, list and remove agent extensions (skills and MCP servers) for OpenClaw.

Nothing from a pasted link is installed or run by ``inspect``. It returns a proposal the user
must approve; ``install`` then applies exactly that proposal, identified by its id.

Skills are copied into OpenClaw's managed skills folder. MCP servers run in Local MCP
(``projects/mcp_hub``), which keeps their keys; OpenClaw's config gets only the server's local address
on the hub and the hub's token. Servers using the older SSE transport are still saved in OpenClaw's
config directly. PockPock records what it installed in ``~/.openclaw/pockpock/extensions.json``
(``"hub": true`` for a server in Local MCP) and only ever replaces or removes those entries.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import mcp_probe
from .hub_client import HubClient
from .sources import (
    LAUNCHERS,
    README_ORIGIN,
    SLUG,
    Fetcher,
    Link,
    McpCandidate,
    SkillCandidate,
    Snapshot,
    SourceError,
    extract_skill,
    fetch_archive,
    find_mcp,
    find_mcp_folders,
    find_skills,
    local_candidate,
    parse_link,
    remote_candidate,
)

PROPOSAL_TTL_SECONDS = 15 * 60
MAX_PROPOSALS = 4
MAX_ARGS = 40
MAX_ARG_CHARS = 500
MAX_SECRET_CHARS = 4000
GATEWAY_TIMEOUT_SECONDS = 60
SERVER_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
HELPER_PATH = Path(__file__).with_name("gateway_config.mjs")
# What OpenClaw's gateway shows instead of a secret value.
REDACTED = "__OPENCLAW_REDACTED__"


class ExtensionError(Exception):
    """A request failed in a way the user can act on."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass
class Proposal:
    id: str
    created: float
    link: Link
    kind: str  # "skills" or "mcp"
    skills: list[SkillCandidate]
    mcp: McpCandidate | None
    commit: str = ""
    archive: Path | None = None
    # Sub-folders that each document their own MCP server (issue #64).
    mcp_folders: list[dict[str, str]] | None = None


def args_hint(mcp: McpCandidate) -> str:
    """What the user must add before a server can start, when PockPock can tell (issue #65)."""
    if mcp.transport != "stdio":
        return ""
    if any("server-filesystem" in arg for arg in mcp.args):
        folders = [arg for arg in mcp.args if not arg.startswith("-") and "server-filesystem" not in arg]
        if not folders:
            return "This server needs at least one folder it may read and write. Add each folder as its own line."
        return "Replace the example folders with folders on this PC the server may read and write."
    return ""


class GatewayConfig:
    """Runs the Node helper that edits OpenClaw's MCP server list through its gateway."""

    def __init__(self, node: str = "node"):
        self.node = node

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        node = shutil.which(self.node)
        if not node:
            raise ExtensionError("node_missing", "Node.js is not installed, so PockPock cannot reach OpenClaw.", 503)
        try:
            completed = subprocess.run(
                [node, str(HELPER_PATH)], input=json.dumps(request).encode("utf-8"), capture_output=True,
                timeout=GATEWAY_TIMEOUT_SECONDS, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as err:
            raise ExtensionError("gateway_timeout", "The OpenClaw gateway did not answer in time.", 504) from err
        lines = completed.stdout.decode("utf-8", "replace").strip().splitlines()
        try:
            result = json.loads(lines[-1]) if lines else {}
        except ValueError:
            result = {}
        if not isinstance(result, dict) or not result.get("ok"):
            code = str(result.get("code") or "gateway_failed") if isinstance(result, dict) else "gateway_failed"
            message = str(result.get("message") or "PockPock could not reach the OpenClaw gateway.") if isinstance(result, dict) else "PockPock could not reach the OpenClaw gateway."
            raise ExtensionError(code, message, 409 if code == "exists" else 404 if code == "not_found" else 503 if code in {"gateway_offline", "not_installed"} else 502)
        return result


def default_state_dir() -> Path:
    configured = os.environ.get("OPENCLAW_STATE_DIR", "").strip()
    return Path(configured) if configured else Path.home() / ".openclaw"


class ExtensionService:
    def __init__(
        self,
        state_dir: Path | None = None,
        fetch: Fetcher = fetch_archive,
        gateway: GatewayConfig | None = None,
        probe_stdio: Callable[[str, list[str], dict[str, str]], list[dict[str, str]]] = mcp_probe.probe_stdio,
        probe_http: Callable[[str, dict[str, str]], list[dict[str, str]]] = mcp_probe.probe_http,
        clock: Callable[[], float] = time.monotonic,
        hub: HubClient | None = None,
    ):
        self.state_dir = state_dir or default_state_dir()
        self.skills_dir = self.state_dir / "skills"
        self.manifest_path = self.state_dir / "pockpock" / "extensions.json"
        self.fetch = fetch
        self.gateway = gateway or GatewayConfig()
        self.probe_stdio = probe_stdio
        self.probe_http = probe_http
        self.clock = clock
        self.hub = hub or HubClient()
        self._proposals: dict[str, Proposal] = {}
        self._lock = threading.Lock()
        self._install_lock = threading.Lock()

    # ----- manifest -----

    def _read_manifest(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        result: dict[str, dict[str, Any]] = {"skills": {}, "mcp": {}}
        for section in result:
            entries = data.get(section) if isinstance(data, dict) else None
            if isinstance(entries, dict):
                result[section] = {str(key): value for key, value in entries.items() if isinstance(value, dict)}
        return result

    def _write_manifest(self, manifest: dict[str, dict[str, Any]]) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, **manifest}, indent=2), encoding="utf-8")
        os.replace(temporary, self.manifest_path)

    # ----- proposals -----

    def _discard(self, proposal: Proposal) -> None:
        if proposal.archive:
            try:
                proposal.archive.unlink(missing_ok=True)
            except OSError:
                pass

    def _store(self, proposal: Proposal) -> None:
        with self._lock:
            now = self.clock()
            for key in [key for key, item in self._proposals.items() if now - item.created > PROPOSAL_TTL_SECONDS]:
                self._discard(self._proposals.pop(key))
            while len(self._proposals) >= MAX_PROPOSALS:
                self._discard(self._proposals.pop(next(iter(self._proposals))))
            self._proposals[proposal.id] = proposal

    def _take(self, proposal_id: str) -> Proposal:
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if not proposal or self.clock() - proposal.created > PROPOSAL_TTL_SECONDS:
                raise ExtensionError("expired", "That preview has expired. Paste the link again.", 410)
            return proposal

    def cancel(self, proposal_id: str) -> None:
        with self._lock:
            proposal = self._proposals.pop(proposal_id, None)
        if proposal:
            self._discard(proposal)

    # ----- inspect -----

    def inspect(self, url: str, prefer: str | None = None) -> dict[str, Any]:
        """Describe what installing ``url`` would do. Downloads from GitHub only; runs nothing.

        A repository can hold both skills and an MCP server. ``prefer`` ("skills" or "mcp")
        picks one; otherwise a server documented in the README wins, because repositories
        that are only skill collections do not document one.
        """
        also = ""
        try:
            link = parse_link(url)
            if link.kind == "remote":
                proposal = Proposal(secrets.token_urlsafe(16), self.clock(), link, "mcp", [], remote_candidate(link))
            elif link.kind == "local":
                proposal = Proposal(secrets.token_urlsafe(16), self.clock(), link, "mcp", [], local_candidate(link))
            else:
                data = self.fetch(link)
                snapshot = Snapshot(data, link)
                skills = find_skills(snapshot)
                mcp = find_mcp(snapshot)
                folders = find_mcp_folders(snapshot) if not mcp else []
                if not skills and not mcp:
                    if folders:
                        names = ", ".join(item["name"] for item in folders[:8])
                        raise SourceError(
                            "choose_folder",
                            f"This repository holds {len(folders)} MCP servers, each in its own folder ({names}"
                            f"{', …' if len(folders) > 8 else ''}). Paste the link to the folder of the one you want.",
                            422,
                        )
                    raise SourceError(
                        "unrecognized",
                        "PockPock found no skill (a folder with a SKILL.md file) and no MCP server setup in that repository.",
                        422,
                    )
                if skills and mcp:
                    kind = prefer if prefer in {"skills", "mcp"} else "mcp" if mcp.origin == README_ORIGIN else "skills"
                    also = "skills" if kind == "mcp" else "mcp"
                else:
                    kind = "skills" if skills else "mcp"
                proposal = Proposal(secrets.token_urlsafe(16), self.clock(), link, kind, skills, mcp, snapshot.commit, mcp_folders=folders)
                if kind == "skills":
                    folder = Path(tempfile.gettempdir()) / "pockpock-extensions"
                    folder.mkdir(parents=True, exist_ok=True)
                    proposal.archive = folder / f"{proposal.id}.zip"
                    proposal.archive.write_bytes(data)
        except SourceError as err:
            raise ExtensionError(err.code, str(err), err.status_code) from err
        self._store(proposal)
        return {**self._describe(proposal), "also": also}

    def _describe(self, proposal: Proposal) -> dict[str, Any]:
        manifest = self._read_manifest()
        link = proposal.link
        source = link.url + (f"/tree/{link.ref}/{link.path}".rstrip("/") if link.ref else "")
        view: dict[str, Any] = {
            "id": proposal.id,
            "kind": proposal.kind,
            "source": source,
            "commit": proposal.commit,
            "expires_in": PROPOSAL_TTL_SECONDS,
            "mcp_folders": (proposal.mcp_folders or [])[:30],
        }
        if proposal.kind == "skills":
            view["skills"] = [{
                "slug": skill.slug,
                "name": skill.name,
                "description": skill.description,
                "path": skill.path,
                "files": skill.files,
                "size": skill.size,
                "has_scripts": skill.has_scripts,
                "adds_header": skill.adds_header,
                "installed": skill.slug in manifest["skills"],
                "conflict": skill.slug not in manifest["skills"] and (self.skills_dir / skill.slug).exists(),
            } for skill in proposal.skills]
        else:
            mcp = proposal.mcp
            assert mcp is not None
            view["mcp"] = {
                "name": mcp.name,
                "transport": mcp.transport,
                "command": mcp.command,
                "args": list(mcp.args),
                "env_keys": list(mcp.env),
                "url": mcp.url,
                "origin": mcp.origin,
                "launcher_available": bool(shutil.which(mcp.command)) if mcp.command else True,
                "installed": mcp.name in manifest["mcp"],
                "args_hint": args_hint(mcp),
            }
        return view

    # ----- install -----

    def install(
        self,
        proposal_id: str,
        skills: list[str] | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        authorization: str | None = None,
    ) -> dict[str, Any]:
        proposal = self._take(proposal_id)
        if not self._install_lock.acquire(blocking=False):
            raise ExtensionError("busy", "Another install is still running. Wait for it to finish.", 409)
        try:
            if proposal.kind == "skills":
                result = self._install_skills(proposal, skills)
            else:
                result = self._install_mcp(proposal, args, env or {}, authorization or "")
        finally:
            self._install_lock.release()
        self.cancel(proposal_id)
        return result

    def _install_skills(self, proposal: Proposal, selected: list[str] | None) -> dict[str, Any]:
        available = {skill.slug: skill for skill in proposal.skills}
        chosen = list(dict.fromkeys(selected)) if selected is not None else list(available)
        if not chosen or any(slug not in available for slug in chosen):
            raise ExtensionError("invalid_selection", "Choose at least one skill from the preview.")
        manifest = self._read_manifest()
        for slug in chosen:
            if slug not in manifest["skills"] and (self.skills_dir / slug).exists():
                raise ExtensionError("conflict", f"OpenClaw already has a skill named \"{slug}\" that PockPock did not install. Remove it first.", 409)
        try:
            snapshot = Snapshot(proposal.archive.read_bytes() if proposal.archive else b"", proposal.link)
        except (OSError, SourceError) as err:
            raise ExtensionError("expired", "That preview has expired. Paste the link again.", 410) from err
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        installed = []
        for slug in chosen:
            skill = available[slug]
            staging = self.skills_dir / f".pockpock-staging-{secrets.token_hex(6)}"
            try:
                extract_skill(snapshot, skill, staging)
                destination = self.skills_dir / slug
                if destination.exists():
                    shutil.rmtree(destination)
                os.replace(staging, destination)
            except SourceError as err:
                raise ExtensionError(err.code, str(err), err.status_code) from err
            except OSError as err:
                raise ExtensionError("write_failed", f"Could not write the skill \"{slug}\" to OpenClaw's skills folder.", 500) from err
            finally:
                shutil.rmtree(staging, ignore_errors=True)
            manifest["skills"][slug] = {
                "name": skill.name,
                "description": skill.description,
                "source": proposal.link.url,
                "path": skill.path,
                "commit": proposal.commit,
                "installed_at": int(time.time()),
            }
            self._write_manifest(manifest)
            installed.append({"slug": slug, "name": skill.name})
        return {"kind": "skills", "installed": installed}

    def _install_mcp(self, proposal: Proposal, args: list[str] | None, env: dict[str, str], authorization: str) -> dict[str, Any]:
        mcp = proposal.mcp
        assert mcp is not None
        if not SERVER_NAME.fullmatch(mcp.name):
            raise ExtensionError("invalid_name", "PockPock could not derive a valid name for this server.")
        manifest = self._read_manifest()
        tools: list[dict[str, str]] | None
        try:
            if mcp.transport == "stdio":
                if mcp.command not in LAUNCHERS:
                    raise ExtensionError("launcher_refused", f"PockPock does not start MCP servers with `{mcp.command}`.")
                final_args = list(mcp.args) if args is None else [str(arg) for arg in args]
                if len(final_args) > MAX_ARGS or any(not arg or len(arg) > MAX_ARG_CHARS or "\x00" in arg for arg in final_args):
                    raise ExtensionError("invalid_args", "The arguments are not valid. Use one argument per line, with no empty lines.")
                final_env = {}
                for key, value in env.items():
                    if key not in mcp.env:
                        raise ExtensionError("invalid_env", f"\"{key}\" is not a setting this server asked for.")
                    if not isinstance(value, str) or len(value) > MAX_SECRET_CHARS or "\x00" in value:
                        raise ExtensionError("invalid_env", f"The value for {key} is not valid.")
                    if value.strip():
                        final_env[key] = value.strip()
                tools = self.probe_stdio(mcp.command, final_args, final_env)
                server: dict[str, Any] = {"command": mcp.command, "args": final_args}
                if final_env:
                    server["env"] = final_env
                hub_definition: dict[str, Any] | None = {"transport": "stdio", "command": mcp.command, "args": final_args, "env": final_env}
            else:
                headers = {}
                if authorization.strip():
                    if len(authorization) > MAX_SECRET_CHARS or any(ord(char) < 32 for char in authorization):
                        raise ExtensionError("invalid_header", "The Authorization value is not valid.")
                    headers["Authorization"] = authorization.strip()
                # The older SSE transport is saved without a test connection.
                tools = self.probe_http(mcp.url, headers) if mcp.transport == "streamable-http" else None
                server = {"url": mcp.url, "transport": mcp.transport}
                if headers:
                    server["headers"] = headers
                # Local MCP speaks streamable HTTP to remote servers; the older SSE transport stays in OpenClaw.
                hub_definition = {"transport": "streamable-http", "url": mcp.url, "headers": headers} if mcp.transport == "streamable-http" else None
        except mcp_probe.ProbeError as err:
            message = str(err)
            if re.search(r"allowed director", message, re.I):
                message += " Add at least one folder the server may use as the last argument, one per line, then try again."
            raise ExtensionError("connect_failed", message, 502) from err
        replacing = mcp.name in manifest["mcp"]
        if hub_definition is not None:
            if not replacing and mcp.name in (self.gateway.run({"op": "mcp_list"}).get("servers") or {}):
                raise ExtensionError("exists", f"OpenClaw already has an MCP server named \"{mcp.name}\".", 409)
            server = self.hub.put(mcp.name, {**hub_definition, "source": proposal.link.url})["client"]
            try:
                self.gateway.run({"op": "mcp_set", "name": mcp.name, "server": server, "replace": replacing})
            except ExtensionError:
                if not replacing:
                    try:
                        self.hub.remove(mcp.name)
                    except ExtensionError:
                        pass
                raise
        else:
            self.gateway.run({"op": "mcp_set", "name": mcp.name, "server": server, "replace": replacing})
        manifest["mcp"][mcp.name] = {"source": proposal.link.url, "installed_at": int(time.time()), "hub": hub_definition is not None}
        self._write_manifest(manifest)
        return {"kind": "mcp", "name": mcp.name, "verified": tools is not None, "tools": tools or [], "local": hub_definition is not None}

    # ----- list and remove -----

    def list(self) -> dict[str, Any]:
        manifest = self._read_manifest()
        skills = [{
            "slug": slug,
            "name": str(entry.get("name") or slug),
            "description": str(entry.get("description") or ""),
            "source": str(entry.get("source") or ""),
            "missing": not (self.skills_dir / slug / "SKILL.md").is_file(),
            "enabled": True,
        } for slug, entry in manifest["skills"].items() if SLUG.fullmatch(slug)]
        builtin: list[dict[str, Any]] = []
        servers: list[dict[str, Any]] = []
        detail = ""
        hub_detail = ""
        try:
            in_hub = {str(item.get("name")): item for item in self.hub.servers()}
        except ExtensionError as err:
            in_hub, hub_detail = {}, str(err)
        try:
            # OpenClaw knows each skill by the name in its SKILL.md, which may differ from the folder.
            known = self.gateway.run({"op": "skills_list"}).get("skills") or []
            by_name = {str(item.get("name")): item for item in known if isinstance(item, dict)}
            for skill in skills:
                match = by_name.pop(skill["slug"], None) or by_name.pop(skill["name"], None)
                if match:
                    skill["key"] = str(match.get("key") or skill["slug"])
                    skill["enabled"] = not match.get("disabled")
            for item in by_name.values():
                # OpenClaw keeps listing a removed skill for a short while; do not show it.
                if item.get("source") == "openclaw-managed" and not (self.skills_dir / str(item.get("name") or "")).is_dir():
                    continue
                builtin.append({
                    "key": str(item.get("key") or item.get("name") or ""),
                    "name": str(item.get("name") or ""),
                    "description": str(item.get("description") or ""),
                    "enabled": not item.get("disabled"),
                    # OpenClaw reports a switched-off skill as not eligible; it is still usable once
                    # switched back on unless it also lacks something it needs.
                    "ready": bool(item.get("eligible")) or (bool(item.get("disabled")) and not item.get("missing")),
                    "needs": [str(need) for need in item.get("missing") or []],
                })
            configured = self.gateway.run({"op": "mcp_list"}).get("servers") or {}
            for name, server in configured.items():
                if name == "pockpock-connectors":
                    continue  # PockPock's own connector tools; managed on the Connectors page
                local = bool(manifest["mcp"].get(name, {}).get("hub"))
                hub_entry = in_hub.get(name) if local else None
                servers.append({
                    "name": name,
                    "transport": (hub_entry or {}).get("transport") or server.get("transport"),
                    # For a server in Local MCP, what it runs (not the hub's address): shown, and used for tool retrieval.
                    "target": (hub_entry or {}).get("target") or server.get("url") or " ".join([str(server.get("command") or ""), *map(str, server.get("args") or [])]).strip(),
                    "source": str(manifest["mcp"].get(name, {}).get("source") or ""),
                    "managed": name in manifest["mcp"],
                    "enabled": server.get("enabled") is not False,
                    "local": local,
                    # running | stopped (starts on first use) | error | off | unavailable (Local MCP is not running)
                    "state": (hub_entry or {}).get("state") or ("unavailable" if local else ""),
                    "state_detail": (hub_entry or {}).get("detail") or (hub_detail if local else ""),
                    "tools": (hub_entry or {}).get("tools"),
                })
        except ExtensionError as err:
            detail = str(err)
        builtin.sort(key=lambda item: (not item["ready"], item["name"]))
        return {"skills": skills, "builtin_skills": builtin, "mcp": servers, "openclaw_ready": not detail, "detail": detail,
                "local_mcp": {"running": not hub_detail, "detail": hub_detail}}

    # ----- Local MCP -----

    def _local(self, name: str) -> None:
        if not SERVER_NAME.fullmatch(name or "") or not self._read_manifest()["mcp"].get(name, {}).get("hub"):
            raise ExtensionError("not_found", "There is no server with that name in Local MCP.", 404)

    def restart_mcp(self, name: str) -> dict[str, Any]:
        """Starts the server again now and says whether it started."""
        self._local(name)
        return self.hub.restart(name)

    def mcp_log(self, name: str) -> list[str]:
        self._local(name)
        return self.hub.log(name)

    def sync_local_mcp(self) -> dict[str, Any]:
        """Moves servers PockPock installed into Local MCP and keeps OpenClaw pointed at it.

        - A server installed before Local MCP (stdio or streamable HTTP) is read from OpenClaw's config,
          saved in Local MCP with its keys, and OpenClaw's entry is replaced by the hub's address and token,
          so the keys leave OpenClaw's config. Its on/off switch is kept.
        - A server already in Local MCP whose OpenClaw entry differs from the hub's (another port or
          token) is pointed at the hub again.
        - A server in Local MCP that PockPock no longer lists (removed while Local MCP was stopped) is removed.
        Raises ``ExtensionError`` when Local MCP or OpenClaw is not reachable; the caller tries again later.
        """
        with self._install_lock:
            manifest = self._read_manifest()
            in_hub = {str(item.get("name")) for item in self.hub.servers()}
            configured = self.gateway.run({"op": "mcp_list"}).get("servers") or {}
            moved, repointed, removed, lost = [], [], [], []
            for name, entry in list(manifest["mcp"].items()):
                current = configured.get(name)
                if not SERVER_NAME.fullmatch(name) or current is None:
                    continue
                if entry.get("hub"):
                    if name not in in_hub:
                        lost.append(name)  # Local MCP's data was deleted; the server must be added again
                        continue
                    wanted = self.hub.client(name)
                    exported = self.gateway.run({"op": "mcp_export", "name": name}).get("server") or {}
                    if exported.get("url") != wanted.get("url") or (exported.get("headers") or {}) != wanted.get("headers"):
                        self.gateway.run({"op": "mcp_set", "name": name, "server": {**wanted, **({} if current.get("enabled", True) else {"enabled": False})}, "replace": True})
                        repointed.append(name)
                    continue
                if current.get("transport") not in {"stdio", "streamable-http"}:
                    continue  # SSE servers stay in OpenClaw
                exported = self.gateway.run({"op": "mcp_export", "name": name}).get("server") or {}
                if REDACTED in json.dumps(exported):
                    lost.append(name)  # only a hidden copy of its keys could be read; never save that
                    continue
                enabled = exported.get("enabled") is not False
                definition = {key: exported.get(key) for key in ("transport", "command", "args", "env", "url", "headers")}
                client = self.hub.put(name, {**definition, "enabled": enabled, "source": str(entry.get("source") or "")})["client"]
                self.gateway.run({"op": "mcp_set", "name": name, "server": {**client, **({} if enabled else {"enabled": False})}, "replace": True})
                manifest["mcp"][name] = {**entry, "hub": True}
                self._write_manifest(manifest)
                moved.append(name)
            for name in in_hub - {name for name, entry in manifest["mcp"].items() if entry.get("hub")}:
                self.hub.remove(name)
                removed.append(name)
            return {"moved": moved, "repointed": repointed, "removed": removed, "lost": lost}

    def set_enabled(self, kind: str, name: str, enabled: bool) -> dict[str, Any]:
        """Turn a skill or MCP server on or off in OpenClaw without removing it."""
        if kind not in {"skill", "mcp"}:
            raise ExtensionError("invalid_kind", "Choose a skill or an MCP server.")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name or ""):
            raise ExtensionError("invalid_name", "That name is not valid.")
        if kind == "skill":
            try:
                known = self.gateway.run({"op": "skills_list"}).get("skills") or []
            except ExtensionError as err:
                # Issue #63: say "unknown" for a name PockPock does not know, and explain why a known
                # skill cannot be switched while OpenClaw (which keeps the on/off state) is unavailable.
                if name not in self._read_manifest()["skills"]:
                    raise ExtensionError("not_found", "There is no skill with that name.", 404) from err
                raise ExtensionError(
                    err.code,
                    "OpenClaw keeps each skill's on/off switch, and it is not available right now"
                    f" ({err}). Set up or start OpenClaw on the OpenClaw page, then try again.",
                    err.status_code,
                ) from err
            if not any(isinstance(item, dict) and item.get("key") == name for item in known):
                raise ExtensionError("not_found", "OpenClaw has no skill with that name.", 404)
        if kind == "mcp" and self._read_manifest()["mcp"].get(name, {}).get("hub"):
            # Local MCP stops a switched-off server and refuses it to every agent, not only OpenClaw.
            self.hub.set_enabled(name, bool(enabled))
        self.gateway.run({"op": "skill_enable" if kind == "skill" else "mcp_enable", "name": name, "enabled": bool(enabled)})
        return {"ok": True, "enabled": bool(enabled)}

    def remove(self, kind: str, name: str) -> dict[str, Any]:
        manifest = self._read_manifest()
        if kind == "skill":
            if not SLUG.fullmatch(name or "") or name not in manifest["skills"]:
                raise ExtensionError("not_found", "PockPock did not install a skill with that name.", 404)
            shutil.rmtree(self.skills_dir / name, ignore_errors=True)
            if (self.skills_dir / name).exists():
                raise ExtensionError("remove_failed", "The skill folder could not be deleted. Close any program using it and try again.", 500)
            del manifest["skills"][name]
            try:
                # Clear an "off" switch so the skill is not silently disabled if it is added again.
                self.gateway.run({"op": "skill_enable", "name": name, "enabled": True})
            except ExtensionError:
                pass
        elif kind == "mcp":
            if not SERVER_NAME.fullmatch(name or "") or name not in manifest["mcp"]:
                raise ExtensionError("not_found", "PockPock did not connect an MCP server with that name.", 404)
            self.gateway.run({"op": "mcp_remove", "name": name})
            if manifest["mcp"][name].get("hub"):
                try:
                    self.hub.remove(name)
                except ExtensionError:
                    pass  # Local MCP is stopped: sync_local_mcp removes it there when it runs again
            del manifest["mcp"][name]
        else:
            raise ExtensionError("invalid_kind", "Choose a skill or an MCP server to remove.")
        self._write_manifest(manifest)
        return {"ok": True}
