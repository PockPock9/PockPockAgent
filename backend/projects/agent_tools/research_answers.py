"""Validated, evidence-bound answer contracts for public research."""

from __future__ import annotations

import json
import re
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .research_contracts import SourceEvidence, SourceRecord


MAX_RESEARCH_ANSWER_CHARS = 100_000
RESEARCH_ANSWER_CONTRACT_VERSION = 1


class ResearchCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    quote: str = Field(min_length=1, max_length=1200)


class ResearchClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)
    status: Literal["supported", "unsupported"]
    citations: list[ResearchCitation] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def require_citations_for_supported_claims(self):
        source_ids = [citation.source_id for citation in self.citations]
        if self.status == "supported" and not source_ids:
            raise ValueError("Supported claims require at least one evidence citation")
        if self.status == "unsupported" and source_ids:
            raise ValueError("Unsupported claims must not include citations")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("A claim must not cite the same source more than once")
        return self


class ResearchConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=1200)
    citations: list[ResearchCitation] = Field(min_length=2, max_length=6)

    @model_validator(mode="after")
    def require_distinct_sources(self):
        source_ids = [citation.source_id for citation in self.citations]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("A conflict must cite distinct sources")
        return self


class ResearchAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1]
    claims: list[ResearchClaim] = Field(default_factory=list, max_length=80)
    conflicts: list[ResearchConflict] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    completion_checks: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("limitations")
    @classmethod
    def bound_limitations(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 500 for item in value):
            raise ValueError("Evidence limitations must be non-empty and at most 500 characters")
        return value

    @field_validator("completion_checks")
    @classmethod
    def bound_completion_checks(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 1000 for item in value):
            raise ValueError("Completion checks must be non-empty and at most 1,000 characters")
        return value


class ResearchAnswerValidationError(ValueError):
    """The model answer could not be tied to the retrieved evidence."""

    def __init__(self, message: str, category: str = "invalid_answer_or_source_schema"):
        super().__init__(message)
        self.category = category


def validate_research_answer(
    content: str,
    source_data: list[dict],
    evidence_data: list[dict],
    source_aliases: dict[str, str] | None = None,
) -> ResearchAnswer:
    if not isinstance(content, str) or not content.strip() or len(content) > MAX_RESEARCH_ANSWER_CHARS:
        raise ResearchAnswerValidationError(
            "The research answer is empty or exceeds its size limit",
            category="invalid_answer_size",
        )
    candidate = content.strip()
    fenced_json = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        candidate,
        flags=re.IGNORECASE | re.DOTALL,
    )
    try:
        answer_data = json.loads(fenced_json.group(1) if fenced_json else candidate)
    except (ValueError, TypeError) as err:
        raise ResearchAnswerValidationError(
            "The research answer is not valid JSON",
            category="invalid_json",
        ) from err
    if not isinstance(answer_data, dict):
        raise ResearchAnswerValidationError(
            "The research answer must be a JSON object",
            category="invalid_answer_schema",
        )
    if source_aliases:
        for collection_name in ("claims", "conflicts"):
            items = answer_data.get(collection_name)
            if not isinstance(items, list):
                continue
            for item in items:
                citations = item.get("citations") if isinstance(item, dict) else None
                if not isinstance(citations, list):
                    continue
                for citation in citations:
                    if not isinstance(citation, dict):
                        continue
                    source_id = citation.get("source_id")
                    if isinstance(source_id, str) and source_id in source_aliases:
                        citation["source_id"] = source_aliases[source_id]
    try:
        answer = ResearchAnswer.model_validate(answer_data)
    except ValidationError as err:
        raise ResearchAnswerValidationError(
            "The research answer does not match the required schema",
            category="invalid_answer_schema",
        ) from err
    try:
        sources = [SourceRecord.model_validate(item) for item in source_data]
        evidence = [SourceEvidence.model_validate(item) for item in evidence_data]
    except ValidationError as err:
        raise ResearchAnswerValidationError(
            "Retrieved research source records do not match their required schema",
            category="invalid_source_schema",
        ) from err

    if len({source.source_id for source in sources}) != len(sources):
        raise ResearchAnswerValidationError(
            "Retrieved source records must have unique source IDs",
            category="duplicate_source_records",
        )
    if len({item.source_id for item in evidence}) != len(evidence):
        raise ResearchAnswerValidationError(
            "Retrieved evidence records must have unique source IDs",
            category="duplicate_source_records",
        )
    source_by_id = {source.source_id: source for source in sources}
    evidence_by_id = {item.source_id: item for item in evidence}
    for claim in answer.claims:
        for citation in claim.citations:
            excerpt = _citation_excerpt(citation.source_id, source_by_id, evidence_by_id)
            if citation.quote not in excerpt:
                raise ResearchAnswerValidationError(
                    "A claim citation quote must exactly match a retrieved source excerpt",
                    category="citation_quote_mismatch",
                )
    for conflict in answer.conflicts:
        for citation in conflict.citations:
            excerpt = _citation_excerpt(citation.source_id, source_by_id, evidence_by_id)
            if citation.quote not in excerpt:
                raise ResearchAnswerValidationError(
                    "A conflict citation quote must exactly match a retrieved source excerpt",
                    category="citation_quote_mismatch",
                )
    return answer


