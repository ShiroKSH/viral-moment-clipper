from backend.schemas.transcript import TranscriptSegment, TranscriptWord
from backend.services import pipeline


def test_subtitle_quality_requests_local_pass_for_broken_word_timing():
    segments = [
        TranscriptSegment(
            id=1,
            start=0,
            end=12,
            text="broken timing",
            words=[
                TranscriptWord(word="broken", start=0, end=0, probability=0.08),
                TranscriptWord(word="timing", start=0, end=1, probability=0.95),
            ],
        )
    ]

    assert pipeline._needs_clip_subtitle_pass(segments, 12)
