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
- Phase 8 done: accept/reject/edit/render feedback, durable metrics, online preferences, sklearn logistic training, immutable feature snapshots, and learning dashboard.
- Phase 9 initial done: README, tests, build/audit/smoke checks.
- Runtime hardening done: local FFmpeg path, CUDA Whisper setup, GPU-first CPU fallback policy, NVENC quality flags, CUDA hwaccel decode, visible runtime modes in UI/job logs, active-project guard, project cleanup/delete, computed upload/analyze/render activity dates.
- Subtitle hardening done: boundary words are retained, sparse word timestamps fall back to segment text timing, transcript schema supports speakers, clip-local retranscription inherits canonical project speaker IDs, speaker-aware moment scoring boosts dialogue-heavy clips, and ASS output uses a stable baseline with distinct speaker colors.
- Candidate quality hardening done: `content_arc_v2` scores complete hook-to-payoff arcs, combines disclosure/CTA/offer/urgency/brand/context evidence into promotional cores, rejects clips with at least 2 seconds or 10% promo overlap, suppresses duplicates, preserves shortlist diversity, and writes a complete selection audit sidecar.
- Render GPU hardening done: default NVENC render uses CUDA decode, a true soft `bilateral_cuda` background blur, full-resolution sharp foreground, and `overlay_cuda`; frames download to CPU only for montage/text/ASS, the actual encoder is verified, and `gpu_filters` remains configurable.
- Text encoding hardening done: UTF-8 mojibake repair runs through transcript save/load, subtitles, captions, segmenting, ranking, and legacy clip reads so Russian text stays readable in UI and burned-in ASS.
- Project UX hardening done: upload creates an explicit new project with DB-backed upload time, project list sorts by true latest activity, analyze is disabled without a source video, busy state covers upload/render/analyze, and accept/reject review state is separate from rendered state.
- Speaker backend hardening done: `speaker_turn_v3` uses normalized SpeechBrain embeddings with outlier-resistant seeded clustering, adaptive short-turn assignment, canonical project IDs, explicit coverage/version metadata, and local-feature fallback when the neural backend is missing or overloaded.
- Semantic montage hardening done: accents use real transcript word timestamps, CUDA-assisted source-cut detection protects existing edits, natural cuts reduce the generated-effect budget, fixed-interval motion is removed, and cliffhanger scoring rejects comma fragments/dangling connectors.
- Retention grammar done: long source shots receive at most 2.8% cut-shaped lens motion, factual claims can receive timed evidence typography, and one strong question/reveal/contrast may receive a paired quiet sound plus 3.2-4.5% visual pulse even when longer shot motion is present.
- Caption retention hardening done: phrase groups span up to two balanced lines, short ASR cards merge across segment boundaries, display time targets 18 CPS when silence permits, sparse word timing recovers from segment text, low density/internal gaps/missing tails trigger a local transcription pass, and hyphenated ASR tokens render correctly.
- Ending coherence done: dangling conclusions are extended through their payoff, post-sentence padding cannot capture the next utterance, the promo-validated analysis boundary remains immutable during render, hook/title/caption text is rebuilt from that interval, and the CTA is a focused 1.0-second motion treatment over the final frame.
- Analysis coverage done: optional Ollama analysis scans overlapping validated windows across the complete transcript and uses configurable low temperature/seed values for repeatable candidates.
- Artifact lifecycle done: each successful reanalysis archives previous clips/subtitles/metadata/reports under a timestamped generation with a manifest; source media stays in place, and cancellation stops before the next queued clip.
- Render integrity done: successful output requires the expected 1080x1920 video duration/frame count, writes an integrity JSON sidecar, and rejects audio-only tails or truncated motion graphs.
- Corrupt-source recovery done: audio extraction records normal/recovery mode, render reuses the clean recovered WAV when source AAC is damaged, and audio/video duration is verified after muxing.
- Learning hardening done: automatic `rendered` events do not train the ranker; feedback/metrics keep immutable feature snapshots, repeated events collapse to the latest decision, project cleanup invalidates stale models, and training commits atomically after enough distinct outcomes.
- Job and persistence hardening done: SQLite-backed jobs survive UI reloads, a partial unique index prevents duplicate active work across processes, startup recovery records interrupted work and restores project state, running cancellation keeps the project locked until a worker checkpoint, managed DB contexts release Windows file handles, WAL/busy timeout protect concurrent reads, cancellation is available in the progress panel, failed replacement uploads preserve the previous source, and config/JSON sidecars use atomic replacement.

