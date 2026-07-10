from __future__ import annotations

from dataclasses import dataclass
import math
import re

from backend.core.config import DynamicEditConfig
from backend.schemas.clips import ClipCandidate
from backend.schemas.transcript import Transcript
from backend.services.content_quality import repair_mojibake


@dataclass(frozen=True)
class MontageProfile:
    max_beats: int
    seconds_per_beat: float
    min_gap_sec: float
    zoom_scale: float
    beat_duration_sec: float


@dataclass(frozen=True)
class MontageBeat:
    timestamp: float
    duration: float
    score: float
    kind: str
    reason: str
    scale_to: float


@dataclass(frozen=True)
class SemanticAccent:
    timestamp: float
    duration: float
    score: float
    kind: str
    text: str
    reason: str


@dataclass(frozen=True)
class ShotMotion:
    start: float
    end: float
    scale_from: float
    scale_to: float
    reason: str


@dataclass(frozen=True)
class _SpokenWord:
    text: str
    start: float
    end: float
    speaker: str | None
    probability: float | None = None


@dataclass(frozen=True)
class _BeatCandidate:
    timestamp: float
    score: float
    kind: str
    reason: str


PROFILES = {
    "clean": MontageProfile(0, 60.0, 8.0, 1.0, 0.0),
    "balanced": MontageProfile(2, 16.0, 5.2, 1.035, 1.20),
    "aggressive": MontageProfile(3, 9.0, 3.8, 1.065, 1.05),
    "podcast": MontageProfile(1, 22.0, 8.0, 1.030, 1.25),
    "gaming": MontageProfile(4, 7.0, 3.2, 1.080, 0.95),
    "banger": MontageProfile(3, 10.0, 4.4, 1.045, 1.10),
    "story": MontageProfile(1, 22.0, 8.0, 1.026, 1.20),
    "meme": MontageProfile(4, 6.5, 2.9, 1.085, 0.90),
}

QUESTION_PREFIXES = ("почему", "зачем", "разве", "неужели")
QUESTION_CUES = {
    "почему",
    "зачем",
    "разве",
    "неужели",
    "кто",
    "кого",
    "кому",
    "где",
    "куда",
    "откуда",
    "когда",
    "сколько",
    "какой",
    "какая",
    "какие",
    "какое",
    "как",
    "что",
    "че",
    "чего",
}
QUESTION_FILLERS = {"а", "в", "во", "да", "же", "ли", "на", "не", "нет", "ну", "просто", "с", "так", "типа", "это"}
CONTRAST_PREFIXES = ("но", "однако", "зато", "хотя", "вместо")
REVEAL_PREFIXES = ("поэтому", "значит", "итог", "вывод", "главное", "получается")
STAKES_PREFIXES = ("важн", "проблем", "ошиб", "страх", "тревож", "никогда", "всегда")
TOKEN_RE = re.compile(r"\w+(?:[?!.,…]+)?", re.UNICODE)
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?%?", re.UNICODE)
QUANTITY_SCORES = {
    "миллиард": 9.7,
    "миллиарда": 9.7,
    "миллионов": 9.6,
    "миллион": 9.6,
    "тысячи": 9.4,
    "тысяч": 9.4,
    "сотни": 9.2,
    "сотен": 9.2,
}
FACT_UNIT_PREFIXES = (
    "год",
    "лет",
    "месяц",
    "дн",
    "час",
    "минут",
    "секунд",
    "процент",
    "миллион",
    "миллиард",
    "тысяч",
    "раз",
)


def montage_profile(name: str) -> MontageProfile:
    return PROFILES.get(name, PROFILES["balanced"])


def _tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(repair_mojibake(text))


