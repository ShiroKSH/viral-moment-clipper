from __future__ import annotations

from backend.core.config import Settings
from backend.core.utils import clamp
from backend.schemas.moments import InterestingMoment
from backend.schemas.transcript import Transcript, TranscriptSegment
from backend.services.content_quality import repair_mojibake


TERMINAL_PUNCTUATION = (".", "!", "?", "…")
CONTINUATION_PUNCTUATION = (",", ";", ":")
DANGLING_ENDINGS = {
    "а",
    "будто",
    "если",
    "и",
    "или",
    "когда",
    "но",
    "потому",
    "поэтому",
    "так",
    "что",
    "чтобы",
}
CURIOSITY_KEYWORDS = (
    "почему",
    "как",
    "зачем",
    "что",
    "но",
    "однако",
    "если",
    "проблем",
    "важн",
    "главн",
    "значит",
    "задач",
    "страх",
    "тревож",
)
POST_PAYOFF_PREFIXES = ("но ", "однако ", "зато ", "при этом ")
DEICTIC_ENDINGS = (
    "вот тут",
    "вот это",
    "вот так",
    "смотрите",
    "происходит вот это",
    "получилось вот так",
    "так что, бам",
    "так что бам",
)
FOLLOWUP_PREFIXES = ("было ", "но ", "однако ", "зато ", "а теперь ", "в итоге ")


def _looks_finished(segment: TranscriptSegment) -> bool:
    text = repair_mojibake(segment.text).strip()
    return not text or text.endswith(TERMINAL_PUNCTUATION)


def _ends_with_dangling_word(segment: TranscriptSegment) -> bool:
    text = repair_mojibake(segment.text).strip().lower().rstrip(" .,!?:;…")
    return bool(text) and text.split()[-1] in DANGLING_ENDINGS


def _needs_followup(segment: TranscriptSegment) -> bool:
    text = repair_mojibake(segment.text).strip().lower().rstrip(" .,!?:;…")
    return any(text.endswith(ending) for ending in DEICTIC_ENDINGS)


def _natural_end(transcript: Transcript, moment_end: float, fallback_end: float, max_extension_sec: float = 18.0) -> float:
    segments = transcript.segments
    if not segments:
        return fallback_end
    index = next((idx for idx, segment in enumerate(segments) if segment.end >= moment_end - 0.2), None)
    if index is None:
        return fallback_end
    current = segments[index]
    end = max(fallback_end, current.end)
    deadline = end + max_extension_sec
    while index + 1 < len(segments):
        next_segment = segments[index + 1]
        gap = next_segment.start - current.end
        max_unfinished_gap = 2.4 if _ends_with_dangling_word(current) else 1.35
        next_text = repair_mojibake(next_segment.text).strip().lower()
        follows_payoff = next_text.startswith(FOLLOWUP_PREFIXES) and gap <= 1.35
        if (_looks_finished(current) and not _needs_followup(current) and not follows_payoff) or gap > max_unfinished_gap or next_segment.end > deadline:
            break
        index += 1
        current = next_segment
        end = max(end, current.end)
    return end


def _safe_tail_end(transcript: Transcript, speech_end: float, padding_sec: float) -> float:
    """Pad into silence without leaking the next utterance into the clip."""
    padded_end = speech_end + max(0.0, padding_sec)
    next_start = next(
        (
            segment.start
            for segment in transcript.segments
            if segment.start >= speech_end - 0.02 and segment.end > speech_end + 0.02
        ),
        None,
    )
    if next_start is None or next_start >= padded_end:
        return padded_end
    return max(speech_end, next_start - 0.02)


def _sentence_start_anchor(transcript: Transcript, moment_start: float) -> tuple[float, float | None] | None:
    candidates: list[tuple[float, float | None]] = []
    for index, segment in enumerate(transcript.segments):
        if segment.start > moment_start + 1.0:
            break
        previous = transcript.segments[index - 1] if index > 0 else None
        if previous is None or _looks_finished(previous) or segment.start - previous.end > 0.85:
            candidates.append((segment.start, previous.end if previous is not None else None))
    return candidates[-1] if candidates else None


def _preserve_end_within_limit(start: float, end: float, max_duration: float) -> tuple[float, float]:
    if end - start <= max_duration:
        return start, end
    return max(0.0, end - max_duration), end


