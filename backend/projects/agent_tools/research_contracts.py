"""Versioned provider-neutral contracts for public research sources and evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import ipaddress
import re
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RESEARCH_CONTRACT_VERSION = 1
MAX_SOURCE_EXCERPT_CHARS = 1200
_PROVIDER_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "dclid", "mc_cid", "mc_eid"}


def canonical_source_url(value: str) -> str:
    """Return a stable HTTP(S) source identity while preserving page-specific query data."""
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError("A source URL must be non-empty and at most 4,096 characters")
    try:
        parsed = urlsplit(value.strip())
        host = parsed.hostname
        port = parsed.port
    except ValueError as err:
        raise ValueError("The source URL is malformed") from err
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not host or parsed.username is not None or parsed.password is not None:
        raise ValueError("Sources must use HTTP or HTTPS and must not contain credentials")
    if port not in ({None, 80} if scheme == "http" else {None, 443}):
        raise ValueError("Source URLs must use standard HTTP or HTTPS ports")
    host = host.rstrip(".").lower()
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as err:
        raise ValueError("The source hostname is invalid") from err
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError("Local network hostnames are not valid public research sources")
        if len(labels) < 2 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
            raise ValueError("The source hostname is invalid")
        netloc = host
    else:
        if not address.is_global:
            raise ValueError("Private and reserved IP addresses are not valid public research sources")
        host = address.compressed
        netloc = f"[{host}]" if address.version == 6 else host
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    query_items = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        folded = key.casefold()
        if folded.startswith("utm_") or folded in _TRACKING_QUERY_KEYS:
            continue
        query_items.append((key, item))
    query_items.sort(key=lambda pair: (pair[0].casefold(), pair[0], pair[1]))
    return urlunsplit((scheme, netloc, path, urlencode(query_items, doseq=True), ""))


def source_identity(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Research timestamps must include a timezone")
    return value.astimezone(timezone.utc)


class SourceRecord(BaseModel):
    """A retrievable source independent of the search or fetch provider shape."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = RESEARCH_CONTRACT_VERSION
    source_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    canonical_url: str = Field(min_length=1, max_length=2048)
    title: str = Field(default="", max_length=512)
    snippet: str = Field(default="", max_length=1200)
    provider: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    also_seen_by: list[str] = Field(default_factory=list, max_length=8)
    published_at: datetime | None = None
    retrieved_at: datetime

    @field_validator("published_at", "retrieved_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return _aware_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_identity(self):
        canonical = canonical_source_url(self.canonical_url)
        if canonical != self.canonical_url:
            raise ValueError("canonical_url must already be normalized")
        if source_identity(canonical) != self.source_id:
            raise ValueError("source_id must match the canonical URL identity")
        if not _PROVIDER_ID.fullmatch(self.provider) or any(not _PROVIDER_ID.fullmatch(item) for item in self.also_seen_by):
            raise ValueError("Provider IDs must use the stable lowercase provider identifier format")
        if self.provider in self.also_seen_by or len(self.also_seen_by) != len(set(self.also_seen_by)):
            raise ValueError("also_seen_by must contain unique provider IDs other than provider")
        return self


class SourceEvidence(BaseModel):
    """A bounded supporting excerpt tied to one normalized source record."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = RESEARCH_CONTRACT_VERSION
    source_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    excerpt: str = Field(min_length=1, max_length=MAX_SOURCE_EXCERPT_CHARS)
    retrieved_at: datetime
    locator: str | None = Field(default=None, max_length=240)

    _normalize_retrieved_at = field_validator("retrieved_at")(_aware_utc)


class ResearchProviderError(BaseModel):
    """Stable provider failure shape; retry metadata is operational, not provider-specific."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = RESEARCH_CONTRACT_VERSION
    provider: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    code: Literal[
        "unavailable", "rate_limited", "invalid_query", "unsafe_destination",
        "timeout", "response_too_large", "unsupported_content", "upstream_error",
    ]
    message: str = Field(min_length=1, max_length=500)
    retryable: bool
    retry_after_seconds: int | None = Field(default=None, ge=0, le=3600)
    http_status: int | None = Field(default=None, ge=100, le=599)


class ResearchResponse(BaseModel):
    """Provider-independent search or named-host discovery result."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = RESEARCH_CONTRACT_VERSION
    query: str = Field(min_length=1, max_length=500)
    provider: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    retrieved_at: datetime
    results: list[SourceRecord] = Field(default_factory=list, max_length=50)
    errors: list[ResearchProviderError] = Field(default_factory=list, max_length=20)

    _normalize_retrieved_at = field_validator("retrieved_at")(_aware_utc)

    @model_validator(mode="after")
    def require_unique_sources(self):
        identities = [record.source_id for record in self.results]
        if len(identities) != len(set(identities)):
            raise ValueError("Research responses must deduplicate canonical source identities")
        return self


def make_source_record(
    *,
    url: str,
    provider: str,
    retrieved_at: datetime,
    title: str = "",
    snippet: str = "",
    published_at: datetime | None = None,
) -> SourceRecord:
    canonical = canonical_source_url(url)
    return SourceRecord(
        source_id=source_identity(canonical),
        canonical_url=canonical,
        title=title[:512],
        snippet=snippet[:1200],
        provider=provider,
        retrieved_at=retrieved_at,
        published_at=published_at,
    )


def named_host_page_record(page: dict[str, str], *, retrieved_at: datetime) -> tuple[SourceRecord, SourceEvidence]:
    """Adapt the existing `{url, title, text}` named-host fetcher result."""
    text = page.get("text", "")
    if not text.strip():
        raise ValueError("A named-host page needs visible text before evidence can be created")
    record = make_source_record(
        url=page.get("url", ""),
        provider="named_host_fetcher",
        retrieved_at=retrieved_at,
        title=page.get("title", ""),
        snippet=text[:1200],
    )
    evidence = SourceEvidence(source_id=record.source_id, excerpt=text[:MAX_SOURCE_EXCERPT_CHARS], retrieved_at=retrieved_at)
    return record, evidence


def deduplicate_sources(records: list[SourceRecord]) -> list[SourceRecord]:
    """Merge duplicate canonical URLs while preserving the first provider and freshest metadata."""
    merged: dict[str, SourceRecord] = {}
    for record in records:
        existing = merged.get(record.source_id)
        if existing is None:
            merged[record.source_id] = record
            continue
        providers = list(dict.fromkeys([*existing.also_seen_by, record.provider, *record.also_seen_by]))
        providers = [provider for provider in providers if provider != existing.provider][:8]
        retrieved_at = max(existing.retrieved_at, record.retrieved_at)
        published_at = existing.published_at or record.published_at
        merged[record.source_id] = existing.model_copy(update={
            "title": existing.title or record.title,
            "snippet": record.snippet if len(record.snippet) > len(existing.snippet) else existing.snippet,
            "also_seen_by": providers,
            "retrieved_at": retrieved_at,
            "published_at": published_at,
        })
    return list(merged.values())
