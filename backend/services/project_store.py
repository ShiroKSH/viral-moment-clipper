from __future__ import annotations

import json
from pathlib import Path
import shutil
from uuid import uuid4

from backend.core.config import Settings
from backend.core.errors import AppError
from backend.core.paths import project_output_dir, resolve_project_path
from backend.core.utils import utc_now
from backend.db.database import get_connection, row_to_dict, rows_to_dicts
from backend.schemas.clips import ClipCandidate
from backend.schemas.moments import InterestingMoment
from backend.schemas.render import EditPlan
from backend.schemas.video import Project, ProjectCreate, VideoMetadata
from backend.services.content_quality import repair_mojibake
from backend.services.video_probe import metadata_json, playable_duration


def create_project(payload: ProjectCreate, config: Settings) -> Project:
    project_id = uuid4().hex
    output_dir = project_output_dir(config, payload.name, project_id, payload.output_dir)
    created_at = utc_now()
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO projects (id, name, author_handle, source_path, output_dir, created_at, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, payload.name, payload.author_handle, None, str(output_dir), created_at, "created"),
        )
    return Project(id=project_id, name=payload.name, author_handle=payload.author_handle, output_dir=str(output_dir), created_at=created_at, last_activity_at=created_at, status="created")


def _video_from_row(video_row: dict | None) -> VideoMetadata | None:
    if not video_row:
        return None
    stored_metadata = json.loads(video_row["metadata_json"])
    raw_metadata = stored_metadata.get("raw", {}) if isinstance(stored_metadata, dict) else {}
    return VideoMetadata(
        duration=playable_duration(raw_metadata) or video_row["duration"] or 0,
        width=video_row["width"] or 0,
        height=video_row["height"] or 0,
        fps=video_row["fps"] or 0,
        video_codec=video_row["video_codec"] or "",
        audio_codec=video_row["audio_codec"] or "",
        raw=raw_metadata,
    )


def _project_from_row(row: dict, video: VideoMetadata | None = None) -> Project:
    source_path = row.get("source_path")
    uploaded_at = row.get("uploaded_at")
    analyzed_at = row.get("analyzed_at")
    rendered_at = row.get("rendered_at")
    last_activity_at = max([value for value in (row["created_at"], uploaded_at, analyzed_at, rendered_at, row.get("feedback_at")) if value], default=row["created_at"])
    return Project(
        id=row["id"],
        name=row["name"],
        author_handle=row.get("author_handle") or "",
        source_path=source_path,
        output_dir=row["output_dir"],
        created_at=row["created_at"],
        uploaded_at=uploaded_at,
        analyzed_at=analyzed_at,
        rendered_at=rendered_at,
        last_activity_at=last_activity_at,
        status=row["status"],
        video=video,
    )


PROJECT_ACTIVITY_SELECT = """
SELECT projects.*,
       (
         SELECT COALESCE(source_videos.uploaded_at, projects.created_at)
         FROM source_videos
         WHERE source_videos.project_id = projects.id
         ORDER BY rowid DESC
         LIMIT 1
       ) AS uploaded_at,
       (
         SELECT transcripts.created_at
         FROM transcripts
         WHERE transcripts.project_id = projects.id
         ORDER BY transcripts.created_at DESC
         LIMIT 1
       ) AS analyzed_at,
       (
         SELECT feedback.created_at
         FROM feedback
         WHERE feedback.project_id = projects.id
           AND feedback.action = 'rendered'
         ORDER BY feedback.created_at DESC
         LIMIT 1
       ) AS rendered_at,
       (
         SELECT feedback.created_at
         FROM feedback
         WHERE feedback.project_id = projects.id
         ORDER BY feedback.created_at DESC
         LIMIT 1
       ) AS feedback_at
FROM projects
"""


