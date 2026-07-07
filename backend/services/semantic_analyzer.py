from __future__ import annotations

from backend.core.config import Settings
from backend.schemas.moments import InterestingMoment, SentenceSegment
from backend.services.content_quality import filter_quality_moments
from backend.services.heuristic_analyzer import analyze_with_heuristics
from backend.services.local_llm_analyzer import analyze_with_local_llm
from backend.services.moment_merger import merge_overlapping_moments


def find_interesting_moments(sentences: list[SentenceSegment], config: Settings) -> list[InterestingMoment]:
    heuristic = analyze_with_heuristics(sentences, config)
    llm = analyze_with_local_llm(sentences, config)
    merged = merge_overlapping_moments([*heuristic, *llm])
    return filter_quality_moments(merged, config.clips.min_score, config.clips.target_count)
