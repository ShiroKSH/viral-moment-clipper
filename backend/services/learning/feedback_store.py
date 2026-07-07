from __future__ import annotations

from uuid import uuid4

from backend.core.utils import utc_now
from backend.db.database import get_connection
from backend.schemas.feedback import FeedbackRequest


def store_feedback(project_id: str, clip_id: str | None, moment_id: str | None, feedback: FeedbackRequest) -> str:
    feedback_id = uuid4().hex
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO feedback (id, project_id, clip_id, moment_id, action, user_rating, user_note, old_start, old_end, new_start, new_end, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                utc_now(),
            ),
        )
    return feedback_id
