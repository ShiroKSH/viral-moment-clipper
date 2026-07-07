from backend.services.content_quality import quality_penalty


def test_quality_penalty_flags_ad_and_generic_clip_text():
    ad_penalty, ad_problems = quality_penalty("Реклама: промокод, скидка и ссылка в описании.")
    generic_penalty, generic_problems = quality_penalty("В этом фрагменте есть важная мысль, которую можно превратить в короткий клип.")

    assert ad_penalty >= 40
    assert "ad or CTA language" in ad_problems
    assert generic_penalty >= 40
    assert "generic clip-analysis text" in generic_problems
