from __future__ import annotations

from threading import Lock
from uuid import uuid4

from backend.core.utils import utc_now
from backend.schemas.jobs import JobRecord, JobStatus


_jobs: dict[str, JobRecord] = {}
_lock = Lock()


def create_job(project_id: str | None = None) -> JobRecord:
    job = JobRecord(job_id=uuid4().hex, project_id=project_id, started_at=utc_now())
    with _lock:
        _jobs[job.job_id] = job
    return job


def get_job(job_id: str) -> JobRecord | None:
    with _lock:
        return _jobs.get(job_id)


def update_job(job_id: str, *, status: JobStatus | None = None, stage: str | None = None, progress: float | None = None, message: str | None = None, log: str | None = None, error: str | None = None) -> JobRecord:
    with _lock:
        job = _jobs[job_id]
        if status is not None:
            job.status = status
        if stage is not None:
            job.stage = stage
        if progress is not None:
            job.progress = progress
        if message is not None:
            job.message = message
        if log:
            job.logs.append(log)
            job.logs = job.logs[-200:]
        if error is not None:
            job.error = error
        if status in {JobStatus.done, JobStatus.failed, JobStatus.cancelled}:
            job.finished_at = utc_now()
        _jobs[job_id] = job
        return job


def cancel_job(job_id: str) -> JobRecord | None:
    if not get_job(job_id):
        return None
    return update_job(job_id, status=JobStatus.cancelled, stage="cancelled", progress=0, message="Cancelled")