def _curiosity_score(segment: TranscriptSegment, start: float, config: Settings) -> float:
    text = repair_mojibake(segment.text).lower()
    elapsed = segment.end - start
    score = -abs(elapsed - config.clips.cliffhanger_preferred_duration_sec) * 0.18
    if "?" in text:
        score += 3.0
    if text.rstrip().endswith(("...", "…")):
        score += 2.5
    elif text.rstrip().endswith("!"):
        score += 1.5
    elif text.rstrip().endswith("."):
        score += 1.0
    elif text.rstrip().endswith(CONTINUATION_PUNCTUATION):
        score -= 3.5
    else:
        score -= 1.5
    last_word = text.rstrip(" .,!?:;…").split()[-1] if text.strip() else ""
    if last_word in DANGLING_ENDINGS:
        score -= 4.0
    score += min(2.0, sum(0.6 for keyword in CURIOSITY_KEYWORDS if keyword in text))
    if text.startswith(POST_PAYOFF_PREFIXES):
        score += 2.2
    if len(text.split()) >= 4:
        score += 0.8
    return score


def _post_payoff_turn_end(transcript: Transcript, payoff_end: float) -> float:
    for segment in transcript.segments:
        if segment.end <= payoff_end + 0.02:
            continue
        if segment.start - payoff_end > 3.2:
            break
        text = repair_mojibake(segment.text).strip().lower()
        if text.startswith(POST_PAYOFF_PREFIXES) and _looks_finished(segment):
            return segment.end
        if segment.start > payoff_end + 0.55:
            break
    return payoff_end


def _cliffhanger_end(transcript: Transcript, start: float, complete_speech_end: float, config: Settings) -> float:
    lower = start + config.clips.cliffhanger_min_duration_sec
    coherent_speech_end = _post_payoff_turn_end(transcript, complete_speech_end)
    upper = min(
        coherent_speech_end,
        start + config.clips.cliffhanger_max_duration_sec,
        transcript.duration or coherent_speech_end,
    )
    if upper <= lower:
        target = min(complete_speech_end, start + config.clips.cliffhanger_preferred_duration_sec)
        speech_end = _natural_end(transcript, target, target, max_extension_sec=4.0)
        return _safe_tail_end(transcript, min(speech_end, complete_speech_end), 0.12)
    candidates = [segment for segment in transcript.segments if lower <= segment.end <= upper]
    if not candidates:
        return _safe_tail_end(transcript, upper, 0.12)
    best = max(candidates, key=lambda segment: _curiosity_score(segment, start, config))
    return _safe_tail_end(transcript, min(best.end, coherent_speech_end), 0.12)


def choose_clip_boundary(moment: InterestingMoment, transcript: Transcript, config: Settings) -> tuple[float, float]:
    start = max(0, moment.start - config.clips.pad_before_sec)
    end = moment.end + config.clips.pad_after_sec
    duration = end - start
    if duration > config.clips.max_duration_sec:
        end = start + config.clips.max_duration_sec

    if config.clips.avoid_cutting_sentences:
        sentence_ends = [segment.end for segment in transcript.segments if segment.end >= moment.end - 1]
        start_anchor = _sentence_start_anchor(transcript, moment.start)
        if start_anchor:
            anchor, previous_end = start_anchor
            start = max(0, anchor - config.clips.pad_before_sec)
            if previous_end is not None and previous_end > start:
                start = min(anchor, previous_end + 0.03)
        if sentence_ends:
            end = sentence_ends[0] + config.clips.pad_after_sec
        complete_speech_end = _natural_end(transcript, moment.end, end - config.clips.pad_after_sec)
        complete_end = _safe_tail_end(transcript, complete_speech_end, config.clips.pad_after_sec)
        if config.clips.ending_strategy == "cliffhanger":
            end = _cliffhanger_end(transcript, start, complete_speech_end, config)
        else:
            end = complete_end
            start, end = _preserve_end_within_limit(start, end, config.clips.max_duration_sec)
    min_duration = config.clips.cliffhanger_min_duration_sec if config.clips.ending_strategy == "cliffhanger" else config.clips.min_duration_sec
    if end - start < min_duration:
        target_end = min(transcript.duration or start + min_duration, start + min_duration)
        speech_end = _natural_end(transcript, target_end, target_end, max_extension_sec=6.0)
        end = _safe_tail_end(transcript, speech_end, config.clips.pad_after_sec)
    end = clamp(end, start + 1, transcript.duration or end)
    if end - start > config.clips.max_duration_sec:
        start, end = _preserve_end_within_limit(start, end, config.clips.max_duration_sec)
    return round(start, 2), round(end, 2)
