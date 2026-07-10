from __future__ import annotations

from backend.core.config import Settings
from backend.schemas.moments import InterestingMoment, SentenceSegment
from backend.services.candidate_selector import calibrate_moment
from backend.services.heuristic_analyzer import analyze_with_heuristics, speaker_metrics
from backend.services.local_llm_analyzer import analyze_with_local_llm


def _apply_speaker_metrics(moments: list[InterestingMoment], sentences: list[SentenceSegment]) -> list[InterestingMoment]:
    for moment in moments:
        window = [sentence for sentence in sentences if sentence.end >= moment.start and sentence.start <= moment.end]
        if not window:
            continue
        dialogue = speaker_metrics(window)
        moment.speaker_count = int(dialogue["speaker_count"])
        moment.speaker_switches = int(dialogue["speaker_switches"])
        moment.dialogue_score = dialogue["dialogue_score"]
        if moment.dialogue_score and "Dialogue signal" not in moment.reason:
            boost = min(6.0, moment.dialogue_score * 0.06)
            moment.base_score = round(min(100, moment.base_score + boost), 2)
            moment.personal_score = round(min(100, moment.personal_score + boost), 2)
            moment.final_score = round(min(100, moment.final_score + boost), 2)
            if moment.moment_type == "insight":
                moment.moment_type = "conversation"
            moment.reason += f" Dialogue signal: {moment.speaker_count} speakers, {moment.speaker_switches} turns."
    return moments


def find_interesting_moments(
    sentences: list[SentenceSegment],
    config: Settings,
    *,
    scene_cuts: list[float] | None = None,
) -> list[InterestingMoment]:
    heuristic = analyze_with_heuristics(sentences, config)
    llm = analyze_with_local_llm(sentences, config)
    calibrated = [calibrate_moment(moment, scene_cuts=scene_cuts) for moment in [*heuristic, *llm]]
    calibrated = _apply_speaker_metrics(calibrated, sentences)
    hard_reject = {"ad or CTA language", "generic clip-analysis text", "teaser without payoff"}
    threshold = max(34, config.clips.min_score - 16)
    pool = [moment for moment in calibrated if moment.final_score >= threshold and not hard_reject.intersection(moment.problems)]
    return sorted(pool, key=lambda item: item.final_score, reverse=True)[: max(120, config.clips.target_count * 20)]
