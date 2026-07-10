from __future__ import annotations

import re

from backend.schemas.clips import ClipCandidate
from backend.schemas.transcript import Transcript
from backend.services.content_quality import repair_mojibake


SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?…])\s+")


def clip_transcript_text(transcript: Transcript, start: float, end: float) -> str:
    parts: list[str] = []
    for segment in transcript.segments:
        if segment.end <= start or segment.start >= end:
            continue
        words = [
            repair_mojibake(word.word).strip()
            for word in segment.words
            if word.end > start + 0.02 and word.start < end - 0.02 and repair_mojibake(word.word).strip()
        ]
        text = " ".join(words) if words else repair_mojibake(segment.text).strip()
        if text:
            parts.append(text)
    text = " ".join(" ".join(parts).split())
    return re.sub(r"\s+(-[\w]+)", r"\1", text, flags=re.UNICODE)


def _first_complete_phrase(text: str, max_words: int = 10, max_chars: int = 76) -> str:
    first_sentence = SENTENCE_BREAK_RE.split(text, maxsplit=1)[0].strip()
    words = first_sentence.split()
    phrase = " ".join(words[:max_words]).strip(" ,;:-")
    if len(phrase) <= max_chars:
        return phrase
    return phrase[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-")


def refresh_clip_context(clip: ClipCandidate, transcript: Transcript) -> ClipCandidate:
    text = clip_transcript_text(transcript, clip.start, clip.end)
    if not text:
        return clip
    title = _first_complete_phrase(text) or repair_mojibake(clip.suggested_title)
    sentences = [part.strip() for part in SENTENCE_BREAK_RE.split(text) if part.strip()]
    caption = " ".join(sentences[:2]) if sentences else text
    summary = text if len(text) <= 260 else text[:257].rsplit(" ", 1)[0] + "..."
    return clip.model_copy(
        update={
            "text": text,
            "hook_text": title,
            "suggested_title": title,
            "suggested_caption": caption,
            "summary": summary,
        }
    )
