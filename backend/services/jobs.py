from __future__ import annotations

from threading import Lock
from uuid import uuid4

from backend.core.utils import utc_now
from backend.schemas.jobs import JobRecord, JobStatus


_jobs: dict[str, JobRecord] = {}
_lock = Lock()
_ACTIVE_STATUSES = {JobStatus.queued, JobStatus.running}
_TERMINAL_STATUSES = {JobStatus.done, JobStatus.failed, JobStatus.cancelled}


def _new_job(project_id: str | None) -> JobRecord:
    return JobRecord(job_id=uuid4().hex, project_id=project_id, started_at=utc_now())


def create_job(project_id: str | None = None) -> JobRecord:
    job = _new_job(project_id)
    with _lock:
        _jobs[job.job_id] = job
    return job


def create_project_job(project_id: str) -> tuple[JobRecord, bool]:
    with _lock:
        active_jobs = [
            job
            for job in _jobs.values()
            if job.project_id == project_id and job.status in _ACTIVE_STATUSES
        ]
        if active_jobs:
            newest = max(active_jobs, key=lambda job: job.started_at or "")
            return newest, False
        job = _new_job(project_id)
        _jobs[job.job_id] = job
        return job, True


def get_job(job_id: str) -> JobRecord | None:
    with _lock:
        return _jobs.get(job_id)


def list_jobs(project_id: str | None = None, *, active_only: bool = False) -> list[JobRecord]:
    with _lock:
        jobs = list(_jobs.values())
    if project_id is not None:
        jobs = [job for job in jobs if job.project_id == project_id]
    if active_only:
        jobs = [job for job in jobs if job.status in _ACTIVE_STATUSES]
    return sorted(jobs, key=lambda job: job.started_at or "", reverse=True)


def latest_project_job(project_id: str, *, active_only: bool = False) -> JobRecord | None:
    jobs = list_jobs(project_id, active_only=active_only)
    return jobs[0] if jobs else None


def get_active_project_job(project_id: str) -> JobRecord | None:
    return latest_project_job(project_id, active_only=True)


def update_job(job_id: str, *, status: JobStatus | None = None, stage: str | None = None, progress: float | None = None, message: str | None = None, log: str | None = None, error: str | None = None) -> JobRecord:
    with _lock:
        job = _jobs[job_id]
        if job.status in _TERMINAL_STATUSES:
            return job
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
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        if job.status in _TERMINAL_STATUSES:
            return job
        job.status = JobStatus.cancelled
        job.stage = "cancelled"
        job.message = "Cancelled"
        job.finished_at = utc_now()
        _jobs[job_id] = job
        return job


def is_job_cancelled(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        return bool(job and job.status == JobStatus.cancelled)
