from __future__ import annotations

from dataclasses import dataclass
import re

from backend.core.config import Settings
from backend.core.utils import clamp
from backend.schemas.moments import InterestingMoment, SentenceSegment
from backend.services.content_quality import commercial_evidence, normalize_quality_text, quality_penalty, repair_mojibake
from backend.services.heuristic_analyzer import classify_moment, score_text, summarize
from backend.services.viral_score import calculate_base_score


TEASER_PHRASES = (
    "обязательно вернемся",
    "обязательно вернёмся",
    "дальше в ролике",
    "сначала про",
    "расскажу чуть позже",
    "пока кубик",
    "кубик уже",
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
RESULT_MARKERS = (
    "получилось",
    "оказалось",
    "выяснилось",
    "результат",
    "обогнал",
    "заработал",
    "место",
)
TOPIC_RESET_PHRASES = (
    "теперь можно взрывать",
    "идем дальше",
    "идём дальше",
    "а пока",
    "про эту клетку",
    "кубик снова",
    "кубик уже",
    "кстати, про пользовател",
)
FILLER_OPENINGS = (
    "как так совпало",
    "о-о-о",
    "ооо",
    "вы можете подумать",
    "супер ответственный момент",
    "мы подготовили",
)
DANGLING_WORDS = {"а", "и", "или", "но", "если", "когда", "потому", "поэтому", "что", "чтобы", "короче"}
HARD_REJECT_PROBLEMS = {"ad or CTA language", "promotional segment", "teaser without payoff"}
TOKEN_RE = re.compile(r"[a-zа-я0-9]+", re.IGNORECASE)
NUMBER_RE = re.compile(r"\b\d[\d\s.,]*%?\b", re.UNICODE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
STOPWORDS = {
    "это",
    "как",
    "что",
    "для",
    "или",
    "уже",
    "еще",
    "ещё",
    "там",
    "тут",
    "вот",
    "если",
    "когда",
    "можно",
    "нужно",
    "потом",
    "просто",
    "очень",
    "вообще",
}


@dataclass
class CandidateInterval:
    moment: InterestingMoment
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class PromotionalBlock:
    core_start: float
    core_end: float
    padded_start: float
    padded_end: float
    evidence: tuple[str, ...]


def _normalize(text: str) -> str:
    return normalize_quality_text(repair_mojibake(text)).replace("ё", "е")


def _terms(text: str) -> set[str]:
    return {word for word in TOKEN_RE.findall(_normalize(text)) if len(word) >= 4 and word not in STOPWORDS}


def _first_phrase(text: str, max_words: int = 12) -> str:
    clean = " ".join(repair_mojibake(text).split())
    phrase = SENTENCE_SPLIT_RE.split(clean, maxsplit=1)[0]
    return " ".join(phrase.split()[:max_words]).strip(" ,;:-")


def _last_phrase(text: str) -> str:
    parts = [part.strip() for part in SENTENCE_SPLIT_RE.split(" ".join(repair_mojibake(text).split())) if part.strip()]
    return parts[-1] if parts else ""


def _has_concrete_payoff(text: str) -> bool:
    normalized = _normalize(text)
    before_after = ("было" in normalized and "теперь" in normalized) or ("раньше" in normalized and "сейчас" in normalized)
    result = any(marker in normalized for marker in RESULT_MARKERS)
    spoken_quantity = any(marker in normalized for marker in ("миллион", "тысяч", "рубл", "процент", "место"))
    meaningful_quantity = bool(NUMBER_RE.search(normalized)) and any(
        marker in normalized for marker in ("миллион", "тысяч", "рубл", "мест", "пользовател", "подписчик", "процент")
    )
    return before_after or result or spoken_quantity or meaningful_quantity


def structural_penalty(text: str) -> tuple[float, list[str]]:
    clean = " ".join(repair_mojibake(text).split())
    normalized = _normalize(clean)
    first = _normalize(_first_phrase(clean))
    words = TOKEN_RE.findall(normalized)
    last_word = words[-1] if words else ""
    concrete = _has_concrete_payoff(clean)
    strong_hook = "?" in _first_phrase(clean) or "!" in _first_phrase(clean) or bool(NUMBER_RE.search(first))
    problems: list[str] = []
    penalty = 0.0

    if first.startswith(DEPENDENT_OPENINGS) and not strong_hook:
        problems.append("dependent opening")
        penalty += 14
    if first.startswith(FILLER_OPENINGS):
        problems.append("filler opening")
        penalty += 18
    if any(phrase in normalized for phrase in TEASER_PHRASES) and not concrete:
        problems.append("teaser without payoff")
        penalty += 38
    reset_positions = [normalized.find(phrase) for phrase in TOPIC_RESET_PHRASES if phrase in normalized]
    if reset_positions and min(reset_positions) > len(normalized) * 0.25:
        problems.append("mixed topics")
        penalty += 26
    unfinished = clean.rstrip().endswith((",", ";", ":", "...", "…")) or last_word in DANGLING_WORDS
    if unfinished:
        problems.append("unfinished ending")
        penalty += 22
    if clean.rstrip().endswith("?"):
        problems.append("unanswered question")
        penalty += 28
    if not concrete and len(words) >= 18 and not any(mark in clean for mark in ("?", "!")):
        problems.append("weak payoff")
        penalty += 9
    return penalty, problems


def promotional_blocks(sentences: list[SentenceSegment]) -> list[PromotionalBlock]:
    if not sentences:
        return []
    ordered = sorted(sentences, key=lambda sentence: (sentence.start, sentence.end))
    evidence = [commercial_evidence(sentence.text) for sentence in ordered]
    seeds: list[tuple[int, int]] = [
        (index, index)
        for index, categories in enumerate(evidence)
        if categories & {"disclosure", "cta"}
    ]
    for left in range(len(ordered)):
        categories: set[str] = set()
        right = left
        while right < len(ordered) and ordered[right].end - ordered[left].start <= 30.0:
            if right > left and ordered[right].start - ordered[right - 1].end > 2.8:
                break
            categories.update(evidence[right])
            if {"brand", "offer", "urgency"}.issubset(categories):
                seeds.append((left, right))
                break
            right += 1

    expanded: list[tuple[int, int]] = []
    for seed_left, seed_right in seeds:
        left, right = seed_left, seed_right
        misses = 0
        while left > 0 and ordered[left].start - ordered[left - 1].end <= 2.8:
            candidate = left - 1
            misses = 0 if evidence[candidate] else misses + 1
            if misses >= 3 or ordered[seed_left].start - ordered[candidate].start > 55.0:
                break
            left = candidate
        misses = 0
        while right + 1 < len(ordered) and ordered[right + 1].start - ordered[right].end <= 2.8:
            candidate = right + 1
            misses = 0 if evidence[candidate] else misses + 1
            if misses >= 3 or ordered[candidate].end - ordered[seed_right].end > 12.0:
                break
            right = candidate
        expanded.append((left, right))

    merged: list[tuple[int, int]] = []
    for left, right in sorted(set(expanded)):
        if merged and ordered[left].start <= ordered[merged[-1][1]].end + 3.0:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))

    blocks: list[PromotionalBlock] = []
    for left, right in merged:
        categories = sorted(set().union(*evidence[left : right + 1]))
        core_start = ordered[left].start
        core_end = ordered[right].end
        blocks.append(
            PromotionalBlock(
                core_start=round(core_start, 2),
                core_end=round(core_end, 2),
                padded_start=round(max(0.0, core_start - 4.0), 2),
                padded_end=round(core_end + 3.0, 2),
                evidence=tuple(categories),
            )
        )
    return blocks


