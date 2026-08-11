from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile

from backend.api import routes_projects
from backend.core.config import Settings
from backend.db import database
from backend.schemas.jobs import JobOperation, JobStatus
from backend.schemas.video import Project
from backend.services import pipeline
from backend.services.jobs import (
    acknowledge_job_cancelled,
    cancel_job,
    create_job,
    create_project_job,
    get_active_project_job,
    get_job,
    latest_project_job,
    list_jobs,
    recover_interrupted_jobs,
    update_job,
)


@pytest.fixture(autouse=True)
def isolated_job_database(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "jobs.sqlite3")
    database.init_db()


def _create_project(project_id: str, *, status: str = "uploaded") -> None:
    with database.get_connection() as connection:
        connection.execute(
            """
            INSERT INTO projects (id, name, author_handle, source_path, output_dir, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                project_id,
                "",
                f"{project_id}.mp4",
                f"output/{project_id}",
                "2026-08-11T00:00:00+00:00",
                status,
            ),
        )


def test_latest_project_job_uses_newest_project_job():
    project_id = "jobs_test_latest"
    _create_project(project_id)
    older = create_job(project_id)
    update_job(older.job_id, status=JobStatus.done)
    newer = create_job(project_id)

    assert latest_project_job(project_id).job_id == newer.job_id
    assert latest_project_job("missing_project") is None
    assert older.job_id != newer.job_id


def test_active_project_job_ignores_finished_jobs():
    project_id = "jobs_test_active"
    _create_project(project_id)
    finished = create_job(project_id)
    update_job(finished.job_id, status=JobStatus.done)
    active = create_job(project_id)
    update_job(active.job_id, status=JobStatus.running, stage="transcribing")

    assert get_active_project_job(project_id).job_id == active.job_id


def test_project_job_creation_is_atomic():
    project_id = "jobs_test_atomic_creation"
    _create_project(project_id)

    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = list(executor.map(lambda _: create_project_job(project_id), range(24)))

    assert len({job.job_id for job, _ in jobs}) == 1
    assert sum(created for _, created in jobs) == 1


def test_cancelled_job_cannot_restart():
    project_id = "jobs_test_cancelled_terminal"
    _create_project(project_id)
    job = create_job(project_id)
    cancelled = cancel_job(job.job_id)

    restarted = update_job(job.job_id, status=JobStatus.running, stage="transcribing")

    assert cancelled is not None
    assert restarted.status == JobStatus.cancelled
    assert restarted.stage == "cancelled"
    assert restarted.finished_at is not None


def test_finished_job_cannot_be_cancelled_after_completion():
    project_id = "jobs_test_finished_terminal"
    _create_project(project_id)
    job = create_job(project_id)
    update_job(job.job_id, status=JobStatus.done, stage="done", progress=1)

    unchanged = cancel_job(job.job_id)

    assert unchanged is not None
    assert unchanged.status == JobStatus.done
    assert unchanged.progress == 1


def test_running_job_stays_active_until_worker_acknowledges_cancel():
    project_id = "jobs_test_cancel_ack"
    _create_project(project_id)
    job = create_project_job(project_id)[0]
    update_job(job.job_id, status=JobStatus.running, stage="transcribing")

    cancellation_requested = cancel_job(job.job_id)
    duplicate, created = create_project_job(project_id)

    assert cancellation_requested is not None
    assert cancellation_requested.status == JobStatus.running
    assert cancellation_requested.cancel_requested is True
    assert cancellation_requested.stage == "cancelling"
    assert duplicate.job_id == job.job_id
    assert created is False

    cancelled = acknowledge_job_cancelled(job.job_id)
    replacement, replacement_created = create_project_job(project_id)

    assert cancelled is not None
    assert cancelled.status == JobStatus.cancelled
    assert cancelled.finished_at is not None
    assert replacement.job_id != job.job_id
    assert replacement_created is True


def test_duplicate_analysis_request_schedules_one_background_task(monkeypatch):
    project_id = "jobs_test_route_guard"
    _create_project(project_id)
    monkeypatch.setattr(
        routes_projects.project_store,
        "get_project",
        lambda _: SimpleNamespace(status="uploaded"),
    )
    first_tasks = BackgroundTasks()
    duplicate_tasks = BackgroundTasks()

    first = routes_projects.analyze_project(project_id, first_tasks)
    duplicate = routes_projects.analyze_project(project_id, duplicate_tasks)

    assert first["job_id"] == duplicate["job_id"]
    assert first["operation"] == JobOperation.analysis
    assert first["project_status_before"] == "uploaded"
    assert len(first_tasks.tasks) == 1
    assert duplicate_tasks.tasks == []


def test_cancelled_analysis_job_does_not_touch_project(monkeypatch, tmp_path):
    project_id = "jobs_test_cancelled_pipeline"
    _create_project(project_id)
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
    _create_project(project_id, status="analyzing")
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


def test_job_state_and_logs_are_persisted():
    project_id = "jobs_test_persistence"
    _create_project(project_id)
    job = create_project_job(
        project_id,
        operation=JobOperation.analysis,
        project_status_before="uploaded",
    )[0]

    update_job(
        job.job_id,
        status=JobStatus.running,
        stage="transcribing",
        progress=0.4,
        message="Transcribing speech",
        log="Whisper started",
    )
    persisted = get_job(job.job_id)

    assert persisted is not None
    assert persisted.operation == JobOperation.analysis
    assert persisted.project_status_before == "uploaded"
    assert persisted.status == JobStatus.running
    assert persisted.progress == 0.4
    assert persisted.logs == ["Whisper started"]


def test_recovery_fails_interrupted_job_and_restores_project_status():
    project_id = "jobs_test_recovery"
    _create_project(project_id, status="analyzing")
    job = create_project_job(
        project_id,
        operation=JobOperation.analysis,
        project_status_before="uploaded",
    )[0]
    update_job(job.job_id, status=JobStatus.running, stage="transcribing")

    recovered = recover_interrupted_jobs()
    interrupted = get_job(job.job_id)
    with database.get_connection() as connection:
        project_status = connection.execute(
            "SELECT status FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()["status"]

    assert [item.job_id for item in recovered] == [job.job_id]
    assert interrupted is not None
    assert interrupted.status == JobStatus.failed
    assert interrupted.stage == "interrupted"
    assert interrupted.error == "Interrupted by app restart"
    assert interrupted.finished_at is not None
    assert project_status == "uploaded"


def test_recovery_finishes_requested_cancellation_without_failure():
    project_id = "jobs_test_cancel_recovery"
    _create_project(project_id, status="rendering")
    job = create_project_job(
        project_id,
        operation=JobOperation.render,
        project_status_before="ready",
    )[0]
    update_job(job.job_id, status=JobStatus.running, stage="rendering")
    cancel_job(job.job_id)

    recover_interrupted_jobs()
    cancelled = get_job(job.job_id)
    with database.get_connection() as connection:
        project_status = connection.execute(
            "SELECT status FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()["status"]

    assert cancelled is not None
    assert cancelled.status == JobStatus.cancelled
    assert cancelled.error is None
    assert project_status == "ready"


def test_job_log_history_is_bounded():
    project_id = "jobs_test_log_limit"
    _create_project(project_id)
    job = create_project_job(project_id)[0]

    for index in range(205):
        update_job(job.job_id, log=f"line {index}")

    persisted = get_job(job.job_id)

    assert persisted is not None
    assert len(persisted.logs) == 200
    assert persisted.logs[0] == "line 5"
    assert persisted.logs[-1] == "line 204"


def test_job_history_query_respects_limit():
    project_id = "jobs_test_history_limit"
    _create_project(project_id)
    job_ids: list[str] = []
    for _ in range(3):
        job = create_job(project_id)
        job_ids.append(job.job_id)
        update_job(job.job_id, status=JobStatus.done)

    recent = list_jobs(project_id, limit=2)

    assert [job.job_id for job in recent] == list(reversed(job_ids[-2:]))


def test_job_migration_adds_cancellation_flag_to_existing_table():
    with database.get_connection() as connection:
        connection.execute("DROP TABLE jobs")
        connection.execute(
            """
            CREATE TABLE jobs (
              job_id TEXT PRIMARY KEY,
              project_id TEXT,
              operation TEXT NOT NULL DEFAULT 'generic',
              project_status_before TEXT,
              status TEXT NOT NULL,
              stage TEXT NOT NULL,
              progress REAL NOT NULL DEFAULT 0,
              message TEXT NOT NULL DEFAULT '',
              logs_json TEXT NOT NULL DEFAULT '[]',
              started_at TEXT NOT NULL,
              finished_at TEXT,
              error TEXT
            )
            """
        )

    database.init_db()

    with database.get_connection() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
        }
    assert "cancel_requested" in columns
