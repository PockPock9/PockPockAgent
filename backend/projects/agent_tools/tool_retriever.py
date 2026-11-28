"""Tool retrieval for the agent loop: progressive disclosure of tool schemas.

The agent used to send every permitted tool schema to the model on every
turn. With ~40 tools that is most of the context before the user request is
even read. This module implements the Phase 1 retrieval layer from the
tool-RAG research:

1.  A tool index built from the existing registry
    (:func:`registered_tool_contracts` in ``registry.py``) — the registry
    stays the single source of truth; this module only derives short
    retrievable documents from it, plus example user phrasings used for
    matching.
2.  Deterministic keyword/intent routing for high-confidence intents.
3.  Hybrid retrieval: hand-rolled BM25 (stdlib only; no ``rank-bm25``
    dependency) plus optional dense embeddings via Ollama ``/api/embed``
    with ``nomic-embed-text-v2-moe`` when that model is installed. Without
    it the retriever is keyword-only and says so in its status.
4.  Progressive disclosure: the planner/executor shows the model a one-line
    index of every permitted tool plus the full schemas of only the top 5-8
    retrieved tools (and the always-on core tools). Retrieval happens in the
    harness, before the model call — a weak local model is never asked to
    decide for itself which tools exist.

Permission/risk filtering runs before any ranking (Phase 2): tools the run
is not permitted to use (full-access tools in a default-mode run) and
high-risk tools (workspace writes, project-code execution) unless the run
explicitly allows them are removed from the candidate set first, so a
forbidden tool can never be retrieved, pinned, or shown in the one-line
index however well it matches the query. See :func:`filter_permitted_tools`.

Storage is in-memory brute force: 15 tools is a few hundred short
documents, scored in milliseconds. No sqlite-vec, LanceDB, or Chroma is
needed at this scale, and no new dependency is added.

Fallbacks keep the agent safe: if retrieval finds nothing with any
confidence, or raises, the caller falls back to the full permitted tool
list. A retrieval miss therefore costs tokens, never a failed task.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .contracts import ToolContract, risk_level_for_side_effect
from .registry import registered_tool_contracts

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Default number of retrieved tools whose full schemas reach the model.
DEFAULT_TOP_K = 8

#: Tools that are always included when permitted: cheap, read-only first
#: steps the model needs for grounding (list the workspace, read an
#: attachment). They are already gated by the task-capability filter, so
#: they only appear when the task actually allows them.
CORE_TOOL_NAMES = frozenset({"list_project_files", "read_selected_file"})

#: The meta-tool for mid-task tool discovery. It is registered like any
#: other tool (so the model can call it and the executor can validate it),
#: but it is never ranked against task tools: it is always appended to the
#: selection when permitted, and a search for tools never returns itself.
SEARCH_TOOL_NAME = "search_tools"

#: Ollama embedding model for the dense half of hybrid retrieval. Only used
#: when it is installed; otherwise retrieval is keyword-only.
EMBED_MODEL = "nomic-embed-text-v2-moe"

#: Minimum best BM25 score for the retrieval to be trusted. Below this the
#: query matched nothing meaningful and the caller should use the full list.
MIN_BM25_SCORE = 0.5

#: Permission modes in which high-risk tools (risk level "high": tools that
#: mutate existing workspace files or execute project code) may be retrieved.
#: "default" runs never get them — the executor approval-gates workspace
#: changes, and a "default" run has no approval path for them. The executor
#: always passes the run's permission mode, so in production this is an
#: explicit allowance, not a default.
HIGH_RISK_PERMISSION_MODES = frozenset({"auto-review", "full-access"})

#: Permission required by a tool that a "default" run may never retrieve,
#: mirroring ``require_agent_tool_permission`` in the gateway: tools that
#: require full access are invisible to default-mode runs.
FULL_ACCESS_PERMISSION = "full-access"


def high_risk_allowed(permission_mode: str | None, allow_high_risk: bool | None) -> bool:
    """Whether high-risk tools may be retrieved for this run.

    An explicit ``allow_high_risk`` flag wins. Otherwise a run permission
    mode decides: auto-review and full-access allow them (the executor
    approval-gates workspace changes in auto-review); "default" does not.
    With no run context at all (eval harness, unit tests) the set is
    unfiltered, so retrieval measurements stay comparable — the executor,
    the only production caller, always passes a permission mode.
    """
    if allow_high_risk is not None:
        return allow_high_risk
    if permission_mode is None:
        return True
    return permission_mode in HIGH_RISK_PERMISSION_MODES


def filter_permitted_tools(
    contracts: Mapping[str, ToolContract],
    *,
    permission_mode: str | None = None,
    allow_high_risk: bool | None = None,
) -> tuple[set[str], dict[str, str]]:
    """Apply permission/risk filtering to a tool set, before any ranking.

    Returns ``(allowed names, filtered-out names with reasons)``. A filtered
    tool can never be retrieved, pinned by deterministic routing, or shown
    as a full schema — it is removed before BM25/dense scoring runs, so
    ranking cannot resurrect it. Two rules, in order:

    1. Permission: tools whose contract requires full access are excluded
       from "default"-mode runs (same rule the executor enforces at call
       time, applied here so the model never sees the tool at all).
    2. Risk: high-risk tools (``risk_level == "high"``) are excluded unless
       the run explicitly allows them (see :func:`high_risk_allowed`).
    """
    allowed: set[str] = set()
    filtered_out: dict[str, str] = {}
    allow_high = high_risk_allowed(permission_mode, allow_high_risk)
    for name, contract in contracts.items():
        if contract.required_permission == FULL_ACCESS_PERMISSION and permission_mode == "default":
            filtered_out[name] = "permission: requires full-access, run is default mode"
        elif risk_level_for_side_effect(contract.side_effect) == "high" and not allow_high:
            filtered_out[name] = "risk: high-risk tool not allowed in this run"
        else:
            allowed.add(name)
    return allowed, filtered_out

ENV_FLAG = "POCKPOCK_TOOL_RETRIEVAL_ENABLED"


def tool_retrieval_enabled() -> bool:
    """Whether the retrieval path is switched on (env flag, default on)."""
    return os.environ.get(ENV_FLAG, "1").strip().lower() not in {"0", "false", "no", "off"}


def estimate_tokens(text: str) -> int:
    """Rough token estimate for schema accounting (~4 chars per token)."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Example phrasings (retrieval enrichment only, not a second registry)
