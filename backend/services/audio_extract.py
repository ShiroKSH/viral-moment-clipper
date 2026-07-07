from __future__ import annotations

from pathlib import Path

from backend.core.config import Settings
from backend.core.ffmpeg import run_command


def extract_wav(source_path: Path, output_path: Path, config: Settings) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        config.paths.ffmpeg_path,
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-acodec",
        "pcm_s16le",
        str(output_path),
    ]
    run_command(argv, timeout=None)
    return output_path