def get_project(project_id: str) -> Project | None:
    with get_connection() as connection:
        project_row = row_to_dict(connection.execute(PROJECT_ACTIVITY_SELECT + " WHERE projects.id = ?", (project_id,)).fetchone())
        if not project_row:
            return None
        video_row = row_to_dict(connection.execute("SELECT * FROM source_videos WHERE project_id = ? ORDER BY rowid DESC LIMIT 1", (project_id,)).fetchone())
    return _project_from_row(project_row, video=_video_from_row(video_row))


def list_projects() -> list[Project]:
    with get_connection() as connection:
        rows = rows_to_dicts(
            connection.execute(
                PROJECT_ACTIVITY_SELECT
                + """
                ORDER BY max(
                  COALESCE(rendered_at, ''),
                  COALESCE(analyzed_at, ''),
                  COALESCE(uploaded_at, ''),
                  COALESCE(feedback_at, ''),
                  projects.created_at
                ) DESC
                """
            ).fetchall()
        )
        project_ids = [row["id"] for row in rows]
        video_by_project: dict[str, VideoMetadata] = {}
        if project_ids:
            placeholders = ",".join("?" for _ in project_ids)
            video_rows = rows_to_dicts(
                connection.execute(f"SELECT * FROM source_videos WHERE project_id IN ({placeholders}) ORDER BY rowid DESC", project_ids).fetchall()
            )
            for video_row in video_rows:
                project_id = video_row["project_id"]
                if project_id not in video_by_project:
                    video = _video_from_row(video_row)
                    if video:
                        video_by_project[project_id] = video
    return [_project_from_row(row, video=video_by_project.get(row["id"])) for row in rows]


def _safe_remove_project_output(output_dir: str, config: Settings) -> None:
    base_dir = resolve_project_path(config.paths.output_dir)
    target = resolve_project_path(output_dir)
    if target == base_dir or base_dir not in target.parents:
        raise AppError(f"Refusing to delete project files outside output dir: {target}")
    if target.exists():
        shutil.rmtree(target)


def delete_project(
    project_id: str,
    config: Settings,
    *,
    remove_files: bool = True,
    reconcile_learning: bool = True,
) -> Project | None:
    project = get_project(project_id)
    if not project:
        return None
    if remove_files:
        _safe_remove_project_output(project.output_dir, config)
    with get_connection() as connection:
        connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    if reconcile_learning:
        try:
            from backend.services.learning.training import train_personal_ranker

            train_personal_ranker(config)
        except Exception:
            pass
    return project


def delete_projects_except(keep_project_id: str, config: Settings, *, remove_files: bool = True) -> list[Project]:
    if not get_project(keep_project_id):
        raise AppError("Project to keep not found")
    deleted: list[Project] = []
    for project in list_projects():
        if project.id == keep_project_id:
            continue
        removed = delete_project(project.id, config, remove_files=remove_files, reconcile_learning=False)
        if removed:
            deleted.append(removed)
    if deleted:
        try:
            from backend.services.learning.training import train_personal_ranker

            train_personal_ranker(config)
        except Exception:
            pass
    return deleted


