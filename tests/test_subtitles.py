from backend.schemas.transcript import Transcript, TranscriptSegment, TranscriptWord
from backend.services.subtitles import write_ass


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
