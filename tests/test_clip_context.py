from backend.schemas.clips import ClipCandidate
from backend.schemas.transcript import Transcript, TranscriptSegment, TranscriptWord
from backend.services.clip_context import refresh_clip_context


def test_refresh_clip_context_matches_refined_render_boundary():
    clip = ClipCandidate(
        id="clip_context",
        moment_id="moment_context",
        start=10,
        end=15,
        duration=5,
        final_score=80,
        moment_type="insight",
        hook_text="stale fragment",
        summary="stale summary",
        reason="reason",
        text="stale fragment outside the render",
        suggested_title="stale fragment",
        suggested_caption="stale caption",
    )
    transcript = Transcript(
        duration=20,
        segments=[
            TranscriptSegment(
                id=1,
                start=9,
                end=12,
                text="old fragment. Actual hook starts here.",
                words=[
                    TranscriptWord(word="old", start=9, end=9.3),
                    TranscriptWord(word="fragment.", start=9.3, end=9.8),
                    TranscriptWord(word="Actual", start=10.1, end=10.5),
                    TranscriptWord(word="hook", start=10.5, end=10.8),
                    TranscriptWord(word="starts", start=10.8, end=11.2),
                    TranscriptWord(word="here.", start=11.2, end=11.6),
                ],
            ),
            TranscriptSegment(id=2, start=12.3, end=14, text="Second complete sentence.", words=[]),
        ],
    )

    refreshed = refresh_clip_context(clip, transcript)

    assert refreshed.text == "Actual hook starts here. Second complete sentence."
    assert refreshed.hook_text == "Actual hook starts here."
    assert refreshed.suggested_title == "Actual hook starts here."
    assert refreshed.suggested_caption == "Actual hook starts here. Second complete sentence."


def test_refresh_clip_context_joins_hyphenated_tokens():
    clip = ClipCandidate(
        id="clip_hyphen",
        moment_id="moment_hyphen",
        start=0,
        end=2,
        duration=2,
        final_score=70,
        moment_type="insight",
        hook_text="old",
        summary="old",
        reason="reason",
        text="old",
        suggested_title="old",
        suggested_caption="old",
    )
    transcript = Transcript(
        duration=2,
        segments=[
            TranscriptSegment(
                id=1,
                start=0,
                end=1,
                text="что-то новое",
                words=[
                    TranscriptWord(word="что", start=0, end=0.3),
                    TranscriptWord(word="-то", start=0.3, end=0.5),
                    TranscriptWord(word="новое", start=0.5, end=1),
                ],
            )
        ],
    )

    assert refresh_clip_context(clip, transcript).text == "что-то новое"
