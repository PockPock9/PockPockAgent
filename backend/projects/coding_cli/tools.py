"""The coding agent's tools: list, search, read, edit, write, run commands, keep a to-do list.

Every path stays inside the project folder. Edits are snapshotted so /undo can restore them.
Outputs are kept short (local models have small context windows) and say how to get more.
"""

from __future__ import annotations

import difflib
import fnmatch
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

MAX_OUTPUT = 12_000
MAX_READ_LINES = 400
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".dart_tool", "target", ".idea", ".mypy_cache", ".pytest_cache", "coverage"}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".exe", ".dll", ".so", ".dylib", ".bin", ".woff", ".woff2", ".ttf", ".mp3", ".mp4", ".pyc", ".class", ".jar", ".docx", ".xlsx", ".pptx", ".sqlite3", ".db"}


class ToolError(Exception):
    pass


@dataclass
class Workspace:
    root: Path
    snapshots: list[list[tuple[Path, str | None]]] = field(default_factory=list)  # per turn: (path, old text or None if new)
    read_files: set[Path] = field(default_factory=set)
    todos: list[dict] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    def path(self, value: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ToolError("A path is required")
        candidate = (self.root / value.strip().strip('"')).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ToolError(f"{value} is outside the project folder {self.root}. Use a path inside it.")
        return candidate

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix() or "."

    def begin_turn(self) -> None:
        self.snapshots.append([])

    def snapshot(self, path: Path) -> None:
        if not self.snapshots:
            self.begin_turn()
        if any(saved == path for saved, _ in self.snapshots[-1]):
            return
        self.snapshots[-1].append((path, path.read_text(encoding="utf-8", errors="replace") if path.exists() else None))

    def undo(self) -> list[str]:
        while self.snapshots and not self.snapshots[-1]:
            self.snapshots.pop()
        if not self.snapshots:
            return []
        restored = []
        for path, text in reversed(self.snapshots.pop()):
            if text is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(text, encoding="utf-8", newline="")
            restored.append(self.rel(path))
        return restored


def clip(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n… [{len(text) - limit} characters cut] …\n{text[-half:]}"


def project_files(ws: Workspace, limit: int = 5000) -> list[str]:
    """Files in the project, using git's list (respects .gitignore) when it is a repository."""
    if (ws.root / ".git").exists() and shutil.which("git"):
        done = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ws.root, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if done.returncode == 0:
            return [line for line in done.stdout.splitlines() if line][:limit]
    found: list[str] = []
    for current, dirs, files in os.walk(ws.root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            found.append((Path(current) / name).relative_to(ws.root).as_posix())
            if len(found) >= limit:
                return found
    return found


# ---------------- tools ----------------

def list_files(ws: Workspace, pattern: str = "", path: str = "") -> str:
    files = project_files(ws)
    if path:
        prefix = ws.rel(ws.path(path)).rstrip("/") + "/"
        files = [f for f in files if f.startswith(prefix) or prefix == "./"]
    if pattern:
        files = [f for f in files if fnmatch.fnmatch(f, pattern) or fnmatch.fnmatch(Path(f).name, pattern)]
    if not files:
        return "No files match."
    shown = files[:300]
    more = f"\n… and {len(files) - 300} more. Narrow it with pattern or path." if len(files) > 300 else ""
    return "\n".join(shown) + more


def search(ws: Workspace, pattern: str, path: str = "", glob: str = "", ignore_case: bool = True) -> str:
    if not pattern:
        raise ToolError("A search pattern is required")
    try:
        regex = re.compile(pattern, re.I if ignore_case else 0)
    except re.error:
        regex = re.compile(re.escape(pattern), re.I if ignore_case else 0)
    files = project_files(ws)
    if path:
        prefix = ws.rel(ws.path(path)).rstrip("/")
        files = [f for f in files if f == prefix or f.startswith(prefix + "/") or prefix == "."]
    if glob:
        files = [f for f in files if fnmatch.fnmatch(f, glob) or fnmatch.fnmatch(Path(f).name, glob)]
    hits: list[str] = []
    for rel in files:
        if Path(rel).suffix.lower() in BINARY_EXT:
            continue
        full = ws.root / rel
        try:
            if full.stat().st_size > 2_000_000:
                continue
            for number, line in enumerate(full.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    hits.append(f"{rel}:{number}: {line.strip()[:200]}")
                    if len(hits) >= 200:
                        return "\n".join(hits) + "\n… more matches; narrow the search."
        except OSError:
            continue
    return "\n".join(hits) or "No matches."


def read_file(ws: Workspace, path: str, start_line: int = 1, end_line: int | None = None) -> str:
    target = ws.path(path)
    if target.is_dir():
        return list_files(ws, path=path)
    if not target.exists():
        close = difflib.get_close_matches(path, project_files(ws), n=3, cutoff=0.5)
        raise ToolError(f"{path} does not exist." + (f" Did you mean: {', '.join(close)}?" if close else ""))
    if target.suffix.lower() in BINARY_EXT:
        raise ToolError(f"{path} is a binary file and cannot be read as text.")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, int(start_line or 1))
    end = min(len(lines), int(end_line) if end_line else start + MAX_READ_LINES - 1)
    if end - start + 1 > MAX_READ_LINES:
        end = start + MAX_READ_LINES - 1
    ws.read_files.add(target)
    body = "\n".join(f"{number:>5}  {lines[number - 1]}" for number in range(start, end + 1))
    tail = f"\n[lines {start}-{end} of {len(lines)}; read more with start_line={end + 1}]" if end < len(lines) else f"\n[end of file, {len(lines)} lines]"
    return clip(body + tail, 40_000)


def _diff(rel: str, old: str, new: str) -> str:
    lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{rel}", f"b/{rel}", lineterm="", n=2))
    return clip("\n".join(lines), 6000) if lines else "(no change)"


def _loose_find(text: str, needle: str) -> tuple[int, int] | None:
    """Find needle ignoring differences in indentation and trailing spaces (small models drift on these)."""
    def norm(line: str) -> str:
        return line.strip()
    lines, wanted = text.split("\n"), [norm(line) for line in needle.strip("\n").split("\n")]
    if not wanted or not any(wanted):
        return None
    matches = [i for i in range(len(lines) - len(wanted) + 1) if [norm(l) for l in lines[i:i + len(wanted)]] == wanted]
    if len(matches) != 1:
        return None
    start = sum(len(l) + 1 for l in lines[:matches[0]])
    end = start + sum(len(l) + 1 for l in lines[matches[0]:matches[0] + len(wanted)]) - 1
    return start, end


def edit_file(ws: Workspace, path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
    target = ws.path(path)
    if not target.exists():
        raise ToolError(f"{path} does not exist. Use write_file to create it.")
    text = target.read_text(encoding="utf-8", errors="replace")
    if not old_text:
        raise ToolError("old_text is empty. Copy the exact lines to replace from read_file output (without the line numbers).")
    count = text.count(old_text)
    if count == 0:
        found = _loose_find(text, old_text)
        if not found:
            raise ToolError(f"old_text was not found in {path}. Read the file again and copy the exact current lines (without line numbers).")
        indent = re.match(r"[ \t]*", text[found[0]:]).group(0)
        new_lines = new_text.strip("\n").split("\n")
        base = re.match(r"[ \t]*", new_lines[0]).group(0) if new_lines else ""
        adjusted = "\n".join(indent + line[len(base):] if line.startswith(base) else line for line in new_lines)
        updated = text[:found[0]] + adjusted + text[found[1]:]
    elif count > 1 and not replace_all:
        raise ToolError(f"old_text appears {count} times in {path}. Include more surrounding lines so it is unique, or set replace_all.")
    else:
        updated = text.replace(old_text, new_text) if replace_all else text.replace(old_text, new_text, 1)
    ws.snapshot(target)
    target.write_text(updated, encoding="utf-8", newline="")
    ws.read_files.add(target)
    ws.changed.append(ws.rel(target))
    return f"Edited {ws.rel(target)}.\n" + _diff(ws.rel(target), text, updated)


def write_file(ws: Workspace, path: str, content: str) -> str:
    target = ws.path(path)
    if target.exists() and target not in ws.read_files and target.stat().st_size > 0:
        raise ToolError(f"{path} already exists. Read it first, then use edit_file for changes (or write_file again to replace it).")
    old = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
    ws.snapshot(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content if content.endswith("\n") or not content else content + "\n", encoding="utf-8", newline="")
    ws.read_files.add(target)
    ws.changed.append(ws.rel(target))
    if not old:
        return f"Created {ws.rel(target)} ({len(content.splitlines())} lines)."
    return f"Replaced {ws.rel(target)}.\n" + _diff(ws.rel(target), old, content)


def shell_command() -> list[str]:
    if sys.platform == "win32":
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
    return ["/bin/sh", "-c"]


def run_command(ws: Workspace, command: str, timeout: int = 120) -> str:
    if not command or not command.strip():
        raise ToolError("A command is required")
    timeout = max(5, min(int(timeout or 120), 900))
    env = dict(os.environ, PYTHONIOENCODING="utf-8", CI="1", NO_COLOR="1", FORCE_COLOR="0")
    try:
        done = subprocess.run([*shell_command(), command], cwd=ws.root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as err:
        out = (err.stdout or "") + (err.stderr or "") if isinstance(err.stdout, str) else ""
        return clip(f"Timed out after {timeout} s.\n{out}")
    output = (done.stdout or "") + (("\n" + done.stderr) if done.stderr else "")
    return clip(f"Exit code {done.returncode}\n{output.strip()}")


def todo_write(ws: Workspace, items: list) -> str:
    todos = []
    for item in items or []:
        if isinstance(item, str):
            item = {"task": item, "status": "pending"}
        if isinstance(item, dict) and str(item.get("task") or item.get("content") or "").strip():
            status = str(item.get("status", "pending")).lower()
            todos.append({"task": str(item.get("task") or item.get("content")).strip()[:200], "status": status if status in ("pending", "in_progress", "done") else "pending"})
    ws.todos = todos[:20]
    return "To-do list:\n" + "\n".join(f"[{'x' if t['status'] == 'done' else '>' if t['status'] == 'in_progress' else ' '}] {t['task']}" for t in ws.todos)


# ---------------- schemas ----------------

def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required}}}


TOOLS = [
    _fn("list_files", "List project files (respects .gitignore). Use pattern like '*.py' or 'src/**/*.ts' to narrow.",
        {"pattern": {"type": "string"}, "path": {"type": "string", "description": "Folder inside the project"}}, []),
    _fn("search", "Search file contents with a regular expression. Returns path:line: text.",
        {"pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string", "description": "Only files matching, e.g. *.py"}}, ["pattern"]),
    _fn("read_file", "Read a text file with line numbers (up to 400 lines per call). Read a file before editing it.",
        {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, ["path"]),
    _fn("edit_file", "Replace exact text in a file. old_text must match the current file (copy it from read_file without line numbers) and be unique; include a few surrounding lines.",
        {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}, "replace_all": {"type": "boolean"}}, ["path", "old_text", "new_text"]),
    _fn("write_file", "Create a new file, or replace a whole file you have read. Use edit_file for small changes.",
        {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    _fn("run_command", "Run a shell command in the project folder (tests, builds, git, package managers). Returns exit code and output.",
        {"command": {"type": "string"}, "timeout": {"type": "integer", "description": "Seconds, default 120"}}, ["command"]),
    _fn("todo_write", "Write or update your to-do list for a multi-step task. Pass the full list each time with status pending, in_progress or done.",
        {"items": {"type": "array", "items": {"type": "object", "properties": {"task": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "done"]}}, "required": ["task"]}}}, ["items"]),
]

READ_ONLY = {"list_files", "search", "read_file", "todo_write"}
EDITS = {"edit_file", "write_file"}

HANDLERS = {
    "list_files": list_files, "search": search, "read_file": read_file, "edit_file": edit_file,
    "write_file": write_file, "run_command": run_command, "todo_write": todo_write,
}


def call(ws: Workspace, name: str, arguments: dict) -> str:
    handler = HANDLERS.get(name)
    if handler is None:
        raise ToolError(f"There is no tool named {name}. Tools: {', '.join(HANDLERS)}")
    import inspect

    accepted = set(inspect.signature(handler).parameters) - {"ws"}
    aliases = {"file_path": "path", "filename": "path", "file": "path", "cmd": "command", "query": "pattern", "old_string": "old_text", "new_string": "new_text", "text": "content", "todos": "items"}
    clean = {}
    for key, value in (arguments or {}).items():
        key = aliases.get(key, key) if key not in accepted else key
        if key in accepted:
            clean[key] = value
    try:
        return handler(ws, **clean)
    except TypeError as err:
        raise ToolError(f"Wrong arguments for {name}: {err}") from err
