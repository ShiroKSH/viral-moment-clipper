from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.core.config import load_config
from backend.core.errors import AppError
from backend.core.paths import safe_upload_name
from backend.schemas.render import RenderRequest
from backend.schemas.video import ProjectCreate
from backend.services import project_store
from backend.services.content_quality import repair_mojibake
from backend.services.jobs import create_job, get_active_project_job
from backend.services.pipeline import run_analysis, run_render
from backend.services.video_probe import probe_video

router = APIRouter(prefix="/api/projects", tags=["projects"])

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


class ProjectCleanupRequest(BaseModel):
    keep_project_id: str
    remove_files: bool = True


def _speaker_summary_from_payload(payload: dict) -> tuple[str, dict[str, int]]:
    speaker_counts: dict[str, int] = {}
    for segment in payload.get("segments", []):
        speaker = segment.get("speaker")
        if speaker:
            speaker_counts[speaker] = speaker_counts.get(speaker, 0) + 1
    if not speaker_counts:
        return "speakers=none", {}
    return "speakers=" + ", ".join(f"{speaker}:{count}" for speaker, count in sorted(speaker_counts.items())), speaker_counts


def _clip_speaker_metrics(payload: dict, start: float, end: float) -> dict:
    speakers: list[str] = []
    for segment in payload.get("segments", []):
        if segment.get("end", 0) < start or segment.get("start", 0) > end:
            continue
        speaker = segment.get("speaker")
        if speaker:
            speakers.append(speaker)
    unique = list(dict.fromkeys(speakers))
    switches = sum(1 for left, right in zip(speakers, speakers[1:]) if left != right)
    dialogue_score = 0.0
    if len(unique) >= 2:
        duration = max(1.0, end - start)
        dialogue_score = min(100.0, 42 + (len(unique) - 1) * 18 + min(28, switches / duration * 90))
    return {"speaker_count": len(unique), "speaker_switches": switches, "dialogue_score": round(dialogue_score, 2)}


@router.post("")
def create_project(payload: ProjectCreate) -> dict:
    return project_store.create_project(payload, load_config()).model_dump()


@router.get("")
def list_projects() -> list[dict]:
    return [project.model_dump() for project in project_store.list_projects()]


@router.post("/cleanup")
def cleanup_projects(payload: ProjectCleanupRequest) -> dict:
    try:
        deleted = project_store.delete_projects_except(payload.keep_project_id, load_config(), remove_files=payload.remove_files)
    except AppError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "deleted": [project.model_dump() for project in deleted],
        "projects": [project.model_dump() for project in project_store.list_projects()],
    }


@router.get("/{project_id}")
def get_project(project_id: str) -> dict:
    project = project_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.model_dump()


@router.delete("/{project_id}")
def delete_project(project_id: str, remove_files: bool = True) -> dict:
    try:
        project = project_store.delete_project(project_id, load_config(), remove_files=remove_files)
    except AppError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"deleted": project.model_dump()}


@router.post("/{project_id}/upload")
def upload_video(project_id: str, file: UploadFile = File(...)) -> dict:
    project = project_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    filename = safe_upload_name(file.filename or "video.mp4")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported video format")
    target = Path(project.output_dir) / "source" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    try:
        metadata = probe_video(target, load_config())
    except AppError as exc:
        project_store.set_project_status(project_id, "probe_failed")
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    project_store.attach_video(project_id, target, metadata)
    updated = project_store.get_project(project_id)
    return {"project": updated.model_dump() if updated else None, "video": metadata.model_dump()}


@router.post("/{project_id}/analyze")
def analyze_project(project_id: str, background_tasks: BackgroundTasks) -> dict:
    if not project_store.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    active_job = get_active_project_job(project_id)
    if active_job:
        return active_job.model_dump()
    job = create_job(project_id)
    background_tasks.add_task(run_analysis, project_id, job.job_id)
    return job.model_dump()


@router.get("/{project_id}/analysis")
def project_analysis(project_id: str) -> dict:
    project = project_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    transcript_preview = ""
    speaker_summary = "speakers=none"
    transcript_payload: dict | None = None
    transcript_paths = project_store.latest_transcript_paths(project_id)
    if transcript_paths and transcript_paths[0].exists():
        import json

        transcript_payload = json.loads(transcript_paths[0].read_text(encoding="utf-8"))
        transcript_preview = repair_mojibake(transcript_payload.get("text", ""))[:1200]
        speaker_summary, _ = _speaker_summary_from_payload(transcript_payload)
    clips = [clip.model_dump() for clip in project_store.list_clips(project_id)]
    if transcript_payload:
        for clip in clips:
            if not clip.get("speaker_count"):
                clip.update(_clip_speaker_metrics(transcript_payload, float(clip["start"]), float(clip["end"])))
    return {
        "project": project.model_dump(),
        "clips": clips,
        "transcript_preview": transcript_preview,
        "speaker_summary": speaker_summary,
    }


@router.post("/{project_id}/render")
def render_project(project_id: str, payload: RenderRequest, background_tasks: BackgroundTasks) -> dict:
    if not project_store.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    active_job = get_active_project_job(project_id)
    if active_job:
        return active_job.model_dump()
    job = create_job(project_id)
    background_tasks.add_task(run_render, project_id, job.job_id, payload.clip_ids)
    return job.model_dump()


@router.get("/{project_id}/open-output-folder")
def open_output_folder(project_id: str) -> dict:
    project = project_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    path = Path(project.output_dir)
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    return {"path": str(path)}