def promotional_ranges(sentences: list[SentenceSegment]) -> list[tuple[float, float]]:
    return [(block.core_start, block.core_end) for block in promotional_blocks(sentences)]


def _text_for_interval(sentences: list[SentenceSegment], start: float, end: float) -> str:
    return " ".join(
        repair_mojibake(sentence.text).strip()
        for sentence in sentences
        if sentence.end > start + 0.02 and sentence.start < end - 0.02 and repair_mojibake(sentence.text).strip()
    )


def calibrate_moment(
    moment: InterestingMoment,
    *,
    text: str | None = None,
    start: float | None = None,
    end: float | None = None,
    scene_cuts: list[float] | None = None,
) -> InterestingMoment:
    actual_start = moment.start if start is None else start
    actual_end = moment.end if end is None else end
    duration = max(1.0, actual_end - actual_start)
    actual_text = " ".join(repair_mojibake(text or moment.text).split())
    scores = score_text(actual_text, duration)
    cuts = [cut for cut in (scene_cuts or []) if actual_start <= cut <= actual_end]
    if scene_cuts is not None:
        cut_rate = len(cuts) / duration
        scores["visual_energy_score"] = clamp(38 + min(54, cut_rate * 145), 25, 92)

    text_penalty, text_problems = quality_penalty(actual_text)
    arc_penalty, arc_problems = structural_penalty(actual_text)
    base_score = calculate_base_score(scores)
    adjusted = round(clamp(base_score - text_penalty - arc_penalty, 0, 100), 2)
    problems = list(dict.fromkeys([*text_problems, *arc_problems]))
    hook = _first_phrase(actual_text) or repair_mojibake(moment.hook_text)
    payoff = _last_phrase(actual_text) or repair_mojibake(moment.payoff_text)
    summary = summarize(actual_text, 240)

    moment.start = round(actual_start, 2)
    moment.end = round(actual_end, 2)
    moment.duration = round(duration, 2)
    moment.text = actual_text
    moment.summary = summary
    moment.hook_text = hook[:90]
    moment.payoff_text = payoff[:120]
    moment.moment_type = classify_moment(actual_text)
    moment.problems = problems
    moment.suggested_title = hook[:80]
    moment.suggested_caption = summary
    for key, value in scores.items():
        setattr(moment, key, round(value, 2))
    moment.base_score = adjusted
    moment.personal_score = adjusted
    moment.final_score = adjusted
    moment.reason = (
        f"Calibrated content arc: hook={moment.hook_score:.0f}, standalone={moment.standalone_score:.0f}, "
        f"retention={moment.retention_score:.0f}, visual={moment.visual_energy_score:.0f}; "
        f"quality penalty={text_penalty + arc_penalty:.0f}."
    )
    return moment


