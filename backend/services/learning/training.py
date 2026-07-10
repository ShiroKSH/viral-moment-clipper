from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from statistics import median
from typing import Any
from uuid import uuid4

import joblib
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from backend.core.config import Settings, load_config
from backend.core.paths import resolve_project_path
from backend.core.utils import utc_now, write_json
from backend.db.database import get_connection
from backend.services.learning.feature_extractor import CATEGORICAL_FEATURES, NUMERIC_FEATURES, feature_row


def _metric_value(row: sqlite3.Row, name: str) -> float:
    value = row[name]
    return float(value or 0)


def latest_feedback_rows() -> list[dict[str, Any]]:
    """Load one latest explicit decision per candidate, with published metrics."""
    try:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT feedback.id, feedback.clip_id, feedback.moment_id,
                       feedback.action, feedback.user_rating, feedback.created_at,
                       feedback.features_json,
                       moments.id AS candidate_id, moments.text, moments.summary,
                       moments.moment_type, moments.hook_text, moments.payoff_text,
                       moments.start, moments.end, moments.duration,
                       moments.semantic_interest_score, moments.hook_score,
                       moments.clarity_score, moments.emotion_score, moments.novelty_score,
                       moments.standalone_score, moments.retention_score,
                       moments.speech_density_score, moments.audio_energy_score,
                       moments.visual_energy_score, moments.base_score, moments.source_json,
                       COALESCE(metrics.metric_count, 0) AS metric_count,
                       COALESCE(metrics.retention_percent, 0) AS retention_percent,
                       COALESCE(metrics.avg_watch_time_sec, 0) AS avg_watch_time_sec,
                       COALESCE(metrics.views, 0) AS views
                FROM feedback
                LEFT JOIN moments ON moments.id = feedback.moment_id
                LEFT JOIN (
                  SELECT COALESCE(moment_id, clip_id) AS candidate_key,
                         COUNT(*) AS metric_count,
                         AVG(NULLIF(retention_percent, 0)) AS retention_percent,
                         AVG(NULLIF(avg_watch_time_sec, 0)) AS avg_watch_time_sec,
                         AVG(NULLIF(views, 0)) AS views
                  FROM publish_metrics
                  GROUP BY COALESCE(moment_id, clip_id)
                ) AS metrics ON metrics.candidate_key = COALESCE(feedback.moment_id, feedback.clip_id)
                WHERE feedback.action IN ('accept', 'reject')
                   OR feedback.user_rating IS NOT NULL
                ORDER BY feedback.created_at DESC, feedback.id DESC
                """
            ).fetchall()
    except sqlite3.Error:
        return []

    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        key = str(item.get("moment_id") or item.get("clip_id") or item["candidate_id"])
        if key not in latest:
            latest[key] = item
    return list(latest.values())


def label_for_feedback(row: dict[str, Any]) -> int | None:
    action = row.get("action")
    if action == "accept":
        return 1
    if action == "reject":
        return 0
    rating = row.get("user_rating")
    if rating is None:
        return None
    if int(rating) >= 4:
        return 1
    if int(rating) <= 2:
        return 0
    return None


def labeled_training_rows(rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    result = []
    for row in rows if rows is not None else latest_feedback_rows():
        label = label_for_feedback(row)
        if label is None:
            continue
        item = dict(row)
        item["label"] = label
        item["features"] = _features_for_training(item)
        if item["features"].get("moment_type") in {None, "", "unknown"}:
            continue
        result.append(item)
    return result


def _features_for_training(row: dict[str, Any]) -> dict[str, float | str]:
    raw_snapshot = row.get("features_json")
    if raw_snapshot:
        try:
            snapshot = json.loads(raw_snapshot)
            if isinstance(snapshot, dict):
                return {name: snapshot.get(name, 0) for name in CATEGORICAL_FEATURES + NUMERIC_FEATURES}
        except (json.JSONDecodeError, TypeError):
            pass
    raw_source = row.get("source_json")
    if raw_source:
        try:
            source = json.loads(raw_source)
            if isinstance(source, dict) and source.get("moment_type"):
                return feature_row(source)
        except (json.JSONDecodeError, TypeError):
            pass
    return feature_row(row)


def retention_summary(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    retained = [_metric_value(row, "retention_percent") for row in rows if _metric_value(row, "retention_percent") > 0]
    watches = [_metric_value(row, "avg_watch_time_sec") for row in rows if _metric_value(row, "avg_watch_time_sec") > 0]
    views = [_metric_value(row, "views") for row in rows if _metric_value(row, "views") > 0]
    return {
        "samples_with_retention": len(retained),
        "average_retention_percent": round(sum(retained) / len(retained), 2) if retained else 0,
        "median_retention_percent": round(median(retained), 2) if retained else 0,
        "average_watch_time_sec": round(sum(watches) / len(watches), 2) if watches else 0,
        "average_views": round(sum(views) / len(views), 2) if views else 0,
    }


def training_readiness(rows: list[dict[str, Any]], min_feedback: int) -> dict[str, Any]:
    positives = sum(row["label"] == 1 for row in rows)
    negatives = sum(row["label"] == 0 for row in rows)
    minimum_per_class = max(2, math.ceil(min_feedback / 4))
    majority = max(positives, negatives)
    minority = min(positives, negatives)
    balanced = minority >= minimum_per_class and majority <= minority * 3
    return {
        "training_ready": len(rows) >= min_feedback and balanced,
        "training_rows": len(rows),
        "positive_count": positives,
        "negative_count": negatives,
        "minimum_per_class": minimum_per_class,
        "balanced": balanced,
    }


def _fingerprint(rows: list[dict[str, Any]]) -> str:
    records = [
        {
            "candidate_id": row.get("candidate_id") or row.get("moment_id") or row.get("clip_id"),
            "label": row["label"],
            "created_at": row["created_at"],
            "features": row["features"],
            "retention_percent": _metric_value(row, "retention_percent"),
            "avg_watch_time_sec": _metric_value(row, "avg_watch_time_sec"),
            "views": _metric_value(row, "views"),
        }
        for row in rows
    ]
    content = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _active_fingerprint() -> str | None:
    try:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT metrics_json FROM ranking_models WHERE active = 1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return json.loads(row["metrics_json"] or "{}").get("training_fingerprint")
    except (sqlite3.Error, json.JSONDecodeError, TypeError):
        return None


def _build_model() -> Pipeline:
    return Pipeline(
        steps=[
            ("features", DictVectorizer(sparse=True)),
            ("classifier", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)),
        ]
    )


def _training_metrics(model: Pipeline, rows: list[dict[str, Any]], labels: list[int]) -> dict[str, float]:
    predictions = [int(value) for value in model.predict([row["features"] for row in rows])]
    accuracy = sum(prediction == label for prediction, label in zip(predictions, labels)) / max(len(labels), 1)
    positives = [index for index, label in enumerate(labels) if label == 1]
    negatives = [index for index, label in enumerate(labels) if label == 0]
    positive_accuracy = sum(predictions[index] == 1 for index in positives) / max(len(positives), 1)
    negative_accuracy = sum(predictions[index] == 0 for index in negatives) / max(len(negatives), 1)
    return {
        "training_accuracy": round(accuracy, 4),
        "training_balanced_accuracy": round((positive_accuracy + negative_accuracy) / 2, 4),
    }


def _model_paths(config: Settings, version: str) -> tuple[Path, Path]:
    directory = resolve_project_path(config.paths.models_dir) / "ranking_models"
    return directory / f"{version}.joblib", directory / f"{version}.json"


def train_personal_ranker(config: Settings | None = None) -> dict[str, Any]:
    config = config or load_config()
    rows = labeled_training_rows()
    readiness = training_readiness(rows, config.learning.min_feedback_before_training)
    result: dict[str, Any] = {**readiness, "trained": False, "retention": retention_summary(rows)}
    if not readiness["training_ready"]:
        fingerprint = _fingerprint(rows)
        if _active_fingerprint() not in {None, fingerprint}:
            with get_connection() as connection:
                connection.execute("UPDATE ranking_models SET active = 0 WHERE active = 1")
            result["active"] = False
        result["message"] = "Not enough balanced unique feedback samples for local training."
        return result

    fingerprint = _fingerprint(rows)
    if _active_fingerprint() == fingerprint:
        result.update({"trained": False, "active": True, "message": "Active model already contains the latest feedback."})
        return result

    labels = [int(row["label"]) for row in rows]
    model = _build_model()
    metric_rows = sum(_metric_value(row, "metric_count") > 0 for row in rows)
    use_metric_weights = metric_rows >= config.learning.min_metrics_before_training
    weights = []
    for row in rows:
        if not use_metric_weights:
            weights.append(1.0)
            continue
        retention = min(max(_metric_value(row, "retention_percent"), 0), 100) / 100
        agreement = retention if row["label"] == 1 else 1 - retention
        weights.append(0.75 + agreement * 0.75)
    model.fit([row["features"] for row in rows], labels, classifier__sample_weight=weights)
    version = f"personal_ranker_{utc_now().replace('-', '').replace(':', '').replace('.', '')}"
    model_path, sidecar_path = _model_paths(config, version)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    metrics = {
        **_training_metrics(model, rows, labels),
        **retention_summary(rows),
        "training_fingerprint": fingerprint,
        "feature_names": list(CATEGORICAL_FEATURES + NUMERIC_FEATURES),
        "metric_weighting_active": use_metric_weights,
    }
    metrics["model_path"] = str(model_path)
    metrics["sidecar_path"] = str(sidecar_path)
    sidecar = {
        "version": version,
        "model_path": str(model_path),
        "created_at": utc_now(),
        "training_rows": len(rows),
        "positive_count": readiness["positive_count"],
        "negative_count": readiness["negative_count"],
        "metrics": metrics,
    }
    write_json(sidecar_path, sidecar)
    with get_connection() as connection:
        connection.execute("UPDATE ranking_models SET active = 0 WHERE active = 1")
        connection.execute(
            """
            INSERT INTO ranking_models (id, version, model_path, training_rows, metrics_json, created_at, active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (uuid4().hex, version, str(model_path), len(rows), json.dumps(metrics), utc_now()),
        )
    result.update(
        {
            "trained": True,
            "active": True,
            "active_ranker_version": version,
            "model_path": str(model_path),
            "sidecar_path": str(sidecar_path),
            "metrics": metrics,
            "message": "Local sklearn ranker trained and activated.",
        }
    )
    return result


def maybe_train_personal_ranker(config: Settings | None = None) -> dict[str, Any]:
    config = config or load_config()
    if not config.learning.enabled:
        return {"trained": False, "training_ready": False, "message": "Learning is disabled."}
    return train_personal_ranker(config)


def active_model() -> tuple[Pipeline, dict[str, Any]] | None:
    try:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT version, model_path, metrics_json FROM ranking_models WHERE active = 1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        model = joblib.load(row["model_path"])
        metrics = json.loads(row["metrics_json"] or "{}")
        return model, {"version": row["version"], "model_path": row["model_path"], "metrics": metrics}
    except (OSError, ValueError, EOFError, ImportError, sqlite3.Error, json.JSONDecodeError, TypeError):
        return None
