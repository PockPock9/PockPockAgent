"""Turn a pasted link into something installable, without running anything from it.

A GitHub link is downloaded once as a zip archive and read in place: folders containing a
``SKILL.md`` are skills, and a README, ``package.json`` or ``pyproject.toml`` can describe an MCP
server. Any other link is treated as the address of a remote MCP server and is not fetched here.
"""

from __future__ import annotations

import io
import json
import posixpath
import re
import shlex
import stat
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

MAX_LINK_CHARS = 500
MAX_ARCHIVE_BYTES = 80 * 1024 * 1024
MAX_SKILLS_PER_LINK = 60
MAX_SKILL_FILES = 400
MAX_SKILL_BYTES = 25 * 1024 * 1024
MAX_TEXT_BYTES = 512 * 1024
FETCH_TIMEOUT_SECONDS = 45
GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
DOWNLOAD_HOSTS = frozenset({"codeload.github.com", "github.com"})
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
#: Programs an MCP server may be started with. Anything else is refused.
LAUNCHERS = frozenset({"npx", "uvx", "uv", "node", "python", "python3", "py", "docker", "bunx", "bun", "deno", "pnpm", "pipx"})
GITHUB_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PLACEHOLDER = re.compile(r"<[^>]+>|your[_ -]|xxx|\.\.\.|path/to|/path|api[_ -]?key|token|secret|changeme|replace", re.I)
README_ORIGIN = "the repository README"
FENCED_JSON = re.compile(r"```(?:json[c5]?|javascript|js)?[ \t]*\r?\n(.*?)```", re.S | re.I)


class SourceError(Exception):
    """The link cannot be used; the message is safe to show to the user."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class Link:
    kind: str  # "github", "remote", or "local" (a command that starts a server on this PC)
    url: str
    owner: str = ""
    repo: str = ""
    ref: str = ""
    path: str = ""


@dataclass(frozen=True)
class SkillCandidate:
    slug: str
    name: str
    description: str
    directory: str  # folder inside the archive, including the archive's top folder
    path: str  # folder relative to the repository root, for display
    files: int
    size: int
    has_scripts: bool
    # SKILL.md lacks the name/description header OpenClaw needs; PockPock adds it on install (#87).
    adds_header: bool = False


@dataclass(frozen=True)
class McpCandidate:
    name: str
    transport: str  # "stdio", "streamable-http" or "sse"
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    origin: str = ""  # where the definition came from, for display


def slugify(value: str, fallback: str = "extension") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")[:63].strip("-")
    return slug if SLUG.fullmatch(slug or "") else fallback


def parse_link(raw: str) -> Link:
    value = (raw or "").strip()
    if value and not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I) and len(value) <= MAX_LINK_CHARS:
        command = _parse_command(value)
        if command:
            return Link(kind="local", url=value)
    if not value or len(value) > MAX_LINK_CHARS or any(ord(char) < 33 for char in value):
        raise SourceError("invalid_link", "Paste one link, without spaces, or a command that starts an MCP server on this PC.")
    try:
        parsed = urllib.parse.urlsplit(value)
        host = (parsed.hostname or "").lower()
        parsed.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError as err:
        raise SourceError("invalid_link", "That link is not a valid web address.") from err
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise SourceError("invalid_link", "The link must start with https:// and must not contain a username or password.")
    if host in GITHUB_HOSTS:
        return _parse_github(parsed)
    if parsed.scheme != "https" and host not in LOCAL_HOSTS:
        raise SourceError("insecure_link", "Remote MCP servers must use https://. Only servers on this PC may use http://.")
    return Link(kind="remote", url=urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, "")))


def _parse_command(value: str) -> list[str] | None:
    """Split a pasted command such as ``python3 C:\\servers\\server.py`` when it starts with a launcher
    PockPock allows. Nothing is run here (issue #88)."""
    if any(ord(char) < 32 for char in value):
        return None
    try:
        parts = shlex.split(value, posix=sys.platform != "win32")
    except ValueError:
        return None
    parts = [part[1:-1] if len(part) >= 2 and part[0] == part[-1] == '"' else part for part in parts]
    if not parts or launcher_name(parts[0]) not in LAUNCHERS or len(parts) > 41:
        return None
    return parts


def local_candidate(link: Link) -> McpCandidate:
    """The stdio server a pasted local command starts; it is tested before it is saved."""
    parts = _parse_command(link.url) or []
    args = tuple(parts[1:41])
    target = next((arg for arg in args if not arg.startswith("-")), "")
    stem = re.sub(r"\.(py|js|mjs|cjs|ts)$", "", target.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1], flags=re.I)
    if stem.lower() in {"server", "index", "main", "app", "mcp"}:
        parent = target.replace("\\", "/").rstrip("/").rsplit("/", 2)
        stem = parent[-2] if len(parent) >= 2 else stem
    return McpCandidate(
        name=slugify(stem.split("@", 1)[0] if not stem.startswith("@") else stem.rsplit("/", 1)[-1], "local-mcp-server")[:40].strip("-") or "local-mcp-server",
        transport="stdio",
        command=launcher_name(parts[0]) if parts else "",
        args=args,
        origin="the command you entered",
    )


