from backend.schemas.transcript import Transcript, TranscriptSegment, TranscriptWord
from backend.services.sentence_segmenter import segment_transcript, split_plain_text


def test_split_plain_text_handles_russian_sentences():
    text = "Р­С‚Рѕ РїРµСЂРІС‹Р№ С‚РµР·РёСЃ. РџРѕС‡РµРјСѓ СЌС‚Рѕ РІР°Р¶РЅРѕ? РџРѕС‚РѕРјСѓ С‡С‚Рѕ Р·СЂРёС‚РµР»СЊ РґРѕСЃРјРѕС‚СЂРёС‚."
    assert split_plain_text(text) == [
        "Это первый тезис.",
        "Почему это важно?",
        "Потому что зритель досмотрит.",
    ]


def test_segment_transcript_carries_speaker_metadata():
    transcript = Transcript(
        segments=[
            TranscriptSegment(
                id=1,
                start=0,
                end=3,
                text="first second",
                speaker="S1",
                words=[
                    TranscriptWord(word="first", start=0, end=1, speaker="S1"),
                    TranscriptWord(word="second", start=1, end=2, speaker="S2"),
                ],
            )
        ]
    )

    sentences = segment_transcript(transcript)

    assert sentences[0].speakers == ["S1", "S2"]
    assert sentences[0].speaker_switches == 1