def calibrate_candidate_intervals(
    candidates: list[CandidateInterval],
    sentences: list[SentenceSegment],
    scene_cuts: list[float] | None = None,
) -> list[CandidateInterval]:
    for candidate in candidates:
        text = _text_for_interval(sentences, candidate.start, candidate.end)
        calibrate_moment(
            candidate.moment,
            text=text,
            start=candidate.start,
            end=candidate.end,
            scene_cuts=scene_cuts,
        )
    return candidates


def _overlap_ratio(left: CandidateInterval, right: CandidateInterval) -> float:
    overlap = max(0.0, min(left.end, right.end) - max(left.start, right.start))
    return overlap / max(0.001, min(left.duration, right.duration))


def _text_similarity(left: CandidateInterval, right: CandidateInterval) -> float:
    left_terms = _terms(left.moment.text)
    right_terms = _terms(right.moment.text)
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _promo_overlap(candidate: CandidateInterval, block: PromotionalBlock) -> tuple[float, float]:
    seconds = max(0.0, min(candidate.end, block.core_end) - max(candidate.start, block.core_start))
    return seconds, seconds / max(0.001, candidate.duration)


def _duplicate_reason(candidate: CandidateInterval, selected: list[CandidateInterval]) -> str | None:
    for existing in selected:
        overlap = _overlap_ratio(candidate, existing)
        similarity = _text_similarity(candidate, existing)
        midpoint_gap = abs((candidate.start + candidate.end) / 2 - (existing.start + existing.end) / 2)
        edge_gap = max(0.0, max(candidate.start, existing.start) - min(candidate.end, existing.end))
        if overlap >= 0.20:
            return f"temporal duplicate of {existing.moment.id} ({overlap:.0%} overlap)"
        if similarity >= 0.48:
            return f"topic duplicate of {existing.moment.id} ({similarity:.0%} term overlap)"
        if candidate.moment.moment_type == existing.moment.moment_type and similarity >= 0.22:
            return f"same {candidate.moment.moment_type} topic as {existing.moment.id} ({similarity:.0%} term overlap)"
        if midpoint_gap < 35 and not (candidate.moment.final_score >= 82 and existing.moment.final_score >= 82 and similarity < 0.15):
            return f"same source beat as {existing.moment.id} ({midpoint_gap:.1f}s apart)"
        if edge_gap <= 6 and similarity >= 0.25:
            return f"adjacent duplicate of {existing.moment.id}"
        if edge_gap <= 20 and candidate.moment.moment_type == existing.moment.moment_type:
            return f"adjacent {candidate.moment.moment_type} beat after {existing.moment.id}"
    return None


