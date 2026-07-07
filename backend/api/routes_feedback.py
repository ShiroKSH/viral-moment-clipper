from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.db.database import get_connection
from backend.schemas.feedback import FeedbackRequest, MetricsRequest
from backend.services import project_store
from backend.services.learning.feedback_store import store_feedback
from backend.services.learning.metrics_import import store_metrics
from backend.services.learning.model_registry import active_model_summary

router = APIRouter(prefix="/api", tags=["feedback"])


@router.post("/clips/{clip_id}/feedback")
def add_feedback(clip_id: str, payload: FeedbackRequest) -> dict:
    with get_connection() as connection:
        row = connection.execute("SELECT project_id, moment_id FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Clip not found")
    feedback_id = store_feedback(row["project_id"], clip_id, row["moment_id"], payload)
    return {"id": feedback_id}


@router.post("/clips/{clip_id}/metrics")
def add_metrics(clip_id: str, payload: MetricsRequest) -> dict:
    with get_connection() as connection:
        row = connection.execute("SELECT id FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Clip not found")
    return {"id": store_metrics(clip_id, payload)}


@router.get("/learning/summary")
def learning_summary() -> dict:
    with get_connection() as connection:
        total_clips = connection.execute("SELECT COUNT(*) AS count FROM clips").fetchone()["count"]
        accepted = connection.execute("SELECT COUNT(*) AS count FROM feedback WHERE action = 'accept'").fetchone()["count"]
        rejected = connection.execute("SELECT COUNT(*) AS count FROM feedback WHERE action = 'reject'").fetchone()["count"]
        metrics = connection.execute("SELECT COUNT(*) AS count FROM publish_metrics").fetchone()["count"]
        top_types = connection.execute(
            """
            SELECT moments.moment_type, COUNT(*) AS count
            FROM moments
            GROUP BY moments.moment_type
            ORDER BY count DESC
            LIMIT 5
            """
        ).fetchall()
        accepted_score = connection.execute(
            """
            SELECT AVG(moments.final_score) AS score
            FROM feedback
            JOIN moments ON moments.id = feedback.moment_id
            WHERE feedback.action = 'accept'
            """
        ).fetchone()["score"]
    return {
        "total_clips_analyzed": total_clips,
        "accepted_count": accepted,
        "rejected_count": rejected,
        "top_moment_types": [{"moment_type": row["moment_type"], "count": row["count"]} for row in top_types],
        "average_score_accepted": accepted_score or 0,
        "metrics_entered": metrics,
        **active_model_summary(),
    }


@router.post("/learning/train")
def train_learning() -> dict:
    summary = active_model_summary()
    return {"ok": True, "message": "Rejection-aware local ranker refreshed from current feedback.", **summary}