def attach_video(project_id: str, source_path: Path, metadata: VideoMetadata) -> None:
    uploaded_at = utc_now()
    with get_connection() as connection:
        connection.execute("UPDATE projects SET source_path = ?, status = ? WHERE id = ?", (str(source_path), "uploaded", project_id))
        connection.execute("DELETE FROM source_videos WHERE project_id = ?", (project_id,))
        connection.execute(
            """
            INSERT INTO source_videos (id, project_id, path, uploaded_at, duration, width, height, fps, video_codec, audio_codec, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                project_id,
                str(source_path),
                uploaded_at,
                metadata.duration,
                metadata.width,
                metadata.height,
                metadata.fps,
                metadata.video_codec,
                metadata.audio_codec,
                metadata_json(metadata),
            ),
        )


def set_project_status(project_id: str, status: str) -> None:
    with get_connection() as connection:
        connection.execute("UPDATE projects SET status = ? WHERE id = ?", (status, project_id))


def save_transcript_record(project_id: str, language: str, duration: float, json_path: Path, srt_path: Path) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM transcripts WHERE project_id = ?", (project_id,))
        connection.execute(
            "INSERT INTO transcripts (id, project_id, language, duration, transcript_json_path, srt_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uuid4().hex, project_id, language, duration, str(json_path), str(srt_path), utc_now()),
        )


def clear_analysis(project_id: str) -> None:
    with get_connection() as connection:
        _clear_analysis(connection, project_id)


def _clear_analysis(connection, project_id: str) -> None:
    connection.execute("DELETE FROM edit_plans WHERE project_id = ?", (project_id,))
    connection.execute("DELETE FROM clips WHERE project_id = ?", (project_id,))
    connection.execute(
        """
        DELETE FROM moments
        WHERE project_id = ?
          AND id NOT IN (
            SELECT DISTINCT moment_id
            FROM feedback
            WHERE project_id = ? AND moment_id IS NOT NULL
          )
        """,
        (project_id, project_id),
    )


def replace_analysis(
    project_id: str,
    entries: list[tuple[InterestingMoment, ClipCandidate, EditPlan]],
) -> None:
    """Replace one analysis generation in a single SQLite transaction."""
    with get_connection() as connection:
        _clear_analysis(connection, project_id)
        for moment, clip, edit_plan in entries:
            moment.text = repair_mojibake(moment.text)
            moment.summary = repair_mojibake(moment.summary)
            moment.hook_text = repair_mojibake(moment.hook_text)
            moment.payoff_text = repair_mojibake(moment.payoff_text)
            moment.suggested_title = repair_mojibake(moment.suggested_title)
            moment.suggested_caption = repair_mojibake(moment.suggested_caption)
            payload = moment.model_dump()
            connection.execute(
                """
                INSERT OR REPLACE INTO moments (
                  id, project_id, start, end, duration, text, summary, moment_type, hook_text, payoff_text,
                  semantic_interest_score, hook_score, clarity_score, emotion_score, novelty_score, standalone_score,
                  retention_score, speech_density_score, audio_energy_score, visual_energy_score,
                  base_score, personal_score, final_score, reason, problems_json, suggested_title, suggested_caption, source_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    moment.id, project_id, moment.start, moment.end, moment.duration,
                    moment.text, moment.summary, moment.moment_type, moment.hook_text, moment.payoff_text,
                    moment.semantic_interest_score, moment.hook_score, moment.clarity_score, moment.emotion_score,
                    moment.novelty_score, moment.standalone_score, moment.retention_score,
                    moment.speech_density_score, moment.audio_energy_score, moment.visual_energy_score,
                    moment.base_score, moment.personal_score, moment.final_score, moment.reason,
                    json.dumps(moment.problems, ensure_ascii=False), moment.suggested_title,
                    moment.suggested_caption, json.dumps(payload, ensure_ascii=False),
                ),
            )
            connection.execute(
                """
                INSERT INTO clips (id, project_id, moment_id, start, end, duration, selected, rendered, output_path, metadata_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clip.id, project_id, clip.moment_id, clip.start, clip.end, clip.duration,
                    int(clip.selected), int(clip.rendered), clip.output_path, clip.metadata_path, utc_now(),
                ),
            )
            connection.execute(
                """
                INSERT INTO edit_plans (id, project_id, clip_id, profile, operations_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"plan_{clip.id}", project_id, clip.id, edit_plan.profile,
                    json.dumps(edit_plan.model_dump()["operations"], ensure_ascii=False), utc_now(),
                ),
            )


