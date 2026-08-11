# Viral Moment Clipper

Local Windows app for turning long creator videos into vertical clips. It finds potentially interesting speech moments, explains the score, renders Shorts/TikTok/Reels style mp4 files, and learns from feedback over time.

## Requirements
- Windows 10/11 x64.
- Python 3.11 or 3.12.
- Node.js 20+.
- FFmpeg and ffprobe on PATH, or set paths in `config.yaml`.
- NVIDIA CUDA setup for fastest local transcription. CPU fallback depends on faster-whisper settings.
- Optional: SpeechBrain speaker backend for neural speaker embeddings.

## Install
Run:

```bat
install.bat
```

This creates `.venv`, installs Python packages, installs frontend packages, and copies `config.example.yaml` to `config.yaml` when needed.

For neural speaker embeddings, run the optional installer after the base install:

```bat
install-speakers.bat
```

Then set `speakers.embedding_backend: "speechbrain"` in `config.yaml` or Settings. If SpeechBrain, PyTorch, CUDA, or the model download fails, the app falls back to the built-in local speaker clustering.

## Run
Run:

```bat
run.bat
```

Open `http://127.0.0.1:5173`. The backend listens on `http://127.0.0.1:7878`.

## Workflow
1. Create a project and upload `mp4`, `mov`, `mkv`, `webm`, or `avi`.
2. The app probes metadata with ffprobe.
3. Analyze to extract audio, transcribe locally when faster-whisper is available, segment speech, and create candidates.
4. Accept/reject or adjust candidates.
5. Render selected clips to `output/<project>/`.

Uploads are staged and checked with ffprobe before they replace an existing project source. Analysis and render requests share one per-project job guard, cancellation is terminal, and config/JSON sidecars are replaced atomically so an interrupted write does not leave a partial document.

## Montage
The edit planner uses transcript word timestamps and the source video's existing shot changes. Long shots can receive a slow, cut-shaped camera move capped at 2.8%; existing close-ups and short shots stay untouched. Timed evidence typography is reserved for concrete quantities. At most one quiet semantic sound and one synchronized 3.2-4.5% visual pulse can mark a strong question, reveal, or contrast. These rules replace fixed-interval zooms and effect spam.

Subtitles are grouped as readable phrases across transcript segment boundaries, with two balanced lines, adaptive display time, and one highlighted semantic word. Broken word timing, low speech density, a large internal gap, or a missing tail triggers a cached local retranscription pass. That pass inherits the project-level speaker IDs instead of reclustering the same person differently in each clip. Clip endings are finalized during analysis and remain unchanged during render, so a validated boundary cannot expand into an ad or the next utterance.

The default blurred-background render keeps the source aspect ratio, applies a wide `bilateral_cuda` blur to the background, and overlays a full-resolution sharp foreground. Decode, background blur, scaling, composition, and H.264 encoding stay on the NVIDIA path; only libass/text and final montage post-filters download frames to CPU.

Rendered files are accepted only after ffprobe confirms the expected canvas, video-stream duration, audio duration, and frame count. Every render writes an integrity JSON sidecar with the actual encoder; an audio-only tail or truncated motion graph fails the job instead of appearing successful. When source AAC is damaged, the pipeline renders from the recovered clean WAV created during analysis.

## Config
Edit `config.yaml` for FFmpeg paths, model, language, clip duration, render codec, badge text, subtitle timing, Ollama, and learning settings.

## Local LLM
Ollama-compatible analysis is optional. It scans overlapping windows across the complete transcript, uses a configured low temperature and seed for repeatable candidates, and validates every external JSON response with Pydantic. If Ollama is unavailable, heuristic analysis keeps the pipeline running.

For quick offline smoke tests, set `transcription.engine: "fallback"` in `config.yaml`. That uses a deterministic placeholder transcript instead of loading a Whisper model.

## Speaker Labels
Speaker detection is enabled by default. The stable default backend is `local`, which clusters local voice features and writes `S1`, `S2`, etc. into the transcript. The SpeechBrain path uses normalized ECAPA embeddings, outlier-resistant clustering, and project-level canonical IDs. ASS subtitles keep one stable baseline and use clearly different speaker colors so dialogue remains readable without vertical jumps.

The optional `speechbrain` backend uses `speechbrain/spkrec-ecapa-voxceleb` speaker embeddings when installed. It is heavier because it pulls PyTorch/Torchaudio, so it lives in `requirements-speakers.txt` instead of the base install.

Candidate selection records evidence-based promotional ranges in `source/candidate_selection.json`; disclosure, CTA, offer, urgency, brand, and context signals are combined instead of treating every game update as an ad. Reanalysis moves the previous clips, subtitle files, metadata, and reports into `archive/<generation>/` with a manifest, leaving the source media untouched.

## Troubleshooting
- FFmpeg not found: install FFmpeg or set `paths.ffmpeg_path` and `paths.ffprobe_path`.
- CUDA not visible: set `transcription.device: "cpu"` or install compatible NVIDIA/CUDA dependencies.
- SpeechBrain import/model error: keep `speakers.embedding_backend: "local"` or run `install-speakers.bat`; local clustering remains available as fallback.
- Slow first transcription: faster-whisper may download/load a model.

## Scores
- `base_score`: content and retention heuristic. Audio/visual score fields remain placeholders until real extractors land.
- `personal_score`: adjustment from your feedback history.
- `final_score`: combined ranking used for candidate order.

Scores and edit grammars are retention hypotheses, not guaranteed virality. Automatic render events do not count as training feedback; meaningful learning requires explicit review or real publish metrics from distinct clips.

The personal ranker uses online preferences immediately and automatically trains a local sklearn logistic model after the configured number of distinct usable outcomes. Feedback stores immutable feature snapshots, so later reanalysis cannot silently rewrite historical training rows.
