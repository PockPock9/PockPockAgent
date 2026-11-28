"""What the model knows about the project before the first message: rules, folder overview, instructions."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from .tools import Workspace, project_files

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", ".pockpock/instructions.md", ".github/copilot-instructions.md")
MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt", "pubspec.yaml", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "Makefile", "composer.json", "Gemfile", "*.csproj")


def _git(ws: Workspace, *args: str) -> str:
    if not shutil.which("git") or not (ws.root / ".git").exists():
        return ""
    done = subprocess.run(["git", *args], cwd=ws.root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return done.stdout.strip() if done.returncode == 0 else ""


def overview(ws: Workspace) -> str:
    files = project_files(ws)
    languages = Counter(Path(f).suffix.lower() for f in files if Path(f).suffix)
    top = sorted({f.split("/")[0] + ("/" if "/" in f else "") for f in files})[:40]
    manifests = [f for f in files if any(Path(f).match(pattern) for pattern in MANIFESTS) and f.count("/") <= 1][:8]
    parts = [f"Files: {len(files)}. Most common types: " + ", ".join(f"{ext} ({n})" for ext, n in languages.most_common(6))]
    parts.append("Top level: " + ", ".join(top))
    if manifests:
        parts.append("Manifests: " + ", ".join(manifests))
    branch = _git(ws, "rev-parse", "--abbrev-ref", "HEAD")
    if branch:
        status = _git(ws, "status", "--short")
        parts.append(f"Git branch: {branch}. " + (f"Uncommitted changes:\n{status[:1500]}" if status else "Working tree clean."))
    return "\n".join(parts)


def instructions(ws: Workspace) -> str:
    found = []
    for name in INSTRUCTION_FILES:
        path = ws.root / name
        if path.is_file():
            found.append(f"--- {name} ---\n{path.read_text(encoding='utf-8', errors='replace')[:6000]}")
    return "\n\n".join(found)


def shell_name() -> str:
    return "PowerShell (Windows)" if sys.platform == "win32" else "sh"


def system_prompt(ws: Workspace, mode: str) -> str:
    rules = instructions(ws)
    return f"""You are PockPock Code, a careful coding agent running on the user's computer with a local model.
You work in the project folder {ws.root} on {platform.system()} {platform.release()}; commands run in {shell_name()}.

How you work:
1. Understand first. For a question, find the answer in the code (search, read_file) and answer with file paths and line numbers. Never guess what a file contains.
2. For a change with more than two steps, write a short to-do list with todo_write, then update it as you go.
3. Read a file before editing it. Make small, exact edits with edit_file; copy old_text from read_file output without the line numbers. Use write_file for new files.
4. Follow the project's existing style, libraries and structure. Do not add dependencies unless asked.
5. After changing code, check it: run the project's tests, type check, linter or build when they exist (look at the manifests). If a check fails, fix the cause and run it again. Fix the code, not the tests: change a test only when the test itself is wrong, and say so.
   Keep commands simple and non-interactive (for example `python -m unittest`, `npm test`, `git status`); do not open editors or servers that never exit.
6. Do not stop half way. Keep calling tools until the task is done, then reply with a short summary: what you changed (files), how you checked it, and anything left to do.
7. If the request is unclear in a way that changes the result, ask one short question instead of guessing.
8. Never delete or overwrite files outside the request, never run destructive commands (rm -rf, git reset --hard, force push) unless the user asked.
{"Permission: commands and edits run without asking (full auto)." if mode == "full-auto" else "Permission: the user approves commands" + (" and edits" if mode == "suggest" else "") + "; if they decline, find another way or ask."}

Project overview:
{overview(ws)}
{chr(10) + "Project instructions (follow them):" + chr(10) + rules if rules else ""}"""
