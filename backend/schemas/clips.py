from __future__ import annotations

from pydantic import BaseModel, Field


class ClipCandidate(BaseModel):
    id: str
    moment_id: str
    start: float
    end: float
    duration: float
    selected: bool = True
    rendered: bool = False
    final_score: float
    base_score: float = 0
    personal_score: float = 0
    speaker_count: int = 0
    speaker_switches: int = 0
    dialogue_score: float = 0
    moment_type: str
    hook_text: str
    summary: str
    reason: str
    problems: list[str] = Field(default_factory=list)
    text: str
    suggested_title: str
    suggested_caption: str
    edit_profile: str = "balanced"
    latest_feedback_action: str | None = None
    review_action: str | None = None
    boundaries_edited: bool = False
    output_path: str | None = None
    metadata_path: str | None = None


class ClipUpdate(BaseModel):
    start: float | None = None
    end: float | None = None
    selected: bool | None = None
    edit_profile: str | None = None
