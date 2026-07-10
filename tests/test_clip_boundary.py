from backend.core.config import Settings
from backend.schemas.moments import InterestingMoment
from backend.schemas.transcript import Transcript, TranscriptSegment
from backend.services.clip_boundary import choose_clip_boundary


def test_clip_boundary_uses_sentence_edges():
    settings = Settings()
    settings.clips.ending_strategy = "complete_sentence"
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
    start, end = choose_clip_boundary(moment, transcript, settings)
    assert start <= 10
    assert end >= 35
    assert end - start <= settings.clips.max_duration_sec


def test_clip_boundary_extends_until_phrase_finishes():
    settings = Settings()
    settings.clips.ending_strategy = "complete_sentence"
    transcript = Transcript(
        duration=100,
        segments=[
            TranscriptSegment(id=1, start=10, end=20, text="first part without punctuation"),
            TranscriptSegment(id=2, start=20.2, end=30, text="the actual payoff."),
        ],
    )
    moment = InterestingMoment(
        id="moment_001",
        start=12,
        end=19,
        duration=7,
        text="first part without punctuation",
        summary="summary",
        moment_type="insight",
        hook_text="first part",
    )

    _, end = choose_clip_boundary(moment, transcript, settings)

    assert end >= 30


def test_clip_boundary_preserves_payoff_end_when_max_duration_forces_a_cut():
    settings = Settings()
    settings.clips.ending_strategy = "complete_sentence"
    settings.clips.max_duration_sec = 20
    transcript = Transcript(
        duration=100,
        segments=[
            TranscriptSegment(id=1, start=1, end=12, text="setup without punctuation"),
            TranscriptSegment(id=2, start=12.1, end=28, text="payoff finishes here."),
        ],
    )
    moment = InterestingMoment(
        id="moment_001",
        start=2,
        end=10,
        duration=8,
        text="setup without punctuation",
        summary="summary",
        moment_type="insight",
        hook_text="setup",
    )

    start, end = choose_clip_boundary(moment, transcript, settings)

    assert end >= 28
    assert round(end - start, 2) <= settings.clips.max_duration_sec


def test_clip_boundary_can_cut_on_cliffhanger_before_payoff():
    settings = Settings()
    settings.clips.ending_strategy = "cliffhanger"
    settings.clips.cliffhanger_min_duration_sec = 10
    settings.clips.cliffhanger_preferred_duration_sec = 14
    settings.clips.cliffhanger_max_duration_sec = 18
    transcript = Transcript(
        duration=80,
        segments=[
            TranscriptSegment(id=1, start=0, end=7, text="setup"),
            TranscriptSegment(id=2, start=7.1, end=14, text="почему эта задача вообще пугает"),
            TranscriptSegment(id=3, start=14.1, end=32, text="а теперь полный ответ и объяснение."),
        ],
    )
    moment = InterestingMoment(
        id="moment_001",
        start=1,
        end=31,
        duration=30,
        text="setup why answer",
        summary="summary",
        moment_type="insight",
        hook_text="setup",
    )

    _, end = choose_clip_boundary(moment, transcript, settings)

    assert 14 <= end < 20


def test_cliffhanger_rejects_comma_fragment_in_favor_of_complete_thought():
    settings = Settings()
    settings.clips.ending_strategy = "cliffhanger"
    settings.clips.cliffhanger_min_duration_sec = 14
    settings.clips.cliffhanger_preferred_duration_sec = 16
    settings.clips.cliffhanger_max_duration_sec = 20
    transcript = Transcript(
        duration=40,
        segments=[
            TranscriptSegment(id=1, start=0, end=8, text="Начало мысли без финала"),
            TranscriptSegment(id=2, start=8.1, end=14.15, text="Ничего особенно не поменяется."),
            TranscriptSegment(id=3, start=14.3, end=15.0, text="Тысячи лет,"),
            TranscriptSegment(id=4, start=15.1, end=18.0, text="сотни лет этим областям."),
        ],
    )
    moment = InterestingMoment(
        id="moment_fragment",
        start=0.2,
        end=17.5,
        duration=17.3,
        text="thought",
        summary="summary",
        moment_type="insight",
        hook_text="hook",
    )

    _, end = choose_clip_boundary(moment, transcript, settings)

    assert 14.15 <= end < 14.5


