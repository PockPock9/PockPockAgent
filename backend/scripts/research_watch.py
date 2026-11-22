"""Watching saved research sources for changes (UI-01E).

A saved source can be watched: while the gateway runs, it re-reads the page in the background every
`POCKPOCK_SOURCE_WATCH_MINUTES` (default 6 hours, 15 minutes to 7 days) and records a new snapshot when
the text changed, the same way "Check for changes" does. That is network access while PockPock runs, so
it is off by default, turned on per source, and only happens while research ("Named public websites")
is enabled. A change is marked unseen until the user opens it; a failed check is recorded and retried
at the next interval, not sooner.

The checks themselves live in the gateway (`_refresh_saved_research_source`); this module decides
which sources are due and runs them one at a time, so it can be tested without a network.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

logger = logging.getLogger("pockpock.research_watch")

DEFAULT_INTERVAL_MINUTES = 360
MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 7 * 24 * 60
# Checked per tick at most, one after another, so a long list never sends a burst of requests.
CHECKS_PER_TICK = 3
TICK_SECONDS = 60
FIRST_TICK_SECONDS = 30


def watching_enabled() -> bool:
    """POCKPOCK_SOURCE_WATCH=0 stops the background checks entirely (manual checks still work)."""
    return os.environ.get("POCKPOCK_SOURCE_WATCH", "1").strip().lower() not in {"0", "false", "off", "no"}


def watch_interval_minutes() -> int:
    raw = os.environ.get("POCKPOCK_SOURCE_WATCH_MINUTES", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_INTERVAL_MINUTES
    except ValueError:
        value = DEFAULT_INTERVAL_MINUTES
    return max(MIN_INTERVAL_MINUTES, min(MAX_INTERVAL_MINUTES, value))


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def last_attempt(source: dict[str, Any]) -> datetime | None:
    """The newest of the last successful check and the last failed one."""
    watch = source.get("watch") if isinstance(source.get("watch"), dict) else {}
    times = [time for time in (_parse(source.get("last_checked_at")), _parse(watch.get("error_at"))) if time]
    return max(times) if times else None


def next_check_at(source: dict[str, Any], interval_minutes: int) -> datetime | None:
    attempt = last_attempt(source)
    return attempt + timedelta(minutes=interval_minutes) if attempt else None


def due_sources(sources: list[dict[str, Any]], now: datetime, interval_minutes: int) -> list[dict[str, Any]]:
    """Watched sources whose interval has passed, oldest attempt first."""
    due = []
    for source in sources:
        if not isinstance(source, dict) or not (source.get("watch") or {}).get("watched"):
            continue
        attempt = last_attempt(source)
        if attempt is None or now - attempt >= timedelta(minutes=interval_minutes):
            due.append((attempt or datetime.min.replace(tzinfo=timezone.utc), source))
    due.sort(key=lambda item: item[0])
    return [source for _, source in due]


def error_message(err: BaseException) -> str:
    detail = getattr(err, "detail", None)
    text = detail if isinstance(detail, str) and detail.strip() else str(err)
    return " ".join(text.split())[:240] or "The page could not be checked."


async def check_due_sources(
    *,
    list_sources: Callable[[], Awaitable[list[dict[str, Any]]]],
    refresh: Callable[[str, str, str], Awaitable[dict[str, Any]]],
    record: Callable[..., Awaitable[Any]],
    research_enabled: bool,
    interval_minutes: int,
    now: datetime | None = None,
    limit: int = CHECKS_PER_TICK,
) -> dict[str, int]:
    """Check up to `limit` due sources. Returns how many changed, were unchanged and failed."""
    counts = {"changed": 0, "unchanged": 0, "failed": 0}
    if not research_enabled:
        return counts
    sources = await list_sources()
    for source in due_sources(sources, now or datetime.now(timezone.utc), interval_minutes)[:limit]:
        task_id, source_id, workspace_key = source["task_id"], source["source_id"], source["workspace_key"]
        try:
            result = await refresh(task_id, source_id, workspace_key)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # A page that fails is recorded and retried at the next interval.
            counts["failed"] += 1
            await record(task_id, source_id, workspace_key, error=error_message(err))
            continue
        changed = bool(result.get("changed")) and result.get("previous") is not None
        counts["changed" if changed else "unchanged"] += 1
        await record(task_id, source_id, workspace_key, result="changed" if changed else "ok")
    return counts


async def watch_loop(check: Callable[[], Awaitable[dict[str, int]]]) -> None:
    """Runs `check` every minute until cancelled; a failing tick is logged and the loop goes on."""
    await asyncio.sleep(FIRST_TICK_SECONDS)
    while True:
        try:
            counts = await check()
            if any(counts.values()):
                logger.info("Watched sources checked: %s", counts)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Checking watched sources failed")
        await asyncio.sleep(TICK_SECONDS)
