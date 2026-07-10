from __future__ import annotations

from collections import Counter
import re

from backend.core.config import Settings
from backend.core.utils import clamp
from backend.schemas.moments import InterestingMoment, SentenceSegment
from backend.services.content_quality import apply_quality_penalty, repair_mojibake
from backend.services.viral_score import calculate_base_score


TYPE_KEYWORDS = {
    "controversial_take": ("ошибка", "миф", "неправильно", "спор", "проблема", "никогда", "херня"),
    "how_to": ("как ", "шаг", "сделать", "нужно", "способ"),
    "warning": ("важно", "нельзя", "опасно", "риск", "осторожно"),
    "result": ("результат", "получилось", "итог", "вывод", "стало", "теперь", "обогнал", "место"),
    "before_after": ("раньше", "теперь", "было", "стало", "до ", "после", "вместо"),
    "personal_story": ("я ", "мне", "мой", "моя", "история", "однажды"),
}

RESULT_WORDS = (
    "результат",
    "получилось",
    "оказалось",
    "выяснилось",
    "итог",
    "обогнал",
    "заработал",
    "принес",
    "вырос",
    "место",
    "рекорд",
    "приобрел",
    "приобрёл",
)
QUANTITY_WORDS = (
    "миллион",
    "тысяч",
    "сотен",
    "процент",
    "рубл",
    "пользовател",
    "подписчик",
    "мест",
)
DEPENDENT_OPENINGS = (
    "и ",
    "а ",
    "но ",
    "это ",
    "вот ",
    "так вот",
    "как раз",
    "поэтому",
    "кстати",
    "короче",
    "теперь",
    "там ",
    "тут ",
    "на то",
    "после этого",
    "в общем",
    "вы можете подумать",
    "мы подготовили",
    "супер ответственный",
    "о, и, кстати",
    "как раз кубик",
)
TEASER_PHRASES = (
    "обязательно вернемся",
    "обязательно вернёмся",
    "дальше в ролике",
    "сначала про",
    "пока кубик",
    "кубик приземлился",
    "расскажу чуть позже",
)
HUMOR_MARKERS = ("шучу", "прикол", "но нет", "если бы", "смешн", "ха-ха", "ахаха", "ебать", "культ", "мем")
DANGLING_WORDS = {"а", "и", "или", "но", "если", "когда", "потому", "поэтому", "что", "чтобы", "короче"}
NUMBER_RE = re.compile(r"\b\d[\d\s.,]*%?\b", re.UNICODE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


def _normalized(text: str) -> str:
    return " ".join(repair_mojibake(text).lower().replace("ё", "е").split())


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    lowered = _normalized(text)
    return any(word in lowered for word in words)


def _first_phrase(text: str, max_words: int = 16) -> str:
    clean = " ".join(repair_mojibake(text).split())
    first = SENTENCE_SPLIT_RE.split(clean, maxsplit=1)[0]
    return " ".join(first.split()[:max_words])


def _has_quantity(text: str) -> bool:
    lowered = _normalized(text)
    word_quantity = any(word in lowered for word in QUANTITY_WORDS)
    numeric = NUMBER_RE.search(lowered)
    large_number = bool(numeric and len(re.sub(r"\D", "", numeric.group(0))) >= 3)
    return word_quantity or large_number


def _has_result(text: str) -> bool:
    lowered = _normalized(text)
    before_after = ("было" in lowered and "теперь" in lowered) or ("раньше" in lowered and "сейчас" in lowered)
    return before_after or any(word in lowered for word in RESULT_WORDS)


def classify_moment(text: str) -> str:
    lowered = _normalized(text)
    if "дизайн" in lowered:
        return "before_after"
    if any(marker in lowered for marker in ("культ", "мем")):
        return "comedy"
    if _has_quantity(lowered) and _has_result(lowered):
        return "metric_reveal"
    if any(marker in lowered for marker in HUMOR_MARKERS):
        return "comedy"
    if _contains_any(lowered, TYPE_KEYWORDS["controversial_take"]):
        return "controversial_take"
    if "?" in text:
        return "question_answer"
    if _contains_any(lowered, TYPE_KEYWORDS["before_after"]):
        return "before_after"
    if _contains_any(lowered, TYPE_KEYWORDS["how_to"]):
        return "how_to"
    if _contains_any(lowered, TYPE_KEYWORDS["warning"]):
        return "warning"
    if _contains_any(lowered, TYPE_KEYWORDS["result"]):
        return "result"
    if _contains_any(lowered, TYPE_KEYWORDS["personal_story"]):
        return "personal_story"
    return "insight"


def summarize(text: str, max_chars: int = 180) -> str:
    clean = " ".join(repair_mojibake(text).split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip().rsplit(" ", 1)[0] + "..."


def score_text(text: str, duration: float) -> dict[str, float]:
    clean = " ".join(repair_mojibake(text).split())
    lowered = _normalized(clean)
    first = _normalized(_first_phrase(clean))
    words = re.findall(r"[a-zа-я0-9]+", lowered, flags=re.IGNORECASE)
    word_rate = len(words) / max(duration, 1.0)
    questions = clean.count("?")
    exclamations = clean.count("!")
    has_conflict = _contains_any(lowered, TYPE_KEYWORDS["controversial_take"])
    has_story = _contains_any(lowered, TYPE_KEYWORDS["personal_story"])
    has_result = _has_result(lowered)
    has_quantity = _has_quantity(lowered)
    has_humor = any(marker in lowered for marker in HUMOR_MARKERS)
    has_contrast = any(word in lowered for word in (" но ", " однако ", " зато ", " вместо "))
    dependent_opening = first.startswith(DEPENDENT_OPENINGS)
    teaser = any(phrase in lowered for phrase in TEASER_PHRASES)
    last_word = words[-1] if words else ""
    unfinished = clean.rstrip().endswith((",", ";", ":")) or last_word in DANGLING_WORDS
    first_has_hook = "?" in _first_phrase(clean) or "!" in _first_phrase(clean) or _has_quantity(first)

    hook_strength = questions * 11 + exclamations * 5 + has_quantity * 14 + has_conflict * 12
    if dependent_opening and not first_has_hook:
        hook_strength -= 22
    if teaser:
        hook_strength -= 18
    payoff = has_result or has_quantity or (has_contrast and not unfinished)

    return {
        "semantic_interest_score": clamp(
            38 + has_conflict * 16 + has_story * 5 + has_result * 18 + has_quantity * 12 + has_humor * 12 + questions * 6 - teaser * 20,
            0,
            100,
        ),
        "hook_score": clamp(36 + hook_strength, 0, 100),
        "clarity_score": clamp(78 - dependent_opening * 20 - teaser * 20 - unfinished * 16 - max(0, duration - 42) * 0.7, 0, 100),
        "emotion_score": clamp(38 + has_conflict * 15 + has_story * 7 + has_humor * 16 + questions * 5 + exclamations * 8 + has_quantity * 5, 0, 100),
        "novelty_score": clamp(40 + has_conflict * 14 + has_result * 15 + has_quantity * 14 + has_humor * 14, 0, 100),
        "standalone_score": clamp(76 - dependent_opening * 24 - teaser * 28 - unfinished * 24 + payoff * 14, 0, 100),
        "retention_score": clamp(40 + max(0, hook_strength) * 0.62 + payoff * 16 + has_contrast * 8 + has_humor * 12 - teaser * 20, 0, 100),
        "speech_density_score": clamp(word_rate * 28, 25, 100),
        "audio_energy_score": clamp(36 + min(28, exclamations * 8) + min(12, questions * 4) + min(20, word_rate * 7), 0, 100),
        "visual_energy_score": 45,
    }


def build_windows(
    sentences: list[SentenceSegment],
    min_duration: float,
    max_duration: float,
    preferred_duration: float | None = None,
) -> list[list[SentenceSegment]]:
    preferred = clamp(preferred_duration or min_duration * 1.6, min_duration, max_duration)
    targets = sorted({min_duration, preferred, min(max_duration, preferred + 12.0)})
    windows: list[list[SentenceSegment]] = []
    seen: set[tuple[str, str]] = set()
    for index in range(0, len(sentences), 2):
        for target in targets:
            current: list[SentenceSegment] = []
            for sentence in sentences[index:]:
                if current and sentence.end - current[0].start > max_duration:
                    break
                current.append(sentence)
                if current[-1].end - current[0].start >= target:
                    break
            if not current or current[-1].end - current[0].start < min_duration * 0.85:
                continue
            key = (current[0].id, current[-1].id)
            if key not in seen:
                seen.add(key)
                windows.append(current)
    return windows


def speaker_metrics(window: list[SentenceSegment]) -> dict[str, float]:
    ordered_speakers: list[str] = []
    for sentence in window:
        if sentence.speakers:
            ordered_speakers.extend(sentence.speakers)
        elif sentence.speaker:
            ordered_speakers.append(sentence.speaker)
    counts = Counter(ordered_speakers)
    unique = list(counts)
    switches = sum(1 for left, right in zip(ordered_speakers, ordered_speakers[1:]) if left != right)
    switches += sum(sentence.speaker_switches for sentence in window)
    speaker_count = len(unique)
    dialogue_score = 0.0
    if speaker_count >= 2:
        contributions = sorted(counts.values(), reverse=True)
        balanced_enough = len(contributions) > 1 and contributions[1] >= 2 and contributions[1] / sum(contributions) >= 0.12
        if balanced_enough and switches >= 2:
            duration = max(1.0, window[-1].end - window[0].start)
            switch_rate = switches / duration
            dialogue_score = clamp(38 + (speaker_count - 1) * 15 + min(25, switch_rate * 85), 0, 100)
    return {
        "speaker_count": float(speaker_count),
        "speaker_switches": float(switches),
        "dialogue_score": dialogue_score,
    }


def analyze_with_heuristics(sentences: list[SentenceSegment], config: Settings) -> list[InterestingMoment]:
    windows = build_windows(
        sentences,
        config.clips.min_duration_sec,
        config.clips.max_duration_sec,
        config.clips.preferred_duration_sec,
    )
    moments: list[InterestingMoment] = []
    for index, window in enumerate(windows, start=1):
        start = window[0].start
        end = window[-1].end
        duration = end - start
        text = " ".join(sentence.text for sentence in window)
        scores = score_text(text, duration)
        dialogue = speaker_metrics(window)
        base_score = calculate_base_score(scores)
        if base_score < max(32, config.clips.min_score - 22):
            continue
        moment_type = classify_moment(text)
        if dialogue["dialogue_score"] and moment_type == "insight":
            moment_type = "conversation"
        hook_text = summarize(window[0].text, 90)
        summary = summarize(text)
        problems: list[str] = []
        if duration < config.clips.min_duration_sec:
            problems.append("short context")
        if duration > config.clips.max_duration_sec:
            problems.append("long clip")
        moment = InterestingMoment(
            id=f"moment_{index:04}",
            start=round(start, 2),
            end=round(end, 2),
            duration=round(duration, 2),
            text=text,
            summary=summary,
            moment_type=moment_type,
            hook_text=hook_text,
            payoff_text=summarize(window[-1].text, 100),
            speaker_count=int(dialogue["speaker_count"]),
            speaker_switches=int(dialogue["speaker_switches"]),
            dialogue_score=dialogue["dialogue_score"],
            base_score=base_score,
            personal_score=base_score,
            final_score=base_score,
            reason=f"Content arc: {moment_type.replace('_', ' ')}; hook and payoff scored from the transcript.",
            problems=problems,
            suggested_title=hook_text[:80],
            suggested_caption=f"{summary}\n\n#shorts #tiktok #reels",
            **scores,
        )
        moment = apply_quality_penalty(moment)
        if moment.final_score >= max(32, config.clips.min_score - 18):
            moments.append(moment)
    pool_size = max(config.clips.target_count * 20, 120)
    return sorted(moments, key=lambda item: item.final_score, reverse=True)[:pool_size]