def select_candidate_intervals(
    candidates: list[CandidateInterval],
    sentences: list[SentenceSegment],
    config: Settings,
) -> tuple[list[CandidateInterval], dict]:
    promo_blocks = promotional_blocks(sentences)
    selected: list[CandidateInterval] = []
    rejected: list[dict] = []
    type_counts: dict[str, int] = {}
    ordered = sorted(candidates, key=lambda item: item.moment.final_score, reverse=True)

    for candidate in ordered:
        moment = candidate.moment
        overlaps = [_promo_overlap(candidate, block) for block in promo_blocks]
        if any(seconds >= 2.0 or ratio >= 0.10 for seconds, ratio in overlaps):
            if "promotional segment" not in moment.problems:
                moment.problems.append("promotional segment")
        hard_problem = next((problem for problem in moment.problems if problem in HARD_REJECT_PROBLEMS), None)
        if hard_problem:
            rejected.append({"id": moment.id, "score": moment.final_score, "reason": hard_problem})
            continue
        if moment.final_score < config.clips.min_score:
            rejected.append({"id": moment.id, "score": moment.final_score, "reason": "below quality gate"})
            continue
        if "unfinished ending" in moment.problems and moment.final_score < config.clips.min_score + 7:
            rejected.append({"id": moment.id, "score": moment.final_score, "reason": "unfinished ending"})
            continue
        if "dependent opening" in moment.problems and moment.hook_score < 58:
            rejected.append({"id": moment.id, "score": moment.final_score, "reason": "dependent opening"})
            continue
        duplicate = _duplicate_reason(candidate, selected)
        if duplicate:
            rejected.append({"id": moment.id, "score": moment.final_score, "reason": duplicate})
            continue
        type_limit = max(2, config.clips.target_count // 2) if moment.moment_type == "metric_reveal" else 3
        if type_counts.get(moment.moment_type, 0) >= type_limit:
            rejected.append({"id": moment.id, "score": moment.final_score, "reason": f"{moment.moment_type} diversity cap"})
            continue
        selected.append(candidate)
        type_counts[moment.moment_type] = type_counts.get(moment.moment_type, 0) + 1
        if len(selected) >= config.clips.target_count:
            break

    fallback = False
    if not selected:
        fallback = True
        fallback_types: dict[str, int] = {}
        for candidate in ordered:
            moment = candidate.moment
            if HARD_REJECT_PROBLEMS & set(moment.problems) or moment.final_score < config.clips.min_score - 10:
                continue
            duplicate = _duplicate_reason(candidate, selected)
            if duplicate:
                rejected.append({"id": moment.id, "score": moment.final_score, "reason": f"fallback {duplicate}"})
                continue
            if fallback_types.get(moment.moment_type, 0) >= 2:
                rejected.append({"id": moment.id, "score": moment.final_score, "reason": "fallback diversity cap"})
                continue
            if "below strict quality gate" not in moment.problems:
                moment.problems.append("below strict quality gate")
            selected.append(candidate)
            fallback_types[moment.moment_type] = fallback_types.get(moment.moment_type, 0) + 1
            if len(selected) >= min(3, config.clips.target_count):
                break

    audit = {
        "policy_version": "content_arc_v2",
        "pool_count": len(candidates),
        "selected_count": len(selected),
        "fallback": fallback,
        "promotional_ranges": [
            {
                "start": block.padded_start,
                "end": block.padded_end,
                "core_start": block.core_start,
                "core_end": block.core_end,
                "evidence": list(block.evidence),
            }
            for block in promo_blocks
        ],
        "selected": [
            {
                "id": item.moment.id,
                "score": item.moment.final_score,
                "start": item.start,
                "end": item.end,
                "hook": item.moment.hook_text,
            }
            for item in selected
        ],
        "rejected": rejected,
    }
    return selected, audit
