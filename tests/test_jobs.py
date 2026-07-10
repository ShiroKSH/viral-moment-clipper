from backend.schemas.jobs import JobStatus
from backend.services.jobs import create_job, get_active_project_job, latest_project_job, update_job


def test_latest_project_job_uses_newest_project_job():
    project_id = "jobs_test_latest"
    older = create_job(project_id)
    newer = create_job(project_id)

    assert latest_project_job(project_id).job_id == newer.job_id
    assert latest_project_job("missing_project") is None
    assert older.job_id != newer.job_id


def test_active_project_job_ignores_finished_jobs():
    project_id = "jobs_test_active"
    finished = create_job(project_id)
    update_job(finished.job_id, status=JobStatus.done)
    active = create_job(project_id)
    update_job(active.job_id, status=JobStatus.running, stage="transcribing")

    assert get_active_project_job(project_id).job_id == active.job_id