def save_moment(project_id: str, moment: InterestingMoment) -> None:
    moment.text = repair_mojibake(moment.text)
    moment.summary = repair_mojibake(moment.summary)
    moment.hook_text = repair_mojibake(moment.hook_text)
    moment.payoff_text = repair_mojibake(moment.payoff_text)
    moment.suggested_title = repair_mojibake(moment.suggested_title)
    moment.suggested_caption = repair_mojibake(moment.suggested_caption)
    payload = moment.model_dump()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO moments (
              id, project_id, start, end, duration, text, summary, moment_type, hook_text, payoff_text,
              semantic_interest_score, hook_score, clarity_score, emotion_score, novelty_score, standalone_score,
              retention_score, speech_density_score, audio_energy_score, visual_energy_score,
              base_score, personal_score, final_score, reason, problems_json, suggested_title, suggested_caption, source_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                moment.id,
                project_id,
                moment.start,
                moment.end,
                moment.duration,
                moment.text,
                moment.summary,
                moment.moment_type,
                moment.hook_text,
                moment.payoff_text,
                moment.semantic_interest_score,
                moment.hook_score,
                moment.clarity_score,
                moment.emotion_score,
                moment.novelty_score,
                moment.standalone_score,
                moment.retention_score,
                moment.speech_density_score,
                moment.audio_energy_score,
                moment.visual_energy_score,
                moment.base_score,
                moment.personal_score,
                moment.final_score,
                moment.reason,
                json.dumps(moment.problems, ensure_ascii=False),
                moment.suggested_title,
                moment.suggested_caption,
                json.dumps(payload, ensure_ascii=False),
            ),
        )


def get_moment(project_id: str, moment_id: str) -> InterestingMoment | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT source_json FROM moments WHERE id = ? AND project_id = ?",
            (moment_id, project_id),
        ).fetchone()
    if not row:
        return None
    return InterestingMoment.model_validate(json.loads(row["source_json"] or "{}"))


