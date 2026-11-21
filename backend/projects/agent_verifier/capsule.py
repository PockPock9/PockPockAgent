"""Persisted state capsule for a verifiable agent run.

The capsule is the compact, structured record that survives compaction and
process death: goal, decisions, constraints, files changed (with content and
diff hashes), open threads, and the next step. It is the unit a resume loads
and a rewind restores — never the executor's raw transcript, so a resumed run
does not inherit a possibly hallucinated history.

This is a design-only adoption of the plan-and-sequence state capsule: this
module does not depend on the (unmerged) plan_sequence code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field


@dataclass
class ChangedFile:
    """One workspace file touched by a step, identified by content hashes."""

    path: str
    sha256: str = ""
    sha256_before: str = ""
    diff_hash: str = ""
    restored: bool = False


@dataclass
class StateCapsule:
    """Structured resume state for one run, persisted in the ledger."""

    goal: str = ""
    decisions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    files_changed: list[ChangedFile] = field(default_factory=list)
    open_threads: list[str] = field(default_factory=list)
    next_step: str = ""
    step_index: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict | None) -> "StateCapsule":
        if not isinstance(raw, dict):
            return cls()
        files = [
            ChangedFile(**item)
            for item in raw.get("files_changed", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        ]
        return cls(
            goal=str(raw.get("goal", "")),
            decisions=[str(item) for item in raw.get("decisions", []) if isinstance(item, str)],
            constraints=[str(item) for item in raw.get("constraints", []) if isinstance(item, str)],
            files_changed=files,
            open_threads=[str(item) for item in raw.get("open_threads", []) if isinstance(item, str)],
            next_step=str(raw.get("next_step", "")),
            step_index=int(raw.get("step_index", 0) or 0),
        )

    def record_file(self, path: str, *, sha256_before: str = "", sha256: str = "") -> ChangedFile:
        """Record (or refresh) a changed file, with a stable diff hash."""
        diff_hash = hashlib.sha256(
            f"{sha256_before}\n{sha256}".encode("utf-8")
        ).hexdigest()
        for item in self.files_changed:
            if item.path == path:
                item.sha256_before = item.sha256_before or sha256_before
                item.sha256 = sha256
                item.diff_hash = diff_hash
                return item
        item = ChangedFile(path=path, sha256=sha256, sha256_before=sha256_before, diff_hash=diff_hash)
        self.files_changed.append(item)
        return item

    def content_hash(self) -> str:
        """Stable hash of the capsule, for detecting resume drift."""
        payload = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
