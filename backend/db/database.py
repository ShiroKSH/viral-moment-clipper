from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from backend.core.paths import PROJECT_ROOT


DB_PATH = PROJECT_ROOT / "temp" / "viral_moment_clipper.sqlite3"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    from backend.db.models import SCHEMA

    with get_connection() as connection:
        connection.executescript(SCHEMA)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def db_path() -> Path:
    return DB_PATH