def _citation_excerpt(
    source_id: str,
    sources: dict[str, SourceRecord],
    evidence: dict[str, SourceEvidence],
) -> str:
    if source_id not in sources or source_id not in evidence:
        raise ResearchAnswerValidationError(
            "A citation references a source without retrieved evidence",
            category="citation_source_mismatch",
        )
    return evidence[source_id].excerpt


def _escape_markdown(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~])", r"\\\1", value)


def _source_link(source: SourceRecord) -> str:
    title = _escape_markdown(" ".join((source.title.strip() or source.canonical_url).split()))
    url = quote(source.canonical_url, safe=":/?#[]@!$&'()*+,;=%")
    citation = f"[{title}](<{url}>) — retrieved {source.retrieved_at.isoformat()}"
    if source.published_at:
        citation += f", published {source.published_at.isoformat()}"
    return citation


def _render_quote(value: str) -> str:
    lines = value.splitlines() or [value]
    return "\n".join(f"> {_escape_markdown(line)}" for line in lines)


def render_research_answer(
    answer: ResearchAnswer,
    source_data: list[dict],
) -> str:
    sources = {
        source.source_id: source
        for source in (SourceRecord.model_validate(item) for item in source_data)
    }
    sections = ["## Findings"]
    for claim in answer.claims:
        label = "Supported" if claim.status == "supported" else "Unsupported"
        sections.append(f"- **{label}:** {_escape_markdown(' '.join(claim.text.split()))}")
        for citation in claim.citations:
            source = sources[citation.source_id]
            sections.extend((f"  - {_source_link(source)}", f"\n{_render_quote(citation.quote)}"))
    if answer.conflicts:
        sections.append("\n## Conflicting evidence")
        for conflict in answer.conflicts:
            sections.append(f"- **{_escape_markdown(conflict.topic)}:** {_escape_markdown(' '.join(conflict.summary.split()))}")
            for citation in conflict.citations:
                source = sources[citation.source_id]
                sections.extend((f"  - {_source_link(source)}", f"\n{_render_quote(citation.quote)}"))
    if answer.limitations:
        sections.append("\n## Evidence limitations")
        sections.extend(f"- {_escape_markdown(' '.join(item.split()))}" for item in answer.limitations)
    sections.extend(f"\n{item}" for item in answer.completion_checks)
    return "\n\n".join(sections)


def research_answer_json_schema() -> dict:
    """Return the constrained response shape included in the agent's research instructions."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["contract_version", "claims", "conflicts", "limitations", "completion_checks"],
        "properties": {
            "contract_version": {"type": "integer", "const": RESEARCH_ANSWER_CONTRACT_VERSION},
            "claims": {
                "type": "array",
                "maxItems": 80,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["text", "status", "citations"],
                    "properties": {
                        "text": {"type": "string", "minLength": 1, "maxLength": 2000},
                        "status": {"type": "string", "enum": ["supported", "unsupported"]},
                        "citations": {"type": "array", "maxItems": 5, "items": {"$ref": "#/$defs/citation"}},
                    },
                },
            },
            "conflicts": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["topic", "summary", "citations"],
                    "properties": {
                        "topic": {"type": "string", "minLength": 1, "maxLength": 500},
                        "summary": {"type": "string", "minLength": 1, "maxLength": 1200},
                        "citations": {"type": "array", "minItems": 2, "maxItems": 6, "items": {"$ref": "#/$defs/citation"}},
                    },
                },
            },
            "limitations": {"type": "array", "maxItems": 20, "items": {"type": "string", "minLength": 1, "maxLength": 500}},
            "completion_checks": {"type": "array", "maxItems": 12, "items": {"type": "string", "minLength": 1, "maxLength": 1000}},
        },
        "$defs": {
            "citation": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_id", "quote"],
                "properties": {
                    "source_id": {"type": "string", "pattern": "^S[1-9][0-9]*$"},
                    "quote": {"type": "string", "minLength": 1, "maxLength": 1200},
                },
            },
        },
    }
