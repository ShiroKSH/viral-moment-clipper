from backend.schemas.transcript import Transcript, TranscriptSegment, TranscriptWord
from backend.services.subtitles import clip_subtitle_segments, write_ass


def test_write_ass_uses_render_canvas_safe_zone_and_organic_fade(tmp_path):
    transcript = Transcript(
        language="ru",
        duration=3,
        engine="test",
        segments=[
            TranscriptSegment(id=1, start=0, end=0.03, text="skip me", words=[]),
            TranscriptSegment(
                id=2,
                start=0.5,
                end=2.0,
                text="Привет {мир}",
                words=[
                    TranscriptWord(word="Привет", start=0.5, end=1.0),
                    TranscriptWord(word="{мир}", start=1.05, end=2.0),
                ],
            ),
        ],
    )
    path = tmp_path / "clip.ass"

    write_ass(transcript, 0, 3, path, font_size=70, max_words=2, width=720, height=1280, safe_bottom_margin_px=240)

    content = path.read_text(encoding="utf-8")
    assert content.count("PlayResX:") == 1
    assert "PlayResX: 720" in content
    assert "PlayResY: 1280" in content
    assert "80,80,240,1" in content
    assert "skip me" not in content
    assert r"{\fad(70,120)}" in content
    assert "Привет \\{мир\\}" in content


def test_clip_subtitles_are_offset_to_clip_start(tmp_path):
    transcript = Transcript(
        language="ru",
        duration=120,
        engine="faster-whisper:cpu",
        segments=[
            TranscriptSegment(
                id=1,
                start=90.0,
                end=92.2,
                text="я говорю сейчас",
                words=[
                    TranscriptWord(word="я", start=90.0, end=90.3),
                    TranscriptWord(word="говорю", start=90.35, end=91.0),
                    TranscriptWord(word="сейчас", start=91.1, end=92.2),
                ],
            )
        ],
    )
    path = tmp_path / "timed.ass"

    write_ass(transcript, 89.5, 95.0, path, max_words=2)

    content = path.read_text(encoding="utf-8")
    assert "Dialogue: 0,0:00:00.50,0:00:01.50" in content
    assert "Dialogue: 0,0:00:01.60,0:00:02.70" in content
    assert "я говорю" in content
    assert "сейчас" in content


def test_clip_subtitles_drop_partial_boundary_words():
    transcript = Transcript(
        language="ru",
        duration=10,
        engine="faster-whisper:cpu",
        segments=[
            TranscriptSegment(
                id=1,
                start=1.0,
                end=3.0,
                text="раньше сейчас",
                words=[
                    TranscriptWord(word="раньше", start=0.9, end=1.1),
                    TranscriptWord(word="сейчас", start=1.2, end=1.8),
                ],
            )
        ],
    )

    segments = clip_subtitle_segments(transcript, 1.0, 3.0, max_words=3)

    assert [segment.text for segment in segments] == ["сейчас"]