# ---------------------------------------------------------------------------
# Realistic user phrasings per tool, used only to give the retriever the
# user's words (ToolRet shows query<->description overlap is near zero
# without them). The tools themselves, their schemas, and their
# descriptions always come from the registry.

EXAMPLE_PHRASES: dict[str, list[str]] = {
    "search_public_site": [
        "research this topic on the company website and cite your sources",
        "search the docs site for how to configure this",
        "find information about this on example.com",
        "look up the pricing on their website",
    ],
    "scrape_public_page": [
        "get the text of this exact article page",
        "read the content at this URL",
        "fetch this page and tell me what it says",
        "extract the text from this link",
    ],
    "browse_public_page": [
        "open this page in the browser and show me a screenshot",
        "look at this website visually",
        "open example.com so I can see it",
        "take a screenshot of this page",
    ],
    "browser_action": [
        "click the login link on the page you opened",
        "scroll down on that page",
        "type my search into the search box",
        "select an option from the dropdown on the page",
    ],
    "read_selected_file": [
        "analyse the file I attached",
        "summarise the uploaded document",
        "what does my attached spreadsheet say",
        "read the file I just uploaded and explain it",
    ],
    "save_text_artifact": [
        "save the results as a markdown file",
        "write the report to a file for me",
        "create a text file with these notes",
        "export this as a CSV file",
    ],
    "create_office_document": [
        "make a Word document of this report",
        "save this as a PDF",
        "make a PDF invoice or resume",
        "create a spreadsheet with these numbers",
        "build a PowerPoint presentation from this outline",
        "make an Excel workbook of the budget",
    ],
    "generate_local_image": [
        "generate an image of a sunset over mountains",
        "create a picture for my blog post",
        "draw an illustration of a robot",
        "make a logo image for my project",
    ],
    "list_project_files": [
        "what files are in this project",
        "list the files in my workspace",
        "show me the project structure",
        "which files exist in the folder",
    ],
    "search_project": [
        "find where this function is used in the code",
        "search the codebase for this error message",
        "grep the project for this variable name",
        "look through my code for this phrase",
    ],
    "read_project_file": [
        "read the main source file",
        "show me the contents of config.py",
        "open the README in the project and read it",
        "what is in this code file",
    ],
    "propose_project_edit": [
        "fix the bug in this file",
        "change the title in index.html",
        "edit the function to handle empty input",
        "update this file with the new value",
    ],
    "propose_project_patch": [
        "create a new web page in the project",
        "write a Python script that does this",
        "build a small game in the workspace",
        "add a new file with this code",
    ],
    "validate_project": [
        "check the project builds and the syntax is valid",
        "validate my code before I finish",
        "run the project checks and report any problems",
        "make sure the website files are correct",
    ],
}

