from backend.core.config import Settings
from backend.schemas.transcript import Transcript, TranscriptSegment, TranscriptWord
from backend.services.semantic_analyzer import find_interesting_moments
from backend.services.sentence_segmenter import segment_transcript


def _segment(index: int, start: float, text: str) -> TranscriptSegment:
    words = text.split()
    return TranscriptSegment(
        id=index,
        start=start,
        end=start + 12,
        text=text,
        words=[TranscriptWord(word=word, start=start + offset, end=start + offset + 0.5) for offset, word in enumerate(words)],
    )


def test_semantic_analyzer_finds_interesting_moments_and_filters_ads():
    transcript = Transcript(
        duration=84,
        segments=[
            _segment(1, 0, "Почему это важная ошибка для автора?"),
            _segment(2, 12, "Я однажды сделал так и потерял результат."),
            _segment(3, 24, "Теперь нужно делать иначе и вот понятный вывод."),
            _segment(4, 36, "Реклама: используй промокод и переходи по ссылке в описании."),
            _segment(5, 48, "В этом фрагменте есть важная мысль, которую можно превратить в короткий клип."),
            _segment(6, 60, "Поэтому зритель может досмотреть до конца, если сразу дать конфликт и payoff."),
        ],
        text="",
    )
    settings = Settings()
    settings.local_llm.enabled = False
    moments = find_interesting_moments(segment_transcript(transcript), settings)

    assert moments
    assert moments[0].final_score > 50
    joined = " ".join(moment.text.lower() for moment in moments)
    assert "промокод" not in joined
    assert "можно превратить в короткий клип" not in joined
