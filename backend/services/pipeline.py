from __future__ import annotations

from pathlib import Path

from backend.core.config import load_config
from backend.core.errors import AppError
from backend.core.utils import read_json, write_json
from backend.schemas.clips import ClipCandidate
from backend.schemas.feedback import FeedbackRequest
from backend.schemas.jobs import JobStatus
from backend.schemas.transcript import Transcript
from backend.services import project_store
from backend.services.audio_extract import extract_wav
from backend.services.branding import generate_badge
from backend.services.captions import write_caption_file
from backend.services.clip_boundary import choose_clip_boundary
from backend.services.edit_planner import build_edit_plan
from backend.services.jobs import update_job
from backend.services.learning.feedback_store import store_feedback
from backend.services.learning.personal_ranker import apply_personal_ranking
from backend.services.renderer import render_clip
from backend.services.semantic_analyzer import find_interesting_moments
from backend.services.sentence_segmenter import segment_transcript
from backend.services.subtitles import write_ass, write_clip_srt
from backend.services.transcript_postprocess import save_transcript
from backend.services.transcription import transcribe_audio


def run_analysis(project_id: str, job_id: str) -> None:
    config = load_config()
    project = project_store.get_project(project_id)
    source_path = project_store.project_source_path(project_id)
    if not project or not source_path:
        update_job(job_id, status=JobStatus.failed, stage="failed", error="Project has no uploaded video")
        return
    try:
        update_job(job_id, status=JobStatus.running, stage="extracting_audio", progress=0.12, message="Extracting WAV")
        output_dir = Path(project.output_dir)
        audio_path = output_dir / "source" / "audio_16k_mono.wav"
        extract_wav(source_path, audio_path, config)

        update_job(job_id, stage="transcribing", progress=0.28, message="Transcribing speech")
        duration = project.video.duration if project.video else 0
        transcript = transcribe_audio(audio_path, config, duration=duration)
        transcript_json = output_dir / "source" / "transcript_full.json"
        transcript_srt = output_dir / "source" / "transcript_full.srt"
        save_transcript(transcript, transcript_json, transcript_srt)
        project_store.save_transcript_record(project_id, transcript.language, transcript.duration, transcript_json, transcript_srt)

        update_job(job_id, stage="segmenting", progress=0.48, message="Segmenting transcript")
        sentences = segment_transcript(transcript)

        update_job(job_id, stage="semantic_analyzing", progress=0.62, message="Finding potentially interesting moments")
        moments = find_interesting_moments(sentences, config)
        moments = apply_personal_ranking(moments, config)
        if not moments:
            raise AppError("No interesting moments found")

        update_job(job_id, stage="planning_edits", progress=0.78, message="Building clip candidates")
        project_store.clear_analysis(project_id)
        clips: list[ClipCandidate] = []
        project_suffix = project_id[:8]
        for index, moment in enumerate(moments, start=1):
            moment.id = f"{moment.id}_{project_suffix}"
            start, end = choose_clip_boundary(moment, transcript, config)
            clip = ClipCandidate(
                id=f"clip_{index:03}_{project_suffix}",
                moment_id=moment.id,
                start=start,
                end=end,
                duration=round(end - start, 2),
                selected=True,
                final_score=moment.final_score,
                base_score=moment.base_score,
                personal_score=moment.personal_score,
                moment_type=moment.moment_type,
                hook_text=moment.hook_text,
                summary=moment.summary,
                reason=moment.reason,
                problems=moment.problems,
                text=moment.text,
                suggested_title=moment.suggested_title,
                suggested_caption=moment.suggested_caption,
                edit_profile=config.dynamic_edit.profile,
            )
            edit_plan = build_edit_plan(clip, config)
            project_store.save_moment(project_id, moment)
            project_store.save_clip(project_id, clip, edit_plan)
            clips.append(clip)

        write_json(output_dir / "source" / "analysis_report.json", {"moments": [moment.model_dump() for moment in moments], "clips": [clip.model_dump() for clip in clips]})
        project_store.set_project_status(project_id, "ready")
        update_job(job_id, status=JobStatus.done, stage="ready", progress=1, message="Analysis ready", log=f"Created {len(clips)} candidates")
    except Exception as exc:
        project_store.set_project_status(project_id, "analysis_failed")
        update_job(job_id, status=JobStatus.failed, stage="failed", error=str(exc), message="Analysis failed")


