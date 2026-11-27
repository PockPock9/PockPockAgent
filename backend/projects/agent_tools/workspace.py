"""Workspace-scoped file access, edit staging, and validation."""

from .common import *

def _project_path(context: ProjectAgentContext, relative_path: str) -> tuple[Path, str]:
    if not isinstance(relative_path, str) or not relative_path.strip() or len(relative_path) > 240:
        raise AgentToolError("Provide a short project-relative file path")
    normalized = relative_path.replace("\\", "/")
    parts = normalized.split("/")
    if (
        normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
        or any(part in {"", ".", ".."} for part in parts)
        or any(part.lower() in _PROJECT_IGNORED_DIRS for part in parts)
    ):
        raise AgentToolError("Use a relative path inside the selected task workspace")
    filename = parts[-1].lower()
    if filename.startswith(".env") and filename != ".env.example":
        raise AgentToolError("Environment files are not available to the project agent")
    if re.search(r"(^|[._-])(?:credentials?|secrets?|passwords?|private[_-]?keys?|id_rsa|id_ed25519)(?:[._-]|$)", filename):
        raise AgentToolError("Credential and private-key files are not available to the project agent")
    if Path(filename).suffix.lower() not in _PROJECT_EXTENSIONS and filename != ".gitignore":
        raise AgentToolError("The project agent can only access supported text and source files")
    if filename.endswith((".lock", ".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".pfx", ".pyc")):
        raise AgentToolError("Lockfiles, databases, and credential files are not available to the project agent")

    root = context.project_root.resolve()
    target = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise AgentToolError("Symbolic links are not available to the project agent")
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as err:
        raise AgentToolError("Project paths must stay inside the selected task workspace") from err
    return resolved, "/".join(parts)

def list_project_files(context: ProjectAgentContext) -> list[str]:
    root = context.project_root.resolve()
    results: list[str] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name for name in directories
            if name.lower() not in _PROJECT_IGNORED_DIRS
            and not (Path(current) / name).is_symlink()
        )
        for filename in sorted(filenames):
            candidate = Path(current) / filename
            relative = candidate.relative_to(root).as_posix()
            try:
                _project_path(context, relative)
            except AgentToolError:
                continue
            results.append(relative)
            if len(results) >= 300:
                return results
    return results

_BLOCKING_DIALOG = re.compile(r"(?<![\w.$])(?:window\.)?(alert|confirm|prompt)\s*\(")


def _check_blocking_dialogs(source: str, relative: str, checks: list[dict[str, str]], issues: list[dict[str, str]]) -> None:
    """alert/confirm/prompt block the page; inside a game or animation loop they freeze it (often repeatedly)."""
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)
    found = sorted({match.group(1) for match in _BLOCKING_DIALOG.finditer(code)})
    if found:
        issues.append({"path": relative, "message": (
            f"Uses blocking {', '.join(f'{name}()' for name in found)}, which freezes the page until dismissed (and repeatedly "
            "inside a game loop). Show messages such as Game Over in the page or on the canvas instead."
        )})
    checks.append({"name": "No blocking dialogs", "path": relative, "status": "failed" if found else "passed"})