# ---------------------------------------------------------------------------
# Deterministic routing (high-confidence intents only)
# ---------------------------------------------------------------------------
# Each rule is (pattern, tool names). A rule fires only when both a verb
# and its object match, so vague requests fall through to BM25. Rules are
# checked in order; office-document patterns are checked before the
# generic save-a-file pattern.

DETERMINISTIC_RULES: list[tuple[re.Pattern[str], tuple[str, ...]]] = [
    (re.compile(r"\b(word|excel|spreadsheet|powerpoint|presentation|\.docx|\.xlsx|\.pptx)\b", re.I),
     ("create_office_document",)),
    (re.compile(r"\b(generate|create|make|draw)\b.{0,50}\b(image|picture|photo|artwork|illustration|logo)\b", re.I),
     ("generate_local_image",)),
    (re.compile(r"\b(click|scroll)\b.{0,40}\b(page|link|button|down|up)\b|\btype\b.{0,40}\b(search\s?box|textbox|field)\b", re.I),
     ("browser_action",)),
    (re.compile(r"\b(open|show|browse)\b.{0,60}\b(browser|window)\b", re.I),
     ("browse_public_page",)),
    (re.compile(r"\b(screenshot|visually|look at)\b.{0,60}\b(page|website|site|https?://)", re.I),
     ("browse_public_page",)),
    (re.compile(r"\b(save|write|export|draft|create)\b.{0,60}\b(markdown|\.md|\.txt|\.csv|\.json|text file|report|document|notes)\b", re.I),
     ("save_text_artifact",)),
    (re.compile(r"\b(research|search|look up|find)\b.{0,80}\b(website|web site|web page|on the web|online|internet)\b", re.I),
     ("search_public_site",)),
    (re.compile(r"\b(scrape|fetch(?!\s+API\b)|extract|get the text)\b.{0,60}\b(https?://\S+|page|article|url|link)\b", re.I),
     ("scrape_public_page",)),
    (re.compile(r"\b(analy[sz]e|summari[sz]e|explain|read)\b.{0,60}\b(attached|attachment|uploaded)\b", re.I),
     ("read_selected_file",)),
    (re.compile(r"\b(validate|check|verify)\b.{0,50}\b(project|code|build|syntax|website)\b", re.I),
     ("validate_project",)),
    (re.compile(r"\b(fix|edit|change|update|patch|correct)\b.{0,60}\b(bug|code|file|function|title)\b", re.I),
     ("propose_project_edit",)),
    # A fix/edit verb aimed at a named code file ("fix parser.py") is a
    # high-confidence edit even when no bug/code/file noun follows.
    (re.compile(r"\b(fix|edit|change|update|patch|correct)\b.{0,40}\b[\w-]+\.(py|js|mjs|cjs|jsx|ts|tsx|html|css|sql|sh|ps1|rb|go|rs|java)\b", re.I),
     ("propose_project_edit",)),
    (re.compile(r"\b(create|write|build|add)\b.{0,60}\b(new file|script|web ?app|website|game|component)\b", re.I),
     ("propose_project_patch",)),
    # A create/write/build verb aimed at a named code file ("write
    # csv2json.py") is a high-confidence new-file patch. Office extensions
    # (.docx/.xlsx/.pptx) are deliberately excluded: the office rule above
    # owns those.
    (re.compile(r"\b(write|create|build)\b.{0,40}\b[\w-]+\.(py|js|mjs|cjs|jsx|ts|tsx|html|css|sql|sh|ps1|rb|go|rs|java)\b", re.I),
     ("propose_project_patch",)),
    (re.compile(r"\b(search|find|grep|look for)\b.{0,60}\b(in (the )?(code|codebase|project|workspace)|codebase)\b", re.I),
     ("search_project",)),
    (re.compile(r"\b(list|show|what files|what'?s in)\b.{0,50}\b(files|project|workspace|folder|directory)\b", re.I),
     ("list_project_files",)),
    (re.compile(r"\b(read|open|show)\b.{0,50}\b(code file|source file|\w+\.(py|js|ts|html|css|json|md))\b", re.I),
     ("read_project_file",)),
]