def test_clip_start_padding_does_not_include_previous_finished_word():
    settings = Settings()
    settings.clips.ending_strategy = "complete_sentence"
    transcript = Transcript(
        duration=30,
        segments=[
            TranscriptSegment(id=1, start=0, end=1.0, text="Предыдущая фраза."),
            TranscriptSegment(id=2, start=1.2, end=4.0, text="Новый сильный заход."),
            TranscriptSegment(id=3, start=4.2, end=20.0, text="Продолжение мысли."),
        ],
    )
    moment = InterestingMoment(
        id="moment_clean_start",
        start=0.9,
        end=18.0,
        duration=17.1,
        text="thought",
        summary="summary",
        moment_type="insight",
        hook_text="hook",
    )

    start, _ = choose_clip_boundary(moment, transcript, settings)

    assert 1.0 < start < 1.2


def test_cliffhanger_finishes_dangling_conclusion_and_keeps_counterturn():
    settings = Settings()
    settings.clips.ending_strategy = "cliffhanger"
    settings.clips.cliffhanger_min_duration_sec = 12
    settings.clips.cliffhanger_preferred_duration_sec = 19
    settings.clips.cliffhanger_max_duration_sec = 24
    transcript = Transcript(
        duration=30,
        segments=[
            TranscriptSegment(id=1, start=0, end=4, text="Сильный факт в начале."),
            TranscriptSegment(id=2, start=4.2, end=15, text="Аргумент развивается и становится понятным."),
            TranscriptSegment(id=3, start=15.1, end=16, text="И поэтому"),
            TranscriptSegment(id=4, start=17, end=19, text="мы получаем законченный вывод."),
            TranscriptSegment(id=5, start=19.2, end=21, text="Но дальше есть контртезис."),
        ],
    )
    moment = InterestingMoment(
        id="moment_counterturn",
        start=0.2,
        end=16,
        duration=15.8,
        text="thought",
        summary="summary",
        moment_type="insight",
        hook_text="hook",
    )

    _, end = choose_clip_boundary(moment, transcript, settings)

    assert 21.0 <= end <= 21.2


def test_complete_boundary_follows_deictic_reveal_and_counterturn():
    settings = Settings()
    settings.clips.ending_strategy = "complete_sentence"
    transcript = Transcript(
        duration=40,
        segments=[
            TranscriptSegment(id=1, start=0, end=8, text="Какой результат мы получили?"),
            TranscriptSegment(id=2, start=8.1, end=10, text="Вот тут."),
            TranscriptSegment(id=3, start=10.1, end=13, text="Было тридцать тысяч."),
            TranscriptSegment(id=4, start=13.1, end=16, text="Было месяц назад, теперь семьсот тысяч."),
        ],
    )
    moment = InterestingMoment(
        id="reveal",
        start=0,
        end=10,
        duration=10,
        text="question reveal",
        summary="summary",
        moment_type="metric_reveal",
        hook_text="hook",
    )

    _, end = choose_clip_boundary(moment, transcript, settings)

    assert end >= 16


def test_complete_boundary_padding_does_not_capture_next_sentence():
    settings = Settings()
    settings.clips.ending_strategy = "complete_sentence"
    settings.clips.pad_after_sec = 0.45
    transcript = Transcript(
        duration=30,
        segments=[
            TranscriptSegment(id=1, start=0, end=20.0, text="Законченная сильная мысль."),
            TranscriptSegment(id=2, start=20.1, end=24.0, text="Совсем новая тема начинается здесь."),
        ],
    )
    moment = InterestingMoment(
        id="clean_tail",
        start=0,
        end=19.8,
        duration=19.8,
        text="thought",
        summary="summary",
        moment_type="insight",
        hook_text="hook",
    )

    _, end = choose_clip_boundary(moment, transcript, settings)

    assert 20.0 <= end < 20.1