Advanced remaining: immutable render-variant records and blind A/B UI, per-second retention-curve import, stronger neural diarization/WhisperX alignment, conservative silence-removal timeline, face tracking crop, real visual/audio energy features, and enough balanced real feedback to activate the trained model for this installation.

## Verified Runtime Snapshot (2026-07-10)
- Reanalyzed project `bcc7384ffd204b31ae34cd213cb22b72` after identifying the PUBG promotion at 178.60-227.58. All 4 strict-gate candidates have zero overlap with the promo core; 63 stale artifacts moved into a manifest-backed archive generation.
- Real `speaker_turn_v3` output reports `S1:80, S2:40, S3:31, S4:45` at 90% segment coverage. Clip-local CUDA retranscriptions inherit those IDs and expose 3-4 speaker styles per rendered conversation.
- Rendered all 4 replacement clips at exact approved boundaries plus the 1.0-second CTA. Every output reports `Lavc61.19.101 h264_nvenc`; CUDA logs confirm decode, bilateral background blur, scaling, and overlay on GPU.
- Inspected timestamped frames from the replacement output: the center remains sharp, the extended background is softly blurred rather than pixelated, speaker colors are visually distinct, and the CTA contains no subtitle residue.
- Reanalyzed the 23:47 recovery WAV from project `58b528eafdf541939d8bd7facfbc07b2` with `faster-whisper:cuda`; 134 candidates entered the selector and 8 diverse candidates passed.
- Rendered all 8 selected candidates at 1080x1920. Every integrity sidecar reports `Lavc61.19.101 h264_nvenc`, matching audio/video durations, valid frame counts, and zero errors.
- Inspected timestamped frames across all 8 outputs. The background is smooth rather than pixelated, semantic motion is sparse, subtitles are readable, and the final CTA contains no residual subtitle or extra promotional copy.
- Verified every generated SRT begins at the clip speech boundary and ends on a complete phrase; observed density is 2.17-2.91 words/sec with no internal gap above 1.6 seconds.

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
- Include semantic evidence beats, cut-shaped shot motion, source-cut protection, phrase-timed subtitle emphasis, optional hook/progress treatments, and anti-overedit rules.

## Phase 7: Rendering
- Generate SRT/ASS subtitles and badge.
- Build FFmpeg command as argument lists.
- Render 1080x1920 mp4 with `h264_nvenc`, fallback `libx264`.
- Export mp4, subtitles, metadata, caption txt, edit plan, and render-integrity JSON.

## Phase 8: Feedback + Learning
- Accept/reject/edit/render feedback.
- Manual publish metrics.
- Online preference ranker before enough feedback; train a validated sklearn model automatically after the configured distinct-outcome threshold.
- Preserve feature snapshots across reanalysis and keep imported metrics when candidate rows are replaced.
- Learning dashboard shows usable rows, class balance, model state, and retention metrics.

## Phase 9: Polish
- Better UI states/errors/preview.
- README install/run/troubleshooting.
- Unit tests for segmenter, analyzer, scoring, boundaries, edit plans, renderer command, ranker.

## Acceptance Path
`install.bat` -> `run.bat` -> upload -> ffprobe -> audio -> transcript -> candidates -> accept/reject -> render selected -> output files -> feedback/learning stats.
