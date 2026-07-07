from __future__ import annotations

from pathlib import Path

from backend.core.utils import write_json
from backend.schemas.transcript import Transcript
from backend.services.subtitles import write_srt


def save_transcript(transcript: Transcript, json_path: Path, srt_path: Path) -> tuple[Path, Path]:
    write_json(json_path, transcript.model_dump())
    write_srt(transcript, srt_path)
    return json_path, srt_path
