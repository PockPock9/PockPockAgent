"""Local, versioned persistence for user-reviewed browser workflow recipes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from pockpock_paths import app_data_dir


def database_path() -> Path:
    configured = os.environ.get("POCKPOCK_BROWSER_RECIPE_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    return app_data_dir("FrogAI") / "browser-recipes.sqlite3"


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS browser_recipes (
                recipe_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                definition_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS browser_recipe_versions (
                recipe_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                definition_json TEXT NOT NULL,
                PRIMARY KEY (recipe_id, version),
                FOREIGN KEY (recipe_id) REFERENCES browser_recipes(recipe_id) ON DELETE CASCADE
            );
            """
        )


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    definition = json.loads(row["definition_json"])
    return {
        "recipe_id": row["recipe_id"],
        "name": row["name"],
        "version": row["version"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        **definition,
    }


def list_recipes() -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute("SELECT * FROM browser_recipes ORDER BY updated_at DESC, recipe_id").fetchall()
    return [_decode(row) for row in rows]


def get_recipe(recipe_id: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM browser_recipes WHERE recipe_id=?", (recipe_id,)).fetchone()
    return _decode(row) if row else None


def get_versions(recipe_id: str) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT version, created_at, definition_json FROM browser_recipe_versions WHERE recipe_id=? ORDER BY version DESC",
            (recipe_id,),
        ).fetchall()
    return [
        {"version": row["version"], "created_at": row["created_at"], "definition": json.loads(row["definition_json"])}
        for row in rows
    ]


def create_recipe(recipe_id: str, definition: dict[str, Any], timestamp: str) -> dict[str, Any]:
    encoded = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with connect() as connection:
        connection.execute(
            "INSERT INTO browser_recipes(recipe_id,name,version,enabled,created_at,updated_at,definition_json) VALUES(?,?,1,1,?,?,?)",
            (recipe_id, definition["name"], timestamp, timestamp, encoded),
        )
        connection.execute(
            "INSERT INTO browser_recipe_versions(recipe_id,version,created_at,definition_json) VALUES(?,1,?,?)",
            (recipe_id, timestamp, encoded),
        )
    return get_recipe(recipe_id)  # type: ignore[return-value]


def update_recipe(recipe_id: str, expected_version: int, definition: dict[str, Any], timestamp: str) -> dict[str, Any] | None:
    encoded = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT version FROM browser_recipes WHERE recipe_id=?", (recipe_id,)).fetchone()
        if row is None:
            return None
        if row["version"] != expected_version:
            raise ValueError("Recipe version changed; reload it before saving edits")
        next_version = expected_version + 1
        connection.execute(
            "UPDATE browser_recipes SET name=?, version=?, enabled=1, updated_at=?, definition_json=? WHERE recipe_id=?",
            (definition["name"], next_version, timestamp, encoded, recipe_id),
        )
        connection.execute(
            "INSERT INTO browser_recipe_versions(recipe_id,version,created_at,definition_json) VALUES(?,?,?,?)",
            (recipe_id, next_version, timestamp, encoded),
        )
    return get_recipe(recipe_id)


def set_enabled(recipe_id: str, enabled: bool, timestamp: str) -> dict[str, Any] | None:
    with connect() as connection:
        connection.execute("UPDATE browser_recipes SET enabled=?, updated_at=? WHERE recipe_id=?", (int(enabled), timestamp, recipe_id))
    recipe = get_recipe(recipe_id)
    if recipe is not None:
        recipe["enabled"] = enabled
    return recipe


def delete_recipe(recipe_id: str) -> bool:
    with connect() as connection:
        result = connection.execute("DELETE FROM browser_recipes WHERE recipe_id=?", (recipe_id,))
    return result.rowcount == 1