def _parse_github(parsed: urllib.parse.SplitResult) -> Link:
    if parsed.scheme != "https":
        raise SourceError("insecure_link", "GitHub links must start with https://.")
    parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise SourceError("invalid_link", "Paste a link to a GitHub repository or to a folder inside one.")
    owner, repo = parts[0], re.sub(r"\.git$", "", parts[1])
    if not GITHUB_NAME.fullmatch(owner) or not GITHUB_NAME.fullmatch(repo):
        raise SourceError("invalid_link", "That does not look like a GitHub repository link.")
    ref, path = "", ""
    if len(parts) > 3 and parts[2] in {"tree", "blob"}:
        # Branch names containing "/" cannot be told apart from folders; the first segment is used.
        ref = parts[3]
        rest = parts[4:]
        if parts[2] == "blob" and rest:
            rest = rest[:-1]
        path = "/".join(rest)
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", ref) or ".." in rest or any(part.startswith(".") for part in rest):
            raise SourceError("invalid_link", "That GitHub link points to a branch or folder PockPock cannot read.")
    elif len(parts) > 2:
        raise SourceError("invalid_link", "Paste a link to a GitHub repository or to a folder inside one.")
    return Link(kind="github", url=f"https://github.com/{owner}/{repo}", owner=owner, repo=repo, ref=ref, path=path)


