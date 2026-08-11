from __future__ import annotations

import hashlib
from pathlib import Path

from backend.core.config import load_config
from backend.core.errors import AppError
from backend.core.ffmpeg import run_command
from backend.core.utils import read_json, write_json
from backend.schemas.clips import ClipCandidate
from backend.schemas.feedback import FeedbackRequest
from backend.schemas.jobs import JobStatus
from backend.schemas.transcript import Transcript
from backend.services import project_store
from backend.services.analysis_artifacts import archive_analysis_artifacts
from backend.services.audio_extract import audio_extraction_report_path, extract_wav, wav_duration
from backend.services.branding import generate_badge
from backend.services.candidate_selector import (
    CandidateInterval,
    calibrate_candidate_intervals,
    select_candidate_intervals,
)
from backend.services.captions import write_caption_file
from backend.services.clip_boundary import choose_clip_boundary
from backend.services.clip_context import refresh_clip_context
from backend.services.edit_planner import build_edit_plan
from backend.services.jobs import is_job_cancelled, update_job
from backend.services.learning.feedback_store import store_feedback
from backend.services.learning.personal_ranker import apply_personal_ranking
from backend.services.renderer import render_acceleration_summary, render_clip, verify_render_integrity
from backend.services.scene_detect import detect_scene_cuts
from backend.services.semantic_analyzer import find_interesting_moments
from backend.services.sentence_segmenter import segment_transcript
from backend.services.speaker_diarization import (
    assign_speakers,
    has_speaker_labels,
    inherit_speakers_from_reference,
    speaker_summary,
)
from backend.services.subtitles import clip_subtitle_segments, write_ass, write_clip_srt
from backend.services.transcript_postprocess import repair_transcript_text, save_transcript
from backend.services.transcription import is_synthetic_transcript, transcribe_audio


def _candidate_fingerprint(moment) -> str:
    normalized = " ".join(moment.text.lower().split())[:320]
    payload = f"{moment.start:.1f}|{moment.end:.1f}|{normalized}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:8]


def _restore_project_after_cancellation(job_id: str, project_id: str, previous_status: str) -> bool:
    if not is_job_cancelled(job_id):
        return False
    project_store.set_project_status(project_id, previous_status)
    return True


def _subtitle_tail_seconds(segments: list) -> float:
    return max((float(segment.end) for segment in segments), default=0.0)


def _subtitle_word_count(segments: list) -> int:
    return sum(max(len(segment.words), len(segment.text.split())) for segment in segments)


def _largest_internal_subtitle_gap(segments: list) -> float:
    ordered = sorted(segments, key=lambda segment: (segment.start, segment.end))
    return max(
        (max(0.0, float(current.start) - float(previous.end)) for previous, current in zip(ordered, ordered[1:])),
        default=0.0,
    )


def _needs_clip_subtitle_pass(segments: list, duration: float) -> bool:
    if duration < 8:
        return not segments
    if not segments:
        return True
    words = [word for segment in segments for word in segment.words]
    if any(float(word.end) - float(word.start) < 0.04 for word in words):
        return True
    if _subtitle_word_count(segments) / max(duration, 1.0) < 0.65:
        return True
    if _largest_internal_subtitle_gap(segments) > 4.0:
        return True
    probabilities = [float(word.probability) for word in words if word.probability is not None]
    if probabilities:
        low_confidence_ratio = sum(probability < 0.25 for probability in probabilities) / len(probabilities)
        if low_confidence_ratio > 0.10 or sum(probabilities) / len(probabilities) < 0.72:
            return True
    return _subtitle_tail_seconds(segments) < duration - 5


def _extract_clip_audio(source_path: Path, clip: ClipCandidate, output_path: Path, config) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            config.paths.ffmpeg_path,
            "-y",
            "-ss",
            f"{clip.start:.3f}",
            "-i",
            str(source_path),
            "-t",
            f"{clip.duration:.3f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(output_path),
        ],
        timeout=None,
    )
    return output_path


