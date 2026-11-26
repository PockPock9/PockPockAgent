import asyncio
import csv
from dataclasses import dataclass, field
import difflib
import hashlib
from html.parser import HTMLParser
import ipaddress
import io
import json
import logging
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit
import uuid
import aiohttp
from aiohttp.abc import AbstractResolver
from .contracts import (
    ERROR_CONTRACT_VERSION,
    TOOL_CONTRACT_VERSION,
    ToolContract,
    ToolContractError,
    ToolError,
    build_tool_registry,
    validate_tool_input,
    validate_tool_output,
)


MAX_PAGE_BYTES = 2 * 1024 * 1024

MAX_PAGE_TEXT = 40_000

MAX_SITE_PAGES = 5

MAX_LINKS_PER_PAGE = 50

MAX_SITE_PAGE_TEXT = 8_000

MAX_OUTPUT_CHARS = 100_000

MAX_IMAGE_BYTES = 20 * 1024 * 1024

_DOMAIN_REQUESTS: dict[str, float] = {}

_DOMAIN_LOCK = asyncio.Lock()

_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}$")

_DOMAIN_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_@])(?:https?://)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}"
    r"(?::\d+)?(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)

_MEDIA_EXTENSIONS = {
    ".3g2", ".3gp", ".aac", ".avi", ".flac", ".flv", ".m4a", ".m4s",
    ".m4v", ".mkv", ".mov", ".mp3", ".mp4", ".mpeg", ".mpg", ".mpd",
    ".m3u8", ".ogg", ".ogv", ".ts", ".wav", ".webm", ".wmv",
}

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # repository root (backend/projects/agent_tools -> repo)

_PROJECT_IGNORED_DIRS = {
    ".git", ".venv", "node_modules", "dist", "build", "__pycache__",
    ".pytest_cache", ".mypy_cache", "coverage", "credentials", "secrets",
}

_PROJECT_EXTENSIONS = {
    ".bat", ".cjs", ".cmd", ".conf", ".css", ".example", ".gitignore", ".html", ".ini",
    ".js", ".json", ".jsx", ".md", ".mjs", ".ps1", ".py", ".sh", ".sql",
    ".toml", ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml",
}

# One read covers a typical source file (a 455-line stylesheet took three 160-line reads, and the
# run ran out of tool calls); the character limit still bounds what enters the context.
_PROJECT_READ_MAX_LINES = 600

_PROJECT_READ_MAX_CHARS = 20_000

_PROJECT_EDIT_MAX_CHARS = 12_000

_PROJECT_SEARCH_MAX_MATCHES = 40

_PROJECT_SEARCH_MAX_LINE_CHARS = 240

_PROJECT_PATCH_LIMIT = 5

_PROJECT_PATCH_TTL = 30 * 60

_PENDING_PROJECT_PATCHES: dict[str, "PendingProjectPatch"] = {}

logger = logging.getLogger("pockpock-agent-tools")

class AgentToolError(ValueError):
    pass


def non_negated_task_text(task: str) -> str:
    negation = r"\b(?:do\s+not|don't|dont|never|avoid|without|no\s+need\s+to)\b"
    positive_segments = []
    for clause in re.split(r"[.!?;\n]+", task):
        for segment in re.split(r"\b(?:but|instead|however|except|unless)\b", clause, flags=re.IGNORECASE):
            if not re.search(negation, segment, flags=re.IGNORECASE):
                positive_segments.append(segment)
    return " ".join(positive_segments)


def requests_visible_browser(task: str) -> bool:
    negative = r"\b(?:do\s+not|don't|dont|never|avoid|without)\s+"
    browser_target = r"(?:(?:a|an|the|new|visible|real)\s+){0,3}(?:browser|window|tab)\b"
    negative_open = r"(?:open(?:ing)?|launch(?:ing)?|show(?:ing)?|display(?:ing)?|bring(?:ing)?\s+up)"
    if re.search(negative + negative_open + r"\s+" + browser_target, task, re.IGNORECASE) or re.search(
        negative + r"use(?:d|ing)?\s+" + browser_target,
        task,
        re.IGNORECASE,
    ):
        return False
    active_task = non_negated_task_text(task)
    if re.search(r"\b(?:headless|background)\b", active_task, re.IGNORECASE):
        return False
    visible_intent = re.compile(
        r"\b(?:open|launch|show|display|bring\s+up)\b.{0,48}\b"
        r"(?:browser|chrome|chromium|firefox|edge|window|tab)\b"
        r"|\b(?:visible|headed)\s+(?:web\s+)?browser\b",
        re.IGNORECASE,
    )
    return bool(visible_intent.search(active_task))


@dataclass
class AgentToolContext:
    task_id: str
    allowed_hosts: set[str]
    attachments: dict[str, str]
    output_dir: Path
    permission_mode: str = "default"
    visible_browser: bool = False
    scrape_count: int = 0
    image_count: int = 0
    artifacts: list[dict[str, str]] = field(default_factory=list)
    # Tools this run is permitted to use (task capabilities / delegation).
    # The executor sets it; search_tools only ever returns tools from this
    # set. None means "no run context" — the search handler then falls back
    # to read-only tools only, so a context-free call can never surface a
    # write or high-risk tool.
    permitted_tools: frozenset[str] | None = None

@dataclass
class ProjectAgentContext:
    task_id: str
    project_root: Path = _PROJECT_ROOT
    allow_execution: bool = False
    files_read: int = 0
    patches_proposed: int = 0
    inspected_paths: set[str] = field(default_factory=set)
    fully_read_hashes: dict[str, str] = field(default_factory=dict)
    # path -> (content hash, last line read without a gap from line 1): parts read in order add up
    # to a full read, so a file longer than one read can still be replaced.
    read_coverage: dict[str, tuple[str, int]] = field(default_factory=dict)

@dataclass
class PendingProjectPatch:
    patch_id: str
    relative_path: str
    summary: str
    content: str
    original_hash: str | None
    diff: str
    created_at: float
    status: str = "pending"


def task_output_root() -> Path:
    root = Path.home() / "PockPock AI Tasks"
    root.mkdir(parents=True, exist_ok=True)
    return root


def task_output_dir(task_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", task_id):
        raise AgentToolError("Invalid task ID")
    output_dir = task_output_root() / task_id
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


__all__ = [name for name in globals() if not name.startswith("__")]
