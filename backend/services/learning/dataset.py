from __future__ import annotations

import json
import math
from statistics import median
from typing import Any

from backend.db.database import get_connection
from backend.schemas.learning import ClipFeatures
from backend.services.learning.feature_extractor import feature_row


def latest_feedback_rows() -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            WITH decisions AS (
              SELECT *, ROW_NUMBER() OVER (
                PARTITION BY project_id, COALESCE(moment_id, clip_id)
                ORDER BY created_at DESC, id DESC
              ) AS decision_number
              FROM feedback
              WHERE action IN ('accept', 'reject') OR user_rating IS NOT NULL
            ), captures AS (
              SELECT *, ROW_NUMBER() OVER (
                PARTITION BY project_id, COALESCE(moment_id, clip_id), platform,
                             COALESCE(NULLIF(published_url, ''), clip_id)
                ORDER BY captured_at DESC, id DESC
              ) AS capture_number
              FROM publish_metrics
            ), metrics AS (
              SELECT project_id, COALESCE(moment_id, clip_id) AS candidate_key,
                     COUNT(*) AS metric_count,
                     AVG(retention_percent) AS retention_percent,
                     AVG(avg_watch_time_sec) AS avg_watch_time_sec,
                     AVG(views) AS views
              FROM captures WHERE capture_number = 1
              GROUP BY project_id, COALESCE(moment_id, clip_id)
            )
            SELECT feedback.id, feedback.project_id, feedback.clip_id, feedback.moment_id,
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
                   metrics.retention_percent, metrics.avg_watch_time_sec, metrics.views
            FROM decisions AS feedback
            LEFT JOIN moments ON moments.id = feedback.moment_id
            LEFT JOIN metrics ON metrics.project_id = feedback.project_id
              AND metrics.candidate_key = COALESCE(feedback.moment_id, feedback.clip_id)
            WHERE feedback.decision_number = 1
            ORDER BY feedback.project_id, COALESCE(feedback.moment_id, feedback.clip_id)
            """
        ).fetchall()
    return [dict(row) for row in rows]


def label_for_feedback(row: dict[str, Any]) -> int | None:
    if row.get("action") == "accept":
        return 1
    if row.get("action") == "reject":
        return 0
    rating = row.get("user_rating")
    if rating in (4, 5):
        return 1
    if rating in (1, 2):
        return 0
    return None


def _features_for_training(row: dict[str, Any]) -> dict[str, float | str]:
    snapshot = row.get("features_json")
    if snapshot is not None:
        # A damaged snapshot must never be replaced with mutable candidate data.
        return ClipFeatures.model_validate_json(snapshot).as_row()
    source = row.get("source_json")
    if source:
        payload = json.loads(source)
        if not isinstance(payload, dict):
            raise ValueError("Moment source must be a JSON object")
        if payload.get("moment_type"):
            return feature_row(payload)
    return feature_row(row)


def labeled_training_rows(rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    result = []
    for row in rows if rows is not None else latest_feedback_rows():
        label = label_for_feedback(row)
        if label is None:
            continue
        try:
            features = _features_for_training(row)
        except (TypeError, ValueError):
            continue
        if features["moment_type"] == "unknown":
            continue
        result.append({
            **row,
            "label": label,
            "features": features,
            **{name: metric_value(row, name) for name in ("retention_percent", "avg_watch_time_sec", "views")},
        })
    return result


def metric_value(row: dict[str, Any], name: str) -> float | None:
    value = row.get(name)
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    if name == "retention_percent" and number > 100:
        return None
    return number


def retention_summary(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    def observed(name: str) -> list[float]:
        return [value for row in rows if (value := metric_value(row, name)) is not None]

    retained = observed("retention_percent")
    watches = observed("avg_watch_time_sec")
    views = observed("views")
    return {
        "samples_with_retention": len(retained),
        "average_retention_percent": round(sum(retained) / len(retained), 2) if retained else 0,
        "median_retention_percent": round(median(retained), 2) if retained else 0,
        "average_watch_time_sec": round(sum(watches) / len(watches), 2) if watches else 0,
        "average_views": round(sum(views) / len(views), 2) if views else 0,
    }


def sample_weights(rows: list[dict[str, Any]], min_metrics: int) -> tuple[list[float], bool]:
    retentions = [metric_value(row, "retention_percent") for row in rows]
    enabled = sum(value is not None for value in retentions) >= min_metrics
    weights = []
    for row, retention in zip(rows, retentions):
        if not enabled or retention is None:
            weights.append(1.0)
        else:
            agreement = retention / 100 if row["label"] == 1 else 1 - retention / 100
            weights.append(0.75 + agreement * 0.75)
    return weights, enabled


def training_readiness(rows: list[dict[str, Any]], min_feedback: int) -> dict[str, Any]:
    positives = sum(row["label"] == 1 for row in rows)
    negatives = sum(row["label"] == 0 for row in rows)
    minimum_per_class = max(2, math.ceil(min_feedback / 4))
    balanced = min(positives, negatives) >= minimum_per_class and max(positives, negatives) <= min(positives, negatives) * 3
    return {
        "training_ready": len(rows) >= min_feedback and balanced,
        "training_rows": len(rows),
        "positive_count": positives,
        "negative_count": negatives,
        "minimum_per_class": minimum_per_class,
        "balanced": balanced,
        "project_count": len({row["project_id"] for row in rows if row.get("project_id")}),
    }
