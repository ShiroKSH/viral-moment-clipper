import json
import sqlite3

from backend.core.config import Settings
from backend.services.learning import training


def _connection_with_feedback():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE moments (
            id TEXT PRIMARY KEY, text TEXT, summary TEXT, moment_type TEXT, hook_text TEXT,
            payoff_text TEXT, start REAL, end REAL, duration REAL,
            semantic_interest_score REAL, hook_score REAL, clarity_score REAL,
            emotion_score REAL, novelty_score REAL, standalone_score REAL,
            retention_score REAL, speech_density_score REAL, audio_energy_score REAL,
            visual_energy_score REAL, base_score REAL, source_json TEXT
        );
        CREATE TABLE clips (id TEXT PRIMARY KEY, moment_id TEXT);
        CREATE TABLE feedback (
            id TEXT, clip_id TEXT, moment_id TEXT, action TEXT, user_rating INTEGER, features_json TEXT, created_at TEXT
        );
        CREATE TABLE publish_metrics (
            project_id TEXT, clip_id TEXT, moment_id TEXT, retention_percent REAL, avg_watch_time_sec REAL, views INTEGER
        );
        CREATE TABLE ranking_models (
            id TEXT, version TEXT, model_path TEXT, training_rows INTEGER,
            metrics_json TEXT, created_at TEXT, active INTEGER
        );
        """
    )
    for index in range(4):
        moment_id = f"moment_{index}"
        clip_id = f"clip_{index}"
        connection.execute(
            "INSERT INTO moments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                moment_id, f"A useful idea {index}", "summary", "insight" if index % 2 else "personal_story",
                "hook", "payoff", 0, 20, 20, 70, 70, 70, 70, 70, 70, 70, 60, 50, 50, 70, "{}",
            ),
        )
        connection.execute("INSERT INTO clips VALUES (?, ?)", (clip_id, moment_id))
        connection.execute(
            "INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"feedback_{index}", clip_id, moment_id, "accept" if index < 2 else "reject", None, None, f"2026-01-0{index + 1}"),
        )
        connection.execute(
            "INSERT INTO publish_metrics VALUES (?, ?, ?, ?, ?, ?)",
            ("project", clip_id, moment_id, 70 + index, 12 + index, 1000 + index),
        )
    connection.execute(
        "INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("detached", "old_clip", "old_moment", "reject", None, None, "2026-01-10"),
    )
    connection.commit()
    return connection


def test_training_persists_and_activates_local_model(monkeypatch, tmp_path):
    connection = _connection_with_feedback()
    monkeypatch.setattr(training, "get_connection", lambda: connection)
    settings = Settings.model_validate({"paths": {"models_dir": str(tmp_path)}, "learning": {"min_feedback_before_training": 4}})

    result = training.train_personal_ranker(settings)

    assert result["trained"] is True
    assert result["training_rows"] == 4
    assert result["retention"]["samples_with_retention"] == 4
    assert tmp_path.joinpath("ranking_models").joinpath(f"{result['active_ranker_version']}.joblib").exists()
    assert tmp_path.joinpath("ranking_models").joinpath(f"{result['active_ranker_version']}.json").exists()
    active = connection.execute("SELECT active, version FROM ranking_models").fetchone()
    assert tuple(active) == (1, result["active_ranker_version"])
    sidecar = json.loads(tmp_path.joinpath("ranking_models", f"{result['active_ranker_version']}.json").read_text())
    assert sidecar["metrics"]["average_retention_percent"] == 71.5


def test_latest_feedback_uses_moment_id_and_ignores_detached_features(monkeypatch):
    connection = _connection_with_feedback()
    monkeypatch.setattr(training, "get_connection", lambda: connection)

    rows = training.latest_feedback_rows()
    labeled = training.labeled_training_rows(rows)

    assert len(rows) == 5
    assert len(labeled) == 4


def test_training_uses_immutable_feature_snapshot(monkeypatch):
    connection = _connection_with_feedback()
    connection.execute(
        "UPDATE feedback SET features_json = ? WHERE id = 'feedback_0'",
        ('{"moment_type":"snapshot_type","base_score":22,"speaker_count":2,"speaker_switches":4,"dialogue_score":75}',),
    )
    connection.execute("UPDATE moments SET base_score = 99 WHERE id = 'moment_0'")
    connection.commit()
    monkeypatch.setattr(training, "get_connection", lambda: connection)

    row = next(row for row in training.labeled_training_rows() if row["candidate_id"] == "moment_0")

    assert row["features"]["moment_type"] == "snapshot_type"
    assert row["features"]["base_score"] == 22
    assert row["features"]["speaker_count"] == 2