def validate_project(context: ProjectAgentContext) -> dict[str, Any]:
    """Run bounded syntax and local-reference checks over a task workspace."""
    root = context.project_root.resolve()
    files = list_project_files(context)
    issues: list[dict[str, str]] = []
    checks: list[dict[str, str]] = []
    source_files = [path for path in files if Path(path).suffix.lower() in {".py", ".js", ".mjs", ".cjs"}]
    node = shutil.which("node")
    for relative in source_files:
        path = root / relative
        suffix = path.suffix.lower()
        try:
            source = path.read_text(encoding="utf-8")
            if suffix == ".py":
                compile(source, str(path), "exec")
                checks.append({"name": "Python syntax", "path": relative, "status": "passed"})
            elif node and suffix in {".js", ".mjs", ".cjs"}:
                result = subprocess.run(
                    [node, "--check", str(path)], cwd=root, capture_output=True,
                    text=True, timeout=15, check=False,
                )
                if result.returncode:
                    issues.append({"path": relative, "message": (result.stderr or result.stdout).strip()[:2000]})
                    checks.append({"name": "JavaScript syntax", "path": relative, "status": "failed"})
                else:
                    checks.append({"name": "JavaScript syntax", "path": relative, "status": "passed"})
            if suffix in {".js", ".mjs", ".cjs"}:
                _check_blocking_dialogs(source, relative, checks, issues)
        except (SyntaxError, UnicodeError, OSError, subprocess.SubprocessError) as err:
            issues.append({"path": relative, "message": str(err)[:2000]})
            # Same names as the passing checks, so one file keeps one check name (issue #53).
            checks.append({"name": "Python syntax" if suffix == ".py" else "JavaScript syntax", "path": relative, "status": "failed"})

    class LocalReferences(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.references: list[str] = []
            self.inline_scripts: list[list[str]] = []
            self._script: list[str] | None = None

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "script" and not any(key == "src" and value for key, value in attrs):
                self._script = []
            for key, value in attrs:
                if key in {"src", "href"} and value:
                    reference = value.strip()
                    if reference and not reference.startswith(("#", "/", "//", "data:", "http:", "https:", "mailto:", "javascript:")):
                        self.references.append(reference.split("?", 1)[0].split("#", 1)[0])

        def handle_endtag(self, tag: str) -> None:
            if tag == "script" and self._script is not None:
                self.inline_scripts.append(self._script)
                self._script = None

        def handle_data(self, data: str) -> None:
            if self._script is not None:
                self._script.append(data)

    for relative in files:
        if Path(relative).suffix.lower() != ".html":
            continue
        html_path = root / relative
        parser = LocalReferences()
        try:
            parser.feed(html_path.read_text(encoding="utf-8"))
        except (UnicodeError, OSError) as err:
            issues.append({"path": relative, "message": f"Could not parse HTML: {err}"})
            continue
        for reference in parser.references:
            target = (html_path.parent / reference).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                issues.append({"path": relative, "message": f"Local reference escapes the workspace: {reference}"})
                continue
            if not target.is_file():
                issues.append({"path": relative, "message": f"Referenced local file does not exist: {reference}"})
        checks.append({"name": "HTML local references", "path": relative, "status": "failed" if any(item["path"] == relative for item in issues) else "passed"})
        if node:
            for index, script_parts in enumerate(parser.inline_scripts, start=1):
                result = subprocess.run(
                    [node, "--check"], input="".join(script_parts), cwd=root,
                    capture_output=True, text=True, timeout=15, check=False,
                )
                script_name = f"inline script {index}"
                if result.returncode:
                    checks.append({"name": "JavaScript syntax", "path": relative, "status": "failed"})
                    issues.append({"path": relative, "message": f"{script_name}: {(result.stderr or result.stdout).strip()[:2000]}"})
                else:
                    checks.append({"name": "JavaScript syntax", "path": relative, "status": "passed"})

    # A selected Full Access permission allows the agent to run only conventional,
    # explicitly configured project checks. Other modes remain read-only here.
    if context.allow_execution:
        package_json = root / "package.json"
        if package_json.is_file():
            try:
                package = json.loads(package_json.read_text(encoding="utf-8"))
                scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
                if isinstance(scripts, dict):
                    for script_name in ("build", "test"):
                        if not isinstance(scripts.get(script_name), str) or not scripts[script_name].strip():
                            continue
                        npm = shutil.which("npm") or shutil.which("npm.cmd")
                        if not npm:
                            checks.append({"name": f"npm {script_name}", "path": "package.json", "status": "skipped (npm unavailable)"})
                            continue
                        command = [npm, "run", script_name]
                        if os.name == "nt" and npm.lower().endswith((".cmd", ".bat")):
                            command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", subprocess.list2cmdline(command)]
                        try:
                            result = subprocess.run(
                                command, cwd=root, capture_output=True, text=True, timeout=120,
                                check=False, env={**os.environ, "CI": "true"},
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                            )
                            status = "passed" if result.returncode == 0 else "failed"
                            checks.append({"name": f"npm {script_name}", "path": "package.json", "status": status})
                            if result.returncode:
                                issues.append({"path": "package.json", "message": f"npm run {script_name} failed (exit {result.returncode}): {(result.stderr or result.stdout).strip()[-3000:] }"})
                        except subprocess.TimeoutExpired:
                            checks.append({"name": f"npm {script_name}", "path": "package.json", "status": "timed out"})
                            issues.append({"path": "package.json", "message": f"npm run {script_name} exceeded the 120 second validation limit"})
            except (OSError, ValueError, TypeError) as err:
                issues.append({"path": "package.json", "message": f"Could not read project scripts: {err}"})
    if not checks:
        checks.append({"name": "Workspace scan", "path": ".", "status": "passed"})
    return {"valid": not issues, "checks": checks, "issues": issues, "checked_files": len(files), "execution_enabled": context.allow_execution}

async def validate_project_service(context: ProjectAgentContext) -> dict[str, Any]:
    base_url = os.environ.get("POCKPOCK_VALIDATOR_URL", "http://127.0.0.1:8772").rstrip("/")
    token = os.environ.get("POCKPOCK_INTERNAL_TOKEN", "")
    if not token:
        raise AgentToolError("Internal service authentication is not configured")
    timeout = aiohttp.ClientTimeout(total=145)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{base_url}/validate",
                json={"workspace_path": str(context.project_root.resolve()), "allow_execution": context.allow_execution},
                headers={"X-PockPock-Internal-Token": token},
            ) as response:
                result = await response.json()
                if response.status >= 400:
                    detail = result.get("detail", "Validation service failed") if isinstance(result, dict) else "Validation service failed"
                    raise AgentToolError(str(detail))
        if not isinstance(result, dict) or not isinstance(result.get("checks"), list):
            raise AgentToolError("Validation service returned an invalid result")
        return result
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
        raise AgentToolError(f"Validation service is unavailable: {err}") from err

