from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from backend.services.jobs import cancel_job, get_job, latest_project_job, list_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def read_jobs(
    project_id: str | None = None,
    latest: bool = False,
    active_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict] | dict | None:
    if latest:
        if not project_id:
            raise HTTPException(status_code=422, detail="project_id is required for latest job lookup")
        job = latest_project_job(project_id, active_only=active_only)
        return job.model_dump() if job else None
    return [
        job.model_dump()
        for job in list_jobs(project_id, active_only=active_only, limit=limit)
    ]


@router.get("/{job_id}")
def read_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.model_dump()


@router.post("/{job_id}/cancel")
def cancel(job_id: str) -> dict:
    job = cancel_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.model_dump()
