from __future__ import annotations

import re

from backend.schemas.moments import SentenceSegment
from backend.schemas.transcript import Transcript, TranscriptWord
from backend.services.content_quality import repair_mojibake

SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")


def _split_text(text: str) -> list[str]:
    text = repair_mojibake(text)
    pieces = [piece.strip() for piece in SENTENCE_RE.split(text.strip()) if piece.strip()]
    return pieces or ([text.strip()] if text.strip() else [])


def split_plain_text(text: str) -> list[str]:
    return _split_text(text)


def _speaker_metadata(words: list[TranscriptWord | dict], fallback: str | None = None) -> tuple[str | None, list[str], int]:
    speakers: list[str] = []
    for word in words:
        speaker = word.get("speaker") if isinstance(word, dict) else word.speaker
        if speaker:
            speakers.append(speaker)
    if not speakers and fallback:
        speakers = [fallback]
    unique = list(dict.fromkeys(speakers))
    switches = sum(1 for left, right in zip(speakers, speakers[1:]) if left != right)
    speaker = unique[0] if len(unique) == 1 else None
    return speaker, unique, switches


def segment_transcript(transcript: Transcript) -> list[SentenceSegment]:
    sentences: list[SentenceSegment] = []
    next_id = 1
    for segment in transcript.segments:
        parts = _split_text(segment.text)
        if len(parts) == 1:
            speaker, speakers, switches = _speaker_metadata(segment.words, segment.speaker)
            sentences.append(
                SentenceSegment(
                    id=f"sent_{next_id:04}",
                    start=segment.start,
                    end=segment.end,
                    text=repair_mojibake(segment.text).strip(),
                    speaker=speaker,
                    speakers=speakers,
                    speaker_switches=switches,
                    words=[word.model_dump() for word in segment.words],
                )
            )
            next_id += 1
            continue
        words = segment.words
        cursor = 0
        for part in parts:
            count = len(part.split())
            selected_words = words[cursor : cursor + count]
            cursor += count
            if selected_words:
                start = selected_words[0].start
                end = selected_words[-1].end
            else:
                span = (segment.end - segment.start) / len(parts)
                start = segment.start + (next_id - 1) * span
                end = start + span
            speaker, speakers, switches = _speaker_metadata(selected_words, segment.speaker)
            sentences.append(
                SentenceSegment(
                    id=f"sent_{next_id:04}",
                    start=start,
                    end=end,
                    text=part,
                    speaker=speaker,
                    speakers=speakers,
                    speaker_switches=switches,
                    words=[word.model_dump() if isinstance(word, TranscriptWord) else word for word in selected_words],
                )
            )
            next_id += 1
    return sentences