# ---------------------------------------------------------------------------
# Tokenisation + BM25 (stdlib only)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class BM25Index:
    """Small BM25 index (k1=1.5, b=0.75) over short tool documents."""

    def __init__(self, documents: Sequence[Sequence[str]]):
        self.documents = [list(doc) for doc in documents]
        self.doc_count = len(self.documents)
        self.avg_len = sum(len(doc) for doc in self.documents) / max(1, self.doc_count)
        doc_freq: dict[str, int] = {}
        for doc in self.documents:
            for term in set(doc):
                doc_freq[term] = doc_freq.get(term, 0) + 1
        self.idf = {
            term: math.log(1 + (self.doc_count - freq + 0.5) / (freq + 0.5))
            for term, freq in doc_freq.items()
        }

    def score(self, query_terms: Sequence[str]) -> list[float]:
        scores = [0.0] * self.doc_count
        for index, doc in enumerate(self.documents):
            length = len(doc)
            if not length:
                continue
            counts: dict[str, int] = {}
            for term in doc:
                counts[term] = counts.get(term, 0) + 1
            total = 0.0
            for term in query_terms:
                freq = counts.get(term)
                if not freq:
                    continue
                idf = self.idf.get(term, 0.0)
                total += idf * (freq * 2.5) / (freq + 1.5 * (1 - 0.75 + 0.75 * length / self.avg_len))
            scores[index] = total
        return scores


# ---------------------------------------------------------------------------
# Dense embeddings via Ollama (optional)
# ---------------------------------------------------------------------------

