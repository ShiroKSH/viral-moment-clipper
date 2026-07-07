from __future__ import annotations

from backend.core.config import Settings
from backend.core.utils import clamp
from backend.schemas.moments import InterestingMoment
from backend.schemas.transcript import Transcript


def choose_clip_boundary(moment: InterestingMoment, transcript: Transcript, config: Settings) -> tuple[float, float]:
    start = max(0, moment.start - config.clips.pad_before_sec)
    end = moment.end + config.clips.pad_after_sec
    duration = end - start
    if duration > config.clips.max_duration_sec:
        end = start + config.clips.max_duration_sec
    if end - start < config.clips.min_duration_sec:
        end = min(transcript.duration or end + config.clips.min_duration_sec, start + config.clips.min_duration_sec)

    if config.clips.avoid_cutting_sentences:
        sentence_starts = [segment.start for segment in transcript.segments if segment.start <= moment.start + 1]
        sentence_ends = [segment.end for segment in transcript.segments if segment.end >= moment.end - 1]
        if sentence_starts:
            start = max(0, sentence_starts[-1] - config.clips.pad_before_sec)
        if sentence_ends:
            end = sentence_ends[0] + config.clips.pad_after_sec
    end = clamp(end, start + 1, transcript.duration or end)
    if end - start > config.clips.max_duration_sec:
        end = start + config.clips.max_duration_sec
    return round(start, 2), round(end, 2)
