from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile

from backend.api import routes_projects
from backend.core.config import Settings
from backend.schemas.jobs import JobStatus
from backend.schemas.video import Project
from backend.services import pipeline
from backend.services.jobs import (
    cancel_job,
    create_job,
    create_project_job,
    get_active_project_job,
    latest_project_job,
    update_job,
)


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


def test_project_job_creation_is_atomic():
    project_id = "jobs_test_atomic_creation"

    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = list(executor.map(lambda _: create_project_job(project_id), range(24)))

    assert len({job.job_id for job, _ in jobs}) == 1
    assert sum(created for _, created in jobs) == 1


def test_cancelled_job_cannot_restart():
    job = create_job("jobs_test_cancelled_terminal")
    cancelled = cancel_job(job.job_id)

    restarted = update_job(job.job_id, status=JobStatus.running, stage="transcribing")

    assert cancelled is not None
    assert restarted.status == JobStatus.cancelled
    assert restarted.stage == "cancelled"
    assert restarted.finished_at is not None


def test_finished_job_cannot_be_cancelled_after_completion():
    job = create_job("jobs_test_finished_terminal")
    update_job(job.job_id, status=JobStatus.done, stage="done", progress=1)

    unchanged = cancel_job(job.job_id)

    assert unchanged is not None
    assert unchanged.status == JobStatus.done
    assert unchanged.progress == 1


def test_duplicate_analysis_request_schedules_one_background_task(monkeypatch):
    project_id = "jobs_test_route_guard"
    monkeypatch.setattr(routes_projects.project_store, "get_project", lambda _: object())
    first_tasks = BackgroundTasks()
    duplicate_tasks = BackgroundTasks()

    first = routes_projects.analyze_project(project_id, first_tasks)
    duplicate = routes_projects.analyze_project(project_id, duplicate_tasks)

    assert first["job_id"] == duplicate["job_id"]
    assert len(first_tasks.tasks) == 1
    assert duplicate_tasks.tasks == []


def test_cancelled_analysis_job_does_not_touch_project(monkeypatch, tmp_path):
    project_id = "jobs_test_cancelled_pipeline"
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source")
    project = Project(
        id=project_id,
        name="Cancelled analysis",
        output_dir=str(tmp_path),
        source_path=str(source_path),
        created_at="2026-08-11T00:00:00+00:00",
        status="uploaded",
    )
    status_updates: list[str] = []
    monkeypatch.setattr(pipeline, "load_config", Settings)
    monkeypatch.setattr(pipeline.project_store, "get_project", lambda _: project)
    monkeypatch.setattr(pipeline.project_store, "project_source_path", lambda _: source_path)
    monkeypatch.setattr(
        pipeline.project_store,
        "set_project_status",
        lambda _project_id, status: status_updates.append(status),
    )

    job = create_job(project_id)
    cancel_job(job.job_id)
    pipeline.run_analysis(project_id, job.job_id)

    assert status_updates == []


def test_upload_is_rejected_while_project_job_is_active(monkeypatch, tmp_path):
    project_id = "jobs_test_upload_guard"
    project = Project(
        id=project_id,
        name="Busy project",
        output_dir=str(tmp_path),
        created_at="2026-08-11T00:00:00+00:00",
        status="analyzing",
    )
    monkeypatch.setattr(routes_projects.project_store, "get_project", lambda _: project)
    create_project_job(project_id)

    with pytest.raises(HTTPException) as exc_info:
        routes_projects.upload_video(
            project_id,
            UploadFile(filename="replacement.mp4", file=BytesIO(b"video")),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Project is busy: queued"