def _http_json(url: str, payload: Mapping[str, Any] | None, timeout: float = 10.0) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class OllamaEmbedder:
    """Dense embeddings through Ollama ``/api/embed`` (nomic-embed-text-v2-moe).

    Only used when the model is installed. ``available()`` probes
    ``/api/tags``; when the model is missing the retriever is keyword-only
    and says so instead of failing.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:11434", model: str = EMBED_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._available: bool | None = None

    def available(self) -> bool:
        if self._available is None:
            try:
                tags = _http_json(f"{self.base_url}/api/tags", None, timeout=5.0)
                names = {item.get("name") for item in tags.get("models", [])}
                self._available = self.model in names or f"{self.model}:latest" in names
            except (urllib.error.URLError, OSError, ValueError, KeyError):
                self._available = False
        return self._available

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        result = _http_json(
            f"{self.base_url}/api/embed",
            {"model": self.model, "input": list(texts)},
            timeout=30.0,
        )
        embeddings = result.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise ValueError("Ollama returned an unexpected embedding response")
        return [[float(value) for value in vector] for vector in embeddings]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


# ---------------------------------------------------------------------------
# Tool documents + retriever
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolDoc:
    name: str
    category: str
    one_line: str
    text: str
    spec: dict[str, Any]


@dataclass
class Retrieval:
    """What the retriever decided for one task."""

    selected_names: list[str]
    index_lines: list[str]
    method: str  # "deterministic" | "hybrid" | "keyword" | "fallback-full"
    scores: dict[str, float] = field(default_factory=dict)
    tokens_before: int = 0
    tokens_after: int = 0
    dense_available: bool = False
    latency_ms: float = 0.0
    # Tools removed by permission/risk filtering before ranking, with the
    # reason each was excluded. Never empty when the run's permission mode
    # forbids a tool the query would otherwise have matched.
    filtered_out: dict[str, str] = field(default_factory=dict)


def _doc_text(contract: ToolContract) -> str:
    """Retrievable text for one tool: name, description, parameters, examples."""
    params = contract.input_schema.get("properties", {})
    param_text = " ".join(
        f"{name} {info.get('description', '')}" if isinstance(info, dict) else str(name)
        for name, info in params.items()
    )
    examples = " ".join(EXAMPLE_PHRASES.get(contract.name, []))
    # Repeat the name tokens so an exact-name query scores highly.
    name_tokens = " ".join(contract.name.split("_")) * 3
    return " ".join([name_tokens, contract.name, contract.description, param_text, examples])


def build_tool_docs(contracts: Mapping[str, ToolContract] | None = None) -> list[ToolDoc]:
    """Build one retrievable document per registered tool, from the registry."""
    registry = contracts if contracts is not None else registered_tool_contracts()
    docs = []
    for name, contract in registry.items():
        params = contract.input_schema.get("properties", {})
        param_names = ", ".join(sorted(params)) or "none"
        docs.append(ToolDoc(
            name=name,
            category=contract.capability,
            one_line=f"{name} ({contract.capability}): {contract.description} Params: {param_names}.",
            text=_doc_text(contract),
            spec=contract.model_spec(),
        ))
    return docs


class ToolRetriever:
    """Hybrid tool retrieval over the agent tool registry."""

    def __init__(
        self,
        contracts: Mapping[str, ToolContract] | None = None,
        *,
        embedder: OllamaEmbedder | None = None,
        dense_enabled: bool = True,
    ):
        self.contracts_by_name: dict[str, ToolContract] = dict(
            contracts if contracts is not None else registered_tool_contracts()
        )
        self.docs = build_tool_docs(self.contracts_by_name)
        self.by_name = {doc.name: doc for doc in self.docs}
        self.bm25 = BM25Index([tokenize(doc.text) for doc in self.docs])
        self._embedder = embedder
        self._dense_enabled = dense_enabled
        self._doc_embeddings: list[list[float]] | None = None

    # -- dense ------------------------------------------------------------
    def _ensure_embeddings(self) -> bool:
        """Embed the index docs once. Returns False when dense is unavailable."""
        if not self._dense_enabled:
            return False
        if self._doc_embeddings is not None:
            return True
        if self._embedder is None:
            self._embedder = OllamaEmbedder()
        if not self._embedder.available():
            return False
        try:
            self._doc_embeddings = self._embedder.embed([doc.text for doc in self.docs])
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            return False
        return True

    def dense_available(self) -> bool:
        return self._ensure_embeddings()

    def status(self) -> dict[str, Any]:
        """Index status for logs/UI: tool count, dense availability, fallback note."""
        dense = self._ensure_embeddings()
        return {
            "tools": len(self.docs),
            "dense_available": dense,
            "embed_model": EMBED_MODEL if dense else None,
            "fallback_note": None if dense else (
                f"Embedding model {EMBED_MODEL} is not installed in Ollama; "
                "retrieval is keyword-only (BM25 + deterministic routing)."
            ),
        }

    # -- retrieval ----------------------------------------------------------
    def retrieve(
        self,
        task: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        permitted: Sequence[str] | None = None,
        permission_mode: str | None = None,
        allow_high_risk: bool | None = None,
    ) -> Retrieval:
        """Rank permitted tools for ``task``; never raises for a bad query.

        Permission/risk filtering runs first: tools the run may not use are
        removed before deterministic routing and BM25/dense scoring, so a
        forbidden tool can never be retrieved however well it matches.
        ``permitted`` is the caller's allow-list (task capabilities /
        delegation); ``permission_mode`` / ``allow_high_risk`` apply the
        contract permission and risk rules on top of it.
        """
        started = time.monotonic()
        # Permission/risk filtering runs on the candidate set only (the
        # caller's allow-list intersected with the index), before any
        # ranking, so a forbidden tool can never be retrieved, pinned, or
        # shown as a full schema however well it matches the query.
        candidates = {
            doc.name: self.contracts_by_name[doc.name]
            for doc in self.docs
            if (permitted is None or doc.name in set(permitted))
            and doc.name in self.contracts_by_name
        }
        _allowed_names, filtered_out = filter_permitted_tools(
            candidates,
            permission_mode=permission_mode,
            allow_high_risk=allow_high_risk,
        )
        allowed = [doc for doc in self.docs if doc.name in _allowed_names]
        if not allowed:
            return Retrieval([], [], "fallback-full", latency_ms=0.0, filtered_out=filtered_out)
        full_specs = [doc.spec for doc in allowed]
        tokens_before = sum(estimate_tokens(json.dumps(spec)) for spec in full_specs)
        index_lines = [doc.one_line for doc in allowed]

        # 1. Deterministic routing for high-confidence intents.
        pinned: list[str] = []
        for pattern, names in DETERMINISTIC_RULES:
            if pattern.search(task or ""):
                for name in names:
                    if name in {doc.name for doc in allowed} and name not in pinned:
                        pinned.append(name)

        # 2. BM25 over the index, restricted to the permitted set.
        query_terms = tokenize(task or "")
        positions = [self.docs.index(doc) for doc in allowed]
        all_scores = self.bm25.score(query_terms)
        bm25_scores = {allowed[i].name: all_scores[pos] for i, pos in enumerate(positions)}
        best_bm25 = max(bm25_scores.values()) if bm25_scores else 0.0

        # 3. Dense embeddings when available (hybrid: mean of normalised scores).
        dense_scores: dict[str, float] = {}
        dense_on = False
        if query_terms and self._ensure_embeddings() and self._embedder is not None:
            try:
                query_vector = self._embedder.embed([task])[0]
                dense_on = True
                for doc, vector in zip(self.docs, self._doc_embeddings or []):
                    if doc.name in bm25_scores:
                        dense_scores[doc.name] = _cosine(query_vector, vector)
            except (urllib.error.URLError, OSError, ValueError, KeyError):
                dense_on = False
                dense_scores = {}

        def combined(name: str) -> float:
            bm25_norm = bm25_scores.get(name, 0.0) / best_bm25 if best_bm25 else 0.0
            if dense_on and dense_scores:
                best_dense = max(dense_scores.values())
                dense_norm = dense_scores.get(name, 0.0) / best_dense if best_dense else 0.0
                return 0.5 * bm25_norm + 0.5 * dense_norm
            return bm25_norm

        ranked = sorted(bm25_scores, key=lambda name: combined(name), reverse=True)
        # The meta-tool is never ranked against task tools: it is always
        # appended below when permitted, and ranking it could displace a
        # real tool for "search ..." queries.
        ranked = [name for name in ranked if name != SEARCH_TOOL_NAME]
        scores = {name: round(combined(name), 4) for name in ranked}
        method = "hybrid" if dense_on else "keyword"

        # Low-confidence: nothing matched at all -> fall back to the full list.
        if not pinned and best_bm25 < MIN_BM25_SCORE:
            selected = [doc.name for doc in allowed]
            method = "fallback-full"
        else:
            selected = list(dict.fromkeys([*pinned, *ranked[:top_k]]))
            # Core tools and the search_tools escape hatch are appended
            # beyond top_k, never truncated by it.
            allowed_names = {doc.name for doc in allowed}
            for extra in sorted(CORE_TOOL_NAMES | {SEARCH_TOOL_NAME}):
                if extra in allowed_names and extra not in selected:
                    selected.append(extra)

        selected_specs = [self.by_name[name].spec for name in selected]
        tokens_after = sum(estimate_tokens(json.dumps(spec)) for spec in selected_specs)
        return Retrieval(
            selected_names=selected,
            index_lines=index_lines,
            method="deterministic" if pinned else method,
            scores=scores,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            dense_available=dense_on,
            latency_ms=round((time.monotonic() - started) * 1000, 2),
            filtered_out=filtered_out,
        )

    def select_tools(
        self,
        task: str,
        specs: Sequence[dict[str, Any]],
        *,
        top_k: int = DEFAULT_TOP_K,
        permission_mode: str | None = None,
        allow_high_risk: bool | None = None,
    ) -> tuple[list[dict[str, Any]], Retrieval]:
        """Progressive disclosure for one agent turn.

        Returns ``(selected full schemas, retrieval)``. ``retrieval.index_lines``
        is the one-line index of every permitted tool that passed the
        permission/risk filter, to be shown to the model alongside the
        selected schemas. Tools the run may not use are filtered out before
        ranking, so they appear in neither the index nor the schemas.
        """
        permitted = [
            spec["function"]["name"]
            for spec in specs
            if isinstance(spec, dict)
            and isinstance(spec.get("function"), dict)
            and isinstance(spec["function"].get("name"), str)
        ]
        retrieval = self.retrieve(
            task,
            top_k=top_k,
            permitted=permitted,
            permission_mode=permission_mode,
            allow_high_risk=allow_high_risk,
        )
        by_name = {
            spec["function"]["name"]: spec
            for spec in specs
            if isinstance(spec, dict) and isinstance(spec.get("function"), dict)
        }
        return [by_name[name] for name in retrieval.selected_names if name in by_name], retrieval


def hydrate_tools(
    current_tools: Sequence[dict[str, Any]],
    search_result: Mapping[str, Any] | None,
    permitted_specs: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Full schemas to add after a ``search_tools`` call (progressive disclosure).

    ``search_result`` is the validated ``search_tools`` output; ``permitted_specs``
    are the full schemas this run may use. Returns the specs for tools named
    in the result that are permitted and not already in ``current_tools``,
    in result order. The caller appends them to the model's tool list so the
    next turn can call the newly discovered tools. Never adds a tool outside
    the permitted set, even if the search result named one.
    """
    current_names = {
        spec["function"]["name"]
        for spec in current_tools
        if isinstance(spec, dict)
        and isinstance(spec.get("function"), dict)
        and isinstance(spec["function"].get("name"), str)
    }
    by_name = {
        spec["function"]["name"]: spec
        for spec in permitted_specs
        if isinstance(spec, dict)
        and isinstance(spec.get("function"), dict)
        and isinstance(spec["function"].get("name"), str)
    }
    results = search_result.get("results") if isinstance(search_result, dict) else None
    added: list[dict[str, Any]] = []
    for item in results if isinstance(results, list) else []:
        name = item.get("name") if isinstance(item, dict) else None
        if isinstance(name, str) and name in by_name and name not in current_names:
            added.append(by_name[name])
            current_names.add(name)
    return added
