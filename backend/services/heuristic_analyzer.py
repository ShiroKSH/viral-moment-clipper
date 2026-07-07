from __future__ import annotations

import re

from backend.core.config import Settings
from backend.core.utils import clamp
from backend.schemas.moments import InterestingMoment, SentenceSegment
from backend.services.content_quality import apply_quality_penalty
from backend.services.viral_score import calculate_base_score


TYPE_KEYWORDS = {
    "controversial_take": ("ошибка", "миф", "неправильно", "спор", "проблема", "никогда"),
    "personal_story": ("я ", "мне", "мой", "моя", "история", "однажды"),
    "how_to": ("как ", "шаг", "сделать", "нужно", "способ"),
    "warning": ("важно", "нельзя", "опасно", "риск", "осторожно"),
    "result": ("результат", "получилось", "итог", "вывод", "поэтому"),
    "before_after": ("раньше", "теперь", "до ", "после", "вместо"),
}


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    lowered = text.lower().replace("ё", "е")
    return any(word in lowered for word in words)


def classify_moment(text: str) -> str:
    for moment_type, words in TYPE_KEYWORDS.items():
        if _contains_any(text, words):
            return moment_type
    if "?" in text:
        return "question_answer"
    return "insight"


def summarize(text: str, max_chars: int = 180) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "..."


def score_text(text: str, duration: float) -> dict[str, float]:
    lowered = text.lower().replace("ё", "е")
    word_count = len(text.split())
    questions = text.count("?")
    has_conflict = _contains_any(lowered, TYPE_KEYWORDS["controversial_take"])
    has_story = _contains_any(lowered, TYPE_KEYWORDS["personal_story"])
    has_result = _contains_any(lowered, TYPE_KEYWORDS["result"])
    has_warning = _contains_any(lowered, TYPE_KEYWORDS["warning"])
    hook_bonus = 18 if re.search(r"\b(почему|как|важно|нельзя|главное|ошибка)\b", lowered) else 0
    density = clamp((word_count / max(duration, 1)) * 18, 35, 100)
    return {
        "semantic_interest_score": clamp(48 + questions * 8 + has_conflict * 16 + has_story * 10 + has_result * 8 + has_warning * 10, 0, 100),
        "hook_score": clamp(45 + hook_bonus + questions * 8 + has_conflict * 8, 0, 100),
        "clarity_score": clamp(82 - max(0, duration - 50) * 0.4, 35, 100),
        "emotion_score": clamp(45 + has_story * 15 + has_warning * 12 + has_conflict * 10, 0, 100),
        "novelty_score": clamp(50 + has_conflict * 12 + has_result * 6, 0, 100),
        "standalone_score": clamp(70 + has_result * 10 - max(0, 18 - duration), 0, 100),
        "retention_score": clamp(52 + hook_bonus * 0.7 + has_conflict * 8 + has_result * 6, 0, 100),
        "speech_density_score": density,
        "audio_energy_score": 50,
        "visual_energy_score": 50,
    }


def build_windows(sentences: list[SentenceSegment], min_duration: float, max_duration: float) -> list[list[SentenceSegment]]:
    windows: list[list[SentenceSegment]] = []
    index = 0
    while index < len(sentences):
        current: list[SentenceSegment] = []
        for sentence in sentences[index:]:
            if current and sentence.end - current[0].start > max_duration:
                break
            current.append(sentence)
            if current[-1].end - current[0].start >= min_duration:
                break
        if current:
            windows.append(current)
        index += max(1, len(current) // 2)
    return windows


def analyze_with_heuristics(sentences: list[SentenceSegment], config: Settings) -> list[InterestingMoment]:
    windows = build_windows(sentences, config.clips.min_duration_sec, config.clips.max_duration_sec)
    moments: list[InterestingMoment] = []
    for index, window in enumerate(windows, start=1):
        start = window[0].start
        end = window[-1].end
        duration = end - start
        text = " ".join(sentence.text for sentence in window)
        scores = score_text(text, duration)
        base_score = calculate_base_score(scores)
        if base_score < max(35, config.clips.min_score - 25):
            continue
        moment_type = classify_moment(text)
        hook_text = summarize(window[0].text, 90)
        summary = summarize(text)
        problems = []
        if duration < config.clips.min_duration_sec:
            problems.append("short context")
        if duration > config.clips.max_duration_sec:
            problems.append("long clip")
        moment = InterestingMoment(
            id=f"moment_{index:03}",
            start=round(start, 2),
            end=round(end, 2),
            duration=round(duration, 2),
            text=text,
            summary=summary,
            moment_type=moment_type,
            hook_text=hook_text,
            payoff_text=summarize(window[-1].text, 100),
            base_score=base_score,
            personal_score=base_score,
            final_score=base_score,
            reason=f"Potentially interesting moment: {moment_type.replace('_', ' ')} with a clear hook and standalone idea.",
            problems=problems,
            suggested_title=hook_text[:80],
            suggested_caption=f"{summary}\n\n#shorts #tiktok #reels",
            **scores,
        )
        moment = apply_quality_penalty(moment)
        if moment.final_score < max(35, config.clips.min_score - 15) or "ad or CTA language" in moment.problems:
            continue
        moments.append(moment)
    return sorted(moments, key=lambda item: item.final_score, reverse=True)[: config.clips.target_count]
