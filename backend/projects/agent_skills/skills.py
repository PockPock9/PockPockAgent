"""Self-authored skill library (Phase 1 of the agentic-AI differentiation plan).

Skills are stored as files on disk in the open Agent Skills format: one
directory per skill holding a ``SKILL.md`` with YAML frontmatter (``name``,
``description``, ``version``) plus a body, and optional ``scripts/`` and
``references/`` subdirectories. The library is the *procedural* tier of
memory: raw run trajectories are input material, not the asset — what
transfers to the next run is the distilled, verified skill file.

Lifecycle (enforced by :mod:`projects.agent_skills.inbox`, not here):
``draft -> verified -> promoted -> pruned`` (or ``invalidated``). A skill
is retrievable into a live run only while its status is ``promoted``.
Unverified candidates must never be retrieved; this module's
:meth:`SkillLibrary.retrieve` filters on status, and the service layer
only ever hands it promoted skills.

Retrieval reuses the Tool-RAG BM25 path from
``projects.agent_tools.tool_retriever`` (stdlib only), with optional dense
embeddings via Ollama ``/api/embed`` and graceful fallback to keyword-only
— exactly like ``ToolRetriever`` does. No external memory platform, no
vector database, no new dependency.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

# ``BM25Index``/``tokenize``/``OllamaEmbedder`` live in the Tool-RAG module;
# importing them keeps one retrieval implementation instead of two.
from ..agent_tools.tool_retriever import (  # noqa: E402
    BM25Index,
    OllamaEmbedder,
    _cosine,
    tokenize,
)

#: Frontmatter keys a skill file must carry.
REQUIRED_FRONTMATTER = ("name", "description")

#: Semantic-version-ish pattern accepted for ``version``.
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

#: Skill names are directory names: lowercase letters, digits, hyphens.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

#: Maximum body size accepted on load (a skill body is progressive
#: disclosure: metadata ~100 tokens, body <5,000 tokens).
MAX_BODY_CHARS = 40_000

#: Default retrieval depth for a live run.
DEFAULT_TOP_K = 3

#: Minimum best BM25 score for retrieval to be trusted.
MIN_BM25_SCORE = 0.5


def default_skills_dir() -> Path:
    """Default skills directory under the app data dir (env-overridable)."""
    override = os.environ.get("POCKPOCK_SKILLS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    try:
        from pockpock_paths import app_data_dir  # type: ignore

        return app_data_dir("PockPock") / "agent-skills"
    except Exception:
        return Path.home() / ".local" / "share" / "PockPock" / "agent-skills"


def skills_enabled() -> bool:
    """Whether skill retrieval is switched on for live runs (env flag, default off)."""
    return os.environ.get("POCKPOCK_SKILLS_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def slugify(text: str) -> str:
    """Turn free text into a safe skill-name slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:64] or "skill"


# ---------------------------------------------------------------------------
# Skill schema + frontmatter
# ---------------------------------------------------------------------------


