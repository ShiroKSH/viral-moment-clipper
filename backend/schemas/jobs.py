from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class JobRecord(BaseModel):
    job_id: str
    project_id: str | None = None
    status: JobStatus = JobStatus.queued
    stage: str = "queued"
    progress: float = 0
    message: str = ""
    logs: list[str] = Field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
