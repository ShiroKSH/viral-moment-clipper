from backend.services.viral_score import calculate_base_score, combine_personal_score


def test_viral_score_formula_clamps_and_combines():
    scores = {
        "semantic_interest_score": 100,
        "hook_score": 100,
        "clarity_score": 100,
        "emotion_score": 100,
        "novelty_score": 100,
        "standalone_score": 100,
        "retention_score": 100,
        "speech_density_score": 100,
        "audio_energy_score": 100,
        "visual_energy_score": 100,
    }
    assert calculate_base_score(scores) == 100
    assert combine_personal_score(80, 100, 0.35) == 87