@dataclass
class Skill:
    """One skill: frontmatter metadata plus body and optional file refs."""

    name: str
    description: str
    version: str = "0.1.0"
    body: str = ""
    # Verification test shipped with the skill, e.g.
    # {"type": "script", "command": ["python", "scripts/test.py"], "timeout_s": 60}
    # or {"type": "manual"} (human approval alone suffices).
    verification: dict[str, Any] = field(default_factory=dict)
    # Free-form tags / task the skill applies to; used by retrieval and
    # contradiction detection.
    tags: list[str] = field(default_factory=list)
    source_run_id: str = ""
    status: str = "draft"  # draft | verified | promoted | pruned | invalidated
    confidence: float = 0.5
    created_at: str = ""
    updated_at: str = ""

    def to_frontmatter_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
        }
        if self.verification:
            data["verification"] = self.verification
        if self.tags:
            data["tags"] = list(self.tags)
        if self.source_run_id:
            data["source_run_id"] = self.source_run_id
        return data

    def to_markdown(self) -> str:
        """Serialise the skill as SKILL.md (frontmatter + body)."""
        lines = ["---"]
        for key, value in self.to_frontmatter_dict().items():
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        lines.append("---")
        lines.append("")
        lines.append(self.body.rstrip("\n"))
        lines.append("")
        return "\n".join(lines)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split ``---`` frontmatter from the body of a SKILL.md file."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        raise ValueError("SKILL.md frontmatter is not closed with '---'")
    raw = text[3:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")
    data: dict[str, Any] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"Unparseable frontmatter line: {line!r}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        try:
            data[key] = json.loads(value) if value else ""
        except json.JSONDecodeError:
            data[key] = value
    return data, body


def validate_skill(skill: Skill) -> list[str]:
    """Return a list of validation problems (empty means valid)."""
    problems: list[str] = []
    if not _NAME_RE.match(skill.name or ""):
        problems.append(
            "name must be lowercase letters, digits and hyphens (max 64 chars)"
        )
    if not (skill.description or "").strip():
        problems.append("description is required")
    elif len(skill.description) > 1024:
        problems.append("description must be at most 1024 characters")
    if not _VERSION_RE.match(skill.version or ""):
        problems.append("version must look like '1.0.0'")
    if not (skill.body or "").strip():
        problems.append("body must not be empty")
    elif len(skill.body) > MAX_BODY_CHARS:
        problems.append(f"body must be at most {MAX_BODY_CHARS} characters")
    if skill.status not in {"draft", "verified", "promoted", "pruned", "invalidated"}:
        problems.append(f"unknown status: {skill.status!r}")
    if not 0.0 <= skill.confidence <= 1.0:
        problems.append("confidence must be between 0.0 and 1.0")
    verification = skill.verification or {}
    if verification:
        vtype = verification.get("type")
        if vtype == "script":
            command = verification.get("command")
            if not isinstance(command, list) or not command or not all(
                isinstance(part, str) for part in command
            ):
                problems.append("verification script needs a non-empty command list")
        elif vtype == "python":
            if not isinstance(verification.get("code"), str) or not verification["code"].strip():
                problems.append("verification python needs non-empty code")
        elif vtype == "manual":
            pass
        else:
            problems.append(f"unknown verification type: {vtype!r}")
    return problems


def skill_from_markdown(text: str, *, status: str = "draft") -> Skill:
    """Parse a SKILL.md file into a :class:`Skill` (raises on bad input)."""
    data, body = parse_frontmatter(text)
    missing = [key for key in REQUIRED_FRONTMATTER if not data.get(key)]
    if missing:
        raise ValueError(f"SKILL.md frontmatter is missing: {', '.join(missing)}")
    skill = Skill(
        name=str(data["name"]),
        description=str(data["description"]),
        version=str(data.get("version", "0.1.0")),
        body=body,
        verification=data.get("verification") or {},
        tags=list(data.get("tags") or []),
        source_run_id=str(data.get("source_run_id", "")),
        status=status,
    )
    problems = validate_skill(skill)
    if problems:
        raise ValueError("Invalid skill: " + "; ".join(problems))
    return skill


# ---------------------------------------------------------------------------
# Library: CRUD over skill directories on disk
# ---------------------------------------------------------------------------


@dataclass
class SkillRecord:
    """A skill plus its on-disk location and retrieval score (when ranked)."""

    skill: Skill
    path: Path
    score: float = 0.0


class SkillLibrary:
    """CRUD + retrieval over a directory of skill folders.

    Layout: ``<skills_dir>/<name>/SKILL.md`` plus optional ``scripts/``
    and ``references/``. Status lives in the companion SQLite registry
    (see :mod:`projects.agent_skills.inbox`); the file is the source of
    truth for content, the registry for lifecycle state.
    """

    def __init__(
        self,
        skills_dir: Path | str | None = None,
        *,
        embedder: OllamaEmbedder | None = None,
        dense_enabled: bool = True,
    ):
        self.skills_dir = Path(skills_dir) if skills_dir is not None else default_skills_dir()
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._embedder = embedder
        self._dense_enabled = dense_enabled
        self._doc_embeddings: list[list[float]] | None = None
        self._status: dict[str, str] = {}  # name -> status, when no registry is attached

    # -- status registry hook -------------------------------------------------
    def attach_statuses(self, statuses: Mapping[str, str]) -> None:
        """Attach lifecycle statuses (name -> status) from the registry."""
        self._status = dict(statuses)

    def status_of(self, name: str) -> str:
        return self._status.get(name, "draft")

    # -- CRUD -----------------------------------------------------------------
    def skill_path(self, name: str) -> Path:
        if not _NAME_RE.match(name or ""):
            raise ValueError(f"Invalid skill name: {name!r}")
        return self.skills_dir / name / "SKILL.md"

    def create(self, skill: Skill, *, overwrite: bool = False) -> Path:
        """Write a new skill to disk (status starts as ``draft``)."""
        problems = validate_skill(skill)
        if problems:
            raise ValueError("Invalid skill: " + "; ".join(problems))
        path = self.skill_path(skill.name)
        if path.exists() and not overwrite:
            raise FileExistsError(f"Skill already exists: {skill.name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        skill.created_at = skill.created_at or now
        skill.updated_at = now
        path.write_text(skill.to_markdown(), encoding="utf-8")
        self._status[skill.name] = skill.status
        self._doc_embeddings = None  # index is stale
        return path

    def read(self, name: str) -> SkillRecord:
        """Read one skill from disk, with its lifecycle status attached."""
        path = self.skill_path(name)
        if not path.is_file():
            raise FileNotFoundError(f"No such skill: {name}")
        skill = skill_from_markdown(path.read_text(encoding="utf-8"), status=self.status_of(name))
        return SkillRecord(skill=skill, path=path)

    def update(self, skill: Skill) -> Path:
        """Replace a skill's file (name must already exist)."""
        problems = validate_skill(skill)
        if problems:
            raise ValueError("Invalid skill: " + "; ".join(problems))
        path = self.skill_path(skill.name)
        if not path.is_file():
            raise FileNotFoundError(f"No such skill: {skill.name}")
        skill.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path.write_text(skill.to_markdown(), encoding="utf-8")
        self._doc_embeddings = None
        return path

    def delete(self, name: str) -> bool:
        """Remove a skill directory entirely. Returns False if absent."""
        directory = self.skills_dir / name
        if not directory.is_dir():
            return False
        shutil.rmtree(directory)
        self._status.pop(name, None)
        self._doc_embeddings = None
        return True

    def list(self, *, status: str | None = None) -> list[SkillRecord]:
        """List every skill on disk, optionally filtered by lifecycle status."""
        records: list[SkillRecord] = []
        for directory in sorted(self.skills_dir.iterdir()):
            path = directory / "SKILL.md"
            if not directory.is_dir() or not path.is_file():
                continue
            try:
                record = self.read(directory.name)
            except ValueError:
                # A malformed skill file must not hide the rest of the library.
                continue
            if status is None or record.skill.status == status:
                records.append(record)
        return records

    # -- retrieval ------------------------------------------------------------
    def _documents(self, records: Sequence[SkillRecord]) -> list[str]:
        docs = []
        for record in records:
            skill = record.skill
            docs.append(
                " ".join(
                    [
                        skill.name.replace("-", " ") * 3,
                        skill.name,
                        skill.description,
                        " ".join(skill.tags),
                        skill.body[:8000],
                    ]
                )
            )
        return docs

    def _ensure_embeddings(self, docs: Sequence[str]) -> bool:
        if not self._dense_enabled or self._doc_embeddings is not None:
            return self._doc_embeddings is not None
        if self._embedder is None:
            self._embedder = OllamaEmbedder()
        if not self._embedder.available():
            return False
        try:
            self._doc_embeddings = self._embedder.embed(list(docs))
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            return False
        return True

    def retrieve(
        self,
        task: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        dense_enabled: bool | None = None,
    ) -> list[SkillRecord]:
        """Return up to ``top_k`` *promoted* skills relevant to ``task``.

        Unverified (draft/verified-but-not-promoted) skills are never
        returned, however well they match — the promotion gate is the
        guarantee, and this filter is applied before any ranking.
        Keyword-only when no embedding model is installed.
        """
        promoted = self.list(status="promoted")
        if not promoted or not (task or "").strip():
            return []
        docs = self._documents(promoted)
        query_terms = tokenize(task)
        index = BM25Index([tokenize(doc) for doc in docs])
        scores = index.score(query_terms)
        best = max(scores) if scores else 0.0
        if best < MIN_BM25_SCORE:
            return []
        dense_on = False
        dense_scores: dict[str, float] = {}
        if dense_enabled is not False and self._dense_enabled:
            self._doc_embeddings = None  # rebuild per call set; library is small
            if self._ensure_embeddings(docs) and self._embedder is not None:
                try:
                    query_vector = self._embedder.embed([task])[0]
                    dense_on = True
                    for record, vector in zip(promoted, self._doc_embeddings or []):
                        dense_scores[record.skill.name] = _cosine(query_vector, vector)
                except (urllib.error.URLError, OSError, ValueError, KeyError):
                    dense_on = False

        def combined(i: int) -> float:
            bm25_norm = scores[i] / best if best else 0.0
            if dense_on and dense_scores:
                top_dense = max(dense_scores.values())
                dense_norm = dense_scores.get(promoted[i].skill.name, 0.0) / top_dense if top_dense else 0.0
                return 0.5 * bm25_norm + 0.5 * dense_norm
            return bm25_norm

        ranked = sorted(range(len(promoted)), key=combined, reverse=True)[:top_k]
        return [
            SkillRecord(skill=promoted[i].skill, path=promoted[i].path, score=round(combined(i), 4))
            for i in ranked
        ]
