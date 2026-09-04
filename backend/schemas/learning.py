from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


NonNegative = Annotated[float, Field(ge=0)]
Score = Annotated[float, Field(ge=0, le=100)]


class ClipFeatures(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    moment_type: str = "unknown"
    duration: NonNegative = 0
    word_count: NonNegative = 0
    words_per_second: NonNegative = 0
    semantic_interest_score: Score = 0
    hook_score: Score = 0
    clarity_score: Score = 0
    emotion_score: Score = 0
    novelty_score: Score = 0
    standalone_score: Score = 0
    retention_score: Score = 0
    speech_density_score: Score = 0
    audio_energy_score: Score = 0
    visual_energy_score: Score = 0
    speaker_count: NonNegative = 0
    speaker_switches: NonNegative = 0
    dialogue_score: Score = 0
    base_score: Score = 0
    quality_penalty: NonNegative = 0
    starts_with_hook: bool = False
    has_conflict: bool = False
    has_story: bool = False
    has_result: bool = False
    is_ad_like: bool = False
    is_generic_clip_text: bool = False
    is_low_information: bool = False

    @field_validator("moment_type")
    @classmethod
    def normalize_moment_type(cls, value: str) -> str:
        return value.strip() or "unknown"

    def as_row(self) -> dict[str, float | str]:
        return {
            name: value if name == "moment_type" else float(value)
            for name, value in self.model_dump().items()
        }