class _GithubOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != "https" or (target.hostname or "").lower() not in DOWNLOAD_HOSTS:
            raise urllib.error.HTTPError(newurl, code, "Redirect outside GitHub refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_archive(link: Link) -> bytes:
    """Download the repository as a zip. Only GitHub hosts are contacted."""
    ref = urllib.parse.quote(link.ref or "HEAD", safe="")
    url = f"https://codeload.github.com/{link.owner}/{link.repo}/zip/{ref}"
    opener = urllib.request.build_opener(_GithubOnlyRedirects())
    request = urllib.request.Request(url, headers={"User-Agent": "local-agent-extension-installer"})
    try:
        with opener.open(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            data = response.read(MAX_ARCHIVE_BYTES + 1)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            raise SourceError("not_found", "GitHub has no public repository, branch or folder at that link.", 404) from err
        raise SourceError("github_failed", f"GitHub refused the download (HTTP {err.code}). Try again later.", 502) from err
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise SourceError("github_unreachable", "Could not reach GitHub. Check the internet connection and try again.", 502) from err
    if len(data) > MAX_ARCHIVE_BYTES:
        raise SourceError("too_large", "That repository is larger than 80 MB. Link to the skill's own folder or a smaller repository.", 413)
    return data


class Snapshot:
    """A downloaded repository archive, read without extracting it."""

    def __init__(self, data: bytes, link: Link):
        try:
            self.archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as err:
            raise SourceError("bad_archive", "GitHub returned a download PockPock could not read.", 502) from err
        self.link = link
        names = self.archive.namelist()
        self.root = names[0].split("/", 1)[0] if names else ""
        comment = self.archive.comment.decode("ascii", "ignore").strip()
        self.commit = comment if re.fullmatch(r"[0-9a-f]{40}", comment) else ""
        self.base = posixpath.join(self.root, link.path) if link.path else self.root
        prefix = f"{self.base}/"
        self.entries = [info for info in self.archive.infolist() if info.filename.startswith(prefix)]
        if link.path and not self.entries:
            raise SourceError("not_found", "That folder does not exist in the repository.", 404)

    def relative(self, archive_path: str) -> str:
        return archive_path[len(self.root) + 1:] if archive_path.startswith(f"{self.root}/") else archive_path

    def read_text(self, archive_path: str) -> str:
        try:
            info = self.archive.getinfo(archive_path)
        except KeyError:
            return ""
        if info.file_size > MAX_TEXT_BYTES:
            return ""
        return self.archive.read(info).decode("utf-8", "replace")

    def find_readme(self, folder: str) -> str:
        prefix = f"{folder}/"
        for info in self.archive.infolist():
            name = info.filename
            if name.startswith(prefix) and "/" not in name[len(prefix):] and name[len(prefix):].lower() in {"readme.md", "readme.mdx", "readme"}:
                return self.read_text(name)
        return ""


def _frontmatter(text: str) -> dict[str, str]:
    """Read ``name`` and ``description`` from a SKILL.md header without a YAML dependency."""
    match = re.match(r"﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.S)
    if not match:
        return {}
    result: dict[str, str] = {}
    lines = match.group(1).splitlines()
    index = 0
    while index < len(lines):
        entry = re.match(r"^(name|description)[ \t]*:[ \t]*(.*)$", lines[index])
        index += 1
        if not entry:
            continue
        value = entry.group(2).strip()
        if value in {"", ">", "|", ">-", "|-", ">+", "|+"}:
            block = []
            while index < len(lines) and (lines[index].startswith((" ", "\t")) or not lines[index].strip()):
                block.append(lines[index].strip())
                index += 1
            value = " ".join(part for part in block if part)
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[entry.group(1)] = " ".join(value.split())
    return result


def _first_paragraph(text: str) -> str:
    """The first line of prose in a SKILL.md, used when it has no description header."""
    body = re.sub(r"^\ufeff?---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|$)", "", text, count=1, flags=re.S)
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "```", "|", "<", "---", "!")):
            return " ".join(re.sub(r"[*_`]", "", line).split())[:400]
    return ""


def skill_header(text: str, name: str, description: str) -> str:
    """``text`` with the ``name`` and ``description`` header OpenClaw requires.

    OpenClaw silently skips a SKILL.md without them ("description is required"), so a skill that
    looked installed never reached the agent (issue #87). Existing header fields are kept.
    """
    meta = _frontmatter(text)
    missing = []
    if not meta.get("name"):
        missing.append(f"name: {json.dumps(name)}")
    if not meta.get("description"):
        missing.append(f"description: {json.dumps(description)}")
    if not missing:
        return text
    newline = "\r\n" if "\r\n" in text else "\n"
    match = re.match(r"(\ufeff?---[ \t]*\r?\n)", text)
    if match and re.match(r"\ufeff?---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|$)", text, re.S):
        return text[:match.end()] + newline.join(missing) + newline + text[match.end():]
    return "---" + newline + newline.join(missing) + newline + "---" + newline + newline + text.lstrip("\ufeff")


def find_skills(snapshot: Snapshot) -> list[SkillCandidate]:
    """Every folder under the linked path that holds a SKILL.md."""
    skill_files = sorted(
        info.filename for info in snapshot.entries
        if posixpath.basename(info.filename) == "SKILL.md" and info.filename.count("/") - snapshot.base.count("/") <= 6
    )
    candidates: list[SkillCandidate] = []
    used: set[str] = set()
    for skill_file in skill_files[:MAX_SKILLS_PER_LINK]:
        directory = posixpath.dirname(skill_file)
        members = [info for info in snapshot.archive.infolist() if info.filename.startswith(f"{directory}/") and not info.is_dir()]
        size = sum(info.file_size for info in members)
        if len(members) > MAX_SKILL_FILES or size > MAX_SKILL_BYTES:
            continue
        text = snapshot.read_text(skill_file)
        meta = _frontmatter(text)
        folder = posixpath.basename(directory) if directory != snapshot.root else snapshot.link.repo
        slug = slugify(meta.get("name") or folder, slugify(folder, "skill"))
        base_slug, count = slug[:58].strip("-"), 1
        while slug in used:
            count += 1
            slug = f"{base_slug}-{count}"
        used.add(slug)
        candidates.append(SkillCandidate(
            slug=slug,
            name=(meta.get("name") or folder)[:80],
            description=(meta.get("description") or _first_paragraph(text) or f"Skill {meta.get('name') or folder}.")[:400],
            directory=directory,
            path=snapshot.relative(directory) if directory != snapshot.root else "",
            files=len(members),
            size=size,
            has_scripts=any(re.search(r"\.(py|js|mjs|ts|sh|ps1|bat|cmd|exe|rb|pl)$", info.filename, re.I) for info in members),
            adds_header=not (meta.get("name") and meta.get("description")),
        ))
    return candidates


def extract_skill(snapshot: Snapshot, candidate: SkillCandidate, destination: Path) -> None:
    """Write one skill folder to ``destination``. Refuses links and paths that escape it."""
    prefix = f"{candidate.directory}/"
    root = destination.resolve()
    for info in snapshot.archive.infolist():
        if not info.filename.startswith(prefix) or info.is_dir():
            continue
        relative = info.filename[len(prefix):]
        parts = relative.split("/")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise SourceError("unsafe_archive", f"The skill contains a symbolic link ({relative}), which PockPock does not install.")
        if any(part in {"", ".", ".."} or "\\" in part or ":" in part for part in parts) or parts[0] == ".git":
            raise SourceError("unsafe_archive", "The skill contains a file path PockPock does not install.")
        target = (root / Path(*parts)).resolve()
        if root != target and root not in target.parents:
            raise SourceError("unsafe_archive", "The skill contains a file path PockPock does not install.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with snapshot.archive.open(info) as source, open(target, "wb") as output:
            remaining = MAX_SKILL_BYTES
            while chunk := source.read(1024 * 1024):
                remaining -= len(chunk)
                if remaining < 0:
                    raise SourceError("too_large", "The skill is larger than its archive listing claims.", 413)
                output.write(chunk)
    if candidate.adds_header:
        skill_file = root / "SKILL.md"
        text = skill_file.read_text(encoding="utf-8", errors="replace")
        skill_file.write_text(skill_header(text, candidate.slug, candidate.description), encoding="utf-8", newline="")


def _server_entries(document: Any) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(document, dict):
        return []
    for key in ("mcpServers", "servers", "mcp_servers"):
        servers = document.get(key)
        if isinstance(servers, dict):
            return [(str(name), value) for name, value in servers.items() if isinstance(value, dict)]
    nested = document.get("mcp")
    if isinstance(nested, dict):
        return _server_entries(nested)
    if isinstance(document.get("command"), str) or isinstance(document.get("url"), str):
        return [("", document)]
    return []


def _from_definition(name: str, definition: dict[str, Any], origin: str) -> McpCandidate | None:
    command = definition.get("command")
    args = definition.get("args", [])
    if isinstance(command, str) and command.strip():
        launcher = launcher_name(command)
        if launcher not in LAUNCHERS or not isinstance(args, list) or not all(isinstance(arg, (str, int, float)) for arg in args):
            return None
        env = definition.get("env") if isinstance(definition.get("env"), dict) else {}
        return McpCandidate(
            name=name, transport="stdio", command=launcher, args=tuple(str(arg) for arg in args[:40]),
            env={str(key)[:80]: "" for key in list(env)[:20] if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key))},
            origin=origin,
        )
    url = definition.get("url")
    if isinstance(url, str) and url.startswith("https://") and not PLACEHOLDER.search(url):
        transport = "sse" if str(definition.get("type") or definition.get("transport") or "").lower() == "sse" or url.rstrip("/").endswith("/sse") else "streamable-http"
        return McpCandidate(name=name, transport=transport, url=url[:MAX_LINK_CHARS], origin=origin)
    return None