def _clip_subtitle_source(
    source_path: Path,
    output_dir: Path,
    clip: ClipCandidate,
    transcript: Transcript,
    config,
) -> tuple[Transcript, float, float] | None:
    full_segments = []
    if not is_synthetic_transcript(transcript):
        full_segments = clip_subtitle_segments(transcript, clip.start, clip.end, max_words=config.subtitles.max_words_per_line)
    if full_segments and not _needs_clip_subtitle_pass(full_segments, clip.duration):
        return transcript, clip.start, clip.end

    clip_transcript_path = output_dir / "subtitles" / f"{clip.id}_speech_transcript.json"
    if clip_transcript_path.exists():
        clip_transcript = Transcript.model_validate(read_json(clip_transcript_path))
        if repair_transcript_text(clip_transcript):
            write_json(clip_transcript_path, clip_transcript.model_dump())
        if config.speakers.enabled:
            clip_transcript = inherit_speakers_from_reference(clip_transcript, transcript, offset=clip.start)
            write_json(clip_transcript_path, clip_transcript.model_dump())
    else:
        audio_path = output_dir / "subtitles" / f"{clip.id}_speech.wav"
        _extract_clip_audio(source_path, clip, audio_path, config)
        clip_transcript = transcribe_audio(audio_path, config, duration=clip.duration)
        repair_transcript_text(clip_transcript)
        if config.speakers.enabled:
            clip_transcript = inherit_speakers_from_reference(clip_transcript, transcript, offset=clip.start)
        write_json(clip_transcript_path, clip_transcript.model_dump())

    if is_synthetic_transcript(clip_transcript):
        if full_segments:
            return transcript, clip.start, clip.end
        return None

    clip_segments = clip_subtitle_segments(clip_transcript, 0, clip.duration, max_words=config.subtitles.max_words_per_line)
    if not full_segments or _subtitle_tail_seconds(clip_segments) > _subtitle_tail_seconds(full_segments) + 2:
        return clip_transcript, 0, clip.duration
    return transcript, clip.start, clip.end


