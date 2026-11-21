"""Eval task definitions for the agent harness.

A task is a JSON (or YAML) document with a user prompt, optional
attachments and workspace setup files, a reference solution expressed as
tool calls (``stub_actions``), and a list of deterministic verifiers.
The verifiers — not the model — decide pass/fail; see ``verifiers.py``.

Task format::

    {
      "id": "artifact-shopping-list",
      "title": "Save a shopping list as text",
      "category": "artifact",
      "prompt": "Save a plain-text shopping list as shopping.txt: ...",
      "attachments": {"data.csv": "name,score\\n..."},
      "setup": {"files": {"counter.py": "for i in range(1, 11):\\n    print(i)\\n"}},
      "stub_actions": [
        {"tool": "save_text_artifact",
         "arguments": {"filename": "shopping.txt", "content": "..."}}
      ],
      "verifiers": [
        {"kind": "file_contains", "path": "shopping.txt",
         "contains": ["milk", "eggs"]}
      ],
      "requires": [],
      "timeout_s": 60
    }

``requires`` names optional capabilities a task needs, e.g. ``"network"``.
The runner skips tasks whose requirements are not enabled and records
the skip, so the default suite stays runnable offline on a clean VM.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = ("id", "prompt", "verifiers")
OPTIONAL_STRING_FIELDS = ("title", "category")


@dataclass(frozen=True)
class EvalTask:
    """One verifiable agent task."""

    id: str
    prompt: str
    verifiers: list[dict[str, Any]]
    title: str = ""
    category: str = "general"
    attachments: dict[str, str] = field(default_factory=dict)
    setup_files: dict[str, str] = field(default_factory=dict)
    stub_actions: list[dict[str, Any]] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    timeout_s: int = 120

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "prompt": self.prompt,
            "attachments": self.attachments,
            "setup": {"files": self.setup_files},
            "stub_actions": self.stub_actions,
            "verifiers": self.verifiers,
            "requires": self.requires,
            "timeout_s": self.timeout_s,
        }


def _task_from_dict(raw: Any, *, source: str) -> EvalTask:
    if not isinstance(raw, dict):
        raise ValueError(f"Task in {source} must be an object, got {type(raw).__name__}")
    for name in REQUIRED_FIELDS:
        if name not in raw:
            raise ValueError(f"Task in {source} is missing required field {name!r}")
    task_id = raw["id"]
    prompt = raw["prompt"]
    verifiers = raw["verifiers"]
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError(f"Task in {source} needs a non-empty string 'id'")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Task {task_id!r} in {source} needs a non-empty string 'prompt'")
    if not isinstance(verifiers, list) or not verifiers:
        raise ValueError(f"Task {task_id!r} in {source} needs a non-empty 'verifiers' list")
    for check in verifiers:
        if not isinstance(check, dict) or "kind" not in check:
            raise ValueError(f"Task {task_id!r} in {source} has a verifier without a 'kind'")
    attachments = raw.get("attachments") or {}
    setup = raw.get("setup") or {}
    setup_files = setup.get("files") or {} if isinstance(setup, dict) else {}
    stub_actions = raw.get("stub_actions") or []
    requires = raw.get("requires") or []
    if not isinstance(attachments, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in attachments.items()
    ):
        raise ValueError(f"Task {task_id!r} in {source}: 'attachments' must map filenames to text")
    if not isinstance(setup_files, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in setup_files.items()
    ):
        raise ValueError(f"Task {task_id!r} in {source}: 'setup.files' must map paths to text")
    if not isinstance(stub_actions, list) or not all(
        isinstance(action, dict) and isinstance(action.get("tool"), str) for action in stub_actions
    ):
        raise ValueError(f"Task {task_id!r} in {source}: 'stub_actions' need a 'tool' name each")
    if not isinstance(requires, list) or not all(isinstance(item, str) for item in requires):
        raise ValueError(f"Task {task_id!r} in {source}: 'requires' must be a list of strings")
    timeout_s = raw.get("timeout_s", 120)
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, int) or timeout_s <= 0:
        raise ValueError(f"Task {task_id!r} in {source}: 'timeout_s' must be a positive integer")
    return EvalTask(
        id=task_id,
        prompt=prompt,
        verifiers=list(verifiers),
        title=str(raw.get("title") or ""),
        category=str(raw.get("category") or "general"),
        attachments=dict(attachments),
        setup_files=dict(setup_files),
        stub_actions=list(stub_actions),
        requires=list(requires),
        timeout_s=timeout_s,
    )


def load_suite(path: str | Path) -> list[EvalTask]:
    """Load tasks from a JSON or YAML suite file.

    YAML needs PyYAML (already a backend dependency); JSON always works.
    A file may hold a bare list of tasks or ``{"tasks": [...]}``.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as err:  # pragma: no cover - PyYAML is installed
            raise ValueError("YAML suites need PyYAML installed") from err
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    if isinstance(raw, dict):
        raw = raw.get("tasks")
    if not isinstance(raw, list):
        raise ValueError(f"Suite {path} must hold a list of tasks or {{'tasks': [...]}}")
    tasks = [_task_from_dict(item, source=str(path)) for item in raw]
    seen: set[str] = set()
    for task in tasks:
        if task.id in seen:
            raise ValueError(f"Suite {path} has duplicate task id {task.id!r}")
        seen.add(task.id)
    return tasks


def split_suite(
    tasks: list[EvalTask], *, train_size: int, seed: int = 0
) -> tuple[list[EvalTask], list[EvalTask]]:
    """Deterministically split a suite into train / held-out slices.

    Tasks are shuffled with ``seed`` (stdlib ``random`` only), so the same
    seed always yields the same split. Used by the prompt optimizer:
    candidates are selected on the train slice and judged on held-out.
    """
    import random

    ordered = list(tasks)
    random.Random(seed).shuffle(ordered)
    train_size = max(0, min(len(ordered), train_size))
    return ordered[:train_size], ordered[train_size:]
