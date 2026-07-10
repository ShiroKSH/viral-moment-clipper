from __future__ import annotations

from pathlib import Path

from backend.core.utils import write_json
from backend.schemas.transcript import Transcript
from backend.services.content_quality import repair_mojibake
from backend.services.subtitles import write_srt


def repair_transcript_text(transcript: Transcript) -> bool:
    changed = False
    transcript.text, text_changed = _repair_value(transcript.text)
    changed = changed or text_changed
    for segment in transcript.segments:
        segment.text, segment_changed = _repair_value(segment.text)
        changed = changed or segment_changed
        for word in segment.words:
            word.word, word_changed = _repair_value(word.word)
            changed = changed or word_changed
    if changed:
        transcript.text = " ".join(segment.text for segment in transcript.segments)
    return changed


def _repair_value(value: str) -> tuple[str, bool]:
    repaired = repair_mojibake(value)
    return repaired, repaired != value


def save_transcript(transcript: Transcript, json_path: Path, srt_path: Path) -> tuple[Path, Path]:
    repair_transcript_text(transcript)
    write_json(json_path, transcript.model_dump())
    write_srt(transcript, srt_path)
    return json_path, srt_path