def _load_transcript(project_id: str) -> Transcript:
    paths = project_store.latest_transcript_paths(project_id)
    if not paths:
        raise AppError("Transcript not found. Run analysis first.")
    payload = read_json(paths[0])
    return Transcript.model_validate(payload)


def run_render(project_id: str, job_id: str, clip_ids: list[str] | None = None) -> None:
    config = load_config()
    project = project_store.get_project(project_id)
    source_path = project_store.project_source_path(project_id)
    if not project or not source_path:
        update_job(job_id, status=JobStatus.failed, stage="failed", error="Project has no uploaded video")
        return
    try:
        update_job(job_id, status=JobStatus.running, stage="rendering", progress=0.05, message="Preparing render")
        transcript = _load_transcript(project_id)
        output_dir = Path(project.output_dir)
        clips = project_store.list_clips(project_id)
        if clip_ids:
            clips = [clip for clip in clips if clip.id in set(clip_ids)]
        else:
            clips = [clip for clip in clips if clip.selected]
        if not clips:
            raise AppError("No selected clips to render")
        badge_path = generate_badge(output_dir / "metadata" / "badge.png", config)
        total = len(clips)
        for index, clip in enumerate(clips, start=1):
            update_job(job_id, stage="rendering", progress=0.05 + (index - 1) / total * 0.9, message=f"Rendering {clip.id}", log=f"Rendering {clip.id}")
            score = int(round(clip.final_score))
            output_path = output_dir / "clips" / f"{clip.id}_score_{score}.mp4"
            srt_path = output_dir / "subtitles" / f"{clip.id}.srt"
            ass_path = output_dir / "subtitles" / f"{clip.id}.ass"
            metadata_path = output_dir / "metadata" / f"{clip.id}.json"
            edit_plan_path = output_dir / "metadata" / f"{clip.id}_edit_plan.json"
            caption_path = output_dir / "metadata" / f"{clip.id}_caption.txt"
            render_ass_path: Path | None = None
            if config.subtitles.enabled:
                write_clip_srt(transcript, clip.start, clip.end, srt_path, max_words=config.subtitles.max_words_per_line)
                write_ass(
                    transcript,
                    clip.start,
                    clip.end,
                    ass_path,
                    font_size=config.subtitles.font_size,
                    max_words=config.subtitles.max_words_per_line,
                    width=config.render.width,
                    height=config.render.height,
                    safe_bottom_margin_px=config.subtitles.safe_bottom_margin_px,
                )
                render_ass_path = ass_path
            edit_plan = build_edit_plan(clip, config, profile=clip.edit_profile)
            write_json(edit_plan_path, edit_plan.model_dump())
            write_caption_file(clip, caption_path)
            write_json(metadata_path, {"clip": clip.model_dump(), "caption_path": str(caption_path), "edit_plan_path": str(edit_plan_path)})
            render_clip(source_path, output_path, clip, edit_plan, config, ass_path=render_ass_path, badge_path=badge_path)
            project_store.mark_clip_rendered(project_id, clip.id, output_path, srt_path, ass_path, edit_plan_path, metadata_path)
            store_feedback(project_id, clip.id, clip.moment_id, FeedbackRequest(action="rendered"))
        project_store.set_project_status(project_id, "rendered")
        update_job(job_id, status=JobStatus.done, stage="done", progress=1, message="Render complete")
    except Exception as exc:
        update_job(job_id, status=JobStatus.failed, stage="failed", error=str(exc), message="Render failed")
