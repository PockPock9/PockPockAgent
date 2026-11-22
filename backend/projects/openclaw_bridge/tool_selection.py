"""Tool retrieval for the OpenClaw engine: offer each turn only the skills and MCP servers that fit it.

OpenClaw puts every usable skill (name, description, location) and every MCP server's tools into its
prompt on every turn. PockPock cannot change OpenClaw's built-in tools per turn, but OpenClaw accepts a
per-session overlay, `sessions.patch {toolOverrides: {skills: {<key>: false}, mcpServers: {<name>:
false}}}`, which hides skills and MCP servers for that session. Before each turn PockPock ranks the
usable skills and servers against the message (BM25, plus embeddings when an Ollama embedding model is
installed, the same scoring as `agent_tools/tool_retriever.py`) and hides the ones that do not fit.

Safety rules:
- Only hides. A skill or server the user switched off stays off; nothing is switched on.
- Too few candidates (fewer than 8 skills, or one MCP server) are not filtered: there is little to save.
- What the conversation used in its last turns stays offered (sticky), so a follow-up such as "now do
  the same for the other file" keeps its skills.
- Any failure (catalog unavailable, embedding error) returns no overlay: OpenClaw gets everything.
- `POCKPOCK_OPENCLAW_TOOL_RETRIEVAL=0` turns it off; the overlay is then cleared.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import deque
from typing import Any, Callable

from projects.agent_tools.tool_retriever import BM25Index, OllamaEmbedder, _cosine, tokenize as _tokenize

logger = logging.getLogger("pockpock.openclaw.tool_selection")

TOP_SKILLS = 6
MIN_SKILLS_TO_FILTER = 8
STICKY_TURNS = 3
CATALOG_TTL_SECONDS = 300
# Without a keyword match, a skill is offered on embeddings alone when its similarity to the message
# is clearly above the average over all skills (relative, so it does not depend on the embedding model).
DENSE_MARGIN = 0.08
STOPWORDS = frozenset(
    "a an and are as at be but by can could do does for from get give go has have how i if in into is it its "
    "just let like make me my need now of on one or other please same so some than that the then there these "
    "this those to too up us use using want was we what when where which while who why will with would you your "
    "also again all any more most new only out over very".split()
)
CONNECTORS_SERVER = "pockpock-connectors"


def tokenize(text: str) -> list[str]:
    return [word for word in _tokenize(text) if word not in STOPWORDS and len(word) > 1]


def retrieval_enabled() -> bool:
    return os.environ.get("POCKPOCK_OPENCLAW_TOOL_RETRIEVAL", "1").strip().lower() not in {"0", "false", "off", "no"}


def _doc(name: str, description: str) -> str:
    return f"{name.replace('-', ' ').replace('_', ' ')} {name} {description}"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class OpenClawToolSelector:
    """`catalog()` returns {"skills": [{key, name, description}], "mcp": [{name, target}]}: the usable,
    switched-on skills and MCP servers (see ExtensionService.list)."""

    def __init__(self, catalog: Callable[[], dict[str, Any]], embedder: Any | None = None, clock: Callable[[], float] = time.monotonic):
        self._catalog_source = catalog
        self._embedder = embedder
        self._clock = clock
        self._lock = threading.Lock()
        self._catalog: tuple[float, dict[str, Any]] | None = None
        self._vectors: tuple[str, list[list[float]]] | None = None
        self._sticky: dict[str, deque[set[str]]] = {}

    def _get_catalog(self) -> dict[str, Any]:
        now = self._clock()
        if self._catalog and now - self._catalog[0] < CATALOG_TTL_SECONDS:
            return self._catalog[1]
        data = self._catalog_source()
        self._catalog = (now, data)
        return data

    def _rank(self, docs: list[tuple[str, str]], message: str) -> tuple[dict[str, float], dict[str, float], bool]:
        """BM25 and dense scores per name; dense only when an embedding model is available."""
        names = [name for name, _ in docs]
        bm25 = BM25Index([tokenize(text) for _, text in docs]).score(tokenize(message))
        keyword = dict(zip(names, bm25))
        dense: dict[str, float] = {}
        if self._embedder is not None and docs and tokenize(message):
            try:
                if self._embedder.available():
                    signature = hashlib.sha256("\n".join(text for _, text in docs).encode()).hexdigest()
                    if not self._vectors or self._vectors[0] != signature:
                        self._vectors = (signature, self._embedder.embed([text for _, text in docs]))
                    query = self._embedder.embed([message[:2000]])[0]
                    dense = {name: _cosine(query, vector) for name, vector in zip(names, self._vectors[1])}
            except Exception:  # noqa: BLE001 - embeddings are optional; keyword ranking still works
                logger.warning("Embeddings unavailable for OpenClaw tool selection; using keywords only")
                dense = {}
        return keyword, dense, bool(dense)

    @staticmethod
    def _picked(keyword: dict[str, float], dense: dict[str, float], scores: dict[str, float]) -> list[str]:
        """Best first: keyword matches, then skills clearly closer to the message than the average."""
        mean = sum(dense.values()) / len(dense) if dense else 0.0
        fits = [name for name in scores if keyword.get(name, 0.0) > 0 or (dense and dense.get(name, 0.0) - mean >= DENSE_MARGIN)]
        return sorted(fits, key=lambda name: scores[name], reverse=True)

    @staticmethod
    def _combined(keyword: dict[str, float], dense: dict[str, float]) -> dict[str, float]:
        best_keyword = max(keyword.values(), default=0.0)
        best_dense = max(dense.values(), default=0.0)
        scores = {}
        for name, value in keyword.items():
            keyword_norm = value / best_keyword if best_keyword else 0.0
            if dense:
                dense_norm = dense.get(name, 0.0) / best_dense if best_dense else 0.0
                scores[name] = 0.5 * keyword_norm + 0.5 * dense_norm
            else:
                scores[name] = keyword_norm
        return scores

    def select(self, session_id: str, message: str) -> dict[str, Any]:
        """The overlay for this turn and what it did. `toolOverrides` is None when nothing is hidden,
        which also clears an overlay left by an earlier turn."""
        if not retrieval_enabled():
            return {"toolOverrides": None, "reason": "off"}
        with self._lock:
            try:
                catalog = self._get_catalog()
            except Exception:  # noqa: BLE001 - never block a turn on the catalog
                logger.exception("OpenClaw tool selection: catalog unavailable; offering everything")
                return {"toolOverrides": None, "reason": "catalog unavailable"}
            skills = [item for item in catalog.get("skills", []) if isinstance(item, dict) and item.get("key")]
            servers = [item for item in catalog.get("mcp", []) if isinstance(item, dict) and item.get("name") and item["name"] != CONNECTORS_SERVER]
            history = self._sticky.setdefault(session_id, deque(maxlen=STICKY_TURNS))
            sticky = set().union(*history) if history else set()
            overrides: dict[str, dict[str, bool]] = {}
            chosen: set[str] = set()
            summary: dict[str, Any] = {"skills_total": len(skills), "servers_total": len(servers)}

            if len(skills) >= MIN_SKILLS_TO_FILTER:
                docs = [(str(item["key"]), _doc(str(item.get("name") or item["key"]), str(item.get("description") or ""))) for item in skills]
                keyword, dense, dense_on = self._rank(docs, message)
                scores = self._combined(keyword, dense)
                picked = self._picked(keyword, dense, scores)[:TOP_SKILLS]
                keep = set(picked) | {key for key in sticky if key in scores}
                chosen |= set(picked)
                hidden = [key for key, _ in docs if key not in keep]
                if hidden:
                    overrides["skills"] = {key: False for key in hidden}
                text_by_key = dict(docs)
                summary.update({
                    "skills_offered": len(skills) - len(hidden),
                    "skills_kept": sorted(keep)[:20],
                    "method": "hybrid" if dense_on else "keyword",
                    "tokens_saved": sum(estimate_tokens(text_by_key[key]) + 20 for key in hidden),
                })
            else:
                summary["skills_offered"] = len(skills)

            if len(servers) > 1:
                docs = [(str(item["name"]), _doc(str(item["name"]), str(item.get("target") or ""))) for item in servers]
                keyword, dense, dense_on = self._rank(docs, message)
                scores = self._combined(keyword, dense)
                picked = self._picked(keyword, dense, scores)
                keep = set(picked) | {name for name in sticky if name in scores}
                chosen |= set(picked)
                hidden_servers = [name for name, _ in docs if name not in keep]
                if hidden_servers:
                    overrides["mcpServers"] = {name: False for name in hidden_servers}
                summary["servers_offered"] = len(servers) - len(hidden_servers)
            else:
                summary["servers_offered"] = len(servers)

            history.append(chosen)
            return {"toolOverrides": overrides or None, **summary}
