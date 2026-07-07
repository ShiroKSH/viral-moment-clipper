# Viral Moment Clipper

Local Windows app for turning long creator videos into vertical clips. It finds potentially interesting speech moments, explains the score, renders Shorts/TikTok/Reels style mp4 files, and learns from feedback over time.

## Requirements
- Windows 10/11 x64.
- Python 3.11 or 3.12.
- Node.js 20+.
- FFmpeg and ffprobe on PATH, or set paths in `config.yaml`.
- NVIDIA CUDA setup for fastest local transcription. CPU fallback depends on faster-whisper settings.

## Install
Run:

```bat
install.bat
```

This creates `.venv`, installs Python packages, installs frontend packages, and copies `config.example.yaml` to `config.yaml` when needed.

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

## Config
Edit `config.yaml` for FFmpeg paths, model, language, clip duration, render codec, badge text, subtitle style, Ollama, and learning settings.

## Local LLM
Ollama-compatible analysis is optional. If Ollama is unavailable, heuristic analysis keeps the pipeline running.

For quick offline smoke tests, set `transcription.engine: "fallback"` in `config.yaml`. That uses a deterministic placeholder transcript instead of loading a Whisper model.

## Troubleshooting
- FFmpeg not found: install FFmpeg or set `paths.ffmpeg_path` and `paths.ffprobe_path`.
- CUDA not visible: set `transcription.device: "cpu"` or install compatible NVIDIA/CUDA dependencies.
- Slow first transcription: faster-whisper may download/load a model.

## Scores
- `base_score`: content and retention estimate from heuristic/audio/visual signals.
- `personal_score`: adjustment from your feedback history.
- `final_score`: combined ranking used for candidate order.
