"""Search mcpservers.org for MCP servers and skills, from inside PockPock.

mcpservers.org puts its pages behind a browser check (Cloudflare) and its robots.txt disallows /api/,
so PockPock does not read its pages or API. It uses what the site publishes for machines:

- The curated list: mcpservers.org is the site of the GitHub list `wong2/awesome-mcp-servers`; its
  README has each curated server's name, one-line description and repository link (about 540).
- The sitemaps (robots.txt allows them): every server page (`/servers/<owner>/<name>`, about 10,000)
  and every skill page (`/agent-skills/<owner>/<name>`, about 9,500). These give names only.

The curated list is downloaded when the user searches, at most once a day. The sitemaps are large, so
they are downloaded only when the user asks to search all of mcpservers.org, at most once a week, and
kept as a short list of names. Both are cached in one file. A result
from the curated list can be previewed and installed through the normal link flow (its repository
link); every result can be opened on mcpservers.org. Nothing about the user is sent: the requests are
plain downloads of public files with a generic User-Agent.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

SITE = "https://mcpservers.org"
CURATED_URL = "https://raw.githubusercontent.com/wong2/awesome-mcp-servers/main/README.md"
SITEMAP_INDEX = f"{SITE}/sitemap.xml"
TTL_SECONDS = 24 * 60 * 60
INDEX_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_DOWNLOAD = 24 * 1024 * 1024
MAX_SITEMAPS = 40
CURATED_SECTIONS = ("Reference Servers", "Official Servers", "Community Servers")
USER_AGENT = "PockPock-Agent (mcpservers.org directory search)"

_ENTRY = re.compile(
    r"^-\s+(?:\\?\*){2}\[(?P<name>[^\]]+)\]\((?P<url>[^)\s]+)\)(?:\\?\*){0,2}\s*[-–—:]\s*(?P<desc>.+)$"
)
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_SLUG = re.compile(r"^[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._-]{1,150}$")


class DirectoryError(Exception):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https URLs only
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise DirectoryError("A directory file was larger than expected.")
    return data


def parse_curated(markdown: str) -> list[dict[str, str]]:
    """Curated servers from the awesome-mcp-servers README: name, description, link, section."""
    entries: list[dict[str, str]] = []
    section = ""
    for line in markdown.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section not in CURATED_SECTIONS:
            continue
        match = _ENTRY.match(line.strip())
        if not match:
            continue
        url = match["url"]
        if not url.startswith("https://"):
            continue
        description = _MD_LINK.sub(r"\1", match["desc"]).replace("\\", "").strip()
        entries.append({"name": match["name"].replace("\\", "").strip()[:120], "description": description[:400], "url": url[:500], "section": section.split()[0]})
    return entries


def parse_sitemap_locations(xml: bytes) -> list[str]:
    root = ET.fromstring(xml)
    return [element.text.strip() for element in root.iter() if element.tag.endswith("loc") and element.text]


def slugs(locations: list[str], prefix: str) -> list[str]:
    """`owner/name` from English page URLs under `prefix` (localized copies such as /ja/... are skipped)."""
    start = f"{SITE}/{prefix}/"
    found = []
    for location in locations:
        if location.startswith(start):
            slug = location[len(start):].strip("/")
            if _SLUG.match(slug):
                found.append(slug)
    return list(dict.fromkeys(found))


def _words(text: str) -> list[str]:
    return [word for word in re.split(r"[^a-z0-9]+", text.lower()) if word]


class Directory:
    """The curated list (small, refreshed daily, always searched) and the full index (large: the site's
    sitemaps carry every page in 15 languages, about 57 MB for servers and 9 MB for skills; downloaded
    only when the user asks to search all of mcpservers.org, kept as a short list, refreshed weekly)."""

    def __init__(self, cache_path: Path, fetch: Callable[[str], bytes] = download, clock: Callable[[], float] = time.time):
        self.cache_path = cache_path
        self.fetch = fetch
        self.clock = clock
        self._lock = threading.Lock()
        self._cache: dict[str, Any] | None = None

    def _read(self) -> dict[str, Any]:
        if self._cache is None:
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            self._cache = data if isinstance(data, dict) else {}
        return self._cache

    def _write(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self._cache), encoding="utf-8")
        except OSError:
            pass  # Searching still works from memory.

    def _part(self, key: str, ttl: float, download_part: Callable[[], Any]) -> tuple[Any, str]:
        """One cached part ('curated', 'servers' or 'skills'): fresh, re-downloaded, or the old copy."""
        cache = self._read()
        part = cache.get(key)
        fresh = isinstance(part, dict) and isinstance(part.get("fetched_at"), (int, float)) and self.clock() - part["fetched_at"] < ttl
        if fresh:
            return part["items"], ""
        try:
            items = download_part()
        except (OSError, ValueError, ET.ParseError, DirectoryError) as err:
            if isinstance(part, dict) and isinstance(part.get("items"), list):
                return part["items"], "mcpservers.org could not be reached, so this is the list from the last download."
            message = str(err) if isinstance(err, DirectoryError) else f"mcpservers.org could not be reached: {getattr(err, 'reason', None) or err}"
            raise DirectoryError(message) from err
        cache[key] = {"fetched_at": self.clock(), "items": items}
        self._write()
        return items, ""

    def _curated(self) -> list[dict[str, str]]:
        items = parse_curated(self.fetch(CURATED_URL).decode("utf-8", "replace"))
        if not items:
            raise DirectoryError("The mcpservers.org list was empty.")
        return items

    def _index(self, kind: str) -> list[str]:
        index = parse_sitemap_locations(self.fetch(SITEMAP_INDEX))
        prefix, path = (f"{SITE}/sitemaps/servers/", "servers") if kind == "mcp" else (f"{SITE}/sitemaps/skills", "agent-skills")
        found: list[str] = []
        for url in [item for item in index if item.startswith(prefix)][:MAX_SITEMAPS]:
            found.extend(slugs(parse_sitemap_locations(self.fetch(url)), path))
        if not found:
            raise DirectoryError("The mcpservers.org index was empty.")
        return list(dict.fromkeys(found))

    def index_cached(self, kind: str) -> bool:
        return isinstance(self._read().get("servers" if kind == "mcp" else "skills"), dict)

    def search(self, kind: str, query: str, limit: int = 30, full: bool = False) -> dict[str, Any]:
        """Search. `full` downloads the whole index when it is not cached yet; once it is cached it is
        always searched too. Returns results, counts, whether the index is cached, and a note."""
        if kind not in ("mcp", "skills"):
            raise DirectoryError("Unknown kind.", 422)
        words = _words(query)[:8]
        limit = max(1, min(int(limit), 60))
        notes: list[str] = []
        results: list[dict[str, Any]] = []
        with self._lock:
            curated: list[dict[str, str]] = []
            if kind == "mcp":
                curated, note = self._part("curated", TTL_SECONDS, self._curated)
                notes.append(note)
            key = "servers" if kind == "mcp" else "skills"
            pool: list[str] = []
            if full or self.index_cached(kind):
                pool, note = self._part(key, INDEX_TTL_SECONDS, lambda: self._index(kind))
                notes.append(note)
        scored = []
        for entry in curated:
            name, text = entry["name"].lower(), f"{entry['name']} {entry['description']}".lower()
            if all(word in text for word in words):
                scored.append((-(sum(3 for word in words if word in name) + (5 if name == query.strip().lower() else 0)), entry))
        scored.sort(key=lambda item: (item[0], item[1]["name"].lower()))
        for _, entry in scored:
            results.append({
                "name": entry["name"], "description": entry["description"], "owner": entry["section"], "curated": True,
                "install_url": entry["url"] if entry["url"].startswith("https://github.com/") else None,
                "source_url": entry["url"],
                "page_url": f"{SITE}/search?query={urllib.parse.quote(entry['name'])}",
            })
        path = "servers" if kind == "mcp" else "agent-skills"
        if words:
            for slug in pool:
                if all(word in slug.lower() for word in words):
                    owner, name = slug.split("/", 1)
                    results.append({"name": name, "description": "", "owner": owner, "curated": False, "install_url": None, "source_url": None, "page_url": f"{SITE}/{path}/{slug}"})
                    if len(results) >= limit * 4:
                        break
        return {
            "results": results[:limit],
            "total": len(results),
            "counts": {"curated": len(curated), "index": len(pool)},
            "index_cached": bool(pool),
            "note": next((note for note in notes if note), ""),
            "site": SITE,
        }
