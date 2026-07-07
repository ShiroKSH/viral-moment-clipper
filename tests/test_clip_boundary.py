from backend.core.config import Settings
from backend.schemas.moments import InterestingMoment
from backend.schemas.transcript import Transcript, TranscriptSegment
from backend.services.clip_boundary import choose_clip_boundary


def test_clip_boundary_uses_sentence_edges():
    transcript = Transcript(
        duration=100,
        segments=[
            TranscriptSegment(id=1, start=10, end=20, text="hook sentence"),
            TranscriptSegment(id=2, start=20, end=35, text="payoff sentence"),
        ],
    )
    moment = InterestingMoment(
        id="moment_001",
        start=12,
        end=34,
        duration=22,
        text="hook sentence payoff sentence",
        summary="summary",
        moment_type="insight",
        hook_text="hook sentence",
    )
    start, end = choose_clip_boundary(moment, transcript, Settings())
    assert start <= 10
    assert end >= 35
    assert end - start <= Settings().clips.max_duration_sec
