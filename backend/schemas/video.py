from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    author_handle: str = ""
    output_dir: str | None = None


class VideoMetadata(BaseModel):
    duration: float = 0
    width: int = 0
    height: int = 0
    fps: float = 0
    video_codec: str = ""
    audio_codec: str = ""
    raw: dict = Field(default_factory=dict)


class Project(BaseModel):
    id: str
    name: str
    author_handle: str = ""
    source_path: str | None = None
    output_dir: str
    created_at: str
    uploaded_at: str | None = None
    analyzed_at: str | None = None
    rendered_at: str | None = None
    last_activity_at: str | None = None
    status: str
    video: VideoMetadata | None = None


class UploadResult(BaseModel):
    project: Project
    video: VideoMetadata
