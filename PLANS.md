# Viral Moment Clipper Plan

Local Windows app: long video in, speech analysis, potentially interesting moments, vertical clips out. Core path must stay runnable after every phase.

## Current Status
- Phase 1 done: backend/frontend skeleton, scripts, config, health/settings.
- Phase 2 done: project create, upload, ffprobe, SQLite persistence, metadata UI.
- Phase 3 done: FFmpeg audio extraction, faster-whisper path, explicit fallback transcript mode, transcript JSON/SRT.
- Phase 4 done: sentence segmentation, heuristic analyzer, optional Ollama path, merge/score, candidates UI.
- Phase 5 done: editable clip boundaries with sentence-aware start/end.
- Phase 6 done: edit plan JSON with profiles, hook title, punch zoom, subtitle emphasis, progress bar, anti-overedit limits.
- Phase 7 done: SRT/ASS, badge PNG path, FFmpeg command builder, NVENC with libx264 fallback, output sidecars.
- Phase 8 done: accept/reject/edit/render feedback, metrics API, rule-based personal ranking, learning dashboard.
- Phase 9 initial done: README, tests, build/audit/smoke checks.

Advanced remaining: WhisperX alignment, true silence removal edit graph, face tracking crop, visual/audio real feature extraction, sklearn model artifact training after enough feedback, richer preview player.

## Phase 1: Skeleton
- Create Python/FastAPI backend, React/Vite frontend, shared config, batch scripts, repo folders.
- Add `GET /api/health`, `GET/POST /api/settings`.
- Basic UI: upload/settings/progress/candidates/output/learning shells.
- Runnable check: backend health returns ok; frontend loads.

## Phase 2: Video Import
- Create projects, upload video, run `ffprobe`, store metadata in SQLite.
- Persist project folders under `output/<project>/source`.
- Show project list and metadata in UI.
- Runnable check: upload an mp4/mov/mkv/webm/avi, see metadata or clear ffprobe error.

## Phase 3: Audio + Transcription
- Extract WAV 16k mono with FFmpeg.
- Transcribe with faster-whisper when installed; fallback to sample transcript/manual placeholder when unavailable.
- Save `transcript_full.json` and `transcript_full.srt`.
- Show transcript preview in UI.

## Phase 4: Semantic Moment Finder
- Segment transcript into sentences/windows.
- Heuristic analyzer plus optional Ollama-compatible analyzer.
- Merge moments, score, generate candidate explanations.
- Show candidates with score, type, hook, reason, problems, captions.

## Phase 5: Clip Boundaries
- Choose start/end around hook/payoff.
- Respect word/sentence timestamps and configured min/max duration.
- Keep boundaries editable in UI.

## Phase 6: Dynamic Edit Planning
- Generate `EditPlan` JSON.
- Support clean/balanced/aggressive/podcast/gaming profiles.
- Include silence cleanup, hook title, punch zoom, subtitle emphasis, progress bar with anti-overedit rules.

## Phase 7: Rendering
- Generate SRT/ASS subtitles and badge.
- Build FFmpeg command as argument lists.
- Render 1080x1920 mp4 with `h264_nvenc`, fallback `libx264`.
- Export mp4, subtitles, metadata, caption txt, edit plan.

## Phase 8: Feedback + Learning
- Accept/reject/edit/render feedback.
- Manual publish metrics.
- Rule-based personal ranker before enough feedback; train optional sklearn model later.
- Learning dashboard shows basic stats and ranker state.

## Phase 9: Polish
- Better UI states/errors/preview.
- README install/run/troubleshooting.
- Unit tests for segmenter, analyzer, scoring, boundaries, edit plans, renderer command, ranker.

## Acceptance Path
`install.bat` -> `run.bat` -> upload -> ffprobe -> audio -> transcript -> candidates -> accept/reject -> render selected -> output files -> feedback/learning stats.
