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
                text="РџСЂРёРІРµС‚ {РјРёСЂ}",
                words=[
                    TranscriptWord(word="РџСЂРёРІРµС‚", start=0.5, end=1.0),
                    TranscriptWord(word="{РјРёСЂ}", start=1.05, end=2.0),
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
    assert r"{\fad(45,70)}" in content
    assert r"{\k55}Привет" in content
    assert r"{\k95}\{мир\}" in content
    assert "РџСЂ" not in content


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
                text="СЏ РіРѕРІРѕСЂСЋ СЃРµР№С‡Р°СЃ",
                words=[
                    TranscriptWord(word="СЏ", start=90.0, end=90.3),
                    TranscriptWord(word="РіРѕРІРѕСЂСЋ", start=90.35, end=91.0),
                    TranscriptWord(word="СЃРµР№С‡Р°СЃ", start=91.1, end=92.2),
                ],
            )
        ],
    )
    path = tmp_path / "timed.ass"

    write_ass(transcript, 89.5, 95.0, path, max_words=2)

    content = path.read_text(encoding="utf-8")
    assert "Dialogue: 0,0:00:00.50,0:00:02.70" in content
    assert r"{\k35}я" in content
    assert r"\N" in content
    assert "говорю" in content
    assert "сейчас" in content


def test_clip_subtitles_keep_partial_boundary_words():
    transcript = Transcript(
        language="ru",
        duration=10,
        engine="faster-whisper:cpu",
        segments=[
            TranscriptSegment(
                id=1,
                start=1.0,
                end=3.0,
                text="СЂР°РЅСЊС€Рµ СЃРµР№С‡Р°СЃ",
                words=[
                    TranscriptWord(word="СЂР°РЅСЊС€Рµ", start=0.9, end=1.1),
                    TranscriptWord(word="СЃРµР№С‡Р°СЃ", start=1.2, end=1.8),
                ],
            )
        ],
    )

    segments = clip_subtitle_segments(transcript, 1.0, 3.0, max_words=3)

    assert len(segments) == 1
    assert len(segments[0].words) == 2
    assert segments[0].text == "раньше сейчас"


def test_clip_subtitles_recover_segment_text_when_word_timestamps_are_sparse():
    transcript = Transcript(
        language="ru",
        duration=10,
        engine="faster-whisper:cuda",
        segments=[
            TranscriptSegment(
                id=1,
                start=1.0,
                end=3.0,
                text="one two three four",
                speaker="S2",
                words=[TranscriptWord(word="one", start=1.0, end=1.2, speaker="S2")],
            )
        ],
    )

    segments = clip_subtitle_segments(transcript, 0.0, 5.0, max_words=4)

    assert [segment.text for segment in segments] == ["one two three four"]
    assert segments[0].speaker == "S2"


def test_write_ass_uses_speaker_styles_when_speakers_are_present(tmp_path):
    transcript = Transcript(
        language="ru",
        duration=4,
        engine="test",
        segments=[
            TranscriptSegment(
                id=1,
                start=0.0,
                end=1.0,
                text="first voice",
                speaker="S1",
                words=[
                    TranscriptWord(word="first", start=0.0, end=0.4, speaker="S1"),
                    TranscriptWord(word="voice", start=0.4, end=1.0, speaker="S1"),
                ],
            ),
            TranscriptSegment(
                id=2,
                start=1.2,
                end=2.2,
                text="second voice",
                speaker="S2",
                words=[
                    TranscriptWord(word="second", start=1.2, end=1.6, speaker="S2"),
                    TranscriptWord(word="voice", start=1.6, end=2.2, speaker="S2"),
                ],
            ),
        ],
    )
    path = tmp_path / "speaker.ass"

    write_ass(transcript, 0, 3, path, max_words=2)

    content = path.read_text(encoding="utf-8")
    assert "Style: Speaker2" in content
    assert "Dialogue: 0,0:00:01.20,0:00:02.20,Speaker2" in content