def _clip_words(clip: ClipCandidate, transcript: Transcript | None) -> list[_SpokenWord]:
    if transcript is None:
        return []
    words: list[_SpokenWord] = []
    for segment in transcript.segments:
        if segment.end < clip.start or segment.start > clip.end:
            continue
        if segment.words:
            for word in segment.words:
                if word.end < clip.start or word.start > clip.end:
                    continue
                words.append(
                    _SpokenWord(
                        text=repair_mojibake(word.word).strip(),
                        start=max(0.0, word.start - clip.start),
                        end=min(clip.duration, word.end - clip.start),
                        speaker=word.speaker or segment.speaker,
                        probability=word.probability,
                    )
                )
            continue

        tokens = _tokens(segment.text)
        if not tokens:
            continue
        segment_start = max(segment.start, clip.start)
        segment_end = min(segment.end, clip.end)
        step = max(0.05, (segment_end - segment_start) / len(tokens))
        for index, token in enumerate(tokens):
            start = segment_start + index * step
            words.append(
                _SpokenWord(
                    text=token,
                    start=max(0.0, start - clip.start),
                    end=min(clip.duration, start + step - clip.start),
                    speaker=segment.speaker,
                    probability=None,
                )
            )
    return sorted(words, key=lambda word: (word.start, word.end))


def _normalized_word(value: str) -> str:
    return re.sub(r"[^\w]+", "", repair_mojibake(value).lower(), flags=re.UNICODE)


def _semantic_candidate(word: _SpokenWord, moment_type: str) -> _BeatCandidate | None:
    normalized = _normalized_word(word.text)
    if not normalized:
        return None
    timestamp = word.start + 0.06
    if normalized in QUESTION_PREFIXES:
        boost = 0.4 if moment_type in {"controversial_take", "question"} else 0.0
        return _BeatCandidate(timestamp, 9.4 + boost, "question", f"question cue: {normalized}")
    if normalized in REVEAL_PREFIXES:
        boost = 0.4 if moment_type in {"insight", "explanation"} else 0.0
        return _BeatCandidate(timestamp, 8.9 + boost, "reveal", f"reveal cue: {normalized}")
    if normalized in CONTRAST_PREFIXES:
        boost = 0.4 if moment_type == "controversial_take" else 0.0
        return _BeatCandidate(timestamp, 8.5 + boost, "contrast", f"contrast cue: {normalized}")
    if any(normalized.startswith(prefix) for prefix in STAKES_PREFIXES):
        return _BeatCandidate(timestamp, 7.9, "stakes", f"stakes cue: {normalized}")
    return None


def _question_candidate(words: list[_SpokenWord], index: int, moment_type: str) -> _BeatCandidate | None:
    if "?" not in words[index].text:
        return None
    start = index
    while start > 0 and index - start < 11:
        previous = words[start - 1]
        current = words[start]
        if current.start - previous.end > 0.65 or previous.text.rstrip().endswith((".", "!", "?", ";", ":", "…")):
            break
        start -= 1
    phrase = words[start : index + 1]
    normalized = [_normalized_word(word.text) for word in phrase]
    cue_offset = next((offset for offset, token in enumerate(normalized) if token in QUESTION_CUES), None)
    if cue_offset is None:
        return None
    cue = normalized[cue_offset]
    content = [token for token in normalized if token and token not in QUESTION_FILLERS and len(token) >= 3]
    strong_single = cue in {"почему", "зачем", "разве", "неужели"}
    if not strong_single and (len(phrase) < 3 or len(content) < 2):
        return None
    anchor = phrase[cue_offset]
    confidence = anchor.probability if anchor.probability is not None else 0.75
    boost = 0.4 if moment_type in {"controversial_take", "question", "question_answer"} else 0.0
    preview = " ".join(repair_mojibake(word.text).strip() for word in phrase[:6])
    return _BeatCandidate(
        anchor.start + 0.06,
        9.45 + boost + max(0.0, min(1.0, confidence)) * 0.15,
        "question",
        f"question phrase: {preview}",
    )


def _fact_label(words: list[_SpokenWord], index: int) -> str:
    value = repair_mojibake(words[index].text).strip(" ,.!?;:…")
    label = value
    if index + 1 < len(words):
        next_word = words[index + 1]
        normalized = _normalized_word(next_word.text)
        close_enough = next_word.start - words[index].end <= 0.42
        if close_enough and any(normalized.startswith(prefix) for prefix in FACT_UNIT_PREFIXES):
            label += " " + repair_mojibake(next_word.text).strip(" ,.!?;:…")
    return label.upper()[:24]


