from __future__ import annotations

from pydantic import BaseModel, Field


class TranscriptWord(BaseModel):
    word: str
    start: float
    end: float
    probability: float | None = None
    speaker: str | None = None


class TranscriptSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    speaker: str | None = None
    words: list[TranscriptWord] = Field(default_factory=list)


class Transcript(BaseModel):
    language: str = "ru"
    duration: float = 0
    engine: str = "fallback"
    speaker_model_version: str | None = None
    speaker_backend: str | None = None
    speaker_coverage: float = 0.0
    segments: list[TranscriptSegment] = Field(default_factory=list)
    text: str = ""
