from __future__ import annotations

from pydantic import BaseModel, Field


class TranscriptWord(BaseModel):
    word: str
    start: float
    end: float
    probability: float | None = None


class TranscriptSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    words: list[TranscriptWord] = Field(default_factory=list)


class Transcript(BaseModel):
    language: str = "ru"
    duration: float = 0
    engine: str = "fallback"
    segments: list[TranscriptSegment] = Field(default_factory=list)
    text: str = ""
