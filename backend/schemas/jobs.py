from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class JobOperation(str, Enum):
    generic = "generic"
    analysis = "analysis"
    render = "render"


class JobRecord(BaseModel):
    job_id: str
    project_id: str | None = None
    operation: JobOperation = JobOperation.generic
    project_status_before: str | None = None
    status: JobStatus = JobStatus.queued
    cancel_requested: bool = False
    stage: str = "queued"
    progress: float = 0
    message: str = ""
    logs: list[str] = Field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
