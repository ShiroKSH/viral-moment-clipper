from __future__ import annotations

from uuid import uuid4

from backend.core.utils import utc_now
from backend.db.database import get_connection
from backend.schemas.feedback import MetricsRequest


def store_metrics(clip_id: str, metrics: MetricsRequest) -> str:
    metrics_id = uuid4().hex
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO publish_metrics (id, clip_id, platform, published_url, views, likes, comments, shares, saves, avg_watch_time_sec, retention_percent, posted_at, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metrics_id,
                clip_id,
                metrics.platform,
                metrics.published_url,
                metrics.views,
                metrics.likes,
                metrics.comments,
                metrics.shares,
                metrics.saves,
                metrics.avg_watch_time_sec,
                metrics.retention_percent,
                metrics.posted_at,
                utc_now(),
            ),
        )
    return metrics_id
