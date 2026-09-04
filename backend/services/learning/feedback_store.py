from __future__ import annotations

import json
import logging
from uuid import uuid4

from backend.core.config import Settings
from backend.core.utils import utc_now
from backend.db.database import get_connection
from backend.schemas.feedback import FeedbackRequest
from backend.services.learning.feature_extractor import feature_row
from backend.services.learning.training import train_personal_ranker


def _feature_snapshot(project_id: str, moment_id: str | None) -> str | None:
    if not moment_id:
        return None
    with get_connection() as connection:
        row = connection.execute(
            "SELECT source_json FROM moments WHERE project_id = ? AND id = ?",
            (project_id, moment_id),
        ).fetchone()
    if not row:
        return None
    try:
        return json.dumps(feature_row(json.loads(row["source_json"] or "{}")), ensure_ascii=False, sort_keys=True)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def store_feedback(
    project_id: str,
    clip_id: str | None,
    moment_id: str | None,
    feedback: FeedbackRequest,
    config: Settings | None = None,
) -> str:
    feedback_id = uuid4().hex
    features_json = _feature_snapshot(project_id, moment_id)
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO feedback (id, project_id, clip_id, moment_id, action, user_rating, user_note, old_start, old_end, new_start, new_end, features_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feedback_id,
                project_id,
                clip_id,
                moment_id,
                feedback.action,
                feedback.user_rating,
                feedback.user_note,
                feedback.old_start,
                feedback.old_end,
                feedback.new_start,
                feedback.new_end,
                features_json,
                utc_now(),
            ),
        )
    if feedback.action in {"accept", "reject"} or feedback.user_rating is not None:
        try:
            train_personal_ranker(config)
        except Exception:
            # Feedback is durable even when a local model refresh cannot run.
            logging.getLogger(__name__).exception("Feedback saved, but personal ranker refresh failed.")
    return feedback_id
