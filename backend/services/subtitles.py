from __future__ import annotations

from pathlib import Path

from backend.schemas.transcript import Transcript, TranscriptSegment, TranscriptWord


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
        text = " ".join(segment.text.split())
        blocks.append(f"{index}\n{format_srt_time(segment.start)} --> {format_srt_time(segment.end)}\n{text}\n")
    return "\n".join(blocks)


def write_srt(transcript: Transcript, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(transcript_to_srt(transcript), encoding="utf-8")
    return path


def _chunk_words(words: list[TranscriptWord], max_words: int) -> list[list[TranscriptWord]]:
    if not words:
        return []
    return [words[index : index + max_words] for index in range(0, len(words), max_words)]


def clip_subtitle_segments(transcript: Transcript, start: float, end: float, max_words: int = 4) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    next_id = 1
    for segment in transcript.segments:
        if segment.end < start or segment.start > end:
            continue
        words = [word for word in segment.words if word.end > start + 0.05 and word.start < end - 0.05]
        if not words:
            clipped_start = max(segment.start, start) - start
            clipped_end = min(segment.end, end) - start
            if clipped_end - clipped_start < 0.08:
                continue
            segments.append(TranscriptSegment(id=next_id, start=clipped_start, end=clipped_end, text=segment.text.strip(), words=[]))
            next_id += 1
            continue
        for chunk in _chunk_words(words, max_words):
            chunk_text = " ".join(word.word for word in chunk)
            chunk_start = max(chunk[0].start, start) - start
            chunk_end = min(chunk[-1].end, end) - start
            if chunk_end - chunk_start < 0.08:
                continue
            segments.append(
                TranscriptSegment(
                    id=next_id,
                    start=chunk_start,
                    end=chunk_end,
                    text=chunk_text,
                    words=[TranscriptWord(word=w.word, start=max(w.start, start) - start, end=min(w.end, end) - start, probability=w.probability) for w in chunk],
                )
            )
            next_id += 1
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
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    segments = clip_subtitle_segments(transcript, start, end, max_words=max_words)
    header = f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H0000D7FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,80,80,{safe_bottom_margin_px},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for segment in segments:
        text = r"{\fad(70,120)}" + escape_ass_text(segment.text)
        lines.append(f"Dialogue: 0,{format_ass_time(segment.start)},{format_ass_time(segment.end)},Default,,0,0,0,,{text}")
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def escape_ass_text(text: str) -> str:
    return (
        text.strip()
        .replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", " ")
    )
