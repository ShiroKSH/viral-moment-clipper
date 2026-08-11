from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

from backend.core.utils import utc_now
from backend.db.database import get_connection
from backend.schemas.jobs import JobOperation, JobRecord, JobStatus


_TERMINAL_STATUSES = {JobStatus.done, JobStatus.failed, JobStatus.cancelled}
_INTERRUPTED_MESSAGE = "Interrupted by app restart"


def _decode_logs(payload: str | None) -> list[str]:
    try:
        logs = json.loads(payload or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(line) for line in logs] if isinstance(logs, list) else []


def _job_from_row(row: sqlite3.Row | None) -> JobRecord | None:
    if row is None:
        return None
    return JobRecord(
        job_id=row["job_id"],
        project_id=row["project_id"],
        operation=row["operation"],
        project_status_before=row["project_status_before"],
        status=row["status"],
        cancel_requested=bool(row["cancel_requested"]),
        stage=row["stage"],
        progress=row["progress"],
        message=row["message"],
        logs=_decode_logs(row["logs_json"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error=row["error"],
    )


def _new_job(
    project_id: str | None,
    operation: JobOperation,
    project_status_before: str | None,
) -> JobRecord:
    return JobRecord(
        job_id=uuid4().hex,
        project_id=project_id,
        operation=operation,
        project_status_before=project_status_before,
        started_at=utc_now(),
    )


def _insert_job(connection: sqlite3.Connection, job: JobRecord) -> None:
    connection.execute(
        """
        INSERT INTO jobs (
          job_id, project_id, operation, project_status_before, status, cancel_requested, stage,
          progress, message, logs_json, started_at, finished_at, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job.job_id,
            job.project_id,
            job.operation.value,
            job.project_status_before,
            job.status.value,
            int(job.cancel_requested),
            job.stage,
            job.progress,
            job.message,
            json.dumps(job.logs, ensure_ascii=False),
            job.started_at,
            job.finished_at,
            job.error,
        ),
    )


def create_job(
    project_id: str | None = None,
    *,
    operation: JobOperation = JobOperation.generic,
    project_status_before: str | None = None,
) -> JobRecord:
    job = _new_job(project_id, operation, project_status_before)
    with get_connection() as connection:
        _insert_job(connection, job)
    return job


def create_project_job(
    project_id: str,
    *,
    operation: JobOperation = JobOperation.generic,
    project_status_before: str | None = None,
) -> tuple[JobRecord, bool]:
    job = _new_job(project_id, operation, project_status_before)
    with get_connection() as connection:
        try:
            _insert_job(connection, job)
        except sqlite3.IntegrityError:
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE project_id = ? AND status IN ('queued', 'running')
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            active_job = _job_from_row(row)
            if active_job is None:
                raise
            return active_job, False
    return job, True


def get_job(job_id: str) -> JobRecord | None:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return _job_from_row(row)


def list_jobs(
    project_id: str | None = None,
    *,
    active_only: bool = False,
    limit: int = 100,
) -> list[JobRecord]:
    clauses: list[str] = []
    parameters: list[str | int] = []
    if project_id is not None:
        clauses.append("project_id = ?")
        parameters.append(project_id)
    if active_only:
        clauses.append("status IN ('queued', 'running')")
    query = "SELECT * FROM jobs"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY started_at DESC LIMIT ?"
    parameters.append(max(1, min(500, limit)))
    with get_connection() as connection:
        rows = connection.execute(query, parameters).fetchall()
    jobs: list[JobRecord] = []
    for row in rows:
        job = _job_from_row(row)
        if job is not None:
            jobs.append(job)
    return jobs


def latest_project_job(project_id: str, *, active_only: bool = False) -> JobRecord | None:
    jobs = list_jobs(project_id, active_only=active_only, limit=1)
    return jobs[0] if jobs else None


def get_active_project_job(project_id: str) -> JobRecord | None:
    return latest_project_job(project_id, active_only=True)


def update_job(
    job_id: str,
    *,
    status: JobStatus | None = None,
    stage: str | None = None,
    progress: float | None = None,
    message: str | None = None,
    log: str | None = None,
    error: str | None = None,
) -> JobRecord:
    with get_connection() as connection:
        current = _job_from_row(
            connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        )
        if current is None:
            raise KeyError(job_id)
        if current.status in _TERMINAL_STATUSES:
            return current
        if current.cancel_requested:
            if status in _TERMINAL_STATUSES:
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'cancelled', stage = 'cancelled', message = 'Cancelled',
                        finished_at = ?
                    WHERE job_id = ? AND status IN ('queued', 'running')
                    """,
                    (utc_now(), job_id),
                )
                cancelled = _job_from_row(
                    connection.execute(
                        "SELECT * FROM jobs WHERE job_id = ?",
                        (job_id,),
                    ).fetchone()
                )
                if cancelled is None:
                    raise KeyError(job_id)
                return cancelled
            return current

        next_status = status or current.status
        next_logs = current.logs
        if log:
            next_logs = [*next_logs, log][-200:]
        finished_at = utc_now() if next_status in _TERMINAL_STATUSES else current.finished_at
        connection.execute(
            """
            UPDATE jobs
            SET status = ?, stage = ?, progress = ?, message = ?, logs_json = ?,
                finished_at = ?, error = ?
            WHERE job_id = ? AND status IN ('queued', 'running')
            """,
            (
                next_status.value,
                stage if stage is not None else current.stage,
                max(0.0, min(1.0, progress)) if progress is not None else current.progress,
                message if message is not None else current.message,
                json.dumps(next_logs, ensure_ascii=False),
                finished_at,
                error if error is not None else current.error,
                job_id,
            ),
        )
        updated = _job_from_row(
            connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        )
    if updated is None:
        raise KeyError(job_id)
    return updated


def cancel_job(job_id: str) -> JobRecord | None:
    with get_connection() as connection:
        requested_at = utc_now()
        connection.execute(
            """
            UPDATE jobs
            SET cancel_requested = 1,
                status = CASE WHEN status = 'queued' THEN 'cancelled' ELSE status END,
                stage = CASE WHEN status = 'queued' THEN 'cancelled' ELSE 'cancelling' END,
                message = CASE
                  WHEN status = 'queued' THEN 'Cancelled'
                  ELSE 'Cancelling after current step'
                END,
                finished_at = CASE WHEN status = 'queued' THEN ? ELSE finished_at END
            WHERE job_id = ?
              AND status IN ('queued', 'running')
              AND cancel_requested = 0
            """,
            (requested_at, job_id),
        )
        job = _job_from_row(
            connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        )
    return job


def is_job_cancelled(job_id: str) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT status, cancel_requested FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    return bool(
        row
        and (
            row["status"] == JobStatus.cancelled.value
            or bool(row["cancel_requested"])
        )
    )


def acknowledge_job_cancelled(job_id: str) -> JobRecord | None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE jobs
            SET status = 'cancelled', stage = 'cancelled', message = 'Cancelled', finished_at = ?
            WHERE job_id = ?
              AND status = 'running'
              AND cancel_requested = 1
            """,
            (utc_now(), job_id),
        )
        job = _job_from_row(
            connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        )
    return job


def _fallback_project_status(connection: sqlite3.Connection, project_id: str) -> str | None:
    row = connection.execute(
        """
        SELECT projects.source_path,
               EXISTS (SELECT 1 FROM clips WHERE clips.project_id = projects.id) AS has_clips,
               EXISTS (
                 SELECT 1 FROM clips
                 WHERE clips.project_id = projects.id AND clips.rendered = 1
               ) AS has_rendered_clips
        FROM projects
        WHERE projects.id = ?
        """,
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    if row["has_rendered_clips"]:
        return "rendered"
    if row["has_clips"]:
        return "ready"
    return "uploaded" if row["source_path"] else "created"


def recover_interrupted_jobs() -> list[JobRecord]:
    recovered_ids: list[str] = []
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM jobs WHERE status IN ('queued', 'running') ORDER BY started_at"
        ).fetchall()
        for row in rows:
            job = _job_from_row(row)
            if job is None:
                continue
            recovered_ids.append(job.job_id)
            if job.project_id:
                previous_status = job.project_status_before or _fallback_project_status(
                    connection,
                    job.project_id,
                )
                if previous_status:
                    connection.execute(
                        """
                        UPDATE projects SET status = ?
                        WHERE id = ? AND status IN ('analyzing', 'rendering')
                        """,
                        (previous_status, job.project_id),
                    )
            if job.cancel_requested:
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'cancelled', stage = 'cancelled', message = 'Cancelled',
                        finished_at = ?
                    WHERE job_id = ? AND status IN ('queued', 'running')
                    """,
                    (utc_now(), job.job_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'failed', stage = 'interrupted', message = ?, error = ?,
                        finished_at = ?
                    WHERE job_id = ? AND status IN ('queued', 'running')
                    """,
                    (_INTERRUPTED_MESSAGE, _INTERRUPTED_MESSAGE, utc_now(), job.job_id),
                )
        recovered: list[JobRecord] = []
        for job_id in recovered_ids:
            job = _job_from_row(
                connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            )
            if job is not None:
                recovered.append(job)
    return recovered
