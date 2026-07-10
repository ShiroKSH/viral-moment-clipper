from __future__ import annotations

from pydantic import BaseModel, Field


class SentenceSegment(BaseModel):
    id: str
    start: float
    end: float
    text: str
    speaker: str | None = None
    speakers: list[str] = Field(default_factory=list)
    speaker_switches: int = 0
    words: list[dict] = Field(default_factory=list)


class InterestingMoment(BaseModel):
    id: str
    start: float
    end: float
    duration: float
    text: str
    summary: str
    moment_type: str
    hook_text: str
    payoff_text: str = ""
    semantic_interest_score: float = 0
    hook_score: float = 0
    clarity_score: float = 0
    emotion_score: float = 0
    novelty_score: float = 0
    standalone_score: float = 0
    retention_score: float = 0
    speech_density_score: float = 0
    audio_energy_score: float = 0
    visual_energy_score: float = 0
    speaker_count: int = 0
    speaker_switches: int = 0
    dialogue_score: float = 0
    base_score: float = 0
    personal_score: float = 0
    final_score: float = 0
    reason: str = ""
    problems: list[str] = Field(default_factory=list)
    suggested_title: str = ""
    suggested_caption: str = ""
