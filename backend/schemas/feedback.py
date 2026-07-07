from __future__ import annotations

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    action: str
    user_rating: int | None = Field(default=None, ge=1, le=5)
    user_note: str = ""
    old_start: float | None = None
    old_end: float | None = None
    new_start: float | None = None
    new_end: float | None = None


class MetricsRequest(BaseModel):
    platform: str
    published_url: str = ""
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    avg_watch_time_sec: float = 0
    retention_percent: float = 0
    posted_at: str | None = None
