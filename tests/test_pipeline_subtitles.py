from backend.schemas.transcript import TranscriptSegment
from backend.services.pipeline import _largest_internal_subtitle_gap, _needs_clip_subtitle_pass, _subtitle_tail_seconds


def test_subtitle_tail_seconds():
    segments = [
        TranscriptSegment(id=1, start=0.0, end=1.2, text="one"),
        TranscriptSegment(id=2, start=3.0, end=6.4, text="two"),
    ]

    assert _subtitle_tail_seconds(segments) == 6.4


def test_needs_clip_subtitle_pass_when_full_transcript_misses_tail():
    segments = [TranscriptSegment(id=1, start=0.0, end=6.4, text="early only")]

    assert _needs_clip_subtitle_pass(segments, duration=22.8)


def test_does_not_need_clip_pass_when_subtitles_reach_end():
    segments = [
        TranscriptSegment(id=1, start=0.2, end=8.0, text="dense opening words keep the complete subtitle track populated"),
        TranscriptSegment(id=2, start=8.3, end=14.0, text="the middle remains present and properly timed"),
        TranscriptSegment(id=3, start=14.2, end=20.5, text="the final sentence also reaches the end cleanly"),
    ]

    assert not _needs_clip_subtitle_pass(segments, duration=22.8)


def test_needs_clip_pass_when_middle_of_transcript_is_missing():
    segments = [
        TranscriptSegment(id=1, start=0.0, end=5.0, text="opening subtitle words are present here"),
        TranscriptSegment(id=2, start=11.0, end=20.5, text="closing subtitle words are also present here"),
    ]

    assert _largest_internal_subtitle_gap(segments) == 6.0
    assert _needs_clip_subtitle_pass(segments, duration=22.8)
