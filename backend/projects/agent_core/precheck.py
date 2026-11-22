"""A fixed check of a new plan before the user sees it (no model call).

Shown on the plan card as "Plan checked": whether the files the request names are in the open
folder, whether the chosen permission mode allows the tools the plan needs, whether public research
is switched on when the plan needs it, and whether the planner left questions open. Each result is
``{"id", "status": "pass" | "warn", "label", "detail"}``; a warning never blocks approval, it says
what will go wrong and how to avoid it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

_FILE_NAME = re.compile(
    r"(?<![\w/\\.-])((?:[\w.-]+[\\/])*[\w-][\w.-]*\.(?:md|txt|csv|tsv|json|html?|py|js|mjs|cjs|ts|tsx|jsx|css|xlsx|xls|docx|pptx|pdf"
    r"|ya?ml|xml|log|ini|toml|cfg|sh|ps1|sql|ipynb))\b",
    re.IGNORECASE,
)
_ATTACHED_LINE = re.compile(r"^Attached files:\s*(.+)$", re.MULTILINE)
_FOLDER_CAPABILITIES = {"workspace_read", "workspace_write", "project_validation"}
_RESEARCH_CAPABILITIES = {"public_research"}
_SEARCH_LIMIT = 5_000  # entries visited when looking for a file name anywhere in the folder


def named_files(request: str, deliverables: list[str]) -> list[str]:
    """File names the request mentions that it expects to exist: not attachments, not deliverables."""
    attached = {name.strip().lower() for line in _ATTACHED_LINE.findall(request) for name in line.split(",")}
    text = _ATTACHED_LINE.sub("", request)
    produced = {Path(str(item).replace("\\", "/")).name.lower() for item in deliverables}
    found: list[str] = []
    for match in _FILE_NAME.findall(text):
        name = match.replace("\\", "/")
        base = Path(name).name.lower()
        if base in attached or base in produced or name in found:
            continue
        found.append(name)
    return found[:12]


def _exists_in(folder: Path, name: str) -> bool:
    """The relative path exists inside ``folder``, or a file with that name does somewhere below it."""
    try:
        root = folder.resolve()
        candidate = (root / name).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return True
    except (OSError, ValueError):
        return False
    base = Path(name).name.lower()
    seen = 0
    for current, directories, files in os.walk(root):
        directories[:] = [item for item in directories if not item.startswith(".") and item not in {"node_modules", "__pycache__", ".venv", "venv"}]
        seen += len(files) + len(directories)
        if any(item.lower() == base for item in files):
            return True
        if seen > _SEARCH_LIMIT:
            return False
    return False


def plan_precheck(
    *,
    request: str,
    task_brief: dict[str, Any],
    workspace: Path | None,
    permission_mode: str,
    research_enabled: bool,
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    capabilities = set(task_brief.get("required_capabilities") or [])
    deliverables = [str(item) for item in task_brief.get("deliverables") or []]

    names = named_files(request, deliverables)
    if names:
        if workspace is None:
            checks.append({"id": "files", "status": "warn", "label": "No folder open",
                           "detail": f"The request names {', '.join(names)}, but no folder is open, so the agent cannot read them. Open the folder first, or attach the files."})
        else:
            missing = [name for name in names if not _exists_in(workspace, name)]
            if missing:
                checks.append({"id": "files", "status": "warn", "label": "Files not found",
                               "detail": f"Not in {workspace.name}: {', '.join(missing)}."})
            else:
                checks.append({"id": "files", "status": "pass", "label": "Files found", "detail": ", ".join(names)})

    needs_folder = sorted(capabilities & _FOLDER_CAPABILITIES)
    if needs_folder and permission_mode == "default":
        checks.append({"id": "tools", "status": "warn", "label": "Tools not allowed",
                       "detail": "Default permission is read-only and blocks the folder tools this plan needs. Choose Auto-review or Full access before approving."})
    elif capabilities & _RESEARCH_CAPABILITIES and not research_enabled:
        checks.append({"id": "tools", "status": "warn", "label": "Research is off",
                       "detail": "This plan reads public websites, but public research is switched off. Turn it on in Workshop → Research first."})
    else:
        checks.append({"id": "tools", "status": "pass", "label": "Tools allowed",
                       "detail": f"Every tool this plan needs is allowed in {permission_mode.replace('-', ' ').title().replace('Auto Review', 'Auto-review')}."})

    questions = [str(item) for item in task_brief.get("clarifying_questions") or []]
    if questions:
        checks.append({"id": "questions", "status": "warn", "label": f"{len(questions)} {'question' if len(questions) == 1 else 'questions'} open",
                       "detail": "Answer below, or approve and let the agent decide."})
    else:
        checks.append({"id": "questions", "status": "pass", "label": "Nothing unclear", "detail": "The planner asked no questions."})
    return checks
