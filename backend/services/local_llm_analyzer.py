from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, TypeAdapter, model_validator

from backend.core.config import Settings
from backend.schemas.moments import InterestingMoment, SentenceSegment


class _LocalMomentSuggestion(BaseModel):
    start: float = Field(ge=0)
    end: float | None = None
    summary: str = ""
    moment_type: str = "insight"
    hook_text: str = ""
    reason: str = "Local LLM suggested this moment."

    @model_validator(mode="after")
    def validate_interval(self) -> "_LocalMomentSuggestion":
        if self.end is not None and self.end <= self.start:
            raise ValueError("end must be after start")
        return self


SUGGESTION_LIST = TypeAdapter(list[_LocalMomentSuggestion])


def _sentence_windows(
    sentences: list[SentenceSegment],
    max_window_sec: float,
    overlap_sec: float,
) -> list[list[SentenceSegment]]:
    if not sentences:
        return []
    max_window = max(30.0, max_window_sec)
    overlap = max(0.0, min(overlap_sec, max_window * 0.45))
    windows: list[list[SentenceSegment]] = []
    cursor = 0
    while cursor < len(sentences):
        window_start = sentences[cursor].start
        window_end = window_start + max_window
        window = [sentence for sentence in sentences[cursor:] if sentence.start < window_end]
        if not window:
            break
        windows.append(window)
        if window[-1] is sentences[-1]:
            break
        next_start = window_end - overlap
        next_cursor = next(
            (index for index in range(cursor + 1, len(sentences)) if sentences[index].start >= next_start),
            cursor + len(window),
        )
        cursor = max(cursor + 1, next_cursor)
    return windows


def _prompt(window: list[SentenceSegment]) -> str:
    transcript = "\n".join(f"{sentence.start:.2f}-{sentence.end:.2f}: {sentence.text}" for sentence in window)
    return (
        "Return only a strict JSON array of strong short-video moment candidates. "
        "Each object must contain start, end, summary, moment_type, hook_text, reason. "
        "Prefer an independent hook in the first 2.5 seconds, information gain, a coherent payoff, "
        "and a concrete open loop. Reject hooks that depend on words like this/that/there, filler-only "
        "windows, and endings inside an unfinished phrase. Timestamps must remain absolute.\nTranscript:\n"
        + transcript
    )


def _moment_text(sentences: list[SentenceSegment], start: float, end: float) -> str:
    return " ".join(sentence.text for sentence in sentences if sentence.end >= start and sentence.start <= end).strip()


def analyze_with_local_llm(sentences: list[SentenceSegment], config: Settings) -> list[InterestingMoment]:
    if not config.local_llm.enabled:
        return []
    parsed = urlparse(config.local_llm.base_url)
    if parsed.scheme not in {"http", "https"}:
        return []

    windows = _sentence_windows(sentences, config.local_llm.max_window_sec, config.local_llm.overlap_sec)
    moments: list[InterestingMoment] = []
    try:
        client = httpx.Client(timeout=config.local_llm.timeout_sec)
    except Exception:
        return []
    with client:
        for window in windows:
            payload = {
                "model": config.local_llm.model,
                "stream": False,
                "prompt": _prompt(window),
                "options": {
                    "temperature": config.local_llm.temperature,
                    "seed": config.local_llm.seed,
                },
            }
            try:
                response = client.post(f"{config.local_llm.base_url.rstrip('/')}/api/generate", json=payload)
                response.raise_for_status()
                raw = json.loads(response.json().get("response", "[]"))
                suggestions = SUGGESTION_LIST.validate_python(raw)
            except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError):
                continue
            for suggestion in suggestions:
                start = suggestion.start
                end = suggestion.end or start + config.clips.preferred_duration_sec
                if end <= start:
                    continue
                hook = suggestion.hook_text.strip()
                summary = suggestion.summary.strip()
                moments.append(
                    InterestingMoment(
                        id=f"llm_moment_{len(moments) + 1:03}",
                        start=start,
                        end=end,
                        duration=end - start,
                        text=_moment_text(sentences, start, end),
                        summary=summary,
                        moment_type=suggestion.moment_type.strip() or "insight",
                        hook_text=hook,
                        reason=suggestion.reason.strip() or "Local LLM suggested this moment.",
                        suggested_title=hook[:80],
                        suggested_caption=summary,
                        semantic_interest_score=72,
                        hook_score=70,
                        clarity_score=65,
                        emotion_score=60,
                        novelty_score=60,
                        standalone_score=65,
                        retention_score=68,
                        speech_density_score=50,
                        audio_energy_score=50,
                        visual_energy_score=50,
                        base_score=66,
                        personal_score=66,
                        final_score=66,
                    )
                )
    return moments
