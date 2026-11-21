"""Automatic capture of a small allowlist of reusable response preferences."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import re
import sqlite3
import threading
from typing import Callable, Iterator


_STYLE_VALUES = {
    "concise": "concise",
    "brief": "concise",
    "detailed": "detailed",
    "step-by-step": "step-by-step",
    "step by step": "step-by-step",
    "plain-language": "plain language",
    "plain language": "plain language",
}
_CODE_LANGUAGES = {
    "c#": "C#",
    "go": "Go",
    "java": "Java",
    "javascript": "JavaScript",
    "python": "Python",
    "rust": "Rust",
    "typescript": "TypeScript",
}
_REPLY_LANGUAGES = {
    "arabic": "Arabic", "chinese": "Chinese", "dutch": "Dutch", "english": "English", "french": "French",
    "german": "German", "hindi": "Hindi", "indonesian": "Indonesian", "italian": "Italian",
    "japanese": "Japanese", "khmer": "Khmer", "korean": "Korean", "polish": "Polish",
    "portuguese": "Portuguese", "russian": "Russian", "spanish": "Spanish", "thai": "Thai",
    "turkish": "Turkish", "vietnamese": "Vietnamese",
}
_PREFERENCE_PATTERNS = (
    (
        "response_style",
        re.compile(
            r"\b(?:i\s+prefer|please\s+(?:keep|make)|always\s+(?:keep|make))\s+"
            r"(?:your\s+)?(?:answers?|responses?|explanations?)\s+"
            r"(?:to\s+be\s+)?(concise|brief|detailed|step[- ]by[- ]step|plain[- ]language)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "response_style",
        re.compile(
            r"\b(?:i\s+prefer|please\s+keep|always\s+keep)\s+"
            r"(concise|brief|detailed|step[- ]by[- ]step|plain[- ]language)\s+"
            r"(?:answers?|responses?|explanations?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "code_language",
        re.compile(
            r"\b(?:i\s+prefer|always|please\s+always)\s+(?:to\s+)?(?:use\s+)?"
            r"(c#|go|java|javascript|python|rust|typescript)\s+"
            r"(?:for|in)\s+(?:code|examples|code\s+examples|scripts)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "reply_language",
        re.compile(
            r"\b(?:always\s+|please\s+(?:always\s+)?)?(?:answer|reply|respond|write\s+back)\s+(?:to\s+me\s+)?in\s+"
            r"(" + "|".join(_REPLY_LANGUAGES) + r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "reply_language",
        re.compile(
            r"\bi\s+prefer\s+(?:answers?|replies|responses?)\s+in\s+(" + "|".join(_REPLY_LANGUAGES) + r")\b",
            re.IGNORECASE,
        ),
    ),
)

# Phrases that ask PockPock to keep something for later. When one is present but nothing above
# matched, the user is told it was not saved instead of believing it was (issue #62).
_MEMORY_REQUEST = re.compile(
    r"\b(?:remember\s+(?:that|this|my|me|i)|please\s+remember|don'?t\s+forget|keep\s+in\s+mind|"
    r"from\s+now\s+on|next\s+time|my\s+name\s+is|call\s+me|i\s+(?:usually|always)\s+work|my\s+working\s+hours)\b",
    re.IGNORECASE,
)


def extract_safe_preferences(text: str) -> list[tuple[str, str]]:
    """Return only fixed, non-sensitive preference strings; never retain source text."""
    if not isinstance(text, str) or not text:
        return []
    found: dict[str, str] = {}
    for category, pattern in _PREFERENCE_PATTERNS:
        for match in pattern.finditer(text[:20_000]):
            raw_value = re.sub(r"\s+", " ", match.group(1).lower()).strip()
            if category == "response_style":
                value = _STYLE_VALUES.get(raw_value)
                if value:
                    found[category] = f"Prefer {value} responses."
            elif category == "code_language":
                language = _CODE_LANGUAGES.get(raw_value)
                if language:
                    found[category] = f"Prefer {language} for code examples."
            elif category == "reply_language":
                language = _REPLY_LANGUAGES.get(raw_value)
                if language:
                    found[category] = f"Reply in {language}."
    return sorted(found.items())


def unsaved_memory_request(text: str) -> bool:
    """True when the text asks to remember something that memory does not keep."""
    if not isinstance(text, str) or not text:
        return False
    return bool(_MEMORY_REQUEST.search(text[:20_000])) and not extract_safe_preferences(text)


MEMORY_NOT_SAVED = (
    "Not saved to memory: PockPock remembers only how you like answers (concise, detailed, step by step, "
    "plain language), the language for replies, and the language for code examples. Other details are not kept."
)


class LocalPreferenceMemory:
    def __init__(
        self,
        connect_db: Callable[[], sqlite3.Connection],
        lock: threading.Lock,
    ):
        self._connect_db = connect_db
        self._lock = lock

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect_db()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS local_preferences (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    preference TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """INSERT INTO settings (key, value) VALUES ('frog_local_memory_enabled', '1')
                ON CONFLICT(key) DO NOTHING"""
            )

    def is_enabled(self) -> bool:
        self.initialize()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key='frog_local_memory_enabled'"
            ).fetchone()
        return not row or row["value"] == "1"

    def set_enabled(self, enabled: bool) -> None:
        self.initialize()
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO settings (key, value) VALUES ('frog_local_memory_enabled', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                ("1" if enabled else "0",),
            )

    def remember_from_text(self, text: str) -> list[dict[str, str]]:
        self.initialize()
        candidates = extract_safe_preferences(text)
        if not candidates or not self.is_enabled():
            return []
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection() as connection:
            for category, preference in candidates:
                preference_id = hashlib.sha256(category.encode("utf-8")).hexdigest()[:24]
                connection.execute(
                    """INSERT INTO local_preferences (id, category, preference, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        preference=excluded.preference,
                        updated_at=excluded.updated_at""",
                    (preference_id, category, preference, now),
                )
            overflow = connection.execute(
                "SELECT id FROM local_preferences ORDER BY updated_at DESC, id LIMIT -1 OFFSET 50"
            ).fetchall()
            if overflow:
                connection.executemany(
                    "DELETE FROM local_preferences WHERE id=?",
                    [(row["id"],) for row in overflow],
                )
        return self.list_preferences()

    def list_preferences(self) -> list[dict[str, str]]:
        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT id, category, preference, updated_at
                FROM local_preferences ORDER BY category, preference"""
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_preference(self, preference_id: str) -> bool:
        self.initialize()
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM local_preferences WHERE id=?", (preference_id,)
            )
        return cursor.rowcount > 0

    def clear(self) -> None:
        self.initialize()
        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM local_preferences")