def save_clip(project_id: str, clip: ClipCandidate, edit_plan: EditPlan | None = None) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO clips (id, project_id, moment_id, start, end, duration, selected, rendered, output_path, metadata_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM clips WHERE id = ?), ?))
            """,
            (
                clip.id,
                project_id,
                clip.moment_id,
                clip.start,
                clip.end,
                clip.duration,
                int(clip.selected),
                int(clip.rendered),
                clip.output_path,
                clip.metadata_path,
                clip.id,
                utc_now(),
            ),
        )
        if edit_plan:
            connection.execute(
                "INSERT OR REPLACE INTO edit_plans (id, project_id, clip_id, profile, operations_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (f"plan_{clip.id}", project_id, clip.id, edit_plan.profile, json.dumps(edit_plan.model_dump()["operations"], ensure_ascii=False), utc_now()),
            )


def list_clips(project_id: str) -> list[ClipCandidate]:
    with get_connection() as connection:
        rows = rows_to_dicts(
            connection.execute(
                """
                SELECT clips.*, moments.final_score, moments.base_score, moments.personal_score, moments.moment_type, moments.hook_text,
                       moments.summary, moments.reason, moments.problems_json, moments.text, moments.suggested_title, moments.suggested_caption,
                       moments.source_json,
                       COALESCE(edit_plans.profile, 'balanced') AS edit_profile,
                       (
                         SELECT feedback.action
                         FROM feedback
                         WHERE feedback.project_id = clips.project_id
                           AND (feedback.clip_id = clips.id OR feedback.moment_id = clips.moment_id)
                         ORDER BY feedback.created_at DESC
                         LIMIT 1
                       ) AS latest_feedback_action,
                       (
                         SELECT feedback.action
                         FROM feedback
                         WHERE feedback.project_id = clips.project_id
                           AND (feedback.clip_id = clips.id OR feedback.moment_id = clips.moment_id)
                           AND feedback.action IN ('accept', 'reject')
                         ORDER BY feedback.created_at DESC
                         LIMIT 1
                       ) AS review_action,
                       EXISTS (
                         SELECT 1
                         FROM feedback
                         WHERE feedback.project_id = clips.project_id
                           AND (feedback.clip_id = clips.id OR feedback.moment_id = clips.moment_id)
                           AND feedback.action = 'edited'
                       ) AS boundaries_edited
                FROM clips
                JOIN moments ON moments.id = clips.moment_id
                LEFT JOIN edit_plans ON edit_plans.clip_id = clips.id
                WHERE clips.project_id = ?
                ORDER BY moments.final_score DESC
                """,
                (project_id,),
            ).fetchall()
        )
    clips: list[ClipCandidate] = []
    for row in rows:
        source_payload = json.loads(row["source_json"] or "{}")
        clips.append(
            ClipCandidate(
                id=row["id"],
                moment_id=row["moment_id"],
                start=row["start"],
                end=row["end"],
                duration=row["duration"],
                selected=bool(row["selected"]),
                rendered=bool(row["rendered"]),
                final_score=row["final_score"],
                base_score=row["base_score"],
                personal_score=row["personal_score"],
                speaker_count=source_payload.get("speaker_count", 0),
                speaker_switches=source_payload.get("speaker_switches", 0),
                dialogue_score=source_payload.get("dialogue_score", 0),
                moment_type=row["moment_type"],
                hook_text=repair_mojibake(row["hook_text"] or ""),
                summary=repair_mojibake(row["summary"] or ""),
                reason=repair_mojibake(row["reason"] or ""),
                problems=json.loads(row["problems_json"] or "[]"),
                text=repair_mojibake(row["text"] or ""),
                suggested_title=repair_mojibake(row["suggested_title"] or ""),
                suggested_caption=repair_mojibake(row["suggested_caption"] or ""),
                edit_profile=row["edit_profile"],
                latest_feedback_action=row["latest_feedback_action"],
                review_action=row["review_action"],
                boundaries_edited=bool(row["boundaries_edited"]),
                output_path=row["output_path"],
                metadata_path=row["metadata_path"],
            )
        )
    return clips


def get_clip(project_id: str, clip_id: str) -> ClipCandidate | None:
    return next((clip for clip in list_clips(project_id) if clip.id == clip_id), None)


def update_clip(project_id: str, clip_id: str, *, start: float | None = None, end: float | None = None, selected: bool | None = None, edit_profile: str | None = None) -> ClipCandidate | None:
    clip = get_clip(project_id, clip_id)
    if not clip:
        return None
    old_start, old_end = clip.start, clip.end
    if start is not None:
        clip.start = start
    if end is not None:
        clip.end = end
    clip.duration = round(max(0, clip.end - clip.start), 2)
    if selected is not None:
        clip.selected = selected
    if edit_profile is not None:
        clip.edit_profile = edit_profile
    with get_connection() as connection:
        connection.execute(
            "UPDATE clips SET start = ?, end = ?, duration = ?, selected = ? WHERE id = ? AND project_id = ?",
            (clip.start, clip.end, clip.duration, int(clip.selected), clip_id, project_id),
        )
        if edit_profile is not None:
            connection.execute("UPDATE edit_plans SET profile = ? WHERE clip_id = ? AND project_id = ?", (edit_profile, clip_id, project_id))
    return clip


def mark_clip_rendered(project_id: str, clip_id: str, output_path: Path, srt_path: Path, ass_path: Path, edit_plan_path: Path, metadata_path: Path) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE clips
            SET rendered = 1, output_path = ?, subtitle_srt_path = ?, subtitle_ass_path = ?, edit_plan_path = ?, metadata_path = ?
            WHERE id = ? AND project_id = ?
            """,
            (str(output_path), str(srt_path), str(ass_path), str(edit_plan_path), str(metadata_path), clip_id, project_id),
        )


def project_source_path(project_id: str) -> Path | None:
    with get_connection() as connection:
        row = connection.execute("SELECT source_path FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row or not row["source_path"]:
        return None
    return Path(row["source_path"])


def latest_transcript_paths(project_id: str) -> tuple[Path, Path] | None:
    with get_connection() as connection:
        row = connection.execute("SELECT transcript_json_path, srt_path FROM transcripts WHERE project_id = ? ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone()
    if not row:
        return None
    return Path(row["transcript_json_path"]), Path(row["srt_path"])