def run_analysis(project_id: str, job_id: str) -> None:
    config = load_config()
    project = project_store.get_project(project_id)
    source_path = project_store.project_source_path(project_id)
    if not project or not source_path:
        update_job(job_id, status=JobStatus.failed, stage="failed", error="Project has no uploaded video")
        return
    previous_status = project.status
    try:
        started_job = update_job(
            job_id,
            status=JobStatus.running,
            stage="extracting_audio",
            progress=0.12,
            message="Extracting WAV",
        )
        if started_job.status != JobStatus.running:
            return
        project_store.set_project_status(project_id, "analyzing")
        output_dir = Path(project.output_dir)
        audio_path = output_dir / "source" / "audio_16k_mono.wav"
        extract_wav(source_path, audio_path, config)
        if _restore_project_after_cancellation(job_id, project_id, previous_status):
            return
        extracted_duration = wav_duration(audio_path)
        extraction_report = read_json(audio_extraction_report_path(audio_path), fallback={})

        update_job(
            job_id,
            stage="transcribing",
            progress=0.28,
            message=f"Transcribing speech on {config.transcription.device}/{config.transcription.compute_type}",
            log=(
                f"Transcription target: {config.transcription.device}/{config.transcription.compute_type}, "
                f"require_gpu={config.transcription.require_gpu}, cpu_fallback={config.transcription.cpu_fallback}, "
                f"synthetic_fallback={config.transcription.allow_synthetic_fallback}; "
                f"audio={extracted_duration:.1f}s, extraction={extraction_report.get('mode', 'unknown')}"
            ),
        )
        duration = extracted_duration or (project.video.duration if project.video else 0)
        transcript = transcribe_audio(audio_path, config, duration=duration)
        if _restore_project_after_cancellation(job_id, project_id, previous_status):
            return
        update_job(job_id, stage="transcribing", progress=0.40, message=f"Transcribed with {transcript.engine}", log=f"Transcription engine: {transcript.engine}")
        if config.speakers.enabled:
            update_job(
                job_id,
                stage="speaker_labeling",
                progress=0.44,
                message="Assigning speaker colors",
                log=f"Speaker assignment: {config.speakers.embedding_backend} embeddings with local clustering fallback",
            )
            transcript = assign_speakers(audio_path, transcript, config)
            if _restore_project_after_cancellation(job_id, project_id, previous_status):
                return
            update_job(job_id, stage="speaker_labeling", progress=0.46, message=speaker_summary(transcript), log=speaker_summary(transcript))
        transcript_json = output_dir / "source" / "transcript_full.json"
        transcript_srt = output_dir / "source" / "transcript_full.srt"
        save_transcript(transcript, transcript_json, transcript_srt)
        project_store.save_transcript_record(project_id, transcript.language, transcript.duration, transcript_json, transcript_srt)

        update_job(job_id, stage="segmenting", progress=0.48, message="Segmenting transcript")
        sentences = segment_transcript(transcript)

        source_scene_cuts: list[float] = []
        if config.dynamic_edit.enabled and config.dynamic_edit.scene_detection_enabled:
            update_job(job_id, stage="visual_analyzing", progress=0.55, message="Measuring source shot rhythm")
            source_scene_cuts = detect_scene_cuts(
                source_path,
                ffmpeg_path=config.paths.ffmpeg_path,
                start=0,
                duration=transcript.duration,
                threshold=config.dynamic_edit.scene_threshold,
                hwaccel=config.render.hwaccel,
            )
            if _restore_project_after_cancellation(job_id, project_id, previous_status):
                return

        update_job(
            job_id,
            stage="semantic_analyzing",
            progress=0.62,
            message="Finding complete high-retention moments",
            log=f"Source rhythm: {len(source_scene_cuts)} shot changes",
        )
        moments = find_interesting_moments(sentences, config, scene_cuts=source_scene_cuts)
        if _restore_project_after_cancellation(job_id, project_id, previous_status):
            return
        if not moments:
            raise AppError("No interesting moments found")

        update_job(job_id, stage="planning_edits", progress=0.78, message="Building clip candidates")
        candidate_pool = [
            CandidateInterval(moment=moment, start=start, end=end)
            for moment in moments
            for start, end in [choose_clip_boundary(moment, transcript, config)]
        ]
        calibrate_candidate_intervals(candidate_pool, sentences, source_scene_cuts)
        project_suffix = project_id[:8]
        for candidate in candidate_pool:
            candidate.moment.id = f"moment_{_candidate_fingerprint(candidate.moment)}_{project_suffix}"
        apply_personal_ranking([candidate.moment for candidate in candidate_pool], config)
        selected_candidates, selection_audit = select_candidate_intervals(candidate_pool, sentences, config)
        if not selected_candidates:
            raise AppError("No candidates passed the content quality gate")

        clips: list[ClipCandidate] = []
        selected_moments = []
        analysis_entries = []
        for index, candidate in enumerate(selected_candidates, start=1):
            moment = candidate.moment
            fingerprint = _candidate_fingerprint(moment)
            start, end = candidate.start, candidate.end
            clip = ClipCandidate(
                id=f"clip_{index:02}_{fingerprint}_{project_suffix}",
                moment_id=moment.id,
                start=start,
                end=end,
                duration=round(end - start, 2),
                selected=True,
                final_score=moment.final_score,
                base_score=moment.base_score,
                personal_score=moment.personal_score,
                speaker_count=moment.speaker_count,
                speaker_switches=moment.speaker_switches,
                dialogue_score=moment.dialogue_score,
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
            edit_plan = build_edit_plan(clip, config, transcript=transcript)
            clips.append(clip)
            selected_moments.append(moment)
            analysis_entries.append((moment, clip, edit_plan))

        if _restore_project_after_cancellation(job_id, project_id, previous_status):
            return
        previous_clip_ids = [previous.id for previous in project_store.list_clips(project_id)]
        archive_result = archive_analysis_artifacts(output_dir, previous_clip_ids)
        if archive_result.archive_dir:
            selection_audit["previous_generation_archive"] = str(archive_result.archive_dir)
            update_job(
                job_id,
                stage="planning_edits",
                message="Archived previous analysis generation",
                log=f"Archived {len(archive_result.moved_files)} previous artifacts",
            )
        if archive_result.warnings:
            selection_audit["archive_warnings"] = archive_result.warnings
            update_job(job_id, log="; ".join(archive_result.warnings))

        write_json(output_dir / "source" / "candidate_selection.json", selection_audit)
        write_json(
            output_dir / "source" / "analysis_report.json",
            {
                "policy_version": "content_arc_v2",
                "scene_cut_count": len(source_scene_cuts),
                "candidate_pool": [candidate.moment.model_dump() for candidate in candidate_pool],
                "moments": [moment.model_dump() for moment in selected_moments],
                "clips": [clip.model_dump() for clip in clips],
                "selection_audit_path": str(output_dir / "source" / "candidate_selection.json"),
            },
        )
        project_store.replace_analysis(project_id, analysis_entries)
        project_store.set_project_status(project_id, "ready")
        update_job(job_id, status=JobStatus.done, stage="ready", progress=1, message="Analysis ready", log=f"Created {len(clips)} candidates")
    except Exception as exc:
        if _restore_project_after_cancellation(job_id, project_id, previous_status):
            return
        project_store.set_project_status(project_id, "analysis_failed")
        update_job(job_id, status=JobStatus.failed, stage="failed", error=str(exc), message="Analysis failed")


def _load_transcript(project_id: str) -> Transcript:
    paths = project_store.latest_transcript_paths(project_id)
    if not paths:
        raise AppError("Transcript not found. Run analysis first.")
    payload = read_json(paths[0])
    transcript = Transcript.model_validate(payload)
    if repair_transcript_text(transcript):
        save_transcript(transcript, paths[0], paths[1])
    return transcript


def _speaker_ready_transcript(project_id: str, project_output_dir: Path, config) -> Transcript:
    transcript = _load_transcript(project_id)
    if not config.speakers.enabled or has_speaker_labels(transcript):
        return transcript
    audio_path = project_output_dir / "source" / "audio_16k_mono.wav"
    if not audio_path.exists():
        return transcript
    transcript = assign_speakers(audio_path, transcript, config)
    paths = project_store.latest_transcript_paths(project_id)
    if paths:
        save_transcript(transcript, paths[0], paths[1])
    return transcript


def run_render(project_id: str, job_id: str, clip_ids: list[str] | None = None) -> None:
    config = load_config()
    project = project_store.get_project(project_id)
    source_path = project_store.project_source_path(project_id)
    if not project or not source_path:
        update_job(job_id, status=JobStatus.failed, stage="failed", error="Project has no uploaded video")
        return
    previous_status = project.status
    try:
        started_job = update_job(
            job_id,
            status=JobStatus.running,
            stage="rendering",
            progress=0.05,
            message="Preparing render",
        )
        if started_job.status != JobStatus.running:
            return
        project_store.set_project_status(project_id, "rendering")
        output_dir = Path(project.output_dir)
        transcript = _speaker_ready_transcript(project_id, output_dir, config)
        extracted_audio_path = output_dir / "source" / "audio_16k_mono.wav"
        extraction_report = read_json(audio_extraction_report_path(extracted_audio_path), fallback={})
        recovery_audio_path = (
            extracted_audio_path
            if extracted_audio_path.exists() and extraction_report.get("mode") not in {None, "normal"}
            else None
        )
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
            if _restore_project_after_cancellation(job_id, project_id, previous_status):
                return
            clip = refresh_clip_context(clip, transcript)
            update_job(job_id, stage="rendering", progress=0.05 + (index - 1) / total * 0.9, message=f"Rendering {clip.id}", log=f"Rendering {clip.id}")
            score = int(round(clip.final_score))
            output_path = output_dir / "clips" / f"{clip.id}_score_{score}.mp4"
            srt_path = output_dir / "subtitles" / f"{clip.id}.srt"
            ass_path = output_dir / "subtitles" / f"{clip.id}.ass"
            metadata_path = output_dir / "metadata" / f"{clip.id}.json"
            edit_plan_path = output_dir / "metadata" / f"{clip.id}_edit_plan.json"
            integrity_path = output_dir / "metadata" / f"{clip.id}_render_integrity.json"
            caption_path = output_dir / "metadata" / f"{clip.id}_caption.txt"
            render_ass_path: Path | None = None
            if config.subtitles.enabled:
                subtitle_source = _clip_subtitle_source(source_path, output_dir, clip, transcript, config)
            else:
                subtitle_source = None
            if subtitle_source:
                subtitle_transcript, subtitle_start, subtitle_end = subtitle_source
                write_clip_srt(subtitle_transcript, subtitle_start, subtitle_end, srt_path, max_words=config.subtitles.max_words_per_line)
                write_ass(
                    subtitle_transcript,
                    subtitle_start,
                    subtitle_end,
                    ass_path,
                    font_size=config.subtitles.font_size,
                    max_words=config.subtitles.max_words_per_line,
                    width=config.render.width,
                    height=config.render.height,
                    safe_bottom_margin_px=config.subtitles.safe_bottom_margin_px,
                    speaker_colors_enabled=config.subtitles.speaker_colors_enabled,
                    speaker_labels_enabled=config.subtitles.speaker_labels_enabled,
                    highlight_current_word=config.subtitles.highlight_current_word,
                )
                render_ass_path = ass_path
            scene_cuts: list[float] = []
            if config.dynamic_edit.enabled and config.dynamic_edit.scene_detection_enabled:
                scene_cuts = detect_scene_cuts(
                    source_path,
                    ffmpeg_path=config.paths.ffmpeg_path,
                    start=clip.start,
                    duration=clip.duration,
                    threshold=config.dynamic_edit.scene_threshold,
                    hwaccel=config.render.hwaccel,
                )
                update_job(
                    job_id,
                    stage="rendering",
                    message=f"Planning rhythm for {clip.id}",
                    log=f"Detected {len(scene_cuts)} source shot changes for {clip.id}",
                )
            edit_plan = build_edit_plan(
                clip,
                config,
                profile=clip.edit_profile,
                transcript=transcript,
                scene_cuts=scene_cuts,
            )
            write_json(edit_plan_path, edit_plan.model_dump())
            write_caption_file(clip, caption_path)
            write_json(metadata_path, {"clip": clip.model_dump(), "caption_path": str(caption_path), "edit_plan_path": str(edit_plan_path)})
            recovery_note = " + recovered audio" if recovery_audio_path else ""
            update_job(
                job_id,
                stage="rendering",
                message=f"Rendering {clip.id} with {config.render.video_codec}",
                log=render_acceleration_summary(config, render_ass_path) + recovery_note,
            )
            render_clip(
                source_path,
                output_path,
                clip,
                edit_plan,
                config,
                ass_path=render_ass_path,
                badge_path=badge_path,
                audio_path=recovery_audio_path,
            )
            integrity = verify_render_integrity(output_path, clip, config)
            update_job(
                job_id,
                stage="rendering",
                message=f"Verified {clip.id}",
                log=f"Actual encoder for {clip.id}: {integrity.get('encoder') or 'unknown'}",
            )
            write_json(integrity_path, integrity)
            write_json(
                metadata_path,
                {
                    "clip": clip.model_dump(),
                    "caption_path": str(caption_path),
                    "edit_plan_path": str(edit_plan_path),
                    "render_integrity_path": str(integrity_path),
                },
            )
            project_store.mark_clip_rendered(project_id, clip.id, output_path, srt_path, ass_path, edit_plan_path, metadata_path)
            store_feedback(project_id, clip.id, clip.moment_id, FeedbackRequest(action="rendered"))
        if _restore_project_after_cancellation(job_id, project_id, previous_status):
            return
        project_store.set_project_status(project_id, "rendered")
        update_job(job_id, status=JobStatus.done, stage="done", progress=1, message="Render complete")
    except Exception as exc:
        if _restore_project_after_cancellation(job_id, project_id, previous_status):
            return
        project_store.set_project_status(project_id, "render_failed")
        update_job(job_id, status=JobStatus.failed, stage="failed", error=str(exc), message="Render failed")