def _read_project_content(
    context: ProjectAgentContext,
    relative_path: str,
    *,
    count_usage: bool,
) -> dict[str, str]:
    path, display_path = _project_path(context, relative_path)
    if count_usage and display_path not in context.inspected_paths and context.files_read >= 20:
        raise AgentToolError("A project task may inspect at most 20 files")
    try:
        if not path.is_file():
            raise AgentToolError("The requested project file does not exist")
        data = path.read_bytes()
    except OSError as err:
        raise AgentToolError(f"Could not read the project file: {err}") from err
    if len(data) > 250_000:
        raise AgentToolError("Project files over 250 KB are not available to the coding agent")
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as err:
        raise AgentToolError("The project agent can only read UTF-8 text files") from err
    if count_usage and display_path not in context.inspected_paths:
        context.files_read += 1
        context.inspected_paths.add(display_path)
    return {
        "path": display_path,
        "content": content,
        "_source_hash": hashlib.sha256(data).hexdigest(),
    }

def read_project_file(
    context: ProjectAgentContext,
    relative_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    result = _read_project_content(context, relative_path, count_usage=True)
    lines = result["content"].splitlines(keepends=True)
    total_lines = len(lines)
    if not total_lines:
        context.fully_read_hashes[result["path"]] = result["_source_hash"]
        return {
            "path": result["path"],
            "content": "",
            "start_line": 1,
            "end_line": 0,
            "total_lines": 0,
            "truncated": False,
            "next_start_line": None,
        }
    if start_line is None:
        start_line = 1
    if isinstance(start_line, bool) or not isinstance(start_line, int) or start_line < 1 or start_line > total_lines:
        raise AgentToolError(f"Choose a start line between 1 and {total_lines}")
    if end_line is not None and (
        isinstance(end_line, bool)
        or not isinstance(end_line, int)
        or end_line < start_line
    ):
        raise AgentToolError("The end line must be an integer at or after the start line")

    requested_end = min(
        end_line if end_line is not None else start_line + _PROJECT_READ_MAX_LINES - 1,
        start_line + _PROJECT_READ_MAX_LINES - 1,
        total_lines,
    )
    selected_lines = lines[start_line - 1:requested_end]
    content_lines: list[str] = []
    content_size = 0
    for line in selected_lines:
        if content_size + len(line) > _PROJECT_READ_MAX_CHARS:
            if not content_lines:
                raise AgentToolError("A line in this range is too long; use search_project to inspect a shorter excerpt")
            break
        content_lines.append(line)
        content_size += len(line)

    actual_end = start_line + len(content_lines) - 1
    truncated = actual_end < total_lines
    if start_line == 1 and actual_end == total_lines and not truncated:
        context.fully_read_hashes[result["path"]] = result["_source_hash"]
    else:
        source_hash, covered = context.read_coverage.get(result["path"], ("", 0))
        if source_hash != result["_source_hash"]:
            covered = 0
        if start_line <= covered + 1:
            covered = max(covered, actual_end)
        context.read_coverage[result["path"]] = (result["_source_hash"], covered)
        if covered >= total_lines:
            context.fully_read_hashes[result["path"]] = result["_source_hash"]
    return {
        "path": result["path"],
        "content": "".join(content_lines).replace("\r\n", "\n").replace("\r", "\n"),
        "start_line": start_line,
        "end_line": actual_end,
        "total_lines": total_lines,
        "truncated": truncated,
        "next_start_line": actual_end + 1 if truncated else None,
    }

def search_project(context: ProjectAgentContext, query: str) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip() or len(query) > 120:
        raise AgentToolError("Provide a search phrase of at most 120 characters")
    needle = query.casefold()
    matches: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    scanned = 0
    for relative_path in list_project_files(context):
        if scanned >= 100 or len(matches) >= _PROJECT_SEARCH_MAX_MATCHES:
            break
        scanned += 1
        try:
            content = _read_project_content(context, relative_path, count_usage=False)["content"]
        except AgentToolError as err:
            skipped.append({"path": relative_path, "reason": str(err)})
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            if needle in line.casefold():
                matches.append({
                    "path": relative_path,
                    "line": line_number,
                    "text": line[:_PROJECT_SEARCH_MAX_LINE_CHARS],
                })
                if len(matches) >= _PROJECT_SEARCH_MAX_MATCHES:
                    break
    return {
        "query": query,
        "files_scanned": scanned,
        "matches": matches,
        "skipped_files": skipped[:20],
    }

def _stage_project_content(
    context: ProjectAgentContext,
    display_path: str,
    original: bytes,
    original_text: str,
    content: str,
    summary: str,
    *,
    original_exists: bool,
) -> dict[str, Any]:
    if context.patches_proposed >= _PROJECT_PATCH_LIMIT:
        raise AgentToolError(f"A project task may propose at most {_PROJECT_PATCH_LIMIT} file changes")
    if not isinstance(content, str) or len(content.encode("utf-8")) > 250_000:
        raise AgentToolError("A proposed project file must be at most 250 KB")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 240:
        raise AgentToolError("Provide a short explanation for the proposed change")
    encoded = content.encode("utf-8")
    if original == encoded:
        raise AgentToolError("The proposed content does not change this file")
    _expire_project_patches()
    if sum(patch.status == "pending" for patch in _PENDING_PROJECT_PATCHES.values()) >= 50:
        raise AgentToolError("Too many project changes are awaiting review; apply or discard one before continuing")
    patch_id = uuid.uuid4().hex
    diff = "\n".join(difflib.unified_diff(
        original_text.splitlines(),
        content.splitlines(),
        fromfile=f"a/{display_path}" if original_exists else "/dev/null",
        tofile=f"b/{display_path}",
        lineterm="",
    ))
    if len(diff) > 50_000:
        diff = diff[:50_000] + "\n… diff truncated at 50 KB"
    patch = PendingProjectPatch(
        patch_id=patch_id,
        relative_path=display_path,
        summary=summary.strip(),
        content=content,
        original_hash=hashlib.sha256(original).hexdigest() if original_exists else None,
        diff=diff,
        created_at=time.monotonic(),
    )
    _PENDING_PROJECT_PATCHES[patch_id] = patch
    context.patches_proposed += 1
    return {
        "patch_id": patch.patch_id,
        "path": patch.relative_path,
        "summary": patch.summary,
        "diff": patch.diff,
        "status": patch.status,
    }

def propose_project_patch(
    context: ProjectAgentContext,
    relative_path: str,
    content: str,
    summary: str,
) -> dict[str, Any]:
    path, display_path = _project_path(context, relative_path)
    original_exists = path.exists()
    if original_exists and display_path not in context.inspected_paths:
        raise AgentToolError("Read this exact file before proposing a replacement for it")
    if original_exists and not path.is_file():
        raise AgentToolError("Only regular project files can be changed")
    full_read_hash = context.fully_read_hashes.get(display_path)
    if original_exists and full_read_hash is None:
        raise AgentToolError(
            "Read the whole file before proposing a full replacement (in one call, or in consecutive parts "
            "starting at line 1); use propose_project_edit for localized changes"
        )
    try:
        original = path.read_bytes() if original_exists else b""
        if len(original) > 250_000:
            raise AgentToolError("Project files over 250 KB cannot be changed by the coding agent")
        original_text = original.decode("utf-8")
    except (OSError, UnicodeDecodeError) as err:
        raise AgentToolError(f"Could not safely prepare the project diff: {err}") from err
    if original_exists and hashlib.sha256(original).hexdigest() != full_read_hash:
        raise AgentToolError(
            "The project file changed after it was read in full; read it again before proposing a full replacement"
        )
    return _stage_project_content(
        context,
        display_path,
        original,
        original_text,
        content,
        summary,
        original_exists=original_exists,
    )

def propose_project_addition(
    context: ProjectAgentContext,
    relative_path: str,
    content: str,
    summary: str,
) -> dict[str, Any]:
    path, display_path = _project_path(context, relative_path)
    _expire_project_patches()
    if path.exists():
        raise AgentToolError("The proposed child file conflicts with a file already in the parent workspace")
    if any(
        patch.status == "pending" and patch.relative_path == display_path
        for patch in _PENDING_PROJECT_PATCHES.values()
    ):
        raise AgentToolError("The proposed child file conflicts with another pending parent patch")
    return _stage_project_content(
        context,
        display_path,
        b"",
        "",
        content,
        summary,
        original_exists=False,
    )

def propose_project_edit(
    context: ProjectAgentContext,
    relative_path: str,
    old_text: str,
    new_text: str,
    summary: str,
) -> dict[str, Any]:
    path, display_path = _project_path(context, relative_path)
    if not path.exists() or not path.is_file():
        raise AgentToolError("Exact-text edits require an existing regular project file")
    if display_path not in context.inspected_paths:
        raise AgentToolError("Read this exact file before proposing an edit")
    if not isinstance(old_text, str) or not old_text or len(old_text) > _PROJECT_EDIT_MAX_CHARS:
        raise AgentToolError("Provide a non-empty exact source snippet of at most 12,000 characters")
    if not isinstance(new_text, str) or len(new_text) > _PROJECT_EDIT_MAX_CHARS:
        raise AgentToolError("The replacement snippet must be at most 12,000 characters")
    try:
        original = path.read_bytes()
        if len(original) > 250_000:
            raise AgentToolError("Project files over 250 KB cannot be changed by the coding agent")
        original_text = original.decode("utf-8")
    except (OSError, UnicodeDecodeError) as err:
        raise AgentToolError(f"Could not safely prepare the project edit: {err}") from err
    line_ending = "\r\n" if "\r\n" in original_text else "\n"
    old_text = old_text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", line_ending)
    new_text = new_text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", line_ending)
    if original_text.count(old_text) != 1:
        raise AgentToolError("The exact source snippet must occur exactly once in the current file")
    content = original_text.replace(old_text, new_text, 1)
    return _stage_project_content(
        context,
        display_path,
        original,
        original_text,
        content,
        summary,
        original_exists=True,
    )

def _expire_project_patches() -> None:
    now = time.monotonic()
    for patch_id in [
        patch_id for patch_id, patch in _PENDING_PROJECT_PATCHES.items()
        if now - patch.created_at > _PROJECT_PATCH_TTL
    ]:
        del _PENDING_PROJECT_PATCHES[patch_id]

def apply_project_patch(patch_id: str, project_root: Path = _PROJECT_ROOT) -> dict[str, str]:
    _expire_project_patches()
    patch = _PENDING_PROJECT_PATCHES.get(patch_id)
    if patch is None:
        raise AgentToolError("This project diff expired or is no longer available")
    if patch.status != "pending":
        raise AgentToolError("This project diff has already been applied")
    path, display_path = _project_path(ProjectAgentContext("", project_root), patch.relative_path)
    if display_path != patch.relative_path:
        raise AgentToolError("The proposed project path changed; request a fresh diff")
    try:
        current = path.read_bytes() if path.exists() else None
    except OSError as err:
        raise AgentToolError(f"Could not verify the project file before applying: {err}") from err
    current_hash = hashlib.sha256(current).hexdigest() if current is not None else None
    if current_hash != patch.original_hash:
        raise AgentToolError("The project file changed after this diff was created. Ask the brain for a fresh diff.")

    path.parent.mkdir(parents=True, exist_ok=True)
    # Re-resolve after creating parent folders so the new path still remains
    # inside the selected workspace and no newly introduced symlink is followed.
    path, display_path = _project_path(ProjectAgentContext("", project_root), patch.relative_path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as output:
            output.write(patch.content.encode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
        if patch.original_hash is not None:
            latest = path.read_bytes()
            if hashlib.sha256(latest).hexdigest() != patch.original_hash:
                raise AgentToolError("The project file changed while applying the diff. Request a fresh review.")
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        if patch.original_hash is None:
            if path.exists():
                raise AgentToolError("A file appeared at this path after the diff was created")
            os.replace(temporary, path)
        else:
            if path.is_symlink():
                raise AgentToolError("Symbolic links are not available to the project agent")
            os.replace(temporary, path)
    except AgentToolError:
        raise
    except OSError as err:
        raise AgentToolError(f"Could not apply the approved project diff: {err}") from err
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove temporary project patch file")
    patch.status = "applied"
    return {"patch_id": patch.patch_id, "path": patch.relative_path, "status": patch.status}

def revert_project_addition(
    relative_path: str,
    expected_content: str,
    project_root: Path = _PROJECT_ROOT,
) -> dict[str, str]:
    path, display_path = _project_path(ProjectAgentContext("", project_root), relative_path)
    if path.is_symlink() or not path.is_file():
        raise AgentToolError("The merged child file is no longer a regular project file")
    try:
        current = path.read_bytes()
    except OSError as err:
        raise AgentToolError(f"Could not verify the merged child file before reverting: {err}") from err
    if current != expected_content.encode("utf-8"):
        raise AgentToolError("The merged child file changed after application; it was left untouched")
    try:
        path.unlink()
    except OSError as err:
        raise AgentToolError(f"Could not revert the unvalidated child file: {err}") from err
    return {"path": display_path, "status": "reverted"}