def launcher_name(command: str) -> str:
    return re.sub(r"\.(exe|cmd|bat)$", "", command.strip().replace("\\", "/").rsplit("/", 1)[-1].lower())


def find_mcp(snapshot: Snapshot) -> McpCandidate | None:
    """Best guess at how to start the MCP server this repository documents, or ``None``."""
    default_name = slugify(posixpath.basename(snapshot.link.path) or snapshot.link.repo, "mcp-server")[:40].strip("-")
    folders = [snapshot.base] if snapshot.base == snapshot.root else [snapshot.base, snapshot.root]
    for folder in folders:
        readme = snapshot.find_readme(folder)
        found: list[McpCandidate] = []
        for block in FENCED_JSON.findall(readme)[:60]:
            try:
                document = json.loads(block)
            except ValueError:
                try:
                    document = json.loads("{" + block.strip().rstrip(",") + "}")
                except ValueError:
                    continue
            for _, definition in _server_entries(document):
                candidate = _from_definition(default_name, definition, README_ORIGIN)
                if candidate:
                    found.append(candidate)
        if found:
            # Prefer launchers that need no extra software, then the README's own order.
            order = {"npx": 0, "uvx": 1, "uv": 1}
            return min(found, key=lambda item: (0 if item.transport == "stdio" else 3, order.get(item.command, 2)))
    for folder in folders:
        package = snapshot.read_text(f"{folder}/package.json")
        if package:
            try:
                manifest = json.loads(package)
            except ValueError:
                manifest = {}
            name = manifest.get("name") if isinstance(manifest, dict) else None
            if isinstance(name, str) and re.fullmatch(r"(@[a-z0-9._~-]+/)?[a-z0-9._~-]+", name) and manifest.get("bin") and not manifest.get("private"):
                return McpCandidate(name=default_name, transport="stdio", command="npx", args=("-y", name), origin="package.json (assumes the package is published to npm)")
        project = snapshot.read_text(f"{folder}/pyproject.toml")
        if project:
            try:
                table = tomllib.loads(project).get("project", {})
            except (tomllib.TOMLDecodeError, AttributeError):
                table = {}
            name = table.get("name") if isinstance(table, dict) else None
            if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", name) and table.get("scripts"):
                return McpCandidate(name=default_name, transport="stdio", command="uvx", args=(name,), origin="pyproject.toml (assumes the package is published to PyPI)")
    return None


