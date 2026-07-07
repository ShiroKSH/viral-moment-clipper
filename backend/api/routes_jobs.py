from fastapi import APIRouter, HTTPException

from backend.services.jobs import cancel_job, get_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


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
