from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FeedbackRequest(BaseModel):
    action: Literal["accept", "reject", "edited", "rendered"]
    user_rating: int | None = Field(default=None, ge=1, le=5)
    user_note: str = ""
    old_start: float | None = None
    old_end: float | None = None
    new_start: float | None = None
    new_end: float | None = None

    @model_validator(mode="after")
    def decision_and_rating_agree(self) -> "FeedbackRequest":
        if self.action == "accept" and self.user_rating is not None and self.user_rating <= 2:
            raise ValueError("An accepted clip cannot have a rating below 3")
        if self.action == "reject" and self.user_rating is not None and self.user_rating >= 4:
            raise ValueError("A rejected clip cannot have a rating above 3")
        return self


class MetricsRequest(BaseModel):
    platform: str = Field(min_length=1, max_length=40)
    published_url: str = ""
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    saves: int = Field(default=0, ge=0)
    avg_watch_time_sec: float = Field(default=0, ge=0)
    retention_percent: float = Field(default=0, ge=0, le=100)
    posted_at: str | None = None
