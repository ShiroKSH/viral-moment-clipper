from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from backend.core.paths import PROJECT_ROOT


DB_PATH = PROJECT_ROOT / "temp" / "viral_moment_clipper.sqlite3"


class ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=5.0, factory=ManagedConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def init_db() -> None:
    from backend.db.models import SCHEMA

    with get_connection() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(SCHEMA)
        _migrate_source_videos(connection)
        _migrate_feedback(connection)
        _migrate_publish_metrics(connection)
        _migrate_jobs(connection)


def _migrate_source_videos(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(source_videos)").fetchall()}
    if "uploaded_at" not in columns:
        connection.execute("ALTER TABLE source_videos ADD COLUMN uploaded_at TEXT")


def _migrate_feedback(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(feedback)").fetchall()}
    if "features_json" not in columns:
        connection.execute("ALTER TABLE feedback ADD COLUMN features_json TEXT")

    from backend.services.learning.feature_extractor import feature_row

    rows = connection.execute(
        """
        SELECT feedback.id, moments.source_json
        FROM feedback
        JOIN moments ON moments.id = feedback.moment_id
        WHERE feedback.features_json IS NULL
        """
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["source_json"] or "{}")
            snapshot = json.dumps(feature_row(payload), ensure_ascii=False)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        connection.execute("UPDATE feedback SET features_json = ? WHERE id = ?", (snapshot, row["id"]))

    connection.execute(
        """
        UPDATE feedback
        SET features_json = (
          SELECT donor.features_json
          FROM feedback AS donor
          WHERE donor.project_id = feedback.project_id
            AND donor.features_json IS NOT NULL
            AND (donor.moment_id = feedback.moment_id OR donor.clip_id = feedback.clip_id)
          ORDER BY donor.created_at DESC, donor.id DESC
          LIMIT 1
        )
        WHERE features_json IS NULL
        """
    )

    legacy_rows = connection.execute(
        """
        SELECT feedback.id, feedback.clip_id, feedback.moment_id, projects.output_dir
        FROM feedback
        JOIN projects ON projects.id = feedback.project_id
        WHERE feedback.features_json IS NULL
          AND feedback.action IN ('accept', 'reject')
          AND feedback.clip_id IS NOT NULL
          AND feedback.moment_id IS NOT NULL
        """
    ).fetchall()
    for row in legacy_rows:
        metadata_path = Path(row["output_dir"]) / "metadata" / f"{row['clip_id']}.json"
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            clip = payload.get("clip", {})
            if clip.get("moment_id") != row["moment_id"]:
                continue
            snapshot = json.dumps(feature_row(clip), ensure_ascii=False, sort_keys=True)
        except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        connection.execute("UPDATE feedback SET features_json = ? WHERE id = ?", (snapshot, row["id"]))


def _migrate_publish_metrics(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(publish_metrics)").fetchall()}
    foreign_keys = connection.execute("PRAGMA foreign_key_list(publish_metrics)").fetchall()
    durable_schema = {"project_id", "moment_id"}.issubset(columns) and not any(
        row["table"] == "clips" for row in foreign_keys
    )
    if durable_schema:
        return

    project_expr = "COALESCE(metrics.project_id, clips.project_id)" if "project_id" in columns else "clips.project_id"
    moment_expr = "COALESCE(metrics.moment_id, clips.moment_id)" if "moment_id" in columns else "clips.moment_id"
    connection.execute(
        """
        CREATE TABLE publish_metrics_new (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          clip_id TEXT NOT NULL,
          moment_id TEXT,
          platform TEXT NOT NULL,
          published_url TEXT,
          views INTEGER,
          likes INTEGER,
          comments INTEGER,
          shares INTEGER,
          saves INTEGER,
          avg_watch_time_sec REAL,
          retention_percent REAL,
          posted_at TEXT,
          captured_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        f"""
        INSERT INTO publish_metrics_new (
          id, project_id, clip_id, moment_id, platform, published_url, views, likes,
          comments, shares, saves, avg_watch_time_sec, retention_percent, posted_at, captured_at
        )
        SELECT metrics.id, {project_expr}, metrics.clip_id, {moment_expr}, metrics.platform,
               metrics.published_url, metrics.views, metrics.likes, metrics.comments, metrics.shares,
               metrics.saves, metrics.avg_watch_time_sec, metrics.retention_percent,
               metrics.posted_at, metrics.captured_at
        FROM publish_metrics AS metrics
        LEFT JOIN clips ON clips.id = metrics.clip_id
        WHERE {project_expr} IS NOT NULL
        """
    )
    connection.execute("DROP TABLE publish_metrics")
    connection.execute("ALTER TABLE publish_metrics_new RENAME TO publish_metrics")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_publish_metrics_moment ON publish_metrics(moment_id)")


def _migrate_jobs(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()}
    if "cancel_requested" not in columns:
        connection.execute(
            "ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0"
        )


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def db_path() -> Path:
    return DB_PATH
