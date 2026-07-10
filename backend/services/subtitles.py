from __future__ import annotations

from pathlib import Path
import re

from backend.schemas.transcript import Transcript, TranscriptSegment, TranscriptWord
from backend.services.content_quality import repair_mojibake


ORPHAN_WORDS = {"а", "бы", "в", "и", "к", "ли", "не", "но", "о", "с", "то", "у"}


def format_srt_time(seconds: float) -> str:
    milliseconds = int(round(max(0, seconds) * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def format_ass_time(seconds: float) -> str:
    centiseconds = int(round(max(0, seconds) * 100))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{centis:02}"


def transcript_to_srt(transcript: Transcript) -> str:
    blocks: list[str] = []
    for index, segment in enumerate(transcript.segments, start=1):
        text = " ".join(repair_mojibake(segment.text).split())
        blocks.append(f"{index}\n{format_srt_time(segment.start)} --> {format_srt_time(segment.end)}\n{text}\n")
    return "\n".join(blocks)


def write_srt(transcript: Transcript, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(transcript_to_srt(transcript), encoding="utf-8")
    return path


def _chunk_words(words: list[TranscriptWord], max_words: int) -> list[list[TranscriptWord]]:
    if not words:
        return []
    max_caption_words = max(2, max_words * 2 + 1)
    chunks: list[list[TranscriptWord]] = []
    current: list[TranscriptWord] = []
    current_speaker = words[0].speaker
    for index, word in enumerate(words):
        if current and word.speaker != current_speaker:
            chunks.append(current)
            current = []
            current_speaker = word.speaker
        projected_chars = len(" ".join(repair_mojibake(item.word) for item in [*current, word]))
        if current and (len(current) >= max_caption_words or projected_chars > 52):
            if len(current) > 1 and _normalized_caption_word(current[-1].word) in ORPHAN_WORDS:
                carry = current.pop()
                chunks.append(current)
                current = [carry]
            else:
                chunks.append(current)
                current = []
            current_speaker = word.speaker
        current.append(word)
        next_word = words[index + 1] if index + 1 < len(words) else None
        pause_seconds = max(0.0, next_word.start - word.end) if next_word else 0.0
        text = repair_mojibake(word.word).rstrip()
        ellipsis = text.endswith(("...", "…"))
        terminal = text.endswith((".", "!", "?", ";", ":")) and not ellipsis
        duration = max(0.0, word.end - current[0].start)
        hard_boundary = terminal or pause_seconds >= 0.38
        soft_boundary = text.endswith(",") or ellipsis or pause_seconds >= 0.20
        reached_limit = len(current) >= max_caption_words or duration >= 2.5
        reached_target = duration >= 1.15 and soft_boundary
        orphan_tail = _normalized_caption_word(word.word) in ORPHAN_WORDS
        if (hard_boundary or reached_limit or reached_target) and not orphan_tail:
            chunks.append(current)
            current = []
            current_speaker = next_word.speaker if next_word else None
    if current:
        chunks.append(current)

    merged: list[list[TranscriptWord]] = []
    for chunk in chunks:
        chunk_duration = max(0.0, chunk[-1].end - chunk[0].start)
        can_merge_previous = bool(
            merged
            and merged[-1][-1].speaker == chunk[0].speaker
            and len(merged[-1]) + len(chunk) <= max_caption_words + 1
            and len(" ".join(repair_mojibake(word.word) for word in [*merged[-1], *chunk])) <= 56
        )
        previous_duration = max(0.0, merged[-1][-1].end - merged[-1][0].start) if merged else 1.0
        if can_merge_previous and (chunk_duration < 0.62 or previous_duration < 0.62):
            merged[-1].extend(chunk)
        else:
            merged.append(chunk)
    return merged


def _normalized_caption_word(value: str) -> str:
    return re.sub(r"[^\w]+", "", repair_mojibake(value).lower(), flags=re.UNICODE)


def _join_display_words(words: list[TranscriptWord]) -> str:
    text = ""
    for word in words:
        token = repair_mojibake(word.word)
        if text and not token.startswith("-"):
            text += " "
        text += token
    return text


def _balanced_line_break(words: list[TranscriptWord], max_words_per_line: int) -> int | None:
    if len(words) <= max_words_per_line:
        return None
    index = (len(words) + 1) // 2
    if index < len(words) and repair_mojibake(words[index].word).startswith("-"):
        index += 1
    return min(index, len(words) - 1)


def _speaker_for_words(words: list[TranscriptWord], fallback: str | None) -> str | None:
    counts: dict[str, int] = {}
    for word in words:
        if word.speaker:
            counts[word.speaker] = counts.get(word.speaker, 0) + 1
    if not counts:
        return fallback
    return max(counts.items(), key=lambda item: item[1])[0]


def _pseudo_words_from_segment(segment: TranscriptSegment, start: float, end: float) -> list[TranscriptWord]:
    if min(segment.end, end) - max(segment.start, start) < 0.08:
        return []
    tokens = repair_mojibake(segment.text).strip().split()
    if not tokens:
        return []
    word_duration = max(0.08, (segment.end - segment.start) / len(tokens))
    pseudo_words = [
        TranscriptWord(
            word=token,
            start=segment.start + index * word_duration,
            end=min(segment.end, segment.start + (index + 1) * word_duration),
            speaker=segment.speaker,
        )
        for index, token in enumerate(tokens)
    ]
    return [word for word in pseudo_words if word.end > start + 0.02 and word.start < end - 0.02]


def _clip_words_for_segment(segment: TranscriptSegment, start: float, end: float) -> list[TranscriptWord]:
    words = [word for word in segment.words if word.end > start + 0.02 and word.start < end - 0.02]
    text_word_count = len(repair_mojibake(segment.text).split())
    segment_fully_inside_clip = segment.start >= start and segment.end <= end
    missing_most_words = segment_fully_inside_clip and text_word_count > 2 and len(words) <= text_word_count * 0.45
    if not words or missing_most_words:
        return _pseudo_words_from_segment(segment, start, end)
    return words


def clip_subtitle_segments(transcript: Transcript, start: float, end: float, max_words: int = 4) -> list[TranscriptSegment]:
    clip_words: list[TranscriptWord] = []
    for segment in transcript.segments:
        if segment.end < start or segment.start > end:
            continue
        words = _clip_words_for_segment(segment, start, end)
        clip_words.extend(
            TranscriptWord(
                word=repair_mojibake(word.word),
                start=max(word.start, start),
                end=min(word.end, end),
                probability=word.probability,
                speaker=word.speaker or segment.speaker,
            )
            for word in words
            if min(word.end, end) - max(word.start, start) >= 0.0
        )

    ordered_words = sorted(clip_words, key=lambda word: (word.start, word.end))
    deduped_words: list[TranscriptWord] = []
    for word in ordered_words:
        if deduped_words and abs(word.start - deduped_words[-1].start) < 0.02 and word.word == deduped_words[-1].word:
            continue
        deduped_words.append(word)

    segments: list[TranscriptSegment] = []
    chunks = _chunk_words(deduped_words, max_words)
    for index, chunk in enumerate(chunks, start=1):
        chunk_text = _join_display_words(chunk)
        chunk_start = max(chunk[0].start, start) - start
        chunk_end = min(chunk[-1].end, end) - start
        next_start = chunks[index][0].start - start if index < len(chunks) else end - start
        reading_target = max(0.65, len(chunk_text) / 18.0)
        if chunk_end - chunk_start < reading_target:
            chunk_end = min(
                max(chunk_end, chunk_start + reading_target),
                max(chunk_end, next_start - 0.08),
                end - start,
            )
        if chunk_end - chunk_start < 0.08:
            continue
        segments.append(
            TranscriptSegment(
                id=index,
                start=chunk_start,
                end=chunk_end,
                text=chunk_text,
                speaker=_speaker_for_words(chunk, chunk[0].speaker),
                words=[
                    TranscriptWord(
                        word=repair_mojibake(word.word),
                        start=max(word.start, start) - start,
                        end=min(word.end, end) - start,
                        probability=word.probability,
                        speaker=word.speaker,
                    )
                    for word in chunk
                ],
            )
        )
    return segments


def write_clip_srt(transcript: Transcript, start: float, end: float, path: Path, max_words: int = 4) -> Path:
    clip_transcript = Transcript(
        language=transcript.language,
        duration=end - start,
        engine=transcript.engine,
        segments=clip_subtitle_segments(transcript, start, end, max_words=max_words),
        text="",
    )
    return write_srt(clip_transcript, path)


def write_ass(
    transcript: Transcript,
    start: float,
    end: float,
    path: Path,
    font_size: int = 78,
    max_words: int = 4,
    width: int = 1080,
    height: int = 1920,
    safe_bottom_margin_px: int = 300,
    speaker_colors_enabled: bool = True,
    speaker_labels_enabled: bool = False,
    highlight_current_word: bool = True,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    segments = clip_subtitle_segments(transcript, start, end, max_words=max_words)
    speaker_margin = safe_bottom_margin_px
    header = f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H009B9B9B,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,1,2,80,80,{safe_bottom_margin_px},1
Style: Speaker1,Arial,{font_size},&H00FFFFFF,&H009B9B9B,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,1,2,80,80,{speaker_margin},1
Style: Speaker2,Arial,{font_size},&H004FD9FF,&H0048738F,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,1,2,80,80,{speaker_margin},1
Style: Speaker3,Arial,{font_size},&H00F2C66D,&H00765F39,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,1,2,80,80,{speaker_margin},1
Style: Speaker4,Arial,{font_size},&H00D997FF,&H00714E86,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,1,2,80,80,{speaker_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for segment in segments:
        speaker_prefix = f"{segment.speaker}: " if speaker_labels_enabled and segment.speaker else ""
        text = _ass_dialogue_text(segment, speaker_prefix, highlight_current_word, max_words)
        style = _speaker_style(segment.speaker) if speaker_colors_enabled else "Default"
        lines.append(f"Dialogue: 0,{format_ass_time(segment.start)},{format_ass_time(segment.end)},{style},,0,0,0,,{text}")
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def _ass_dialogue_text(
    segment: TranscriptSegment,
    prefix: str,
    highlight_current_word: bool,
    max_words_per_line: int,
) -> str:
    fade = r"{\fad(45,70)}" if segment.end - segment.start >= 0.8 else ""
    line_break_index = _balanced_line_break(segment.words, max_words_per_line)
    if not highlight_current_word or not segment.words:
        words = escape_ass_text(prefix + repair_mojibake(segment.text)).split()
        line_break_index = (len(words) + 1) // 2 if len(words) > max_words_per_line else None
        parts: list[str] = []
        for index, word in enumerate(words):
            if line_break_index is not None and index == line_break_index:
                parts.append(r"\N")
            parts.append(word)
        return fade + " ".join(parts).replace(r" \N ", r"\N")

    parts = [fade + escape_ass_text(prefix)]
    semantic_accent_used = False
    for index, word in enumerate(segment.words):
        if line_break_index is not None and index == line_break_index:
            parts.append(r"\N")
        next_start = segment.words[index + 1].start if index + 1 < len(segment.words) else word.end
        duration_cs = max(7, int(round(max(0.07, next_start - word.start) * 100)))
        escaped = escape_ass_text(repair_mojibake(word.word))
        if _is_semantic_accent_word(word.word) and not semantic_accent_used:
            semantic_accent_used = True
            parts.append(
                r"{\1c&H0000D7FF&\2c&H00464F57&\bord6\k"
                + str(duration_cs)
                + "}"
                + escaped
                + r"{\r}"
            )
        else:
            parts.append(r"{\k" + str(duration_cs) + "}" + escaped)
    result = " ".join(part for part in parts if part).replace(r" \N ", r"\N")
    return re.sub(r" (?=\{\\[^}]+\}-)", "", result)


def _is_semantic_accent_word(value: str) -> bool:
    normalized = re.sub(r"[^\w%]+", "", repair_mojibake(value).lower(), flags=re.UNICODE)
    if any(character.isdigit() for character in normalized):
        return True
    return normalized in {
        "важно",
        "всегда",
        "главное",
        "миллиард",
        "миллион",
        "никогда",
        "почему",
        "проблема",
        "сотни",
        "тысячи",
    }


def _speaker_style(speaker: str | None) -> str:
    if not speaker:
        return "Default"
    match = re.search(r"(\d+)$", speaker)
    if match:
        index = (int(match.group(1)) - 1) % 4
    else:
        index = sum(ord(char) for char in speaker) % 4
    return f"Speaker{index + 1}"


def escape_ass_text(text: str) -> str:
    return (
        text.strip()
        .replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", " ")
    )
