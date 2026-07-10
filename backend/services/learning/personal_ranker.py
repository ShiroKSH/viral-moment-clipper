from __future__ import annotations

from collections import Counter
from typing import Any

from backend.core.config import Settings, load_config
from backend.db.database import get_connection
from backend.schemas.moments import InterestingMoment
from backend.services.learning import training as training_service
from backend.services.learning.feature_extractor import NUMERIC_FEATURES, feature_row
from backend.services.viral_score import combine_personal_score


def feedback_count() -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(DISTINCT COALESCE(moment_id, clip_id)) AS count
            FROM feedback
            WHERE action IN ('accept', 'reject') OR user_rating IS NOT NULL
            """
        ).fetchone()
    return int(row["count"] if row else 0)


def preferred_types() -> set[str]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT moments.moment_type
            FROM feedback
            JOIN moments ON moments.id = feedback.moment_id
            WHERE feedback.action = 'accept' OR feedback.user_rating >= 4
            """
        ).fetchall()
    counts = Counter(row["moment_type"] for row in rows)
    return {moment_type for moment_type, count in counts.items() if count >= 2}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0


def online_preference_adjustment(
    moment: InterestingMoment,
    rows: list[dict[str, Any]] | None = None,
) -> float:
    """Small cold-start update from types and numeric signals, never raw words."""
    rows = rows if rows is not None else training_service.labeled_training_rows()
    positives = [row for row in rows if row["label"] == 1]
    negatives = [row for row in rows if row["label"] == 0]
    if not rows:
        return 0

    current = feature_row(moment)
    adjustment = 0.0
    positive_type_rate = sum(row["features"]["moment_type"] == current["moment_type"] for row in positives) / max(len(positives), 1)
    negative_type_rate = sum(row["features"]["moment_type"] == current["moment_type"] for row in negatives) / max(len(negatives), 1)
    adjustment += max(-1.0, min(1.0, positive_type_rate - negative_type_rate)) * 6

    for name in NUMERIC_FEATURES:
        positive_values = [float(row["features"].get(name, 0) or 0) for row in positives]
        negative_values = [float(row["features"].get(name, 0) or 0) for row in negatives]
        if not positive_values or not negative_values:
            continue
        difference = (_mean(positive_values) - _mean(negative_values)) / 100
        current_value = float(current.get(name, 0) or 0)
        center = (_mean(positive_values) + _mean(negative_values)) / 2
        direction = 1 if current_value >= center else -1
        adjustment += max(-1.0, min(1.0, difference)) * direction * 0.15
    return max(-12, min(12, adjustment))


def _model_score(model: Any, moment: InterestingMoment) -> float | None:
    try:
        probabilities = model.predict_proba([feature_row(moment)])[0]
        classes = list(model.classes_)
        positive_index = classes.index(1)
        return max(0, min(100, float(probabilities[positive_index]) * 100))
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None


def apply_personal_ranking(moments: list[InterestingMoment], config: Settings) -> list[InterestingMoment]:
    if not config.learning.enabled:
        for moment in moments:
            moment.personal_score = moment.base_score
            moment.final_score = moment.base_score
        return sorted(moments, key=lambda item: item.final_score, reverse=True)
    active = training_service.active_model()
    rows = None if active else training_service.labeled_training_rows()
    for moment in moments:
        model_score = _model_score(active[0], moment) if active else None
        if model_score is not None:
            learned = model_score
            moment.reason += " Personal ranking: local sklearn model prediction."
        else:
            learned = max(0, min(100, moment.base_score + online_preference_adjustment(moment, rows)))
            if learned != moment.base_score:
                moment.reason += " Personal ranking: online type and feature preference."
        moment.personal_score = round(learned, 2)
        moment.final_score = combine_personal_score(moment.base_score, learned, config.learning.personal_score_weight)
    return sorted(moments, key=lambda item: item.final_score, reverse=True)


def ranker_summary() -> dict:
    count = feedback_count()
    config = load_config()
    rows = training_service.labeled_training_rows()
    readiness = training_service.training_readiness(rows, config.learning.min_feedback_before_training)
    active = training_service.active_model()
    return {
        "feedback_count": count,
        "active_ranker_version": active[1]["version"] if active else "online_preference_v001",
        "training_ready": readiness["training_ready"],
        "model_active": bool(active),
        "training_rows": readiness["training_rows"],
        "positive_count": readiness["positive_count"],
        "negative_count": readiness["negative_count"],
        "balanced": readiness["balanced"],
        "preferred_types": sorted(preferred_types()),
        "retention": training_service.retention_summary(rows),
    }