def remote_candidate(link: Link) -> McpCandidate:
    parsed = urllib.parse.urlsplit(link.url)
    host = (parsed.hostname or "server").removeprefix("www.").removeprefix("mcp.")
    transport = "sse" if parsed.path.rstrip("/").endswith("/sse") else "streamable-http"
    if host in LOCAL_HOSTS or re.fullmatch(r"[0-9.]+|[0-9a-f:]+", host):
        # "127.0.0.1" used to become the name "127" (issue #89): use the path, else the port.
        generic = {"mcp", "sse", "api", "v1", "v2", "stream", "http"}
        words = [part for part in parsed.path.split("/") if part and part.lower() not in generic]
        name = slugify(f"local-{words[-1]}" if words else f"local-{parsed.port or 'server'}", "local-mcp-server")
    else:
        name = slugify(host.split(".")[0] if "." in host else host, "mcp-server")
    return McpCandidate(name=name[:40].strip("-"), transport=transport, url=link.url, origin="the link you pasted")


def find_mcp_folders(snapshot: Snapshot, limit: int = 30) -> list[dict[str, str]]:
    """Sub-folders whose own README documents an MCP server, for a repository that holds several.

    modelcontextprotocol/servers keeps each server in src/<name> with its own README, so the root
    never proposed one (issue #64). The user picks a folder and inspects that link instead.
    """
    if snapshot.link.kind != "github":
        return []
    folders: list[dict[str, str]] = []
    base_depth = snapshot.base.count("/")
    seen: set[str] = set()
    for info in snapshot.entries:
        name = info.filename
        folder = posixpath.dirname(name)
        if folder in seen or folder == snapshot.base or folder.count("/") - base_depth > 2:
            continue
        if posixpath.basename(name).lower() not in {"readme.md", "readme.mdx", "readme"}:
            continue
        seen.add(folder)
        readme = snapshot.read_text(name)
        if not any(_server_entries(_loose_json(block)) for block in FENCED_JSON.findall(readme)[:20]):
            continue
        relative = snapshot.relative(folder)
        ref = snapshot.link.ref or "HEAD"
        folders.append({
            "name": posixpath.basename(folder),
            "path": relative,
            "url": f"{snapshot.link.url}/tree/{ref}/{relative}",
        })
        if len(folders) >= limit:
            break
    return sorted(folders, key=lambda item: item["path"])


def _loose_json(block: str) -> Any:
    try:
        return json.loads(block)
    except ValueError:
        try:
            return json.loads("{" + block.strip().rstrip(",") + "}")
        except ValueError:
            return None


Fetcher = Callable[[Link], bytes]
