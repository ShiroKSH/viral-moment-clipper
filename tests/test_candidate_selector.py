from backend.core.config import Settings
from backend.schemas.moments import InterestingMoment, SentenceSegment
from backend.services.candidate_selector import (
    CandidateInterval,
    calibrate_moment,
    promotional_ranges,
    select_candidate_intervals,
    structural_penalty,
)


def _moment(moment_id: str, start: float, end: float, text: str, score: float = 82) -> InterestingMoment:
    return InterestingMoment(
        id=moment_id,
        start=start,
        end=end,
        duration=end - start,
        text=text,
        summary=text,
        moment_type="insight",
        hook_text=text.split(".", 1)[0],
        base_score=score,
        personal_score=score,
        final_score=score,
    )


def _pubg_ad_sentences() -> list[SentenceSegment]:
    return [
        SentenceSegment(id="clean", start=144.76, end=175.41, text="Команда спорит и пытается найти монстра."),
        SentenceSegment(id="q", start=179.46, end=180.26, text="Знаешь, что это?"),
        SentenceSegment(id="intro", start=180.44, end=183.46, text="Это новая суперэмбовая штука. Грозовой вершитель."),
        SentenceSegment(id="brand", start=183.62, end=187.72, text="Редкий дроп в новом обновлении PUBG Mobile Metro Royal."),
        SentenceSegment(id="scarcity", start=187.72, end=193.88, text="Он выпадает у одного из ста тысяч игроков, и шанс уменьшается."),
        SentenceSegment(id="benefit", start=193.98, end=204.28, text="Сражайся с боссами, чтобы получить оружие и буст к скорости."),
        SentenceSegment(id="offer", start=204.38, end=211.88, text="Главное: получи возможность разделить призовой фонд."),
        SentenceSegment(id="money", start=211.88, end=215.68, text="В размере миллиона рублей с другими обладателями."),
        SentenceSegment(id="event", start=215.78, end=221.50, text="В событии участвует известный автор, и он ждать не будет."),
        SentenceSegment(id="cta", start=221.60, end=224.46, text="Скачивай PUBG Mobile и начинай охоту."),
        SentenceSegment(id="urgent", start=224.66, end=227.58, text="Успей до 20 июля, потом эта штука исчезнет."),
    ]


def test_promotional_ranges_expand_back_from_link_cta():
    sentences = [
        SentenceSegment(id="s1", start=100, end=104, text="Программа обучает работе с роботами."),
        SentenceSegment(id="s2", start=145, end=149, text="Ссылка на программу находится в описании."),
    ]

    assert promotional_ranges(sentences) == [(145.0, 149.0)]


def test_promotional_ranges_detect_sponsor_read_without_link_cta():
    sentences = _pubg_ad_sentences()

    ranges = promotional_ranges(sentences)

    assert any(start <= 183.62 and end >= 224.46 for start, end in ranges)


def test_pubg_ad_tail_rejects_candidate_but_clean_preceding_clip_survives():
    settings = Settings()
    settings.clips.target_count = 2
    settings.clips.min_score = 60
    sentences = _pubg_ad_sentences()
    clean = CandidateInterval(_moment("clean", 144.76, 175.0, sentences[0].text, 90), 144.76, 175.0)
    infected = CandidateInterval(_moment("infected", 144.76, 187.72, "Чистый текст кандидата", 88), 144.76, 187.72)

    selected, audit = select_candidate_intervals([infected, clean], sentences, settings)

    assert [candidate.moment.id for candidate in selected] == ["clean"]
    assert any(item["id"] == "infected" and item["reason"] == "promotional segment" for item in audit["rejected"])
    assert audit["promotional_ranges"][0]["core_start"] <= 179.46
    assert audit["promotional_ranges"][0]["core_end"] >= 227.58


def test_structural_penalty_rejects_filler_hook_and_unanswered_question():
    penalty, problems = structural_penalty("Как так совпало? Мы пока только готовим ответ?")

    assert penalty >= 40
    assert "filler opening" in problems
    assert "unanswered question" in problems


def test_calibration_separates_metric_reveal_from_filler():
    strong = _moment(
        "strong",
        0,
        24,
        "Было 30 тысяч пользователей. Теперь их семьсот тысяч. Это новый рекорд.",
    )
    weak = _moment(
        "weak",
        30,
        54,
        "В общем, мы немного походили по офису и потом пошли дальше.",
    )

    calibrate_moment(strong)
    calibrate_moment(weak)

    assert strong.final_score >= weak.final_score + 20
    assert strong.moment_type == "metric_reveal"


def test_selection_rejects_promotional_zone_and_post_boundary_duplicate():
    settings = Settings()
    settings.clips.target_count = 4
    settings.clips.min_score = 60
    sentences = [
        SentenceSegment(id="ad", start=80, end=84, text="Ссылка на курс в описании."),
        SentenceSegment(id="a", start=200, end=220, text="Сильный результат: было десять тысяч, стало сто тысяч."),
        SentenceSegment(id="b", start=218, end=238, text="Тот же результат с дополнительными словами."),
    ]
    ad = CandidateInterval(_moment("ad_moment", 75, 85, "Курс дает актуальные знания.", 95), 75, 85)
    best = CandidateInterval(_moment("best", 200, 224, sentences[1].text, 90), 200, 224)
    duplicate = CandidateInterval(_moment("duplicate", 218, 240, sentences[2].text, 85), 218, 240)

    selected, audit = select_candidate_intervals([ad, duplicate, best], sentences, settings)

    assert [candidate.moment.id for candidate in selected] == ["best"]
    reasons = {item["id"]: item["reason"] for item in audit["rejected"]}
    assert reasons["ad_moment"] == "promotional segment"
    assert "duplicate" in reasons["duplicate"]


def test_fallback_selection_still_suppresses_duplicates():
    settings = Settings()
    settings.clips.target_count = 3
    settings.clips.min_score = 70
    first = CandidateInterval(_moment("first", 10, 32, "Один цельный рассказ с понятным выводом.", 65), 10, 32)
    duplicate = CandidateInterval(_moment("duplicate", 25, 45, "Тот же цельный рассказ с понятным выводом.", 64), 25, 45)

    selected, audit = select_candidate_intervals([duplicate, first], [], settings)

    assert audit["fallback"] is True
    assert [candidate.moment.id for candidate in selected] == ["first"]
    assert any(item["id"] == "duplicate" and "duplicate" in item["reason"] for item in audit["rejected"])
