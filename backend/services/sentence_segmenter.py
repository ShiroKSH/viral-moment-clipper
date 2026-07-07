from __future__ import annotations

import re

from backend.schemas.moments import SentenceSegment
from backend.schemas.transcript import Transcript, TranscriptWord

SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")


def _split_text(text: str) -> list[str]:
    pieces = [piece.strip() for piece in SENTENCE_RE.split(text.strip()) if piece.strip()]
    return pieces or ([text.strip()] if text.strip() else [])


def split_plain_text(text: str) -> list[str]:
    return _split_text(text)


def segment_transcript(transcript: Transcript) -> list[SentenceSegment]:
    sentences: list[SentenceSegment] = []
    next_id = 1
    for segment in transcript.segments:
        parts = _split_text(segment.text)
        if len(parts) == 1:
            sentences.append(SentenceSegment(id=f"sent_{next_id:04}", start=segment.start, end=segment.end, text=segment.text.strip(), words=[word.model_dump() for word in segment.words]))
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
            sentences.append(SentenceSegment(id=f"sent_{next_id:04}", start=start, end=end, text=part, words=[word.model_dump() if isinstance(word, TranscriptWord) else word for word in selected_words]))
            next_id += 1
    return sentences