def test_write_ass_splits_one_line_when_speaker_changes(tmp_path):
    transcript = Transcript(
        language="ru",
        duration=2,
        engine="test",
        segments=[
            TranscriptSegment(
                id=1,
                start=0.0,
                end=1.8,
                text="first second",
                words=[
                    TranscriptWord(word="first", start=0.0, end=0.8, speaker="S1"),
                    TranscriptWord(word="second", start=0.8, end=1.8, speaker="S2"),
                ],
            )
        ],
    )
    path = tmp_path / "speaker-split.ass"

    write_ass(transcript, 0, 2, path, max_words=3, safe_bottom_margin_px=300)

    content = path.read_text(encoding="utf-8")
    assert "Style: Speaker2,Arial,78,&H004FD9FF" in content
    assert "80,80,300,1" in content
    assert "Dialogue: 0,0:00:00.00,0:00:00.80,Speaker1" in content
    assert "Dialogue: 0,0:00:00.80,0:00:01.80,Speaker2" in content


def test_write_ass_can_disable_word_highlighting(tmp_path):
    transcript = Transcript(
        duration=2,
        segments=[
            TranscriptSegment(
                id=1,
                start=0,
                end=1,
                text="plain words",
                words=[
                    TranscriptWord(word="plain", start=0, end=0.4),
                    TranscriptWord(word="words", start=0.4, end=1.0),
                ],
            )
        ],
    )
    path = tmp_path / "plain.ass"

    write_ass(transcript, 0, 2, path, highlight_current_word=False)

    content = path.read_text(encoding="utf-8")
    assert "plain words" in content
    assert r"{\k" not in content


def test_subtitle_chunks_follow_clauses_and_meaningful_pauses():
    transcript = Transcript(
        duration=5,
        segments=[
            TranscriptSegment(
                id=1,
                start=0,
                end=4,
                text="first idea, second part 500 years.",
                words=[
                    TranscriptWord(word="first", start=0.0, end=0.3),
                    TranscriptWord(word="idea,", start=0.31, end=0.7),
                    TranscriptWord(word="second", start=1.12, end=1.5),
                    TranscriptWord(word="part", start=1.51, end=1.8),
                    TranscriptWord(word="500", start=1.81, end=2.05),
                    TranscriptWord(word="years.", start=2.06, end=2.5),
                ],
            )
        ],
    )

    segments = clip_subtitle_segments(transcript, 0, 4, max_words=4)

    assert [segment.text for segment in segments] == ["first idea,", "second part 500 years."]


def test_write_ass_accents_numeric_evidence_word(tmp_path):
    transcript = Transcript(
        duration=2,
        segments=[
            TranscriptSegment(
                id=1,
                start=0,
                end=1.4,
                text="этому 500 лет",
                words=[
                    TranscriptWord(word="этому", start=0, end=0.4),
                    TranscriptWord(word="500", start=0.4, end=0.8),
                    TranscriptWord(word="лет", start=0.8, end=1.4),
                ],
            )
        ],
    )
    path = tmp_path / "evidence.ass"

    write_ass(transcript, 0, 2, path, max_words=3)

    content = path.read_text(encoding="utf-8")
    assert r"{\1c&H0000D7FF&\2c&H00464F57&\bord6\k40}500{\r}" in content


def test_subtitles_join_hyphenated_asr_tokens(tmp_path):
    transcript = Transcript(
        duration=2,
        segments=[
            TranscriptSegment(
                id=1,
                start=0,
                end=1,
                text="что -то новое",
                words=[
                    TranscriptWord(word="что", start=0, end=0.3),
                    TranscriptWord(word="-то", start=0.3, end=0.5),
                    TranscriptWord(word="новое", start=0.5, end=1),
                ],
            )
        ],
    )
    path = tmp_path / "hyphen.ass"

    write_ass(transcript, 0, 2, path, max_words=3)

    content = path.read_text(encoding="utf-8")
    assert r"{\k30}что{\k20}-то" in content
    assert "что -то" not in content


def test_subtitle_line_break_does_not_split_hyphenated_token(tmp_path):
    values = ["навряд", "ли", "вы", "что", "-то", "можете", "новое", "придумать."]
    transcript = Transcript(
        duration=4,
        segments=[
            TranscriptSegment(
                id=1,
                start=0,
                end=4,
                text="навряд ли вы что-то можете новое придумать.",
                words=[
                    TranscriptWord(word=value, start=index * 0.4, end=(index + 1) * 0.4)
                    for index, value in enumerate(values)
                ],
            )
        ],
    )
    path = tmp_path / "hyphen-line.ass"

    write_ass(transcript, 0, 4, path, max_words=3)

    content = path.read_text(encoding="utf-8")
    assert r"{\k40}что{\k40}-то\N" in content
