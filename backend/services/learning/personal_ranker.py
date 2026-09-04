from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import logging
import sqlite3
from typing import Any

import numpy as np

from backend.core.config import Settings, load_config
from backend.db.database import get_connection
from backend.schemas.moments import InterestingMoment
from backend.services.learning import dataset, model_registry
from backend.services.learning.feature_extractor import NUMERIC_FEATURES, feature_row
from backend.services.viral_score import combine_personal_score


MODEL_REASON = "Personal ranking: local sklearn model prediction."
ONLINE_REASON = "Personal ranking: online type and feature preference."


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


def preferred_types(rows: list[dict[str, Any]]) -> set[str]:
    positives = Counter(row["features"]["moment_type"] for row in rows if row["label"] == 1)
    negatives = Counter(row["features"]["moment_type"] for row in rows if row["label"] == 0)
    return {kind for kind, count in positives.items() if count >= 2 and count > negatives[kind]}


@dataclass
class _PreferenceProfile:
    type_adjustments: dict[str, float]
    numeric_preferences: dict[str, tuple[float, float]]


def _preference_profile(rows: list[dict[str, Any]]) -> _PreferenceProfile:
    positives = [row for row in rows if row["label"] == 1]
    negatives = [row for row in rows if row["label"] == 0]
    positive_types = Counter(row["features"]["moment_type"] for row in positives)
    negative_types = Counter(row["features"]["moment_type"] for row in negatives)
    types = {}
    for kind in positive_types.keys() | negative_types.keys():
        support = positive_types[kind] + negative_types[kind]
        difference = positive_types[kind] / max(len(positives), 1) - negative_types[kind] / max(len(negatives), 1)
        types[kind] = difference * 6 * support / (support + 4)

    numeric = {}
    if positives and negatives:
        support = min(len(positives), len(negatives))
        confidence = support / (support + 4)
        for name in NUMERIC_FEATURES:
            positive_values = [float(row["features"].get(name, 0)) for row in positives]
            negative_values = [float(row["features"].get(name, 0)) for row in negatives]
            scale = float(np.std(positive_values + negative_values))
            if scale == 0:
                continue
            positive_mean, negative_mean = float(np.mean(positive_values)), float(np.mean(negative_values))
            difference = max(-1.0, min(1.0, (positive_mean - negative_mean) / scale))
            numeric[name] = ((positive_mean + negative_mean) / 2, difference * confidence * 0.15)
    return _PreferenceProfile(types, numeric)


def _online_adjustment(features: dict[str, float | str], profile: _PreferenceProfile) -> float:
    adjustment = profile.type_adjustments.get(str(features["moment_type"]), 0.0)
    for name, (center, strength) in profile.numeric_preferences.items():
        value = float(features[name])
        if value != center:
            adjustment += strength if value > center else -strength
    return max(-12.0, min(12.0, adjustment))


def online_preference_adjustment(moment: InterestingMoment, rows: list[dict[str, Any]] | None = None) -> float:
    rows = rows if rows is not None else dataset.labeled_training_rows()
    return _online_adjustment(feature_row(moment), _preference_profile(rows))


def _load_preference_profile() -> _PreferenceProfile:
    try:
        return _preference_profile(dataset.labeled_training_rows())
    except sqlite3.Error:
        logging.getLogger(__name__).warning("Feedback is temporarily unavailable; using base scores.")
        return _PreferenceProfile({}, {})


def _model_scores(model: Any, features: list[dict[str, float | str]]) -> list[float | None]:
    try:
        classes = list(model.classes_)
        if len(classes) != 2 or set(classes) != {0, 1}:
            return [None] * len(features)
        probabilities = np.asarray(model.predict_proba(features), dtype=float)
        if probabilities.shape != (len(features), 2):
            return [None] * len(features)
        positive_index = classes.index(1)
        return [
            float(row[positive_index]) * 100
            if np.isfinite(row).all() and (row >= 0).all() and (row <= 1).all() and np.isclose(row.sum(), 1)
            else None
            for row in probabilities
        ]
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, RuntimeError):
        return [None] * len(features)


def apply_personal_ranking(moments: list[InterestingMoment], config: Settings) -> list[InterestingMoment]:
    if not moments:
        return []
    for moment in moments:
        moment.reason = moment.reason.replace(MODEL_REASON, "").replace(ONLINE_REASON, "").strip()
    if not config.learning.enabled:
        for moment in moments:
            moment.personal_score = moment.base_score
            moment.final_score = moment.base_score
        return sorted(moments, key=lambda item: item.final_score, reverse=True)

    features = []
    valid_indices = []
    for index, moment in enumerate(moments):
        try:
            features.append(feature_row(moment))
            valid_indices.append(index)
        except (TypeError, ValueError):
            continue
    active = model_registry.active_model() if features else None
    predictions = _model_scores(active[0], features) if active else [None] * len(features)
    profile = _load_preference_profile() if any(score is None for score in predictions) else None
    for moment in moments:
        moment.personal_score = moment.base_score
        moment.final_score = moment.base_score
    for index, current, model_score in zip(valid_indices, features, predictions):
        moment = moments[index]
        if model_score is not None:
            learned = model_score
            reason = MODEL_REASON
        else:
            learned = max(0, min(100, moment.base_score + _online_adjustment(current, profile)))
            reason = ONLINE_REASON if learned != moment.base_score else ""
        if reason:
            moment.reason = f"{moment.reason} {reason}".strip()
        moment.personal_score = round(learned, 2)
        moment.final_score = combine_personal_score(moment.base_score, learned, config.learning.personal_score_weight)
    return sorted(moments, key=lambda item: item.final_score, reverse=True)


def ranker_summary() -> dict:
    config = load_config()
    rows = dataset.labeled_training_rows()
    readiness = dataset.training_readiness(rows, config.learning.min_feedback_before_training)
    active = model_registry.active_model() if config.learning.enabled else None
    latest = model_registry.latest_model_record()
    return {
        "feedback_count": feedback_count(),
        "active_ranker_version": active[1]["version"] if active else "online_preference_v002",
        **readiness,
        "training_ready": config.learning.enabled and readiness["training_ready"],
        "model_active": bool(active),
        "preferred_types": sorted(preferred_types(rows)),
        "retention": dataset.retention_summary(rows),
        "validation": latest["metrics"].get("validation") if latest else None,
    }
