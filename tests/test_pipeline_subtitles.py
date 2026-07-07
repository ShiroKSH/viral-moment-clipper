from backend.schemas.transcript import TranscriptSegment
from backend.services.pipeline import _needs_clip_subtitle_pass, _subtitle_tail_seconds


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
    segments = [TranscriptSegment(id=1, start=17.0, end=20.5, text="near end")]

    assert not _needs_clip_subtitle_pass(segments, duration=22.8)
