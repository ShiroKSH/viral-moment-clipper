from backend.services.content_quality import quality_penalty


def test_quality_penalty_flags_ad_and_generic_clip_text():
    ad_penalty, ad_problems = quality_penalty("Реклама: промокод, скидка и ссылка в описании.")
    generic_penalty, generic_problems = quality_penalty("В этом фрагменте есть важная мысль, которую можно превратить в короткий клип.")

    assert ad_penalty >= 40
    assert "ad or CTA language" in ad_problems
    assert generic_penalty >= 40
    assert "generic clip-analysis text" in generic_problems


def test_quality_penalty_flags_branded_sponsor_read_before_the_cta():
    penalty, problems = quality_penalty(
        "Самый редкий легендарный дроп в новом обновлении. "
        "Получи шанс разделить призовой фонд и успей до 20 июля."
    )

    assert penalty >= 52
    assert "ad or CTA language" in problems


def test_contextual_game_update_is_not_an_ad_without_commercial_evidence():
    _, problems = quality_penalty("В новом обновлении PUBG Mobile появился редкий легендарный дроп.")

    assert "ad or CTA language" not in problems