def plan_semantic_accents(
    clip: ClipCandidate,
    transcript: Transcript | None,
    *,
    scene_cuts: list[float] | None = None,
) -> list[SemanticAccent]:
    words = _clip_words(clip, transcript)
    if not words:
        return []
    cuts = scene_cuts or []
    evidence: list[SemanticAccent] = []
    semantic: list[SemanticAccent] = []
    for index, word in enumerate(words):
        normalized = _normalized_word(word.text)
        if NUMBER_RE.fullmatch(normalized) or normalized in QUANTITY_SCORES:
            digit_count = sum(character.isdigit() for character in normalized)
            score = 9.6 + min(0.8, digit_count * 0.12) if digit_count else QUANTITY_SCORES[normalized]
            evidence.append(
                SemanticAccent(
                    timestamp=max(0.35, round(word.start - 0.04, 2)),
                    duration=1.28,
                    score=round(score, 2),
                    kind="evidence",
                    text=_fact_label(words, index),
                    reason=f"timed factual anchor: {normalized}",
                )
            )
            continue
        candidate = _question_candidate(words, index, clip.moment_type) or _semantic_candidate(word, clip.moment_type)
        if candidate and candidate.kind in {"question", "reveal", "contrast"}:
            semantic.append(
                SemanticAccent(
                    timestamp=round(candidate.timestamp, 2),
                    duration=0.18,
                    score=round(candidate.score, 2),
                    kind=candidate.kind,
                    text="",
                    reason=candidate.reason,
                )
            )

    selected: list[SemanticAccent] = []
    for accent in sorted(evidence, key=lambda item: (-item.score, item.timestamp)):
        if accent.timestamp > clip.duration - 1.1 or any(abs(accent.timestamp - cut) < 0.18 for cut in cuts):
            continue
        if any(abs(accent.timestamp - existing.timestamp) < 6.0 for existing in selected):
            continue
        selected.append(accent)
        if len(selected) >= 2:
            break
    audible = next(
        (
            accent
            for accent in sorted(semantic, key=lambda item: (-item.score, item.timestamp))
            if accent.score >= 9.0
            and accent.timestamp <= clip.duration - 1.1
            and all(abs(accent.timestamp - cut) >= 0.60 for cut in cuts)
        ),
        None,
    )
    if audible is not None:
        selected.append(audible)
    return sorted(selected, key=lambda item: item.timestamp)


def plan_shot_motion(
    clip: ClipCandidate,
    *,
    profile_name: str,
    scene_cuts: list[float] | None = None,
) -> list[ShotMotion]:
    if profile_name == "clean" or not scene_cuts:
        return []
    duration = max(1.0, clip.end - clip.start)
    cuts = sorted(cut for cut in scene_cuts if 0.08 < cut < duration - 0.4)
    boundaries = [0.0, *cuts, duration]
    eligible = [
        (index, start, end)
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]))
        if end - start >= 4.2 and (start >= 0.18 or end >= 0.70)
    ]
    if not eligible:
        return []

    max_scale = {
        "podcast": 1.018,
        "balanced": 1.020,
        "story": 1.022,
        "banger": 1.026,
        "aggressive": 1.028,
        "gaming": 1.028,
        "meme": 1.028,
    }.get(profile_name, 1.020)
    motions: list[ShotMotion] = []
    for motion_index, (shot_index, start, end) in enumerate(eligible[:3]):
        stable_end = max(start + 0.8, end - (0.22 if end >= duration - 0.05 else 0.04))
        if motion_index == 2:
            scale_from, scale_to = min(max_scale, 1.018), 1.002
            direction = "release"
        elif motion_index == 1:
            scale_from, scale_to = 1.008, max_scale
            direction = "build"
        else:
            scale_from, scale_to = 1.0, min(max_scale, 1.022)
            direction = "push"
        motions.append(
            ShotMotion(
                start=round(start, 2),
                end=round(stable_end, 2),
                scale_from=round(scale_from, 3),
                scale_to=round(scale_to, 3),
                reason=f"source shot {shot_index}: cut-shaped {direction}",
            )
        )
    return motions


