from __future__ import annotations

from pydantic import BaseModel, Field


class EditOperation(BaseModel):
    type: str
    start: float | None = None
    end: float | None = None
    reason: str = ""
    scale_from: float | None = None
    scale_to: float | None = None
    text: str | None = None


class EditPlan(BaseModel):
    clip_id: str
    profile: str
    strategy: str = "semantic_tension_v1"
    natural_cut_count: int = 0
    generated_effect_count: int = 0
    operations: list[EditOperation] = Field(default_factory=list)


class RenderRequest(BaseModel):
    clip_ids: list[str] | None = None


class RenderResult(BaseModel):
    clip_id: str
    output_path: str
    metadata_path: str
    subtitle_srt_path: str
    subtitle_ass_path: str
    edit_plan_path: str