def _dedupe_candidates(candidates: list[_BeatCandidate]) -> list[_BeatCandidate]:
    selected: list[_BeatCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (-item.score, item.timestamp)):
        if any(abs(candidate.timestamp - existing.timestamp) < 0.55 for existing in selected):
            continue
        selected.append(candidate)
    return selected


def _beat_budget(
    duration: float,
    profile: MontageProfile,
    config: DynamicEditConfig,
    scene_cuts: list[float],
) -> int:
    if profile.max_beats <= 0 or config.max_punch_zoom_per_10_sec <= 0:
        return 0
    duration_budget = max(1, math.ceil(duration / profile.seconds_per_beat))
    configured_budget = max(1, int(duration / 10 * config.max_punch_zoom_per_10_sec))
    base_budget = min(profile.max_beats, duration_budget, configured_budget)
    natural_edit_credit = (len(scene_cuts) + 1) // 2
    opening_span = scene_cuts[0] if scene_cuts else duration
    opening_floor = 1 if opening_span >= max(4.8, profile.min_gap_sec) else 0
    return max(opening_floor, base_budget - natural_edit_credit)


def plan_montage_beats(
    clip: ClipCandidate,
    config: DynamicEditConfig,
    *,
    profile_name: str,
    transcript: Transcript | None = None,
    scene_cuts: list[float] | None = None,
) -> list[MontageBeat]:
    duration = max(1.0, clip.end - clip.start)
    profile = montage_profile(profile_name)
    cuts = sorted(cut for cut in (scene_cuts or []) if 0.08 < cut < duration - 0.4)
    budget = _beat_budget(duration, profile, config, cuts)
    if budget == 0:
        return []

    words = _clip_words(clip, transcript)
    candidates: list[_BeatCandidate] = []
    if words and words[0].start < 2.4:
        candidates.append(
            _BeatCandidate(
                timestamp=max(0.45, words[0].start + 0.12),
                score=10.5,
                kind="hook",
                reason="hook: first spoken phrase",
            )
        )
    elif repair_mojibake(clip.hook_text or clip.text).strip():
        candidates.append(_BeatCandidate(0.55, 9.8, "hook", "hook: transcript timing unavailable"))

    pause_threshold = max(0.50, config.max_pause_sec)
    for index, word in enumerate(words):
        semantic = _question_candidate(words, index, clip.moment_type) or _semantic_candidate(word, clip.moment_type)
        if semantic is not None:
            candidates.append(semantic)
        if index == 0:
            continue
        previous = words[index - 1]
        if word.start - previous.end >= pause_threshold:
            candidates.append(
                _BeatCandidate(word.start + 0.05, 7.7, "resume", "speech resumes after a meaningful pause")
            )
        if word.speaker and previous.speaker and word.speaker != previous.speaker:
            candidates.append(_BeatCandidate(word.start + 0.04, 8.3, "speaker", "speaker change"))

    guard = max(0.35, config.scene_guard_sec)
    min_gap = max(profile.min_gap_sec, config.pattern_interrupt_every_sec)
    chosen: list[_BeatCandidate] = []
    for candidate in _dedupe_candidates(candidates):
        if candidate.timestamp < 0.35 or candidate.timestamp > duration - 1.45:
            continue
        if any(abs(candidate.timestamp - cut) < guard for cut in cuts):
            continue
        if any(abs(candidate.timestamp - existing.timestamp) < min_gap for existing in chosen):
            continue
        chosen.append(candidate)
        if len(chosen) >= budget:
            break

    beats: list[MontageBeat] = []
    for candidate in sorted(chosen, key=lambda item: item.timestamp):
        intensity = max(0.55, min(1.0, candidate.score / 10.5))
        scale_to = 1.0 + (profile.zoom_scale - 1.0) * intensity
        beat_duration = min(profile.beat_duration_sec, duration - candidate.timestamp)
        beats.append(
            MontageBeat(
                timestamp=round(candidate.timestamp, 2),
                duration=round(max(0.65, beat_duration), 2),
                score=round(candidate.score, 2),
                kind=candidate.kind,
                reason=candidate.reason,
                scale_to=round(scale_to, 3),
            )
        )
    return beats
